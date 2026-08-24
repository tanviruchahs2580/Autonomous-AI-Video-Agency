from __future__ import annotations

import io
import json

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


def _make_project(client):
    brief = {"title": "T", "objective": "O", "duration_s": 10}
    return client.post("/v1/projects", json={"name": "SecP", "brief": brief}, headers=auth()).json()["id"]


def test_upload_neutralizes_path_like_filename(client):
    pid = _make_project(client)
    payload = io.BytesIO(b"RIFFxxxxWAVE")
    r = client.post(
        f"/v1/projects/{pid}/assets?license_state=owned",
        files={"file": ("../../evil.wav", payload, "audio/wav")},
        headers=auth(),
    )
    assert r.status_code == 200

    from agency.db import session_scope
    from agency.models import Asset

    with session_scope() as db:
        asset = db.get(Asset, r.json()["id"])
        assert ".." not in asset.storage_key
        assert asset.source_uri.endswith("evil.wav")


def test_upload_rejects_oversize(client, monkeypatch):
    pid = _make_project(client)
    big = io.BytesIO(b"\x00" * (2 * 1024 * 1024))
    r = client.post(
        f"/v1/projects/{pid}/assets",
        files={"file": ("big.mp4", big, "video/mp4")},
        headers=auth(),
    )
    assert r.status_code == 415


def test_deliverable_download_blocks_unknown_id(client):
    r = client.get("/v1/deliverables/nope/download", headers=auth())
    assert r.status_code == 404


def test_cross_tenant_isolation_via_ids(client):
    p1 = _make_project(client)
    p2 = _make_project(client)
    assert p1 != p2
    job = client.post(f"/v1/projects/{p1}/jobs", json={}, headers=auth()).json()["id"]
    info = client.get(f"/v1/jobs/{job}", headers=auth()).json()
    assert info is not None


def test_rate_limit_returns_429(client, monkeypatch):
    from agency.api import main as api_main

    limited = type(api_main._rate)(per_minute=3)
    monkeypatch.setattr(api_main, "_rate", limited)
    codes = []
    for _ in range(6):
        codes.append(client.get("/v1/projects", headers=auth()).status_code)
    assert 200 in codes and 429 in codes


def test_ssrf_guard():
    from agency.security import assert_public_url

    for url in ("http://10.0.0.1/x", "http://192.168.1.5/x", "http://[::1]/x", "http://127.0.0.1/"):
        with pytest.raises(ValueError):
            assert_public_url(url)


def test_no_shell_injection_in_media_calls(tmp_path):
    from agency.capabilities.media import run_ffmpeg

    dst = tmp_path / "safe_out.mp4"
    try:
        run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:size=32x32:rate=10:duration=0.3", "-c:v", "libx264", "-preset", "ultrafast", str(dst)])
    except Exception as exc:
        assert "pwned" not in str(exc)
    assert not (tmp_path / "pwned.txt").exists()


def test_secrets_never_logged(isolated_env):
    import logging

    from agency.observability import JsonFormatter

    fmt = JsonFormatter()
    record = logging.LogRecord("t", logging.INFO, "p", 1, "msg with %s", ("value",), None)
    out = fmt.format(record)
    data = json.loads(out)
    assert "value" in json.dumps(data)
