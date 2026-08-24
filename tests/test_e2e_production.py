from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


def test_full_production_run_produces_playable_video(migrated_db, brief_small, tmp_path):
    from agency.agents.stages import HANDLERS
    from agency.capabilities.media import assert_playable, probe
    from agency.db import session_scope
    from agency.models import Deliverable, Project, QAReport
    from agency.workflow.engine import WorkflowEngine, claim_job, create_job

    with session_scope() as db:
        project = Project(name="E2E Nimbus", brief_json=json.dumps(brief_small))
        db.add(project)
        db.commit()
        project_id = project.id
        job, created = create_job(db, project_id=project_id, job_type="production", payload={"brief": brief_small}, idempotency_key=f"e2e-{project_id}")
        job_id = job.id

    engine = WorkflowEngine(handlers=HANDLERS, max_task_retries=3, repair_budget=2)
    with session_scope() as db:
        claimed = claim_job(db, job_id=job_id, worker_id="pytest-e2e")
        assert claimed is not None
        result = engine.execute_job(db, claimed, worker_id="pytest-e2e")
        assert result.state == "completed", f"job failed: {result.error}"
        payload = result.result
        qa = db.query(QAReport).filter_by(job_id=job_id).all()
        deliverables = db.query(Deliverable).filter_by(project_id=project_id).all()

    layers = {r.layer: r.passed for r in qa}
    assert layers.get("technical") is True
    assert layers.get("creative") is True
    assert layers.get("multimodal") is True

    master_path = Path(payload["deliverables"][0]["path"])
    assert master_path.exists() and master_path.stat().st_size > 50_000
    info = probe(master_path)
    assert info.video_codec == "h264"
    assert info.audio_codec == "aac"
    assert (info.width, info.height) == (320, 180)
    assert 8 <= info.duration_s <= 24
    assert_playable(master_path)

    assert len(deliverables) >= 1
    manifest = json.loads(deliverables[0].manifest_json)
    assert manifest["title"] == brief_small["title"]
    assert manifest["cta"] == brief_small["cta"]


def test_e2e_rerun_is_deduplicated(migrated_db, brief_small):
    from agency.db import session_scope
    from agency.models import Project
    from agency.workflow.engine import create_job

    with session_scope() as db:
        project = Project(name="Dedupe", brief_json=json.dumps(brief_small))
        db.add(project)
        db.commit()
        pid = project.id
        j1, c1 = create_job(db, pid, "production", {"brief": brief_small}, idempotency_key="dup-1")
        j2, c2 = create_job(db, pid, "production", {"brief": brief_small}, idempotency_key="dup-1")
    assert c1 is True and c2 is False and j1.id == j2.id
