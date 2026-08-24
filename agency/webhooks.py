from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Budget, CostEntry, Webhook, WebhookDelivery, now_iso

logger = logging.getLogger("agency.webhooks")

WEBHOOK_EVENT_TYPES = [
    "job.created",
    "job.started",
    "stage.completed",
    "job.repaired",
    "job.failed",
    "approval.required",
    "job.completed",
]


def sign_payload(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def dispatch_event(db: Session, org_id: str | None, event_type: str, payload: dict[str, Any]) -> list[str]:
    if org_id is None:
        return []
    hooks = db.execute(select(Webhook).where(Webhook.org_id == org_id, Webhook.active == True)).scalars().all()  # noqa: E712
    delivery_ids: list[str] = []
    for hook in hooks:
        if hook.events and event_type not in hook.events:
            continue
        delivery = WebhookDelivery(
            webhook_id=hook.id,
            event_type=event_type,
            payload_json=json.dumps({"event": event_type, "org_id": org_id, "data": payload}, default=str),
            status="pending",
            next_retry_at=now_iso(),
        )
        db.add(delivery)
        db.commit()
        delivery_ids.append(delivery.id)
    return delivery_ids


def process_pending_deliveries(
    db: Session,
    transport: httpx.BaseTransport | None = None,
    now: datetime | None = None,
    max_batch: int = 50,
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    pending = db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.status.in_(["pending", "retrying"]))
        .order_by(WebhookDelivery.created_at)
        .limit(max_batch)
    ).scalars().all()
    stats = {"delivered": 0, "retrying": 0, "dead": 0, "skipped": 0}
    client = httpx.Client(timeout=10.0, transport=transport) if transport else httpx.Client(timeout=10.0)
    try:
        for delivery in pending:
            if delivery.next_retry_at and delivery.next_retry_at > now.isoformat():
                stats["skipped"] += 1
                continue
            hook = db.get(Webhook, delivery.webhook_id)
            if hook is None or not hook.active:
                delivery.status = "dead"
                delivery.last_error = "webhook removed or deactivated"
                db.commit()
                stats["dead"] += 1
                continue
            body = delivery.payload_json.encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "X-Agency-Signature": sign_payload(hook.secret, body),
                "X-Agency-Delivery-Id": delivery.id,
                "X-Agency-Event": delivery.event_type,
                "User-Agent": "AgencyWebhook/1.0",
            }
            delivery.attempts += 1
            try:
                resp = client.post(hook.url, content=body, headers=headers)
                delivery.response_code = resp.status_code
                if 200 <= resp.status_code < 300:
                    delivery.status = "delivered"
                    delivery.delivered_at = now_iso()
                    stats["delivered"] += 1
                else:
                    raise RuntimeError(f"HTTP {resp.status_code}")
            except Exception as exc:
                delivery.last_error = str(exc)[:300]
                if delivery.attempts >= delivery.max_attempts:
                    delivery.status = "dead"
                    stats["dead"] += 1
                else:
                    backoff_s = min(2 ** delivery.attempts * 5, 3600)
                    delivery.next_retry_at = (now + timedelta(seconds=backoff_s)).isoformat()
                    delivery.status = "retrying"
                    stats["retrying"] += 1
            db.commit()
    finally:
        client.close()
    return stats


def check_budget(db: Session, org_id: str | None, project_id: str | None, estimated_cost_usd: float) -> dict:
    if org_id is None:
        return {"allowed": True}
    budgets = db.execute(
        select(Budget).where(Budget.active == True, (Budget.org_id == org_id) | (Budget.org_id.is_(None)))  # noqa: E712
    ).scalars().all()
    now = datetime.now(UTC)
    for b in budgets:
        if b.max_cost_per_job_usd is not None and estimated_cost_usd > b.max_cost_per_job_usd:
            return {"allowed": False, "reason": f"estimated ${estimated_cost_usd:.2f} exceeds per-job cap ${b.max_cost_per_job_usd:.2f}"}
        if b.project_id and b.project_id != project_id:
            continue
        spent_q = select(CostEntry).where(CostEntry.org_id == org_id)
        rows = db.execute(spent_q).scalars().all()
        today = now.date().isoformat()
        month = now.date().strftime("%Y-%m")
        daily = sum(c.amount_usd for c in rows if c.created_at and c.created_at[:10] == today)
        monthly = sum(c.amount_usd for c in rows if c.created_at and c.created_at[:7] == month)
        if b.daily_limit_usd is not None and daily + estimated_cost_usd > b.daily_limit_usd:
            return {"allowed": False, "reason": f"tenant daily budget ${b.daily_limit_usd:.2f} would be exceeded (${daily:.2f} spent + ${estimated_cost_usd:.2f} estimated)"}
        if b.monthly_limit_usd is not None and monthly + estimated_cost_usd > b.monthly_limit_usd:
            return {"allowed": False, "reason": f"tenant monthly budget ${b.monthly_limit_usd:.2f} would be exceeded (${monthly:.2f} spent)"}
    return {"allowed": True}


__all__ = ["sign_payload", "dispatch_event", "process_pending_deliveries", "check_budget", "WEBHOOK_EVENT_TYPES"]
