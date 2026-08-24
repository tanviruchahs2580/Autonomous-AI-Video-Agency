from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger("agency.captions")

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{fontsize},&H00FFFFFF,&H00FFFFFF,&H00101418,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,{margin_l},{margin_r},{margin_v},1
Style: CaptionSafe,{font},{fontsize},&H00FFFFFF,&H00FFFFFF,&H00101418,&H80000000,-1,0,0,0,100,100,0,0,3,10,0,2,{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(seconds: float) -> str:
    seconds = max(seconds, 0)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def group_words_into_cues(words: list[dict], max_chars: int = 42, max_dur: float = 3.2, max_words: int = 8) -> list[dict]:
    cues: list[dict] = []
    current: list[dict] = []
    chars = 0
    for w in words:
        prospective_chars = chars + len(w["word"]) + (1 if current else 0)
        dur = w["end"] - current[0]["start"] if current else w["end"] - w["start"]
        if current and (prospective_chars > max_chars or len(current) >= max_words or dur > max_dur):
            cues.append({"start": current[0]["start"], "end": current[-1]["end"], "text": " ".join(x["word"] for x in current)})
            current = []
            chars = 0
        current.append(w)
        chars = chars + len(w["word"]) + (1 if chars else 0)
    if current:
        cues.append({"start": current[0]["start"], "end": current[-1]["end"], "text": " ".join(x["word"] for x in current)})
    for i, cue in enumerate(cues):
        next_start = cues[i + 1]["start"] if i + 1 < len(cues) else cue["end"]
        cue["end"] = min(max(cue["end"], cue["start"] + 0.4), max(next_start, cue["start"] + 0.4))
    return cues


def build_ass(
    dst: Path,
    words: list[dict],
    width: int,
    height: int,
    safe_zone_pct: float = 0.08,
    font_size_ratio: float = 0.042,
    font_name: str = "Arial",
) -> Path:
    margin_v = int(height * safe_zone_pct)
    margin_lr = int(width * safe_zone_pct)
    fontsize = int(height * font_size_ratio)
    header = ASS_HEADER.format(width=width, height=height, font=font_name, fontsize=fontsize, margin_l=margin_lr, margin_r=margin_lr, margin_v=margin_v)
    lines = [header]
    for cue in group_words_into_cues(words):
        text = re.sub(r"\{[^}]*\}", "", cue["text"])
        lines.append(f"Dialogue: 0,{_ts(cue['start'])},{_ts(cue['end'])},Caption,,0,0,0,,{text}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(lines), encoding="utf-8")
    return dst


def build_srt(dst: Path, words: list[dict]) -> Path:
    def srt_ts(seconds: float) -> str:
        ms = int(round(seconds * 1000))
        h, rem = divmod(ms, 3600000)
        m, rem = divmod(rem, 60000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    blocks = []
    for i, cue in enumerate(group_words_into_cues(words), 1):
        blocks.append(f"{i}\n{srt_ts(cue['start'])} --> {srt_ts(cue['end'])}\n{cue['text']}\n")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(blocks), encoding="utf-8")
    return dst


def validate_captions(words: list[dict], media_duration: float, video_height: int) -> dict:
    findings: list[str] = []
    ok = True
    if not words:
        return {"passed": False, "findings": ["no caption cues generated"]}
    last_end = float(words[-1]["end"])
    if last_end > media_duration + 0.5:
        ok = False
        findings.append(f"captions overrun media duration ({last_end:.2f}s > {media_duration:.2f}s)")
    for i in range(len(words) - 1):
        if words[i]["start"] > words[i + 1]["start"]:
            ok = False
            findings.append(f"non-monotonic caption timing at word {i}")
            break
    cues = group_words_into_cues(words)
    cps_values = []
    for cue in cues:
        dur = max(cue["end"] - cue["start"], 0.01)
        cps_values.append(len(cue["text"]) / dur)
        if len(cue["text"]) / dur > 20:
            findings.append(f"cue too fast: {cue['text'][:30]!r} at {len(cue['text']) / dur:.1f} cps")
            break
    avg_cps = sum(cps_values) / len(cps_values)
    if video_height < 720 and len(cues) and max(len(c["text"]) for c in cues) > 60:
        findings.append("caption lines may be unreadable at low resolution")
    return {"passed": ok, "findings": findings, "cues": len(cues), "avg_cps": round(avg_cps, 2)}
