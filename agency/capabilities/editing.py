from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger("agency.editing")


@dataclass
class Clip:
    src: str
    start: float = 0.0
    end: float = 0.0
    kind: str = "video"
    effects: dict = field(default_factory=dict)


@dataclass
class Track:
    type: str
    clips: list[Clip] = field(default_factory=list)


@dataclass
class TimelineEDL:
    fps: float = 30.0
    width: int = 1920
    height: int = 1080
    tracks: list[Track] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"fps": self.fps, "width": self.width, "height": self.height, "tracks": [{"type": t.type, "clips": [asdict(c) for c in t.clips]} for t in self.tracks]}

    @classmethod
    def from_dict(cls, data: dict) -> TimelineEDL:
        tl = cls(fps=data.get("fps", 30.0), width=data.get("width", 1920), height=data.get("height", 1080))
        for t in data.get("tracks", []):
            track = Track(type=t.get("type", "video"))
            for c in t.get("clips", []):
                track.clips.append(Clip(**{k: v for k, v in c.items() if k in Clip.__dataclass_fields__}))
            tl.tracks.append(track)
        return tl

    def duration(self) -> float:
        total = 0.0
        for t in self.tracks:
            if t.type == "video":
                total = max(total, sum(c.end - c.start for c in t.clips))
        return round(total, 3)

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.fps <= 0 or self.width <= 0 or self.height <= 0:
            problems.append("invalid timeline geometry")
        for ti, t in enumerate(self.tracks):
            cursor = 0.0
            for ci, c in enumerate(t.clips):
                if c.end <= c.start:
                    problems.append(f"track {ti} clip {ci}: non-positive duration")
                if t.type == "video":
                    cursor += c.end - c.start
                src_path = c.src
                if src_path and not Path(src_path).exists():
                    problems.append(f"track {ti} clip {ci}: missing source {src_path}")
        return problems


def apply_silence_cut(word_timings: list[dict], narration_duration: float, keep_pad: float = 0.12, min_silence: float = 0.45) -> tuple[list[tuple[float, float]], list[dict]]:
    silences: list[tuple[float, float]] = []
    sorted_words = sorted(word_timings, key=lambda w: w["start"])
    prev_end = 0.0
    for w in sorted_words:
        gap_start, gap_end = prev_end, float(w["start"])
        if gap_end - gap_start >= min_silence:
            silences.append((gap_start, gap_end))
        prev_end = max(prev_end, float(w["end"]))
    if narration_duration - prev_end >= min_silence:
        silences.append((prev_end, narration_duration))

    keep_ranges: list[tuple[float, float]] = []
    cut_cursor = 0.0
    removed_total = 0.0
    for gs, ge in silences:
        keep_end = gs - keep_pad * 0.5 if gs - cut_cursor > 0.05 else gs
        if keep_end > cut_cursor:
            keep_ranges.append((cut_cursor, keep_end))
        removed = ge - gs - keep_pad
        if removed > 0:
            removed_total += removed
        cut_cursor = ge - keep_pad * 0.5
    if narration_duration > cut_cursor + 0.05:
        keep_ranges.append((cut_cursor, narration_duration))

    new_words: list[dict] = []
    for w in sorted_words:
        offset = sum(max(ge - gs - keep_pad, 0.0) for gs, ge in silences if ge <= w["start"])
        float(w["end"]) - float(w["start"])
        new_words.append({"word": w["word"], "start": round(float(w["start"]) - offset, 3), "end": round(float(w["end"]) - offset, 3)})
    return keep_ranges, new_words


def scene_clip_plan(scenes: list[dict], images: list[Path]) -> list[dict]:
    plan: list[dict] = []
    if len(images) != len(scenes):
        images = [images[i % len(images)] if images else None for i in range(len(scenes))]
    for scene, img in zip(scenes, images, strict=False):
        plan.append({"scene_id": scene.get("id"), "image": str(img) if img else "", "duration": float(scene.get("duration_s", 4.0)), "title": scene.get("title", "")})
    return plan
