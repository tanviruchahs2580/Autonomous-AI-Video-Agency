"""Disaster recovery drill: backup -> inject damage -> restore -> verify integrity. Measures RPO/RTO.

Usage: python scripts/dr_drill.py   (writes docs/evidence/dr_drill.json)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BRIEF = {
    "title": "DR Drill Deliverable",
    "objective": "Prove backup restore integrity end to end.",
    "audience": "ops",
    "platform": "youtube",
    "duration_s": 8,
    "width": 320,
    "height": 180,
    "fps": 24,
    "cta": "Restore",
    "key_points": ["backup works", "restore works"],
}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="agency-dr-"))
    data_dir = tmp / "data"
    evidence: dict = {"started": datetime.now(timezone.utc).isoformat(), "workdir": str(tmp)}

    os.environ.update({
        "AGENCY_DB_URL": f"sqlite:///{(data_dir / 'drill.db').as_posix()}",
        "AGENCY_DATA_DIR": str(data_dir),
        "AGENCY_STORAGE_DIR": str(data_dir / "storage"),
        "AGENCY_TTS_PROVIDER": "synth",
    })
    for mod in list(sys.modules):
        if mod.startswith("agency"):
            del sys.modules[mod]

    import agency.config as config_mod
    from agency.config import Settings

    settings = Settings(env="development", api_key="drill", db_url=os.environ["AGENCY_DB_URL"], storage_dir=data_dir / "storage", data_dir=data_dir, tts_provider="synth")
    config_mod.get_settings = lambda: settings  # type: ignore[assignment]
    import agency.db as db_mod

    for m in ("agency.db", "agency.agents.stages", "agency.api.main", "agency.capabilities.router", "agency.capabilities.tts", "agency.capabilities.media"):
        if m in sys.modules and hasattr(sys.modules[m], "get_settings"):
            setattr(sys.modules[m], "get_settings", lambda: settings)
    db_mod.reset_engine()

    from agency.db import init_db, session_scope
    from agency.models import Job, Project
    from agency.workflow.engine import WorkflowEngine, claim_job, create_job
    from agency.agents.stages import HANDLERS

    init_db()
    with session_scope() as db:
        p = Project(name="DR", org_id="default", brief_json=json.dumps(BRIEF))
        db.add(p)
        db.commit()
        pid = p.id
        job, _ = create_job(db, pid, "production", {"brief": BRIEF}, idempotency_key="dr-1", org_id="default")
        jid = job.id
    engine = WorkflowEngine(handlers=HANDLERS)
    with session_scope() as db:
        cj = claim_job(db, jid, "drill")
        result = engine.execute_job(db, cj, "drill")
    assert result.state == "completed", result.error
    master = Path(result.result["deliverables"][0]["path"])
    master_hash_before = sha256(master)
    evidence["artifact_sha256_before"] = master_hash_before

    # ---- BACKUP ----
    t0 = time.perf_counter()
    backup_dir = tmp / "backup"
    backup_dir.mkdir()
    import sqlite3 as _sq

    src_conn = _sq.connect(data_dir / "drill.db")
    dst_conn = _sq.connect(backup_dir / "drill.db")
    src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()
    shutil.make_archive(str(backup_dir / "artifacts"), "tar", data_dir / "jobs")
    backup_seconds = time.perf_counter() - t0
    last_backup_ts = datetime.now(timezone.utc)
    evidence["backup_seconds"] = round(backup_seconds, 3)
    evidence["backup_files"] = [f.name for f in backup_dir.iterdir()]

    # ---- DISASTER INJECTION ----
    conn = sqlite3.connect(data_dir / "drill.db")
    conn.execute("DELETE FROM deliverables")
    conn.execute("UPDATE jobs SET state='failed', error='simulated corruption' WHERE id=?", (jid,))
    conn.commit()
    conn.close()
    master.unlink()
    evidence["damage_injected"] = {"deliverables_rows": "deleted", "job_state": "failed", "master_deleted": True}

    # ---- RESTORE ----
    db_mod.reset_engine()
    t1 = time.perf_counter()
    for stale_suffix in ("-wal", "-shm"):
        stale = Path(str(data_dir / "drill.db") + stale_suffix)
        stale.unlink(missing_ok=True)
    shutil.copyfile(backup_dir / "drill.db", data_dir / "drill.db")
    shutil.unpack_archive(str(backup_dir / "artifacts.tar"), data_dir / "jobs", "tar")
    restore_seconds = time.perf_counter() - t1
    evidence["restore_seconds_rto_s"] = round(restore_seconds, 3)

    # ---- VERIFY ----
    conn = sqlite3.connect(data_dir / "drill.db")
    dlv_count = conn.execute("SELECT count(*) FROM deliverables").fetchone()[0]
    job_state = conn.execute("SELECT state FROM jobs WHERE id=?", (jid,)).fetchone()[0]
    conn.close()
    master_hash_after = sha256(master)
    evidence["verify"] = {
        "deliverables_rows_restored": dlv_count,
        "job_state_restored": job_state,
        "master_recreated": master.exists(),
        "sha256_match": master_hash_before == master_hash_after,
    }
    rpo_s = (datetime.now(timezone.utc) - last_backup_ts).total_seconds()
    evidence["rpo_s"] = round(rpo_s, 3)
    evidence["passed"] = (
        dlv_count >= 2
        and job_state == "completed"
        and master_hash_before == master_hash_after
        and master.exists()
    )
    evidence["finished"] = datetime.now(timezone.utc).isoformat()

    out = ROOT / "docs" / "evidence" / "dr_drill.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    shutil.rmtree(tmp, ignore_errors=True)
    db_mod.reset_engine()
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
