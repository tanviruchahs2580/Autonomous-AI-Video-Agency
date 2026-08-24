from __future__ import annotations

from datetime import UTC

import pytest

from agency.db import session_scope
from agency.models import Approval
from agency.workflow.engine import TaskFailure, WorkflowEngine, claim_job, create_job

pytestmark = pytest.mark.integration


def test_migrations_apply_and_are_idempotent(isolated_env):

    from agency.db import run_migrations
    from agency.db import session_scope as scope

    with scope() as db:
        first = run_migrations(db)
        assert len(first) >= 1
    with scope() as db:
        second = run_migrations(db)
    assert second == []


def test_create_job_idempotency(migrated_db):
    with session_scope() as db:
        from agency.models import Project

        p = Project(name="t")
        db.add(p)
        db.commit()
        j1, created1 = create_job(db, p.id, "production", {"a": 1}, idempotency_key="k-1")
        j2, created2 = create_job(db, p.id, "production", {"a": 2}, idempotency_key="k-1")
        assert created1 and not created2
        assert j1.id == j2.id


def _mini_handlers(recorder: dict):
    def ok_stage(db, job, task, context):
        recorder.append(task.name)
        return {"ctx_marker": task.name}

    return {
        "step_a": lambda db, job, task, ctx: (recorder.append("step_a"), {"ctx_a": 1})[1],
        "step_b": ok_stage,
        "step_c": lambda db, job, task, ctx: (recorder.append("step_c"), {"done": True})[1],
    }


def test_engine_happy_path_and_resume_skip(migrated_db):
    calls: list[str] = []
    engine = WorkflowEngine(handlers=_mini_handlers(calls), repair_budget=1)
    with session_scope() as db:
        from agency.models import Project

        p = Project(name="happy")
        db.add(p)
        db.commit()
        job, _ = create_job(db, p.id, "production", {})
        engine.plan_job_tasks = lambda t, payload: [("step_a", "A"), ("step_b", "B"), ("step_c", "C")]
        result = engine.execute_job(db, job)
        assert result.state == "completed"
        assert result.result["completed_at"]
        assert calls == ["step_a", "step_b", "step_c"]


def test_engine_retries_transient_failure_then_succeeds(migrated_db):
    state = {"attempts": 0}

    def flaky(db, job, task, context):
        state["attempts"] += 1
        if state["attempts"] < 3:
            raise TaskFailure("provider hiccup", failure_class="transient")
        return {"ok": True}

    handlers = {"solo": flaky}
    engine = WorkflowEngine(handlers=handlers, max_task_retries=4, repair_budget=0)
    with session_scope() as db:
        from agency.models import Project

        p = Project(name="retry")
        db.add(p)
        db.commit()
        job, _ = create_job(db, p.id, "production", {}, max_attempts=5)
        engine.plan_job_tasks = lambda t, payload: [("solo", "S")]
        result = engine.execute_job(db, job)
        assert result.state == "completed"
        assert state["attempts"] == 3


def test_engine_escalates_after_budget_exhausted(migrated_db):
    def always_fail(db, job, task, context):
        raise TaskFailure("hopeless", failure_class="qa_multimodal")

    engine = WorkflowEngine(handlers={"bad": always_fail}, max_task_retries=2, repair_budget=1)
    with session_scope() as db:
        from agency.models import Project

        p = Project(name="esc")
        db.add(p)
        db.commit()
        job, _ = create_job(db, p.id, "production", {}, max_attempts=5)
        engine.plan_job_tasks = lambda t, payload: [("bad", "B")]
        result = engine.execute_job(db, job)
        assert result.state == "awaiting_approval"
        approvals = db.query(Approval).filter_by(job_id=job.id).all()
        assert any(a.kind == "failure_escalation" for a in approvals)


def test_approval_gate_resumes_job(migrated_db):
    def gated(db, job, task, context):
        if context["state"].get("approved") != "yes":
            return {"awaiting_approval": True}
        return {"published": True}

    engine = WorkflowEngine(handlers={"gate": gated})
    engine.plan_job_tasks = lambda job_type, payload: [("gate", "G")]
    with session_scope() as db:
        from agency.models import Project

        p = Project(name="gate")
        db.add(p)
        db.commit()
        job, _ = create_job(db, p.id, "production", {})
        job_id = job.id
        result = engine.execute_job(db, job)
        assert result.state == "awaiting_approval"
        approval = db.query(Approval).filter_by(job_id=job_id).one()
        approval.status = "approved"
        approval.decided_at = "now"
        approval.decided_by = "tester"
        job.state = "queued"
        job.heartbeat_at = None
        db.commit()
    with session_scope() as db:
        job2 = claim_job(db, job_id, worker_id="test")
        assert job2 is not None
        context_state = {"approved": "yes"}
        orig_run = engine._run_single_task

        def patched_run(db_, job_, name, agent, seq, context, worker_id_):
            context.setdefault("state", {}).update(context_state)
            return orig_run(db_, job_, name, agent, seq, context, worker_id_)

        engine._run_single_task = patched_run
        done = engine.execute_job(db, job2)
        assert done.state == "completed"


def test_stale_running_job_is_reclaimable(migrated_db):
    with session_scope() as db:
        from datetime import datetime, timedelta

        from agency.models import Project

        p = Project(name="stale")
        db.add(p)
        db.commit()
        job, _ = create_job(db, p.id, "production", {})
        job.state = "running"
        job.heartbeat_at = (datetime.now(UTC) - timedelta(seconds=400)).isoformat()
        db.commit()
        jid = job.id
    with session_scope() as db:
        claimed = claim_job(db, jid, worker_id="w2")
        assert claimed is None
        from agency.workflow.engine import claim_next_job

        picked = claim_next_job(db, worker_id="w2")
        assert picked is not None and picked.id == jid
