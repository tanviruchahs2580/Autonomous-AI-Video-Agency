from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

API_KEY = "test-key-123"


@pytest.fixture
def client(migrated_db):
    from agency.api.main import app

    with TestClient(app) as c:
        yield c


def auth(key=API_KEY):
    return {"X-API-Key": key}


def test_health_endpoints_public(client):
    assert client.get("/health/live").status_code == 200
    r = client.get("/health/ready")
    assert r.status_code == 200 and r.json()["database"] == "ok"


def test_missing_key_rejected(client):
    r = client.get("/v1/projects")
    assert r.status_code == 401


def test_invalid_key_rejected(client):
    r = client.get("/v1/projects", headers=auth("wrong-key"))
    assert r.status_code == 401


def test_request_id_header_present(client):
    r = client.get("/health/live")
    assert "x-request-id" in {k.lower() for k in r.headers.keys()}


def test_project_crud_and_validation(client):
    r = client.post("/v1/projects", json={"name": "", "brief": {}}, headers=auth())
    assert r.status_code == 422
    brief = {
        "title": "T",
        "objective": "O",
        "duration_s": 10,
        "width": 320,
        "height": 180,
    }
    r = client.post("/v1/projects", json={"name": "P1", "brief": brief}, headers=auth())
    assert r.status_code == 200
    pid = r.json()["id"]
    got = client.get(f"/v1/projects/{pid}", headers=auth()).json()
    assert got["name"] == "P1" and got["spec"] == {}
    listed = client.get("/v1/projects", headers=auth()).json()
    assert listed["total"] >= 1
    deleted = client.delete(f"/v1/projects/{pid}", headers=auth())
    assert deleted.status_code == 204


def test_job_creation_and_idempotency(client):
    brief = {"title": "T", "objective": "O", "duration_s": 10}
    pid = client.post("/v1/projects", json={"name": "P", "brief": brief}, headers=auth()).json()["id"]
    r1 = client.post(f"/v1/projects/{pid}/jobs", json={"idempotency_key": "abc"}, headers=auth())
    r2 = client.post(f"/v1/projects/{pid}/jobs", json={"idempotency_key": "abc"}, headers=auth())
    assert r1.json()["deduplicated"] is False
    assert r2.json()["deduplicated"] is True
    assert r1.json()["id"] == r2.json()["id"]
    job_id = r1.json()["id"]
    info = client.get(f"/v1/jobs/{job_id}", headers=auth()).json()
    assert info["state"] in ("queued",)
    assert isinstance(info["tasks"], list)


def test_job_404(client):
    assert client.get("/v1/jobs/nonexistent", headers=auth()).status_code == 404


def test_cancel_job_flow(client):
    brief = {"title": "T", "objective": "O", "duration_s": 10}
    pid = client.post("/v1/projects", json={"name": "P", "brief": brief}, headers=auth()).json()["id"]
    job_id = client.post(f"/v1/projects/{pid}/jobs", json={}, headers=auth()).json()["id"]
    r = client.post(f"/v1/jobs/{job_id}/cancel", headers=auth())
    assert r.json()["state"] == "cancelled"
    r2 = client.post(f"/v1/jobs/{job_id}/cancel", headers=auth())
    assert r2.status_code == 409


def test_upload_asset_valid_and_malformed(client, tmp_path):
    brief = {"title": "T", "objective": "O", "duration_s": 10}
    pid = client.post("/v1/projects", json={"name": "P", "brief": brief}, headers=auth()).json()["id"]

    fake_mp4 = tmp_path / "real.mp4"
    import subprocess

    from agency.capabilities.media import FFMPEG_BIN

    subprocess.run(
        [FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=red:size=64x64:rate=12:duration=0.5",
         "-c:v", "libx264", "-preset", "ultrafast", str(fake_mp4)],
        check=True, capture_output=True,
    )
    with open(fake_mp4, "rb") as fh:
        ok = client.post(
            f"/v1/projects/{pid}/assets",
            files={"file": ("clip.mp4", fh, "video/mp4")},
            params={"license_state": "owned"},
            headers=auth(),
        )
    assert ok.status_code == 200
    assert ok.json()["license_state"] == "owned"

    evil = io.BytesIO(b"MZ\x90\x00 executable payload")
    bad = client.post(
        f"/v1/projects/{pid}/assets",
        files={"file": ("evil.exe", evil, "application/octet-stream")},
        headers=auth(),
    )
    assert bad.status_code == 415

    txt = io.BytesIO(b"<script>alert(1)</script>")
    bad2 = client.post(
        f"/v1/projects/{pid}/assets",
        files={"file": ("xss.mp4", txt, "video/mp4")},
        headers=auth(),
    )
    assert bad2.status_code == 415


def test_role_permissions_enforced(client):
    key_resp = client.post("/v1/users/key", json={"email": "viewer@example.com", "role": "viewer"}, headers=auth())
    viewer_key = key_resp.json()["api_key"]
    r = client.post("/v1/projects", json={"name": "X", "brief": {"title": "t", "objective": "o"}}, headers={"X-API-Key": viewer_key})
    assert r.status_code == 403
    ok_read = client.get("/v1/projects", headers={"X-API-Key": viewer_key})
    assert ok_read.status_code == 200


def test_admin_required_for_key_issue(client):
    key_resp = client.post("/v1/users/key", json={"email": "ed@example.com", "role": "editor"}, headers=auth())
    editor_key = key_resp.json()["api_key"]
    denied = client.post("/v1/users/key", json={"email": "z@z.com"}, headers={"X-API-Key": editor_key})
    assert denied.status_code == 403


def test_system_status_and_costs(client):
    status = client.get("/v1/system/status", headers=auth()).json()
    assert status["version"]
    assert "local-deterministic" in status["providers"]
    assert status["providers"]["local-deterministic"]["healthy"] is True
    costs = client.get("/v1/costs", headers=auth()).json()
    assert costs["total_usd"] == 0.0
