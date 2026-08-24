from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from .config import get_settings
from .db import session_scope
from .models import Artifact, now_iso
from .observability import audit

logger = logging.getLogger("agency.lifecycle")

TEMPORARY_KINDS = {"generated_image", "narration_audio", "cleaned_narration", "av_intermediate", "rough_cut", "graphics_overlay", "timeline"}
RETAIN_KINDS = {"master_render", "thumbnail", "captions_sidecar"}


def _cutoff(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _is_old(ts: str | None, cutoff: str) -> bool:
    return bool(ts) and ts < cutoff


def run_cleanup(older_than_days: int, apply: bool, include_orphans: bool) -> dict:
    settings = get_settings()
    cutoff = _cutoff(older_than_days)
    summary = {"temp_files_purged": 0, "bytes_freed": 0, "orphans_found": 0, "orphans_deleted": 0, "dry_run": not apply}
    referenced: set[str] = set()

    with session_scope() as db:
        arts = db.execute(select(Artifact)).scalars().all()
        for a in arts:
            referenced.add(a.storage_key)
            if a.kind in TEMPORARY_KINDS and _is_old(a.created_at, cutoff):
                path = Path(a.storage_key)
                if path.exists():
                    size = path.stat().st_size
                    if apply:
                        path.unlink(missing_ok=True)
                        a.meta = {**a.meta, "purged": True, "purged_at": now_iso()}
                    summary["temp_files_purged"] += 1
                    summary["bytes_freed"] += size
        db.commit()

        jobs_root = settings.data_dir / "jobs"
        if include_orphans and jobs_root.exists():
            for file in jobs_root.rglob("*"):
                if file.is_file() and str(file) not in referenced:
                    if "_thumb_frame" in file.name or file.suffix == ".txt":
                        pass
                    summary["orphans_found"] += 1
                    mtime = datetime.fromtimestamp(file.stat().st_mtime, UTC).isoformat()
                    if _is_old(mtime, cutoff):
                        summary["orphans_deleted"] += 1
                        if apply:
                            file.unlink(missing_ok=True)

        if apply:
            audit(db, "system", "lifecycle.cleanup", "storage", "jobs-root", summary)
    return summary
