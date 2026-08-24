from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np

from ..capabilities.captions import build_ass, build_srt, validate_captions
from ..capabilities.editing import TimelineEDL, apply_silence_cut
from ..capabilities.graphics import (
    dominant_colors,
    palette_distance,
    palette_from_brand,
    render_lower_third,
    render_scene_image,
    render_thumbnail,
    render_title_card,
)
from ..capabilities.media import (
    MediaError,
    assert_playable,
    burn_subtitles,
    color_grade,
    concat_videos,
    extract_audio,
    loudness_measure,
    loudness_normalize,
    mix_audio,
    mux_av,
    probe,
    render_image_clip,
)
from ..capabilities.router import route
from ..capabilities.tts import SynthTTSProvider, generate_music_bed, get_tts_provider, write_wav
from ..config import get_settings
from ..models import (
    Artifact,
    Deliverable,
    Job,
    Project,
    QAReport,
    ScriptVersion,
    Storyboard,
    Task,
    Timeline,
    now_iso,
)
from ..observability import emit_event, record_cost
from ..workflow.engine import HandlerFn, TaskFailure

logger = logging.getLogger("agency.stages")

PLATFORM_SPECS: dict[str, dict] = {
    "youtube": {"width": 1920, "height": 1080, "fps": 30.0, "variants": ["16:9"]},
    "youtube_shorts": {"width": 1080, "height": 1920, "fps": 30.0, "variants": ["9:16"]},
    "tiktok": {"width": 1080, "height": 1920, "fps": 30.0, "variants": ["9:16"]},
    "instagram_reels": {"width": 1080, "height": 1920, "fps": 30.0, "variants": ["9:16"]},
    "instagram_feed": {"width": 1080, "height": 1080, "fps": 30.0, "variants": ["1:1", "4:5"]},
    "linkedin": {"width": 1920, "height": 1080, "fps": 30.0, "variants": ["16:9", "1:1"]},
}


class ApprovalRequired(Exception):
    pass


def job_workdir(job_id: str) -> Path:
    settings = get_settings()
    workdir = settings.data_dir / "jobs" / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


def register_artifact(
    db,
    project_id: str | None,
    job_id: str | None,
    task_id: str | None,
    kind: str,
    path: Path,
    metadata: dict | None = None,
    provenance: dict | None = None,
) -> Artifact:
    art = Artifact(
        project_id=project_id,
        job_id=job_id,
        task_id=task_id,
        kind=kind,
        storage_key=str(path),
        sha256=None,
        bytes=path.stat().st_size if path.exists() else None,
        metadata_json=json.dumps(metadata or {}),
        provenance_json=json.dumps(provenance or {}),
    )
    db.add(art)
    db.commit()
    return art


def stage_intake(db, job: Job, task: Task, context: dict) -> dict:
    brief = context["payload"].get("brief") or {}
    required = ["title", "objective"]
    missing = [f for f in required if not brief.get(f)]
    if missing:
        raise TaskFailure(f"brief missing required fields: {missing}", failure_class="invalid_brief")
    platform = str(brief.get("platform", "youtube")).lower()
    spec_platform = PLATFORM_SPECS.get(platform, PLATFORM_SPECS["youtube"])
    duration = float(brief.get("duration_s", 45))
    if not 5 <= duration <= 3600:
        raise TaskFailure(f"duration {duration}s outside supported range", failure_class="invalid_brief")
    width = int(brief.get("width") or spec_platform["width"])
    height = int(brief.get("height") or spec_platform["height"])
    fps = float(brief.get("fps") or spec_platform["fps"])
    if width % 2 or height % 2:
        raise TaskFailure("width/height must be even for h264 output", failure_class="invalid_brief")
    settings_caps = get_settings()
    if duration > float(settings_caps.media_max_duration_s):
        raise TaskFailure(f"duration {duration}s exceeds platform cap {settings_caps.media_max_duration_s}s", failure_class="invalid_brief")
    if width > int(settings_caps.media_max_width) or height > int(settings_caps.media_max_height):
        raise TaskFailure(f"resolution {width}x{height} exceeds platform cap", failure_class="invalid_brief")
    if duration > float(settings_caps.media_max_duration_s):
        raise TaskFailure(f"duration {duration}s exceeds platform cap {settings_caps.media_max_duration_s}s", failure_class="invalid_brief")
    if width > int(settings_caps.media_max_width) or height > int(settings_caps.media_max_height):
        raise TaskFailure(f"resolution {width}x{height} exceeds platform cap", failure_class="invalid_brief")
    spec = {
        "title": str(brief["title"])[:200],
        "objective": str(brief["objective"])[:2000],
        "audience": str(brief.get("audience", "general"))[:300],
        "platform": platform,
        "resolution": {"width": width, "height": height, "fps": fps},
        "duration_s": duration,
        "brand": brief.get("brand", {}),
        "language": brief.get("language", "en"),
        "cta": str(brief.get("cta", "Learn more")) [:200],
        "key_points": [str(k)[:300] for k in brief.get("key_points", [])][:8],
    }
    project = db.get(Project, job.project_id)
    if project is not None:
        project.spec = spec
        project.status = "in_production"
        project.updated_at = now_iso()
        db.commit()
    context["state"]["ctx_spec"] = spec
    return {"ctx_spec": spec, "message": f"brief validated for {platform}"}


def stage_research(db, job: Job, task: Task, context: dict) -> dict:
    spec = context["state"].get("ctx_spec")
    if not spec:
        raise TaskFailure("spec missing", failure_class="state_missing")
    points = [str(k)[:300] for k in spec.get("key_points", [])][:6]
    if not points:
        keywords = [w.strip(",.?!").lower() for w in spec["objective"].split() if len(w) > 4]
        seen: list[str] = []
        for kw in keywords:
            if kw not in seen:
                seen.append(kw)
            if len(seen) >= 5:
                break
        points = [f"Highlight: {kw}" for kw in seen]
    else:
        obj_words = [w.strip(",.?!").lower() for w in spec["objective"].split() if len(w) > 4 and w.lower() not in STOPWORDS]
        added = 0
        for ow in obj_words:
            if added >= 2:
                break
            candidate = f"Focus on {ow}"
            if not any(ow in p.lower() for p in points):
                points.append(candidate)
                added += 1
    claims = []
    for p in points:
        if any(ch.isdigit() for ch in p):
            claims.append({"claim": p, "status": "needs_verification", "note": "numeric claim detected"})
        else:
            claims.append({"claim": p, "status": "unverified_general", "note": ""})
    research = {"points": points, "claims": claims, "sources_required_for_claims": bool(claims)}
    context["state"]["ctx_research"] = research
    return {"ctx_research": research, "points": len(points)}


def stage_creative_direction(db, job: Job, task: Task, context: dict) -> dict:
    spec = context["state"]["ctx_spec"]
    brand = spec.get("brand", {})
    palette = palette_from_brand(brand) if brand else None
    audience = spec.get("audience", "").lower()
    mood = "calm" if any(w in audience for w in ("enterprise", "professional", "finance")) else ("tense" if "alert" in spec["objective"].lower() else "uplifting")
    creative = {
        "concept": f"{spec['title']} - {spec['objective'][:120]}",
        "tone": "confident, clear, benefit-led",
        "palette_hex": ["#{:02x}{:02x}{:02x}".format(*c) for c in (palette or [(16, 24, 32), (31, 111, 235), (242, 247, 250)])],
        "music_mood": mood,
    }
    palette_final = palette or [(16, 24, 32), (31, 111, 235), (242, 247, 250)]
    palette_hex_list = [f"#{p[0]:02x}{p[1]:02x}{p[2]:02x}" for p in palette_final]
    context["state"]["ctx_creative"] = creative
    context["state"]["ctx_palette"] = palette_hex_list
    return {"ctx_creative": creative, "ctx_palette": palette_hex_list}


def _palette_tuples(context: dict) -> list[tuple[int, int, int]]:
    from ..capabilities.graphics import hex_to_rgb

    raw = context["state"].get("ctx_palette") or ["#101820", "#1F6FEB", "#F2F7FA"]
    out: list[tuple[int, int, int]] = []
    for item in raw:
        if isinstance(item, str):
            rgb = hex_to_rgb(item)
            out.append((int(rgb[0]), int(rgb[1]), int(rgb[2])))
        else:
            out.append((int(item[0]), int(item[1]), int(item[2])))
    return out


def _compose_script_local(spec: dict, research: dict) -> dict:
    title = spec["title"]
    audience = spec["audience"]
    cta = spec.get("cta", "Learn more")
    short_form = float(spec.get("duration_s", 30)) < 10
    points = research.get("points") or []
    hook = f"Meet {title}." if short_form else f"If you work with {audience}, this changes everything: {title}."
    max_beats = 2 if short_form else 3
    if short_form and len(points) > 2:
        focus = next((p for p in points[2:] if p.lower().startswith("focus")), points[-1])
        selected = [points[0], focus]
    else:
        selected = points[:max_beats]
    beats = []
    for i, p in enumerate(selected, 1):
        beats.append({"label": f"Beat {i}", "text": f"{p}."})
    while len(beats) < 2:
        beats.append({"label": f"Beat {len(beats) + 1}", "text": f"See how {title.lower()} delivers results."})
    body = " ".join(b["text"] for b in beats)
    close = f"Ready? {cta}." if not cta.lower().endswith("today") else f"Ready? {cta}"
    sections = {"hook": hook, "beats": beats, "cta": close}
    full_text = f"{hook} {body} {close}"
    return {"sections": sections, "full_text": full_text, "generator": "template-composer-v1"}


def _compose_script_llm(spec: dict, research: dict) -> dict | None:
    candidate, reasons = route("text")
    if candidate is None or candidate.provider != "openai":
        return None
    from ..config import get_settings

    settings = get_settings()
    prompt = (
        "You are an expert short-form video scriptwriter.\n"
        f"Title: {spec['title']}\nObjective: {spec['objective']}\nAudience: {spec['audience']}\n"
        f"Key points: {json.dumps(research.get('points', []))}\nCTA: {spec.get('cta')}\n"
        "Write a narration script with sections HOOK, BODY_BEATS (2-3), CTA. "
        "Return strict JSON: {\"hook\": str, \"beats\": [{\"label\": str, \"text\": str}], \"cta\": str}"
    )
    try:
        resp = httpx_post_json(
            f"{settings.openai_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            payload={"model": candidate.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.7, "response_format": {"type": "json_object"}},
            timeout=30,
        )
        content = resp["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        sections = {"hook": parsed["hook"], "beats": parsed["beats"], "cta": parsed["cta"]}
        full_text = " ".join([sections["hook"]] + [b["text"] for b in sections["beats"]] + [sections["cta"]])
        return {"sections": sections, "full_text": full_text, "generator": candidate.model}
    except Exception as exc:
        logger.warning("llm script generation failed: %s", exc)
        return None


def httpx_post_json(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    import httpx

    r = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _enforce_word_budget(composed: dict, spec: dict) -> dict:
    budget = max(int(spec["duration_s"] * 2.0), 14)
    sections = composed["sections"]
    beats = list(sections["beats"])

    def count(text: str) -> int:
        return len(text.split())

    hook_w = count(sections["hook"])
    cta_w = count(sections["cta"])
    fixed = hook_w + cta_w
    avail_for_beats = max(budget - fixed, 6)
    trimmed = False
    while sum(count(b["text"]) for b in beats) > avail_for_beats and len(beats) > 2:
        beats.pop()
        trimmed = True
    per_beat = max(avail_for_beats // max(len(beats), 1), 2)
    for b in beats:
        words_b = b["text"].split()
        if len(words_b) > per_beat:
            b["text"] = " ".join(words_b[:per_beat]).rstrip(",;:.") + "."
            trimmed = True
    sections["beats"] = beats
    body = " ".join(b["text"] for b in beats)
    composed["full_text"] = f"{sections['hook']} {body} {sections['cta']}"
    if trimmed:
        composed["trimmed_to_budget"] = True
    return composed


def stage_script_writing(db, job: Job, task: Task, context: dict) -> dict:
    spec = context["state"]["ctx_spec"]
    research = context["state"].get("ctx_research", {})
    composed = _compose_script_llm(spec, research) or _compose_script_local(spec, research)
    composed = _enforce_word_budget(composed, spec)
    len(composed["full_text"].split())
    version_number = 1 + db.query(ScriptVersion.version).filter_by(project_id=job.project_id).count()
    sv = ScriptVersion(project_id=job.project_id, version=version_number, content_json=json.dumps(composed))
    db.add(sv)
    db.commit()
    context["state"]["ctx_script"] = composed
    return {"ctx_script": composed, "words": len(composed["full_text"].split()), "version": version_number, "generator": composed["generator"]}


def stage_storyboard(db, job: Job, task: Task, context: dict) -> dict:
    spec = context["state"]["ctx_spec"]
    script = context["state"]["ctx_script"]
    sections = script["sections"]
    beat_texts = [b["text"] for b in sections["beats"]]
    scene_texts = [sections["hook"], *beat_texts, sections["cta"]]
    len(scene_texts)
    weights = np.array([max(len(t.split()), 3) for t in scene_texts], dtype=float)
    total_target = spec["duration_s"]
    durations = (weights / weights.sum()) * total_target
    min_dur = 1.6
    durations = np.maximum(durations, min_dur)
    scale = total_target / durations.sum()
    durations = np.maximum(durations * scale, min_dur * 0.95)
    titles = ["Hook", *[f"Point {i + 1}" for i in range(len(beat_texts))], "Call to Action"]
    scenes = []
    for i, (text, dur, title) in enumerate(zip(scene_texts, durations, titles, strict=False)):
        scenes.append({"id": f"scene_{i + 1:02d}", "title": title, "narration": text, "duration_s": round(float(dur), 2), "style_seed": i})
    sb = Storyboard(project_id=job.project_id, scenes_json=json.dumps(scenes))
    db.add(sb)
    db.commit()
    context["state"]["ctx_scenes"] = scenes
    return {"ctx_scenes": scenes, "scene_count": len(scenes)}


def stage_asset_acquisition(db, job: Job, task: Task, context: dict) -> dict:
    spec = context["state"]["ctx_spec"]
    palette = _palette_tuples(context)
    workdir = job_workdir(job.id)
    images_dir = workdir / "images"
    scenes = context["state"]["ctx_scenes"]
    external_assets = context["payload"].get("assets", [])
    usable_external = []
    rejected = []
    for entry in external_assets:
        state = str(entry.get("license_state", "unknown")).lower()
        if state in {"owned", "licensed", "public_domain", "cc0", "generated"}:
            usable_external.append(entry)
        else:
            rejected.append({"source_uri": entry.get("uri"), "reason": f"license_state={state}: unknown rights are never treated as commercial-safe"})
    image_paths = []
    for scene in scenes:
        img_path = images_dir / f"{scene['id']}.png"
        render_scene_image(
            dst=img_path,
            width=int(spec["resolution"]["width"]),
            height=int(spec["resolution"]["height"]),
            title=scene["title"],
            subtitle=spec["title"],
            palette=palette,
            style_seed=scene.get("style_seed", 0),
        )
        register_artifact(db, job.project_id, job.id, task.id, "generated_image", img_path, {"scene": scene["id"]}, {"origin": "procedural-generator", "tool": "pillow-scene-renderer-v1", "license": "generated-in-house"})
        image_paths.append(img_path)
    context["state"]["ctx_images"] = image_paths
    context["state"]["ctx_assets_meta"] = {"usable_external": usable_external, "rejected_unknown_rights": rejected}
    if rejected:
        emit_event(db, job.id, task.id, "warning", "assets.rights_rejected", {"count": len(rejected)}, org_id=job.org_id)
    return {
        "ctx_images": [str(p) for p in image_paths],
        "ctx_assets_meta": context["state"]["ctx_assets_meta"],
        "ctx_images_count": len(image_paths),
        "external_used": len(usable_external),
        "rejected_unknown_rights": len(rejected),
    }


def _synthesize_narration(spec: dict, scenes: list[dict], workdir: Path) -> tuple[Path, list[dict], str, str]:
    from ..capabilities.media import extract_audio

    preferred = get_settings().tts_provider
    provider, fallback_reason = get_tts_provider(preferred)
    segments_dir = workdir / "narration_segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    combined_words: list[dict] = []
    cursor = 0.0
    seg_wavs: list[Path] = []
    for scene in scenes:
        result = None
        try:
            result = provider.synthesize(scene["narration"], segments_dir / f"{scene['id']}_raw.audio")
        except Exception as exc:
            logger.warning("tts provider %s failed for %s (%s); downgrading", getattr(provider, 'name', '?'), scene["id"], exc)
            provider = SynthTTSProvider()
            fallback_reason = f"{getattr(provider, 'name', 'provider')} unavailable: {exc}"
            result = provider.synthesize(scene["narration"], segments_dir / f"{scene['id']}.wav")
        raw = Path(result.path)
        if raw.suffix.lower() != ".wav":
            wav_path = raw.with_suffix(".wav")
            extract_audio(raw, wav_path, sample_rate=24000)
        else:
            wav_path = raw
        from ..capabilities.media import probe as _probe

        dur = _probe(wav_path).duration_s
        words = _align_words_to_duration(scene["narration"], result.words, dur)
        for w in words:
            combined_words.append({"word": w["word"], "start": round(float(w["start"]) + cursor, 3), "end": round(float(w["end"]) + cursor, 3)})
        cursor += dur + 0.28
        seg_wavs.append(wav_path)
    merged = merge_wavs(seg_wavs, gap_s=0.28, out_path=workdir / "narration_full.wav")
    return merged, combined_words, getattr(provider, "name", provider.__class__.__name__), fallback_reason or ""


def _align_words_to_duration(text: str, words: list[dict], duration: float) -> list[dict]:
    if words and abs(words[-1]["end"] - duration) <= max(0.5, duration * 0.15):
        return words
    import numpy as np

    tokens = text.split()
    weights = np.array([len(t) + 2.2 for t in tokens], dtype=float)
    total = float(weights.sum()) or 1.0
    spans = (weights / total) * duration
    out = []
    cursor = 0.0
    for tok, span in zip(tokens, spans, strict=False):
        out.append({"word": tok, "start": round(cursor, 3), "end": round(cursor + span - 0.01, 3)})
        cursor += span
    return out


def merge_wavs(paths: list[Path], gap_s: float, out_path: Path) -> Path:
    import wave

    arrays = []
    sr = None
    for p in paths:
        with wave.open(str(p), "rb") as wf:
            sr = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
            dtype = np.int16
            arr = np.frombuffer(frames, dtype=dtype)
            arrays.append(arr.astype(np.float32))
    gap = np.zeros(int(gap_s * (sr or 24000)), dtype=np.float32)
    pieces: list[np.ndarray] = []
    for i, a in enumerate(arrays):
        pieces.append(a)
        if i < len(arrays) - 1:
            pieces.append(gap)
    merged = np.concatenate(pieces)
    peak = float(np.max(np.abs(merged))) or 1.0
    merged = merged / peak * 0.88
    return write_wav(out_path, merged, sample_rate=sr or 24000)


def stage_narration(db, job: Job, task: Task, context: dict) -> dict:
    spec = context["state"]["ctx_spec"]
    scenes = context["state"]["ctx_scenes"]
    workdir = job_workdir(job.id)
    time.monotonic()
    path, words, provider_name, fallback_reason = _synthesize_narration(spec, scenes, workdir)
    info = probe(path)
    register_artifact(db, job.project_id, job.id, task.id, "narration_audio", path, {"provider": provider_name, "duration_s": info.duration_s}, {"origin": "tts", "provider": provider_name, "license": "generated-in-house"})
    record_cost(db, job.project_id, job.id, task.id, "tts", provider_name, model="", quantity=info.duration_s, unit="seconds", amount_usd=0.0 if provider_name.startswith(("synth", "edge")) else info.duration_s * 0.0002, org_id=job.org_id)

    narration_state = {"path": str(path), "duration": info.duration_s, "words": words, "provider": provider_name}
    context["state"]["ctx_narration"] = narration_state
    out = {"ctx_narration_provider": provider_name, "duration": info.duration_s, "word_count": len(words), "ctx_narration": narration_state}
    if fallback_reason:
        out["fallback_reason"] = fallback_reason
    return out


def stage_autocleanup(db, job: Job, task: Task, context: dict) -> dict:
    narration = context["state"].get("ctx_narration")
    if not narration:
        raise TaskFailure("narration missing", failure_class="state_missing")
    workdir = job_workdir(job.id)
    src = Path(narration["path"])
    keep_ranges, new_words = apply_silence_cut(narration["words"], narration["duration"], keep_pad=0.14, min_silence=0.42)
    dst = workdir / "narration_clean.wav"
    if len(keep_ranges) <= 1:
        import shutil

        shutil.copyfile(src, dst)
        removed = 0.0
        clean_words = narration["words"]
    else:
        from ..capabilities.media import cut_segments

        cut_segments(src, dst, keep_ranges, has_audio=True)
        removed = round(narration["duration"] - probe(dst).duration_s, 3)
        clean_words = new_words
    info = probe(dst)
    cleanup_state = {"path": str(dst), "duration": info.duration_s, "words": clean_words}
    register_artifact(db, job.project_id, job.id, task.id, "cleaned_narration", dst, {"removed_s": removed}, {"origin": "derived", "from": "narration_full.wav"})
    return {"removed_silence_s": removed, "kept_ranges": len(keep_ranges), "final_duration": info.duration_s, "ctx_cleanup": cleanup_state}


def stage_editorial_assembly(db, job: Job, task: Task, context: dict) -> dict:
    spec = context["state"]["ctx_spec"]
    scenes = context["state"]["ctx_scenes"]
    images = context["state"]["ctx_images"]
    cleanup = context["state"].get("ctx_cleanup") or context["state"]["ctx_narration"]
    total_audio = float(cleanup["duration"])
    planned_total = sum(s["duration_s"] for s in scenes)
    scale = total_audio / planned_total
    clips_dir = job_workdir(job.id) / "scene_clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    clip_paths = []
    edl_scenes = []
    for scene, img in zip(scenes, images, strict=False):
        dur = max(round(scene["duration_s"] * scale, 3), 1.0)
        clip_path = clips_dir / f"{scene['id']}.mp4"
        render_image_clip(
            image=img,
            dst=clip_path,
            duration=dur,
            width=int(spec["resolution"]["width"]),
            height=int(spec["resolution"]["height"]),
            fps=float(spec["resolution"]["fps"]),
            zoom=1.06 + 0.02 * (scene.get("style_seed", 0) % 2),
        )
        clip_paths.append(clip_path)
        edl_scenes.append({"id": scene["id"], "src": str(img), "duration": dur})
    tl = TimelineEDL(fps=float(spec["resolution"]["fps"]), width=int(spec["resolution"]["width"]), height=int(spec["resolution"]["height"]))
    from ..capabilities.editing import Clip as EdlClip
    from ..capabilities.editing import Track as EdlTrack

    track = EdlTrack(type="video")
    t_cursor = 0.0
    for sc in edl_scenes:
        track.clips.append(EdlClip(src=sc["src"], start=t_cursor, end=t_cursor + sc["duration"]))
        t_cursor += sc["duration"]
    tl.tracks.append(track)
    problems = tl.validate()
    if problems:
        raise TaskFailure(f"timeline invalid: {problems}", failure_class="invalid_timeline")
    tlrow = Timeline(project_id=job.project_id, version=1, edl_json=json.dumps(tl.to_dict()))
    db.add(tlrow)
    db.commit()
    context["state"]["ctx_scene_clips"] = clip_paths
    context["state"]["ctx_edl"] = tl.to_dict()
    clip_strs = [str(p) for p in clip_paths]
    return {"clips": len(clip_paths), "total_video_s": round(sum(s['duration'] for s in edl_scenes), 2), "scale_applied": round(scale, 3), "ctx_scene_clips": clip_strs, "ctx_edl": tl.to_dict()}


def stage_motion_graphics(db, job: Job, task: Task, context: dict) -> dict:
    spec = context["state"]["ctx_spec"]
    palette = _palette_tuples(context)
    scenes = context["state"]["ctx_scenes"]
    workdir = job_workdir(job.id) / "graphics"
    workdir.mkdir(parents=True, exist_ok=True)
    title_card = render_title_card(workdir / "title_card.png", int(spec["resolution"]["width"]), int(spec["resolution"]["height"]), spec["title"][:40], "Presented by " + str(spec.get("brand", {}).get("name", "the team"))[:40], palette)
    lower_third_scene = scenes[1] if len(scenes) > 1 else scenes[0]
    lt = render_lower_third(workdir / "lower_third.png", int(spec["resolution"]["width"]), int(spec["resolution"]["height"]), spec["title"][:60], str(spec.get("audience", ""))[:40], palette)
    offsets = {}
    cursor = 0.0
    for s in scenes:
        offsets[s["id"]] = cursor
        cursor += s["duration_s"]
    first_scene_len = scenes[0]["duration_s"]
    overlays = [
        {"path": str(title_card), "start": 0.0, "end": round(min(first_scene_len * 0.55, 3.0), 2), "mode": "full"},
        {"path": str(lt), "start": round(offsets[lower_third_scene["id"]] + 0.4, 2), "end": round(offsets[lower_third_scene["id"]] + min(lower_third_scene["duration_s"] - 0.4, 4.5), 2), "mode": "corner", "anchor_x": 0.06, "anchor_y": 0.78},
    ]
    overlays_persist = [{**o, "path": str(o["path"])} for o in overlays]
    register_artifact(db, job.project_id, job.id, task.id, "graphics_overlay", title_card, {}, {"origin": "procedural"})
    register_artifact(db, job.project_id, job.id, task.id, "graphics_overlay", lt, {}, {"origin": "procedural"})
    return {"overlays": len(overlays), "ctx_overlays": overlays_persist}


def stage_rough_concat(db, job: Job, task: Task, context: dict) -> dict:
    clips = [Path(p) for p in context["state"]["ctx_scene_clips"]]
    workdir = job_workdir(job.id)
    rough = workdir / "rough_cut.mp4"
    try:
        concat_videos(clips, rough)
    except MediaError as exc:
        raise TaskFailure(f"concat failed: {exc}", failure_class="ffmpeg_error") from exc
    info = probe(rough)
    rough_state = {"path": str(rough), "duration": info.duration_s}
    register_artifact(db, job.project_id, job.id, task.id, "rough_cut", rough, {"duration_s": info.duration_s}, {"origin": "derived"})
    return {"duration": info.duration_s, "resolution": f"{info.width}x{info.height}", "ctx_rough": rough_state}


def stage_audio_mix(db, job: Job, task: Task, context: dict) -> dict:
    context["state"]["ctx_spec"]
    cleanup = context["state"].get("ctx_cleanup") or context["state"]["ctx_narration"]
    creative = context["state"].get("ctx_creative") or {"music_mood": "uplifting"}
    workdir = job_workdir(job.id)
    narration_path = Path(cleanup["path"])
    total_dur = float(cleanup["duration"])
    music_path = workdir / "music_bed.wav"
    generate_music_bed(music_path, total_dur + 0.5, mood=creative.get("music_mood", "uplifting"))
    mixed_path = workdir / "audio_mixed.m4a"
    mix_audio([narration_path, music_path], [1.0, 0.22], mixed_path, total_duration=total_dur)
    normalized_path = workdir / "audio_final.m4a"
    target_lufs = get_settings().qa_target_lufs
    stats = loudness_normalize(mixed_path, normalized_path, target_lufs=float(target_lufs))
    audio_state = {"path": str(normalized_path), "duration": total_dur, "loudness_before": stats["before"]["input_i"]}
    register_artifact(db, job.project_id, job.id, task.id, "mixed_audio", normalized_path, stats, {"origin": "derived"})
    record_cost(db, job.project_id, job.id, task.id, "audio_processing", provider="local-deterministic", model="", quantity=total_dur, unit="seconds", amount_usd=0.0, org_id=job.org_id)
    return {"loudness_before": stats["before"]["input_i"], "target": target_lufs, "ctx_audio": audio_state}


def stage_av_mux(db, job: Job, task: Task, context: dict) -> dict:
    workdir = job_workdir(job.id)
    rough = Path(context["state"]["ctx_rough"]["path"])
    audio = Path(context["state"]["ctx_audio"]["path"])
    av_path = workdir / "av_no_captions.mp4"
    try:
        mux_av(rough, audio, av_path, shortest=False)
    except MediaError as exc:
        raise TaskFailure(f"mux failed: {exc}", failure_class="qa_sync") from exc
    info = probe(av_path)
    v_dur = info.duration_s
    a_probe = probe(audio)
    if abs(v_dur - a_probe.duration_s) > 1.5:
        raise TaskFailure(f"av drift {abs(v_dur - a_probe.duration_s):.2f}s exceeds tolerance", failure_class="qa_sync")
    av_state = {"path": str(av_path), "duration": v_dur}
    register_artifact(db, job.project_id, job.id, task.id, "av_intermediate", av_path, {"duration_s": v_dur}, {"origin": "derived"})
    return {"duration": v_dur, "ctx_av": av_state}


def stage_burn_captions(db, job: Job, task: Task, context: dict) -> dict:
    spec = context["state"]["ctx_spec"]
    cleanup = context["state"].get("ctx_cleanup") or context["state"]["ctx_narration"]
    workdir = job_workdir(job.id)
    av = Path(context["state"]["ctx_av"]["path"])
    ass_path = workdir / "captions.ass"
    srt_path = workdir / "captions.srt"
    build_ass(ass_path, cleanup["words"], int(spec["resolution"]["width"]), int(spec["resolution"]["height"]))
    build_srt(srt_path, cleanup["words"])
    captioned = workdir / "captioned.mp4"
    try:
        burn_subtitles(av, ass_path, captioned)
    except MediaError as exc:
        raise TaskFailure(f"caption burn failed: {exc}", failure_class="ffmpeg_error") from exc
    context["state"]["ctx_captioned"] = {"path": str(captioned)}
    context["state"]["ctx_caption_files"] = {"ass": str(ass_path), "srt": str(srt_path)}
    register_artifact(db, job.project_id, job.id, task.id, "captions_sidecar", srt_path, {"format": "srt"}, {"origin": "derived"})
    return {"captions_burned": True, "ctx_captioned": {"path": str(captioned)}, "ctx_caption_files": {"ass": str(ass_path), "srt": str(srt_path)}}


def stage_color_grade(db, job: Job, task: Task, context: dict) -> dict:
    workdir = job_workdir(job.id)
    captioned = Path(context["state"]["ctx_captioned"]["path"])
    master = workdir / "master.mp4"
    try:
        color_grade(captioned, master, saturation=1.05, contrast=1.03)
    except MediaError as exc:
        raise TaskFailure(f"grade failed: {exc}", failure_class="ffmpeg_error") from exc
    info = probe(master)
    master_state = {"path": str(master), "duration": info.duration_s, "width": info.width, "height": info.height}
    register_artifact(db, job.project_id, job.id, task.id, "master_render", master, {"duration_s": info.duration_s, "resolution": f"{info.width}x{info.height}", "codec": info.video_codec}, {"origin": "derived"})
    return {"master": str(master.name), "duration": info.duration_s, "ctx_master": master_state}


def _extract_frame(video: Path, at_s: float, dst: Path) -> Path:
    from ..capabilities.media import run_ffmpeg

    run_ffmpeg(["-ss", f"{at_s:.2f}", "-i", str(video), "-frames:v", "1", "-y", str(dst)])
    return dst


def stage_technical_qa(db, job: Job, task: Task, context: dict) -> dict:
    spec = context["state"]["ctx_spec"]
    master_info = context["state"]["ctx_master"]
    master = Path(master_info["path"])
    findings: list[str] = []
    failed_classes: set[str] = set()

    def check(ok: bool, msg: str, cls: str) -> None:
        if not ok:
            findings.append(msg)
            failed_classes.add(cls)

    try:
        info = probe(master)
    except MediaError as exc:
        raise TaskFailure(f"probe failed: {exc}", failure_class="corrupt_media") from exc
    check(info.container.startswith("mov") or "mp4" in info.container, f"container {info.container} not mp4-family", "qa_container")
    check(info.video_codec == "h264", f"video codec {info.video_codec} != h264", "qa_codec")
    check(info.audio_codec in ("aac",), f"audio codec {info.audio_codec} != aac", "qa_codec")
    check((info.width, info.height) == (int(spec["resolution"]["width"]), int(spec["resolution"]["height"])), f"resolution {info.width}x{info.height} != spec", "qa_resolution")
    check(abs((info.fps or 0) - float(spec["resolution"]["fps"])) <= 0.6, f"fps {info.fps} != spec", "qa_fps")
    target = float(spec["duration_s"])
    check(target * 0.65 <= info.duration_s <= target * 1.45, f"duration {info.duration_s:.1f}s outside tolerance of {target}s", "qa_duration")
    check(info.has_audio and info.channels == 2, f"audio channels {info.channels} != stereo", "qa_audio")
    try:
        assert_playable(master)
    except MediaError as exc:
        raise TaskFailure(f"decode failed: {exc}", failure_class="corrupt_media") from exc
    workdir = job_workdir(job.id)
    audio_only = workdir / "qa_audio.wav"
    extract_audio(master, audio_only)
    loud = loudness_measure(audio_only)
    target_lufs = float(get_settings().qa_target_lufs)
    check(abs(loud["input_i"] - target_lufs) <= 3.0, f"loudness {loud['input_i']:.1f} LUFS deviates from target {target_lufs}", "qa_loudness")
    check(loud["input_tp"] <= -0.3, f"true peak {loud['input_tp']:.2f} dBTP too hot", "qa_loudness")
    passed = not findings
    report = QAReport(project_id=job.project_id, job_id=job.id, task_id=task.id, layer="technical", passed=passed, score=1.0 if passed else 0.0, findings=findings)
    db.add(report)
    db.commit()
    context["state"].setdefault("qa_summary", {})["technical"] = {"passed": passed, "findings": findings}
    if not passed:
        primary = sorted(failed_classes)[0]
        raise TaskFailure(f"technical QA failed: {'; '.join(findings)}", failure_class=primary)
    return {"passed": True, "checks": 10, "loudness": loud["input_i"]}


def stage_creative_qa(db, job: Job, task: Task, context: dict) -> dict:
    spec = context["state"]["ctx_spec"]
    script = context["state"]["ctx_script"]
    cleanup = context["state"].get("ctx_cleanup") or context["state"]["ctx_narration"]
    master = Path(context["state"]["ctx_master"]["path"])
    findings: list[str] = []
    narration_text = " ".join(w["word"] for w in cleanup["words"]).lower()
    cta_tokens = [t for t in spec["cta"].lower().split() if len(t) > 2]
    cta_hit = sum(1 for t in cta_tokens if t in narration_text)
    if cta_tokens and cta_hit / len(cta_tokens) < 0.5:
        findings.append("CTA not present in narration audio")
    hooks_ok = sections_present(script, narration_text)
    if not hooks_ok:
        findings.append("hook section missing from narration")
    workdir = job_workdir(job.id)
    palette = _palette_tuples(context)
    dists = []
    for frac in (0.15, 0.5, 0.85):
        frame = workdir / f"qa_frame_{int(frac * 100)}.png"
        _extract_frame(master, context["state"]["ctx_master"]["duration"] * frac, frame)
        dists.append(palette_distance(dominant_colors(frame), palette))
    avg_dist = sum(dists) / len(dists)
    if avg_dist > 160:
        findings.append(f"visual style off-brand (avg palette distance {avg_dist:.0f})")
    cap_validation = validate_captions(cleanup["words"], context["state"]["ctx_master"]["duration"], int(spec["resolution"]["height"]))
    if not cap_validation["passed"]:
        findings.extend(cap_validation["findings"])
    passed = not findings
    score = max(0.0, 1.0 - 0.25 * len(findings)) if passed else max(0.0, 0.6 - 0.2 * len(findings))
    report = QAReport(project_id=job.project_id, job_id=job.id, task_id=task.id, layer="creative", passed=passed, score=round(score, 2), findings=findings)
    db.add(report)
    db.commit()
    context["state"].setdefault("qa_summary", {})["creative"] = {"passed": passed, "findings": findings, "score": round(score, 2), "palette_distance": round(avg_dist, 1)}
    if not passed:
        raise TaskFailure(f"creative QA failed: {'; '.join(findings)}", failure_class="qa_creative")
    return {"passed": True, "palette_distance": round(avg_dist, 1), "caption_avg_cps": cap_validation.get("avg_cps")}


def sections_present(script: dict, narration_text: str) -> bool:
    hook_words = [w for w in script["sections"]["hook"].split() if len(w) > 3]
    if not hook_words:
        return False
    hits = sum(1 for w in hook_words if w.lower() in narration_text)
    return hits / len(hook_words) >= 0.6


STOPWORDS = {
    "that", "with", "from", "this", "your", "have", "will", "into", "more", "than", "then",
    "them", "they", "their", "there", "about", "above", "after", "before", "being", "under",
    "over", "such", "each", "when", "while", "where", "which", "what", "were", "been", "also",
    "very", "just", "only", "most", "some", "both", "every", "without", "within", "through",
    "during", "between", "because", "should", "could", "would", "these", "those", "other",
}


def concept_coverage(brief_texts: list[str], corpus_text: str) -> tuple[float, int]:
    def normalize(words: list[str]) -> list[str]:
        out = []
        for w in words:
            w = w.lower().strip(".,!?;:()\"'")
            if len(w) > 3 and w not in STOPWORDS:
                out.append(w)
        return out

    keywords = normalize(" ".join(brief_texts).split())
    if not keywords:
        return 1.0, 0
    corpus_tokens = normalize(corpus_text.split())
    hits = 0
    for kw in keywords:
        stem = kw[:5]
        matched = any(kw == tok or tok.startswith(stem) or kw.startswith(tok[:5]) for tok in corpus_tokens)
        if matched:
            hits += 1
    return hits / len(keywords), len(keywords)


def stage_multimodal_qa(db, job: Job, task: Task, context: dict) -> dict:
    spec = context["state"]["ctx_spec"]
    scenes = context["state"]["ctx_scenes"]
    master_info = context["state"]["ctx_master"]
    script = context["state"]["ctx_script"]
    findings: list[str] = []
    brief_sources = [spec["objective"], spec["title"], *[f"{k}" for k in spec.get("key_points", [])], *context["state"].get("ctx_research", {}).get("points", [])]
    coverage, keyword_count = concept_coverage(brief_sources, script["full_text"])
    min_coverage = 0.45 if float(spec["duration_s"]) >= 15 else (0.30 if float(spec["duration_s"]) >= 8 else 0.18)
    coverage_note = None
    if keyword_count < 3:
        coverage_note = f"only {keyword_count} scorable brief concepts; coverage gate not applied"
        coverage = max(coverage, min_coverage)
    elif coverage < min_coverage:
        findings.append(f"script covers only {coverage:.0%} of brief concepts (min {min_coverage:.0%} for {spec['duration_s']:.0f}s)")
    if abs(len(scenes) - len(context["state"]["ctx_scene_clips"])) != 0:
        findings.append("storyboard/render scene count mismatch")
    expected_ar = spec["resolution"]["width"] / spec["resolution"]["height"]
    actual_ar = (master_info["width"] or 1) / (master_info["height"] or 1)
    if abs(expected_ar - actual_ar) > 0.02:
        findings.append(f"aspect ratio mismatch: expected {expected_ar:.2f} got {actual_ar:.2f}")
    duration_drift = abs(master_info["duration"] - spec["duration_s"]) / spec["duration_s"]
    if duration_drift > 0.35:
        findings.append(f"final duration drift {duration_drift:.0%} from brief target")
    passed = not findings
    report = QAReport(project_id=job.project_id, job_id=job.id, task_id=task.id, layer="multimodal", passed=passed, score=round(max(0.0, coverage), 2), findings=findings)
    db.add(report)
    db.commit()
    qa_mm: dict = {"passed": passed, "findings": findings, "brief_coverage": round(coverage, 2)}
    if coverage_note:
        qa_mm["coverage_note"] = coverage_note
    context["state"].setdefault("qa_summary", {})["multimodal"] = qa_mm
    if not passed:
        raise TaskFailure(f"multimodal QA failed: {'; '.join(findings)}", failure_class="qa_multimodal")
    return {"passed": True, "brief_coverage": round(coverage, 2)}


def stage_delivery(db, job: Job, task: Task, context: dict) -> dict:
    from sqlalchemy import select

    from ..config import get_settings
    from ..models import Approval

    settings = get_settings()
    if settings.approval_required:
        decided = db.execute(select(Approval).where(Approval.job_id == job.id, Approval.kind == "pre_publish", Approval.status == "approved")).scalar_one_or_none()
        if decided is None:
            return {"awaiting_approval": True, "stage": "delivery"}
    spec = context["state"]["ctx_spec"]
    master = Path(context["state"]["ctx_master"]["path"])
    workdir = job_workdir(job.id) / "deliverables"
    workdir.mkdir(parents=True, exist_ok=True)
    deliverables = []
    thumb_src = workdir / "_thumb_frame.png"
    _extract_frame(master, min(1.5, master_info_duration(context)), thumb_src)
    thumbnail = render_thumbnail(workdir / "thumbnail.png", thumb_src, spec["title"], width=1280, height=720)
    register_artifact(db, job.project_id, job.id, task.id, "thumbnail", thumbnail, {}, {"origin": "derived"})
    square = workdir / "variant_square.mp4"
    from ..capabilities.media import run_ffmpeg

    side = 1080
    vf = f"scale={side}:{side}:force_original_aspect_ratio=increase,crop={side}:{side}"
    run_ffmpeg(["-i", str(master), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-an", str(square)])
    variants = [("master", master), ("square_1x1", square)]
    manifest_common = {
        "title": spec["title"],
        "description": spec["objective"][:400],
        "tags": [w.lower() for w in spec["title"].split() if len(w) > 3][:8],
        "cta": spec["cta"],
        "platform": spec["platform"],
        "language": spec.get("language", "en"),
    }
    for name, path in variants:
        info = probe(path)
        manifest = {
            **manifest_common,
            "file": path.name,
            "duration_s": info.duration_s,
            "resolution": f"{info.width}x{info.height}",
            "sha256": None,
            "license_note": "Contains generated assets produced in-house; external assets listed in provenance.",
        }
        dlv = Deliverable(project_id=job.project_id, job_id=job.id, platform=f"{spec['platform']}:{name}", storage_key=str(path), manifest_json=json.dumps(manifest))
        db.add(dlv)
        db.commit()
        deliverables.append({"kind": name, "path": str(path), "duration_s": info.duration_s})
    metadata_path = workdir / "metadata.json"
    metadata_path.write_text(json.dumps(manifest_common, indent=2), encoding="utf-8")
    context["state"]["ctx_deliverables_list"] = deliverables
    return {"deliverables": deliverables, "thumbnail": str(thumbnail)}


def master_info_duration(context: dict) -> float:
    return float(context["state"]["ctx_master"].get("duration", 1.0))


def stage_finalize(db, job: Job, task: Task, context: dict) -> dict:
    from sqlalchemy import select

    from ..models import CostEntry

    costs = db.execute(select(CostEntry).where(CostEntry.job_id == job.id)).scalars().all()
    total = round(sum(c.amount_usd for c in costs), 6)
    from sqlalchemy import select as _select

    from ..models import Budget

    budgets = db.execute(_select(Budget).where(Budget.active == True, Budget.org_id == job.org_id)).scalars().all()  # noqa: E712
    for b in budgets:
        if b.max_cost_per_job_usd is not None and total > float(b.max_cost_per_job_usd):
            emit_event(db, job.id, task.id, "warning", "budget.exceeded", {"total_usd": total, "cap": b.max_cost_per_job_usd}, org_id=job.org_id)
            break
    deliverables = context["state"].get("ctx_deliverables_list", [])
    context["deliverables"] = deliverables
    context["qa_summary"] = context["state"].get("qa_summary", {})
    context["total_cost_usd"] = total
    project = db.get(Project, job.project_id)
    if project is not None:
        project.status = "delivered"
        project.updated_at = now_iso()
        db.commit()
    emit_event(db, job.id, task.id, "info", "production.finalized", {"cost_usd": total, "deliverables": len(deliverables)})
    return {"total_cost_usd": total, "deliverable_count": len(deliverables)}


HANDLERS: dict[str, HandlerFn] = {
    "intake": stage_intake,
    "research": stage_research,
    "creative_direction": stage_creative_direction,
    "script_writing": stage_script_writing,
    "storyboard": stage_storyboard,
    "asset_acquisition": stage_asset_acquisition,
    "narration": stage_narration,
    "autocleanup": stage_autocleanup,
    "editorial_assembly": stage_editorial_assembly,
    "motion_graphics": stage_motion_graphics,
    "rough_concat": stage_rough_concat,
    "audio_mix": stage_audio_mix,
    "av_mux": stage_av_mux,
    "burn_captions": stage_burn_captions,
    "color_grade": stage_color_grade,
    "technical_qa": stage_technical_qa,
    "creative_qa": stage_creative_qa,
    "multimodal_qa": stage_multimodal_qa,
    "delivery": stage_delivery,
    "finalize": stage_finalize,
}

PRODUCTION_STAGES: list[tuple[str, str]] = [
    ("intake", "Intake Agent"),
    ("research", "Research Agent"),
    ("creative_direction", "Creative Director"),
    ("script_writing", "Script Agent"),
    ("storyboard", "Storyboard Agent"),
    ("asset_acquisition", "Asset Acquisition + Rights Agent"),
    ("narration", "Voice/TTS Agent"),
    ("autocleanup", "Auto-Cleanup Agent"),
    ("editorial_assembly", "Editorial Agent"),
    ("motion_graphics", "Motion Graphics Agent"),
    ("rough_concat", "Render Agent"),
    ("audio_mix", "Sound Design + Music Agent"),
    ("av_mux", "Render Agent"),
    ("burn_captions", "Caption Agent"),
    ("color_grade", "Color Agent"),
    ("technical_qa", "Technical QA Agent"),
    ("creative_qa", "Creative QA Agent"),
    ("multimodal_qa", "Multimodal QA Agent"),
    ("delivery", "Publishing Agent"),
    ("finalize", "Memory + Analytics + FinOps Agent"),
]

STAGE_SEQ: dict[str, int] = {name: idx for idx, (name, _agent) in enumerate(PRODUCTION_STAGES)}

__all__ = ["HANDLERS", "PRODUCTION_STAGES", "STAGE_SEQ", "PLATFORM_SPECS"]



