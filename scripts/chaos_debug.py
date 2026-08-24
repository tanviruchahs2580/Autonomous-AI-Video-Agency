"""Manual chaos reproduction harness with verbose DB state dumps."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WD = Path(os.environ.get("CHAOS_WD", ROOT / "data" / "chaos-debug"))
DB = WD / "chaos.db"

ENV = {
    **os.environ,
    "AGENCY_DB_URL": f"sqlite:///{DB.as_posix()}",
    "AGENCY_DATA_DIR": str(WD),
    "AGENCY_STORAGE_DIR": str(WD / "storage"),
    "AGENCY_TTS_PROVIDER": "synth",
    "PYTHONPATH": str(ROOT),
}

BRIEF = {
    "title": "Chaos Debug",
    "objective": "Survive a worker kill and finish the render.",
    "audience": "engineers",
    "platform": "youtube",
    "duration_s": 14,
    "width": 320,
    "height": 180,
    "fps": 24,
    "cta": "Recover now",
    "key_points": ["point one here", "point two here"],
}


def dump_state(tag: str) -> None:
    from agency.db import session_scope
    from agency.models import Job, Task

    with session_scope() as db:
        jobs = db.query(Job).all()
        for j in jobs:
            print(f"[{tag}] job {j.id[:8]} state={j.state} attempts={j.attempts} hb={j.heartbeat_at}")
            tasks = db.query(Task).filter_by(job_id=j.id).order_by(Task.seq, Task.attempt).all()
            for t in tasks:
                print(f"   seq={t.seq} {t.name} {t.state} att={t.attempt} dur={t.duration_ms}")


def main() -> int:
    WD.mkdir(parents=True, exist_ok=True)
    from agency.config import Settings
    import agency.agents.stages as mod_stages
    import agency.api.main as mod_api
    import agency.capabilities.media as mod_media
    import agency.capabilities.router as mod_router
    import agency.capabilities.tts as mod_tts
    import agency.config as mod_config
    import agency.db as db_mod
    from agency.config import get_settings
    from agency.db import init_db, session_scope
    from agency.models import Job, Project
    from agency.workflow.engine import create_job

    s = Settings(env="development", api_key="k", db_url=ENV["AGENCY_DB_URL"], storage_dir=WD / "storage", data_dir=WD, tts_provider="synth", worker_poll_seconds=0.2)
    db_mod.reset_engine()
    for mod in (mod_config, db_mod, mod_stages, mod_api, mod_router, mod_tts, mod_media):
        if hasattr(mod, "get_settings"):
            pass
    mod_config._settings_singleton = s  # type: ignore[attr-defined]
    init_db()

    with session_scope() as db:
        project = Project(name="ChaosDbg", org_id="default", brief_json=json.dumps(BRIEF))
        db.add(project)
        db.commit()
        pid = project.id
        job, _ = create_job(db, pid, "production", {"brief": BRIEF}, idempotency_key="dbg-1", org_id="default")
        job_id = job.id

    log = open(WD / "w1.log", "wb")
    w1 = subprocess.Popen([sys.executable, "-m", "agency", "worker"], cwd=str(ROOT), env=ENV, stdout=log, stderr=subprocess.STDOUT)
    time.sleep(4)
    w1.kill()
    w1.wait()
    print("worker1 killed")

    from sqlalchemy import text

    with session_scope() as db:
        stale = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        db.execute(text("UPDATE jobs SET heartbeat_at=:hb WHERE id=:i"), {"hb": stale, "i": job_id})
        db.commit()
    dump_state("after-kill")

    log2 = open(WD / "w2.log", "wb")
    w2 = None
    use_inproc = os.environ.get("CHAOS_INPROC") == "1"
    if not use_inproc:
        w2 = subprocess.Popen([sys.executable, "-m", "agency", "worker"], cwd=str(ROOT), env=ENV, stdout=log2, stderr=subprocess.STDOUT)
    for i in range(90):
        time.sleep(2)
        from agency.db import session_scope
        from agency.models import Job

        with session_scope() as db:
            j = db.get(Job, job_id)
            if j.state in ("completed", "failed"):
                print(f"FINAL after ~{i * 2}s: {j.state}")
                if j.error:
                    print("ERR:", j.error[:300])
                break
        if i == 3 and use_inproc:
            print(">>> starting in-process recovery")
            import faulthandler

            faulthandler.dump_traceback_later(60, exit=False)
            from agency.agents.stages import HANDLERS
            from agency.workflow.engine import WorkflowEngine, claim_next_job

            eng = WorkflowEngine(handlers=HANDLERS)
            with session_scope() as db:
                cj = claim_next_job(db, "dbg-recover")
                print("claimed:", cj.id[:8] if cj else None)
                result = eng.execute_job(db, cj, worker_id="dbg-recover")
                print("inproc final:", result.state, (result.error or "")[:200])
        if i % 5 == 4:
            dump_state(f"poll{i}")
    else:
        print("TIMEOUT waiting recovery")
    w2.terminate()
    dump_state("final")
    print("--- w2 log tail ---")
    print(open(WD / "w2.log").read()[-2000:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
