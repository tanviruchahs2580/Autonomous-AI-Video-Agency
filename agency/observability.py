from __future__ import annotations

import json
import logging
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog, CostEntry, Event


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        job_id = getattr(record, "job_id", None)
        task_id = getattr(record, "task_id", None)
        if request_id:
            payload["request_id"] = request_id
        if job_id:
            payload["job_id"] = job_id
        if task_id:
            payload["task_id"] = task_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


@contextmanager
def audit(
    db: Session,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    detail: dict[str, Any] | None = None,
    org_id: str | None = None,
) -> Iterator[dict[str, Any]]:
    ctx: dict[str, Any] = {"actor": actor, "action": action}
    yield ctx
    db.add(
        AuditLog(
            actor=ctx.get("actor", actor),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            org_id=org_id or ctx.get("org_id"),
            detail_json=json.dumps({**(detail or {}), **{k: v for k, v in ctx.items() if k not in ("actor", "action", "org_id")}}, default=str),
        )
    )
    db.commit()


def emit_event(db: Session, job_id: str | None, task_id: str | None, level: str, event: str, data: dict[str, Any] | None = None, org_id: str | None = None) -> None:
    db.add(Event(job_id=job_id, task_id=task_id, level=level, event=event, org_id=org_id, data_json=json.dumps(data or {}, default=str)))
    db.commit()


def record_cost(
    db: Session,
    project_id: str | None,
    job_id: str | None,
    task_id: str | None,
    category: str,
    provider: str,
    model: str,
    quantity: float,
    unit: str,
    amount_usd: float,
    org_id: str | None = None,
) -> None:
    db.add(
        CostEntry(
            project_id=project_id,
            job_id=job_id,
            task_id=task_id,
            org_id=org_id,
            category=category,
            provider=provider,
            model=model,
            quantity=quantity,
            unit=unit,
            amount_usd=round(amount_usd, 6),
        )
    )
    db.commit()
