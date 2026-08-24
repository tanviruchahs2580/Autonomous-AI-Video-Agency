from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture
def client(migrated_db):
    from agency.api.main import app

    with TestClient(app) as c:
        yield c


def auth(key="test-key-123"):
    return {"X-API-Key": key}


class _Recorder:
    def __init__(self, status=200):
        self.status = status
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status)


def _drain(rec: _Recorder | None = None, now=None) -> dict:
    import agency.webhooks as wh
    from agency.db import session_scope

    with session_scope() as db:
        transport = httpx.MockTransport(rec.handler) if rec is not None else None
        return wh.process_pending_deliveries(db, transport=transport, now=now)


def test_webhook_signed_delivery_end_to_end(client):
    rec = _Recorder(200)
    created = client.post("/v1/webhooks", json={"url": "https://example.com/agency-hook"}, headers=auth()).json()
    secret, hook_id = created["secret"], created["id"]

    pid = client.post("/v1/projects", json={"name": "P", "brief": {"title": "t", "objective": "o"}}, headers=auth()).json()["id"]
    job_id = client.post(f"/v1/projects/{pid}/jobs", json={}, headers=auth()).json()["id"]
    run = client.post(f"/v1/jobs/{job_id}/run", headers=auth())
    assert run.status_code == 200

    stats = _drain(rec)
    assert stats["delivered"] >= 1
    assert len(rec.requests) >= 1

    req = rec.requests[-1]
    body = req.read()
    expected_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert req.headers["X-Agency-Signature"] == expected_sig
    assert req.headers["X-Agency-Delivery-Id"]
    payload = json.loads(body)
    assert payload["event"] in ("job.created", "job.completed", "job.repaired")
    assert payload["org_id"] == "default"

    hooks = client.get("/v1/webhooks", headers=auth()).json()["items"]
    assert any(h["id"] == hook_id for h in hooks)


def test_webhook_retry_then_dead_letter(client):
    rec = _Recorder(500)
    client.post("/v1/webhooks", json={"url": "https://example.com/flaky", "events": ["job.failed"]}, headers=auth())

    import agency.webhooks as wh
    from agency.db import session_scope
    from agency.models import WebhookDelivery

    with session_scope() as db:
        wh.dispatch_event(db, "default", "job.failed", {"job_id": "j-sim"})
    base = datetime.now(UTC)
    final_status = None
    attempts_seen = 0
    for attempt in range(7):
        _drain(rec, now=base + timedelta(minutes=attempt * 40))
        with session_scope() as db:
            row = db.query(WebhookDelivery).order_by(WebhookDelivery.created_at.desc()).first()
            final_status = row.status
            attempts_seen = row.attempts
            if final_status == "dead":
                break
    assert final_status == "dead"
    assert attempts_seen == 5
    assert len(rec.requests) == attempts_seen


def test_webhook_event_filter_respected(client):
    rec = _Recorder(200)
    client.post(
        "/v1/webhooks",
        json={"url": "https://example.com/narrow", "events": ["job.completed"]},
        headers=auth(),
    )
    pid = client.post("/v1/projects", json={"name": "P", "brief": {"title": "t", "objective": "o"}}, headers=auth()).json()["id"]
    client.post(f"/v1/projects/{pid}/jobs", json={}, headers=auth())
    stats = _drain(rec)
    assert stats["delivered"] >= 0
    delivered_events = {json.loads(r.read())["event"] for r in rec.requests}
    assert all(e == "job.completed" for e in delivered_events)


def test_webhook_ssrf_blocked(client):
    r = client.post("/v1/webhooks", json={"url": "http://169.254.169.254/latest/meta-data"}, headers=auth())
    assert r.status_code == 422


def test_budget_enforcement_blocks_job(client):
    client.post("/v1/budgets", json={"daily_limit_usd": 0.001}, headers=auth())
    pid = client.post("/v1/projects", json={"name": "P", "brief": {"title": "t", "objective": "o"}}, headers=auth()).json()["id"]
    r = client.post(f"/v1/projects/{pid}/jobs", json={}, headers=auth())
    assert r.status_code == 402
    assert r.json()["error"]["code"] == "budget_exceeded"


def test_metrics_endpoint_exposes_prometheus(client):
    client.get("/v1/system/status", headers=auth())
    body = client.get("/v1/metrics", headers=auth()).text
    assert "agency_api_requests_total" in body
    assert 'agency_queue_depth{state="queued"}' in body


def test_migration_downgrade_upgrade_cycle(migrated_db):
    from sqlalchemy import text

    from agency.db import downgrade_one, run_migrations, session_scope

    def versions(db):
        return [r[0] for r in db.execute(text("SELECT version FROM schema_migrations ORDER BY version")).fetchall()]

    with session_scope() as db:
        before = versions(db)
        assert before

    downed = []
    with session_scope() as db:
        for _ in range(2):
            v = downgrade_one(db)
            if v:
                downed.append(v)
            else:
                break
    assert downed, "expected at least one downgrade step"

    with session_scope() as db:
        run_migrations(db)

    with session_scope() as db:
        after = versions(db)
    assert after == before
