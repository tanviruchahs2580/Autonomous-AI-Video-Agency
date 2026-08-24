from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.chaos]

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def chaos_env(tmp_path, monkeypatch):
    import agency.agents.stages as mod_stages
    import agency.api.main as mod_api
    import agency.capabilities.media as mod_media
    import agency.capabilities.router as mod_router
    import agency.capabilities.tts as mod_tts
    import agency.config as mod_config
    import agency.db as db_mod
    from agency.config import Settings

    data_dir = tmp_path / "chaos-data"
    data_dir.mkdir(parents=True)
    s = Settings(
        env="development",
        api_key="chaos-key",
        db_url=f"sqlite:///{(data_dir / 'chaos.db').as_posix()}",
        storage_dir=data_dir / "storage",
        data_dir=data_dir,
        tts_provider="synth",
        worker_poll_seconds=0.2,
    )
    db_mod.reset_engine()
    for mod in (mod_config, db_mod, mod_stages, mod_api, mod_router, mod_tts, mod_media):
        if hasattr(mod, "get_settings"):
            monkeypatch.setattr(mod, "get_settings", lambda: s)
    from agency.db import init_db

    init_db()
    yield s, data_dir
    db_mod.reset_engine()


def _spawn_worker(env: dict) -> subprocess.Popen:
    full_env = {**os.environ, **env}
    log_file = open(Path(env["AGENCY_DATA_DIR"]) / "worker.log", "ab")
    return subprocess.Popen(
        [sys.executable, "-m", "agency", "worker"],
        cwd=str(PROJECT_ROOT),
        env=full_env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )


def test_worker_kill_midrender_then_recovery(chaos_env, brief_small):
    settings, data_dir = chaos_env
    env = {
        "AGENCY_DB_URL": settings.db_url,
        "AGENCY_DATA_DIR": str(settings.data_dir),
        "AGENCY_STORAGE_DIR": str(settings.storage_dir),
        "AGENCY_TTS_PROVIDER": "synth",
        "PYTHONPATH": str(PROJECT_ROOT),
    }
    from agency.db import session_scope
    from agency.models import Job, Project
    from agency.workflow.engine import create_job

    with session_scope() as db:
        project = Project(name="Chaos", org_id="default", brief_json=json.dumps(brief_small))
        db.add(project)
        db.commit()
        pid, bid = project.id, project.brief
        job, created = create_job(db, pid, "production", {"brief": bid}, idempotency_key="chaos-1", org_id="default")
        job_id = job.id

    worker1 = _spawn_worker(env)
    deadline = time.time() + 60
    killed_state = None
    while time.time() < deadline:
        with session_scope() as db:
            j = db.get(Job, job_id)
            if j.state == "running":
                worker1.kill()
                worker1.wait(timeout=10)
                killed_state = "killed-while-running"
                break
            if j.state in ("completed", "failed"):
                break
        time.sleep(0.5)
    assert killed_state == "killed-while-running", "worker finished too fast to kill mid-render; increase brief duration"

    with session_scope() as db:
        from datetime import datetime, timedelta

        from sqlalchemy import text

        db.execute(text("UPDATE jobs SET heartbeat_at = :hb WHERE id = :id"), {"hb": (datetime.now(UTC) - timedelta(seconds=400)).isoformat(), "id": job_id})
        db.commit()

    from agency.agents.stages import HANDLERS
    from agency.workflow.engine import WorkflowEngine, claim_next_job

    engine = WorkflowEngine(handlers=HANDLERS)
    with session_scope() as db:
        recovered = claim_next_job(db, worker_id="recovery-inproc")
        assert recovered is not None and recovered.id == job_id
        result = engine.execute_job(db, recovered, worker_id="recovery-inproc")
        if result.state != "completed":
            from agency.models import Task

            fails = [
                (t.seq, t.name, t.attempt, t.failure_class, (t.error or "")[:120])
                for t in db.query(Task).filter_by(job_id=job_id, state="failed").all()
            ]
            pytest.fail(f"job ended {result.state}; failed tasks: {fails}")
        master = Path(result.result["deliverables"][0]["path"])
        assert master.exists() and master.stat().st_size > 20_000

        from agency.capabilities.media import assert_playable, probe

        info = probe(master)
        assert info.video_codec == "h264"
        assert_playable(master)
