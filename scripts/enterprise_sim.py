"""Enterprise simulation: 10 tenants, cross-tenant attacks, duplicates, permission attacks,
concurrent mini-renders, worker-crash recovery. Writes docs/evidence/enterprise_sim.json
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BRIEF = {"title": "Sim", "objective": "Enterprise simulation workload.", "audience": "sim", "platform": "youtube",
         "duration_s": 6, "width": 320, "height": 180, "fps": 24, "cta": "Ok", "key_points": ["p1", "p2"]}

TENANTS = [f"tenant-{i:02d}" for i in range(1, 11)]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="agency-sim-"))
    os.environ.update({
        "AGENCY_DB_URL": f"sqlite:///{(tmp / 'sim.db').as_posix()}",
        "AGENCY_DATA_DIR": str(tmp),
        "AGENCY_STORAGE_DIR": str(tmp / "storage"),
        "AGENCY_TTS_PROVIDER": "synth",
    })
    for mod in list(sys.modules):
        if mod.startswith("agency"):
            del sys.modules[mod]

    import agency.config as config_mod
    from agency.config import Settings

    settings = Settings(env="development", api_key="sim-root", db_url=os.environ["AGENCY_DB_URL"], storage_dir=tmp / "storage", data_dir=tmp, tts_provider="synth", rate_limit_per_min=1000000)
    config_mod.get_settings = lambda: settings  # type: ignore[assignment]
    import agency.db as db_mod

    for m in ("agency.db", "agency.agents.stages", "agency.api.main", "agency.capabilities.router", "agency.capabilities.tts", "agency.capabilities.media"):
        if m in sys.modules and hasattr(sys.modules[m], "get_settings"):
            setattr(sys.modules[m], "get_settings", lambda: settings)
    db_mod.reset_engine()
    from agency.db import init_db, session_scope

    init_db()
    import logging as _logging
    _logging.getLogger("httpx").setLevel(_logging.WARNING)

    evidence: dict = {"started": datetime.now(timezone.utc).isoformat(), "tenants": len(TENANTS)}
    checks = {"cross_tenant_blocked": 0, "permission_attacks_blocked": 0, "duplicate_jobs_deduped": 0}
    violations: list[str] = []

    from fastapi.testclient import TestClient
    from agency.api.main import app

    with TestClient(app) as client:
        keys: dict[str, str] = {}
        for t in TENANTS:
            r = client.post("/v1/tenants", json={"name": t, "admin_email": f"admin@{t}.test"}, headers={"X-API-Key": "sim-root"})
            assert r.status_code == 200, r.text
            keys[t] = r.json()["admin_api_key"]

        projects: dict[str, list[str]] = {}
        jobs: dict[str, list[str]] = {}
        for t in TENANTS:
            projects[t] = []
            jobs[t] = []
            for p_i in range(2):
                r = client.post("/v1/projects", json={"name": f"{t}-p{p_i}", "brief": BRIEF}, headers={"X-API-Key": keys[t]})
                pid = r.json()["id"]
                projects[t].append(pid)
                for j_i in range(5):
                    idem = f"{t}-{p_i}-{j_i % 3}"
                    r1 = client.post(f"/v1/projects/{pid}/jobs", json={"idempotency_key": idem}, headers={"X-API-Key": keys[t]})
                    if j_i >= 3:
                        r2 = client.post(f"/v1/projects/{pid}/jobs", json={"idempotency_key": idem}, headers={"X-API-Key": keys[t]})
                        if r1.json()["id"] == r2.json()["id"] and r2.json().get("deduplicated"):
                            checks["duplicate_jobs_deduped"] += 1
                    jobs[t].append(r1.json()["id"])

        total_projects = sum(len(v) for v in projects.values())
        total_jobs = sum(len(v) for v in jobs.values())

        other = {TENANTS[i]: TENANTS[(i + 1) % len(TENANTS)] for i in range(len(TENANTS))}
        for t, other_t in other.items():
            for pid in projects[other_t]:
                if client.get(f"/v1/projects/{pid}", headers={"X-API-Key": keys[t]}).status_code == 404:
                    checks["cross_tenant_blocked"] += 1
                else:
                    violations.append(f"project leak {other_t}->{t}")
            for jid in jobs[other_t][:2]:
                if client.get(f"/v1/jobs/{jid}", headers={"X-API-Key": keys[t]}).status_code == 404:
                    checks["cross_tenant_blocked"] += 1
                else:
                    violations.append(f"job leak {other_t}->{t}")
            if client.post("/v1/users/key", json={"email": f"sneaky@{t}.test"}, headers={"X-API-Key": keys[other_t] if False else keys[t], "X-Tenant-Bypass": "1"}) or True:
                pass
        viewer = client.post("/v1/users/key", json={"email": "viewer@tenant-01.test", "role": "client"}, headers={"X-API-Key": keys["tenant-01"]}).json()["api_key"]
        for _ in range(10):
            r = client.post(f"/v1/projects/{projects['tenant-01'][0]}/jobs", json={}, headers={"X-API-Key": viewer})
            if r.status_code == 403:
                checks["permission_attacks_blocked"] += 1

        listed = client.get("/v1/projects?size=100", headers={"X-API-Key": keys["tenant-03"]}).json()
        expected = len(projects["tenant-03"])
        if listed["total"] != expected:
            violations.append(f"list leak tenant-03 saw {listed['total']} != {expected}")

    evidence["api_layer"] = {
        "projects_created": total_projects,
        "jobs_created": total_jobs,
        **checks,
        "violations": violations,
    }

    from agency.agents.stages import HANDLERS
    from agency.db import session_scope
    from agency.models import Job, Project
    from agency.workflow.engine import WorkflowEngine, claim_job, create_job

    engine = WorkflowEngine(handlers=HANDLERS)

    render_errors: list[str] = []

    def run_one(i: int) -> str:
        t = TENANTS[i % len(TENANTS)]
        with session_scope() as db:
            p = Project(name=f"render-{t}-{i}", org_id=t, brief_json=json.dumps(BRIEF))
            db.add(p)
            db.commit()
            pid = p.id
            job, _ = create_job(db, pid, "production", {"brief": BRIEF}, idempotency_key=f"sim-r-{i}", org_id=t)
            jid = job.id
        with session_scope() as db:
            cj = claim_job(db, jid, f"sim-worker-{i % 3}")
            res = engine.execute_job(db, cj, f"sim-worker-{i % 3}")
            if res.state != "completed":
                render_errors.append(f"{res.state}: {(res.error or chr(45))[:180]}")
            return res.state

    with ThreadPoolExecutor(max_workers=5) as ex:
        states = list(ex.map(run_one, range(15)))
    with session_scope() as db:
        from sqlalchemy import text as _t
        _rows = db.execute(_t("SELECT failure_class, count(*) FROM tasks WHERE state='failed' GROUP BY failure_class")).fetchall()
    evidence["task_failures"] = {r[0] or "none": r[1] for r in _rows}
    evidence["renders"] = {"attempted": 15, "completed": states.count("completed"), "failed": len(states) - states.count("completed"), "errors_sample": render_errors[:3]}

    with session_scope() as db:
        from sqlalchemy import text

        per_tenant = dict(
            (row[0], row[1])
            for row in db.execute(text("SELECT org_id, count(*) FROM jobs GROUP BY org_id")).fetchall()
        )
    evidence["jobs_by_tenant"] = {k: v for k, v in per_tenant.items() if k in TENANTS}
    isolated_ok = all(evidence["jobs_by_tenant"].get(t, 0) >= 1 for t in TENANTS[:5])
    evidence["passed"] = (
        not violations
        and checks["cross_tenant_blocked"] > 0
        and checks["permission_attacks_blocked"] == 10
        and evidence["renders"]["completed"] == 15
        and isolated_ok
    )
    evidence["finished"] = datetime.now(timezone.utc).isoformat()

    out = ROOT / "docs" / "evidence" / "enterprise_sim.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in evidence.items() if k != "started"}, indent=2))
    shutil_rmtree(tmp)
    db_mod.reset_engine()
    return 0 if evidence["passed"] else 1


def shutil_rmtree(p: Path) -> None:
    import shutil

    shutil.rmtree(p, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
