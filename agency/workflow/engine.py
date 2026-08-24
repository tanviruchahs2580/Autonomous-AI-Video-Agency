from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..models import Event, Job, Task, now_iso
from ..observability import emit_event
from ..webhooks import dispatch_event as _dispatch_event

logger = logging.getLogger("agency.workflow")


def notify_webhooks(db: Session, org_id: str | None, event_type: str, data: dict) -> None:
    try:
        _dispatch_event(db, org_id, event_type, data)
    except Exception:
        logger.exception("webhook dispatch failed")

JOB_STATES = ("queued", "running", "paused", "retrying", "failed", "cancelled", "completed", "awaiting_approval")
TASK_STATES = ("pending", "running", "done", "failed", "skipped")

StaleHeartbeatSeconds = 300
HeartbeatIntervalSeconds = 15


def create_job(
    db: Session,
    project_id: str,
    job_type: str,
    payload: dict,
    idempotency_key: str | None = None,
    max_attempts: int = 3,
    priority: int = 5,
    org_id: str | None = None,
) -> tuple[Job, bool]:
    if idempotency_key:
        existing = db.execute(select(Job).where(Job.idempotency_key == idempotency_key)).scalar_one_or_none()
        if existing is not None:
            return existing, False
    job = Job(
        project_id=project_id,
        org_id=org_id,
        type=job_type,
        payload=payload,
        idempotency_key=idempotency_key,
        max_attempts=max_attempts,
        priority=priority,
        state="queued",
    )
    db.add(job)
    db.commit()
    emit_event(db, job.id, None, "info", "job.created", {"type": job_type}, org_id=job.org_id)
    notify_webhooks(db, org_id, "job.created", {"job_id": job.id, "type": job_type})
    return job, True


def claim_job(db: Session, job_id: str, worker_id: str) -> Job | None:
    job = db.get(Job, job_id)
    if job is None:
        return None
    if job.state not in ("queued", "retrying"):
        return None
    job.state = "running"
    job.attempts += 1
    job.started_at = job.started_at or now_iso()
    job.heartbeat_at = now_iso()
    resumed = db.execute(select(Task).where(Task.job_id == job.id, Task.state == "awaiting_approval")).scalars().all()
    for t in resumed:
        decided = db.execute(
            text("SELECT status FROM approvals WHERE job_id = :jid AND status IN ('approved','rejected') ORDER BY decided_at DESC LIMIT 1"),
            {"jid": job.id},
        ).fetchone()
        if decided is not None and decided[0] == "approved":
            t.state = "pending"
            db.add(Event(job_id=job.id, task_id=t.id, level="info", event="task.resumed_after_approval", data_json="{}"))
        elif decided is not None and decided[0] == "rejected":
            t.state = "failed"
            t.error = "rejected by human approver"
    db.commit()
    emit_event(db, job.id, None, "info", "job.claimed", {"worker": worker_id, "attempt": job.attempts}, org_id=job.org_id)
    logger.info("claimed job %s by %s", job.id, worker_id, extra={"job_id": job.id})
    return job


def claim_next_job(db: Session, worker_id: str) -> Job | None:
    now = datetime.now(UTC)
    stale_cutoff = (now - timedelta(seconds=StaleHeartbeatSeconds)).isoformat()
    rows = db.execute(
        select(Job)
        .where(
            (Job.state == "queued")
            | ((Job.state == "running") & ((Job.heartbeat_at.is_(None)) | (Job.heartbeat_at < stale_cutoff)))
            | ((Job.state == "retrying") & (Job.heartbeat_at.is_(None)))
        )
        .order_by(Job.priority, Job.created_at)
    ).scalars().all()
    for job in rows:
        job.state = "running"
        job.attempts += 1
        job.started_at = job.started_at or now_iso()
        job.heartbeat_at = now_iso()
        resumed = db.execute(select(Task).where(Task.job_id == job.id, Task.state == "awaiting_approval")).scalars().all()
        for t in resumed:
            decided = db.execute(
                text("SELECT status FROM approvals WHERE job_id = :jid AND status IN ('approved','rejected') ORDER BY decided_at DESC LIMIT 1"),
                {"jid": job.id},
            ).fetchone()
            if decided is not None and decided[0] == "approved":
                t.state = "pending"
                db.add(Event(job_id=job.id, task_id=t.id, level="info", event="task.resumed_after_approval", data_json="{}"))
            elif decided is not None and decided[0] == "rejected":
                t.state = "failed"
                t.error = "rejected by human approver"
        db.commit()
        emit_event(db, job.id, None, "info", "job.claimed", {"worker": worker_id, "attempt": job.attempts}, org_id=job.org_id)
        logger.info("claimed job %s by %s", job.id, worker_id, extra={"job_id": job.id})
        return job
    return None


def heartbeat(job_id: str) -> None:
    from agency.db import session_scope

    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is not None and job.state == "running":
            job.heartbeat_at = now_iso()
            db.commit()


class TaskFailure(Exception):
    def __init__(self, message: str, failure_class: str = "generic") -> None:
        super().__init__(message)
        self.failure_class = failure_class


HandlerFn = Callable[[Session, Job, Task, dict], dict]


class WorkflowEngine:
    def __init__(self, handlers: dict[str, HandlerFn], max_task_retries: int = 3, repair_budget: int = 2) -> None:
        self.handlers = handlers
        self.max_task_retries = max_task_retries
        self.repair_budget = repair_budget

    def plan_job_tasks(self, job_type: str, payload: dict) -> list[tuple[str, str]]:
        from agency.agents.stages import PRODUCTION_STAGES

        if job_type != "production":
            raise ValueError(f"unknown job type {job_type}")
        return [(name, agent) for name, agent in PRODUCTION_STAGES]

    def execute_job(self, db: Session, job: Job | None, worker_id: str = "inline") -> Job:
        if job is None:
            raise ValueError("execute_job called with no job")
        try:
            plan = self.plan_job_tasks(job.type, job.payload)
            context: dict[str, Any] = {"job": job, "payload": job.payload, "artifacts": {}, "state": {}}
            self._restore_context_state(db, job, context)
            seq = 0
            while seq < len(plan):
                name, agent = plan[seq]
                task = self._run_single_task(db, job, name, agent, seq, context, worker_id)
                if task.state == "awaiting_approval":
                    self._pause_for_approval(db, job, task)
                    return job
                if task.state == "failed":
                    repaired, new_seq = self._attempt_repair(db, job, task, context)
                    if not repaired:
                        if job.state != "awaiting_approval":
                            self._fail_job(db, job, task.error or "unrecoverable task failure")
                        return job
                    if new_seq is not None:
                        seq = new_seq
                    continue
                seq += 1
            self._complete_job(db, job, context)
        except TaskFailure as exc:
            self._fail_job(db, job, str(exc))
        except Exception as exc:
            logger.exception("job crashed", extra={"job_id": job.id})
            self._fail_job(db, job, f"unexpected error: {exc}")
        return job

    def _restore_context_state(self, db: Session, job: Job, context: dict) -> None:
        done_tasks = db.execute(
            select(Task).where(Task.job_id == job.id, Task.state == "done").order_by(Task.seq, Task.attempt)
        ).scalars().all()
        merged: dict[str, Any] = {}
        for t in done_tasks:
            try:
                out = t.output
            except Exception:
                logger.warning("could not deserialize output of task %s", t.id, exc_info=True)
                continue
            if isinstance(out, dict):
                merged.update(out)
        context["state"].update(merged)

    def _run_single_task(
        self,
        db: Session,
        job: Job,
        name: str,
        agent: str,
        seq: int,
        context: dict,
        worker_id: str,
    ) -> Task:
        existing = db.execute(
            select(Task).where(Task.job_id == job.id, Task.seq == seq, Task.state.in_(["done", "awaiting_approval"]))
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        handler = self.handlers[name]
        prior_attempt = db.execute(
            select(func.max(Task.attempt)).where(Task.job_id == job.id, Task.seq == seq)
        ).scalar()
        attempt = (prior_attempt or 0) + 1
        task = Task(
            job_id=job.id,
            name=name,
            agent=agent,
            seq=seq,
            state="running",
            attempt=attempt,
            max_attempts=self.max_task_retries,
            input_json=json.dumps({"stage": name}, default=str),
            started_at=now_iso(),
        )
        db.add(task)
        db.commit()
        started = time.monotonic()
        try:
            output = handler(db, job, task, context)
            output = output if isinstance(output, dict) else {"result": output}
            task.output = output
            context["state"].update({k: v for k, v in output.items() if k.startswith("ctx_")})
            if output.get("awaiting_approval"):
                task.state = "awaiting_approval"
            else:
                task.state = "done"
            emit_event(db, job.id, task.id, "info", f"task.{task.state}", {"stage": name, "agent": agent}, org_id=job.org_id)
        except TaskFailure as exc:
            task.error = str(exc)
            task.failure_class = exc.failure_class
            task.state = "failed"
            emit_event(db, job.id, task.id, "error", "task.failed", {"stage": name, "class": exc.failure_class, "error": str(exc)}, org_id=job.org_id)
        except Exception as exc:
            task.error = f"{type(exc).__name__}: {exc}"
            task.failure_class = "crash"
            task.state = "failed"
            emit_event(db, job.id, task.id, "error", "task.crashed", {"stage": name, "error": task.error}, org_id=job.org_id)
        finally:
            task.duration_ms = int((time.monotonic() - started) * 1000)
            task.finished_at = now_iso()
            db.commit()
        return task

    def _attempt_repair(self, db: Session, job: Job, failed_task: Task, context: dict) -> tuple[bool, int | None]:

        from ..models import Repair

        failure_class = getattr(failed_task, "failure_class", "generic") or "generic"
        retryable_classes = {"transient", "render_crash", "provider_unavailable", "ffmpeg_error"}
        stage_retryable = failed_task.attempt < self.max_task_retries and (
            failure_class in retryable_classes or failed_task.attempt < 2
        )
        plan: dict[str, Any]
        if stage_retryable:
            plan = {"action": "retry_stage", "stage": failed_task.name, "attempt": failed_task.attempt + 1, "backoff_s": min(2 ** failed_task.attempt * 0.1, 1.0)}
        elif job.repair_count < self.repair_budget:
            plan = {"action": "pipeline_repair", "strategy": _repair_strategy_for(failure_class) or {"reset_from_seq": 0}}
            job.repair_count += 1
        else:
            plan = {"action": "escalate_human", "reason": f"repair budget exhausted after {job.repair_count} repairs"}

        repair = Repair(job_id=job.id, failure_class=failure_class, stage=failed_task.name, plan_json=json.dumps(plan, default=str), applied=False)
        db.add(repair)
        db.commit()
        emit_event(db, job.id, failed_task.id, "warning", "repair.planned", plan, org_id=job.org_id)

        action = plan["action"]
        if action == "retry_stage":
            time.sleep(plan["backoff_s"])
            repair.applied = True
            repair.result = "stage queued for retry"
            db.commit()
            emit_event(db, job.id, failed_task.id, "info", "repair.retry_stage", {"stage": failed_task.name})
            notify_webhooks(db, job.org_id, "job.repaired", {"job_id": job.id, "stage": failed_task.name, "mode": "retry"})
            return True, None
        if action == "pipeline_repair" and plan.get("strategy"):
            strategy: dict = plan["strategy"]
            reset_from = strategy.get("reset_from_seq")
            if reset_from is None:
                return False, None
            stale_tasks = [
                t for t in db.execute(select(Task).where(Task.job_id == job.id)).scalars() if t.seq >= reset_from and t.state != "done"
            ]
            for t in stale_tasks:
                db.delete(t)
            db.commit()
            repair.applied = True
            repair.result = f"pipeline restarted from seq {reset_from}"
            db.commit()
            emit_event(db, job.id, None, "info", "repair.pipeline_restart", {"from_seq": reset_from}, org_id=job.org_id)
            return True, reset_from
        if action == "escalate_human":
            repair.applied = True
            repair.result = "escalated to human approval queue"
            db.commit()
            self._pause_for_approval_reason(db, job, f"escalation: {failure_class} at {failed_task.name}")
            return False, None
        return False, None

    def _pause_for_approval(self, db: Session, job: Job, task: Task) -> None:
        from ..models import Approval

        approval = Approval(project_id=job.project_id, job_id=job.id, kind="gate", status="requested", note=f"approval gate at {task.name}")
        db.add(approval)
        job.state = "awaiting_approval"
        job.heartbeat_at = now_iso()
        db.commit()
        emit_event(db, job.id, task.id, "warning", "job.awaiting_approval", {"stage": task.name}, org_id=job.org_id)
        notify_webhooks(db, job.org_id, "approval.required", {"job_id": job.id, "stage": task.name})

    def _pause_for_approval_reason(self, db: Session, job: Job, reason: str) -> None:
        from ..models import Approval

        db.add(Approval(project_id=job.project_id, job_id=job.id, kind="failure_escalation", status="requested", note=reason))
        job.state = "awaiting_approval"
        db.commit()

    def _fail_job(self, db: Session, job: Job, error: str) -> None:
        job.state = "retrying" if job.attempts < job.max_attempts else "failed"
        job.error = error[-2000:]
        job.finished_at = now_iso() if job.state == "failed" else None
        job.heartbeat_at = None
        db.commit()
        emit_event(db, job.id, None, "error", "job." + ("retrying" if job.state == "retrying" else "failed"), {"error": error[:500]}, org_id=job.org_id)
        notify_webhooks(db, job.org_id, "job.failed", {"job_id": job.id, "error": error[:300], "state": job.state})
        logger.error("job %s %s: %s", job.id, job.state, error, extra={"job_id": job.id})

    def _complete_job(self, db: Session, job: Job, context: dict) -> None:
        deliverables = context.get("deliverables", [])
        qa_summary = context.get("qa_summary", {})
        result = {
            "deliverables": deliverables,
            "qa_summary": qa_summary,
            "cost_usd": context.get("total_cost_usd", 0.0),
            "completed_at": now_iso(),
        }
        job.result = result
        job.state = "completed"
        job.finished_at = now_iso()
        job.error = None
        db.commit()
        emit_event(db, job.id, None, "info", "job.completed", {"deliverables": len(deliverables)}, org_id=job.org_id)
        notify_webhooks(db, job.org_id, "job.completed", {"job_id": job.id, "deliverables": len(deliverables)})


def _repair_strategy_for(failure_class: str) -> dict | None:
    from agency.agents.stages import STAGE_SEQ

    strategies: dict[str, dict] = {
        "qa_loudness": {"reset_from_seq": STAGE_SEQ.get("audio_mix", 12)},
        "qa_duration": {"reset_from_seq": STAGE_SEQ.get("editorial_assembly", 8)},
        "qa_sync": {"reset_from_seq": STAGE_SEQ.get("final_render", 13)},
        "corrupt_media": {"reset_from_seq": STAGE_SEQ.get("asset_acquisition", 4)},
        "generic": {"reset_from_seq": 0},
    }
    return strategies.get(failure_class)




