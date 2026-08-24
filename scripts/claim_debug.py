import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="claimdbg-"))
os.environ.update({
    "AGENCY_DB_URL": f"sqlite:///{(tmp / 'c.db').as_posix()}",
    "AGENCY_DATA_DIR": str(tmp),
    "AGENCY_STORAGE_DIR": str(tmp / "storage"),
    "AGENCY_TTS_PROVIDER": "synth",
})
for mod in list(sys.modules):
    if mod.startswith("agency"):
        del sys.modules[mod]

import agency.config as config_mod
from agency.config import Settings

settings = Settings(env="development", api_key="x", db_url=os.environ["AGENCY_DB_URL"], storage_dir=tmp / "storage", data_dir=tmp, tts_provider="synth")
config_mod.get_settings = lambda: settings
import agency.db as db_mod

for m in ("agency.db", "agency.agents.stages", "agency.capabilities.router", "agency.capabilities.tts", "agency.capabilities.media"):
    if m in sys.modules and hasattr(sys.modules[m], "get_settings"):
        setattr(sys.modules[m], "get_settings", lambda: settings)
db_mod.reset_engine()
from agency.db import init_db, session_scope

init_db()
from agency.agents.stages import HANDLERS
from agency.models import Job, Project
from agency.workflow.engine import WorkflowEngine, claim_job, create_job

engine = WorkflowEngine(handlers=HANDLERS)
BRIEF = {"title": "C", "objective": "claim debug", "duration_s": 6, "width": 320, "height": 180, "fps": 24,
         "audience": "x", "platform": "youtube", "cta": "Go", "key_points": ["a", "b"]}


def worker(i):
    tag = f"T{i}"
    with session_scope() as db:
        p = Project(name=f"p{i}", org_id="default", brief_json=json.dumps(BRIEF))
        db.add(p)
        db.commit()
        pid = p.id
        job, _ = create_job(db, pid, "production", {"brief": BRIEF}, idempotency_key=f"c-{i}", org_id="default")
        jid = job.id
        print(f"{tag} created {jid[:8]} state={job.state}", flush=True)
    time.sleep(0.1 * i)
    with session_scope() as db:
        row = db.get(Job, jid)
        print(f"{tag} pre-claim state={row.state}", flush=True)
        t0 = time.time()
        claimed = None
        while time.time() - t0 < 30:
            claimed = claim_job(db, jid, f"W{i}")
            if claimed:
                break
            db.rollback()
            st = db.get(Job, jid).state
            print(f"{tag} claim=None state={st} t={time.time()-t0:.1f}s", flush=True)
            time.sleep(0.5)
        if not claimed:
            print(f"{tag} GIVE UP", flush=True)
            return
        res = engine.execute_job(db, claimed, f"W{i}")
        print(f"{tag} final={res.state}", flush=True)
        from agency.models import Task

        with session_scope() as db:
            for t in db.query(Task).filter_by(job_id=jid, state="failed").all():
                print(f"  FAIL {t.name} cls={t.failure_class}: {(t.error or '')[:150]}", flush=True)
            from agency.models import QAReport

            for q in db.query(QAReport).filter_by(job_id=jid).all():
                print(f"  QA {q.layer} passed={q.passed} findings={q.findings}", flush=True)


threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
for t in threads:
    t.start()
for t in threads:
    t.join()
from agency.db import session_scope as _ss
from agency.models import Job as _J

with _ss() as db:
    for j in db.query(_J).all():
        print(f"DBROW {j.id[:8]} state={j.state} started={j.started_at} finished={j.finished_at}")
db_mod.reset_engine()
