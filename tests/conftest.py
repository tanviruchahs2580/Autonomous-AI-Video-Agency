from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _ffmpeg() -> str:
    from agency.capabilities.media import FFMPEG_BIN

    return FFMPEG_BIN


@pytest.fixture(scope="session")
def ffmpeg_available() -> bool:
    try:
        proc = subprocess.run([_ffmpeg(), "-version"], capture_output=True, timeout=30)
        return proc.returncode == 0
    except Exception:
        return False


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    storage_dir = data_dir / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    test_settings = _build_settings(data_dir)
    import agency.agents.stages as mod_stages
    import agency.api.main as mod_api
    import agency.capabilities.media as mod_media
    import agency.capabilities.router as mod_router
    import agency.capabilities.tts as mod_tts
    import agency.config as mod_config
    import agency.db as db_mod

    db_mod.reset_engine()
    for mod in (mod_config, db_mod, mod_stages, mod_api, mod_router, mod_tts, mod_media):
        if hasattr(mod, "get_settings"):
            monkeypatch.setattr(mod, "get_settings", lambda: test_settings)

    yield test_settings
    db_mod.reset_engine()
    shutil.rmtree(data_dir, ignore_errors=True)


def _build_settings(data_dir: Path):
    from agency.config import Settings

    return Settings(
        env="development",
        api_key="test-key-123",
        db_url=f"sqlite:///{(data_dir / 'test.db').as_posix()}",
        storage_dir=data_dir / "storage",
        data_dir=data_dir,
        tts_provider="synth",
    )


@pytest.fixture
def migrated_db(isolated_env):
    applied = None
    from agency.db import init_db

    applied = init_db()
    assert len(applied) >= 1
    return isolated_env


def _run(cmd: list[str], out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    full = [_ffmpeg()] + cmd[1:] if cmd[0] == "ffmpeg" else cmd
    proc = subprocess.run(full + [str(out)], capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr[-500:]
    return out


@pytest.fixture
def sample_video(tmp_path) -> Path:
    return _run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=24",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest"],
        tmp_path / "fixtures" / "sample.mp4",
    )


@pytest.fixture
def silent_video(tmp_path) -> Path:
    return _run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:duration=2:size=160x120:rate=12",
         "-c:v", "libx264", "-preset", "ultrafast"],
        tmp_path / "fixtures" / "silent.mp4",
    )


@pytest.fixture
def audio_only_wav(tmp_path) -> Path:
    return _run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=2:sample_rate=48000"],
        tmp_path / "fixtures" / "tone.wav",
    )


@pytest.fixture
def corrupted_video(tmp_path, sample_video) -> Path:
    dst = tmp_path / "fixtures" / "corrupt.mp4"
    raw = sample_video.read_bytes()
    dst.write_bytes(raw[: int(len(raw) * 0.35)])
    return dst


@pytest.fixture
def png_image(tmp_path) -> Path:
    from PIL import Image

    p = tmp_path / "fixtures" / "img.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (200, 40, 40)).save(p)
    return p


@pytest.fixture
def brief_small() -> dict:
    return {
        "title": "Nimbus CRM Launch",
        "objective": "Show sales teams how Nimbus CRM automates follow-ups and increases pipeline visibility with real time dashboards.",
        "audience": "sales leaders",
        "platform": "youtube",
        "duration_s": 14,
        "width": 320,
        "height": 180,
        "fps": 24,
        "cta": "Book a demo today",
        "brand": {"name": "Nimbus", "palette": ["#101820", "#1F6FEB", "#F2F7FA", "#FFB000"]},
        "key_points": [
            "Automated follow ups save hours every week",
            "Real time dashboards give full pipeline visibility",
        ],
    }
