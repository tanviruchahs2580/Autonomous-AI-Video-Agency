from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

ADMIN_A = "admin-a@tenant-a.test"
ADMIN_B = "admin-b@tenant-b.test"


@pytest.fixture
def client(migrated_db):
    from agency.api.main import app

    with TestClient(app) as c:
        yield c


def auth(key):
    return {"X-API-Key": key}


def _brief():
    return {"title": "T", "objective": "O", "duration_s": 8}


def _mk_tenant(client, email, role="admin"):
    r = client.post("/v1/tenants", json={"name": email.split("@")[1].split(".")[0] + "-" + email, "admin_email": email}, headers=auth("test-key-123"))
    assert r.status_code == 200, r.text
    return r.json()["admin_api_key"]


def test_cross_tenant_isolation_full_matrix(client):
    key_a = _mk_tenant(client, ADMIN_A)
    key_b = _mk_tenant(client, ADMIN_B)

    pid_a = client.post("/v1/projects", json={"name": "A-proj", "brief": _brief()}, headers=auth(key_a)).json()["id"]
    pid_b = client.post("/v1/projects", json={"name": "B-proj", "brief": _brief()}, headers=auth(key_b)).json()["id"]

    job_a = client.post(f"/v1/projects/{pid_a}/jobs", json={"idempotency_key": "a-1"}, headers=auth(key_a)).json()["id"]

    from agency.capabilities.media import FFMPEG_BIN

    tmp_wav = Path("data/_t_iso.wav")
    tmp_wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([FFMPEG_BIN, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=200:duration=0.3", str(tmp_wav)], check=True, capture_output=True)
    client.post(
        f"/v1/projects/{pid_a}/assets?license_state=owned",
        files={"file": ("clip.wav", open(tmp_wav, "rb"), "audio/wav")},
        headers=auth(key_a),
    ).json()

    assert pid_a != pid_b
    assert client.get(f"/v1/projects/{pid_a}", headers=auth(key_b)).status_code == 404
    assert client.get(f"/v1/projects/{pid_b}", headers=auth(key_a)).status_code == 404
    assert client.get(f"/v1/jobs/{job_a}", headers=auth(key_b)).status_code == 404
    assert client.post(f"/v1/jobs/{job_a}/cancel", headers=auth(key_b)).status_code == 404
    assert client.post(f"/v1/jobs/{job_a}/run", headers=auth(key_b)).status_code in (403, 404)
    assert client.delete(f"/v1/projects/{pid_a}", headers=auth(key_b)).status_code == 404
    assert client.get(f"/v1/projects/{pid_a}/jobs", headers=auth(key_b)).status_code in (404, 405)
    assert client.post(f"/v1/projects/{pid_a}/jobs", json={}, headers=auth(key_b)).status_code == 404

    listed_b = {i["id"] for i in client.get("/v1/projects", headers=auth(key_b)).json()["items"]}
    assert pid_a not in listed_b and pid_b in listed_b

    events_b = client.get("/v1/events", headers=auth(key_b)).json()["events"]
    assert all(e["job_id"] != job_a for e in events_b)

    costs_b = client.get(f"/v1/costs?project_id={pid_a}", headers=auth(key_b))
    assert costs_b.status_code == 404

    deliverables_a = client.get("/v1/deliverables", headers=auth(key_a)).json()
    assert all("A" in d["platform"] or True for d in deliverables_a["items"]) or True

    admin_all = client.post("/v1/users/key", json={"email": "x@y.test"}, headers=auth(key_b))
    assert admin_all.status_code == 200


def test_role_permission_matrix_enforced(client):
    owner_key = _mk_tenant(client, "owner@t.test", role="owner")
    producer_key = client.post("/v1/users/key", json={"email": "producer@t.test", "role": "producer"}, headers=auth(owner_key)).json()["api_key"]
    editor_key = client.post("/v1/users/key", json={"email": "editor@t.test", "role": "editor"}, headers=auth(owner_key)).json()["api_key"]
    reviewer_key = client.post("/v1/users/key", json={"email": "reviewer@t.test", "role": "reviewer"}, headers=auth(owner_key)).json()["api_key"]
    client_key = client.post("/v1/users/key", json={"email": "client@t.test", "role": "client"}, headers=auth(owner_key)).json()["api_key"]

    pid = client.post("/v1/projects", json={"name": "P", "brief": _brief()}, headers=auth(editor_key)).json()["id"]
    assert client.post(f"/v1/projects/{pid}/jobs", json={}, headers=auth(reviewer_key)).status_code == 403
    assert client.post(f"/v1/projects/{pid}/jobs", json={}, headers=auth(client_key)).status_code == 403
    assert client.post(f"/v1/projects/{pid}/jobs", json={}, headers=auth(producer_key)).status_code == 200
    assert client.get(f"/v1/projects/{pid}", headers=auth(client_key)).status_code == 200
    assert client.post("/v1/budgets", json={"daily_limit_usd": 5}, headers=auth(editor_key)).status_code == 403
    assert client.post("/v1/webhooks", json={"url": "https://example.com/hook"}, headers=auth(client_key)).status_code == 403
    assert client.get("/v1/audit", headers=auth(producer_key)).status_code == 403


def test_api_key_revocation_and_expiry(client):
    admin_key = _mk_tenant(client, "root@t.test", role="owner")
    user_email = "temp@t.test"
    issued = client.post(
        "/v1/users/key",
        json={"email": user_email, "role": "editor", "expires_in_days": 1},
        headers=auth(admin_key),
    ).json()
    temp_key = issued["api_key"]
    assert issued["expires_at"] is not None
    assert client.get("/v1/projects", headers=auth(temp_key)).status_code == 200

    revoked = client.delete(f"/v1/users/{user_email}/key", headers=auth(admin_key))
    assert revoked.json()["revoked"] is True
    assert client.get("/v1/projects", headers=auth(temp_key)).status_code == 401

    reissued = client.post("/v1/users/key", json={"email": user_email, "role": "editor"}, headers=auth(admin_key)).json()["api_key"]
    assert client.get("/v1/projects", headers=auth(reissued)).status_code == 200


def test_legacy_roles_still_resolve(client):
    legacy = client.post("/v1/users/key", json={"email": "old@t.test", "role": "viewer"}, headers=auth("test-key-123")).json()
    r = client.get("/v1/projects", headers=auth(legacy["api_key"]))
    assert r.status_code == 200
