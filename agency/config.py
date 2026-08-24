from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENCY_", env_file=str(APP_ROOT / ".env"), extra="ignore")

    env: str = "development"
    api_key: str = "dev-key"
    db_url: str = f"sqlite:///{(APP_ROOT / 'data' / 'agency.db').as_posix()}"
    storage_dir: Path = APP_ROOT / "data" / "storage"
    data_dir: Path = APP_ROOT / "data"
    log_level: str = "INFO"
    rate_limit_per_min: int = 120
    max_upload_mb: int = 512
    approval_required: bool = False

    model_router_text_provider: str = "local"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"

    tts_provider: str = "edge"
    edge_tts_voice: str = "en-US-AriaNeural"
    comfyui_url: str | None = None
    comfyui_workflow_id: str | None = None

    qa_target_lufs: float = -16.0
    qa_max_repairs: int = 2
    worker_poll_seconds: float = 0.5
    ffmpeg_timeout: int = 900

    cors_origins: str = ""
    media_max_duration_s: float = 7200.0
    media_max_width: int = 7680
    media_max_height: int = 4320
    allowed_video_codecs: str = "h264,hevc,vp9,av1"
    allowed_audio_codecs: str = "aac,mp3,opus,flac,pcm_s16le"
    upload_probe_enabled: bool = True
    webhook_max_attempts: int = 5
    default_job_cost_estimate_usd: float = 0.05


@lru_cache
def get_settings() -> Settings:
    return Settings()


def ensure_dirs(settings: Settings) -> None:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
