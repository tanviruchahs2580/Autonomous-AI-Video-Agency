from __future__ import annotations

import pytest

from agency.agents.stages import concept_coverage
from agency.capabilities.captions import build_ass, build_srt, group_words_into_cues, validate_captions
from agency.capabilities.editing import Clip, TimelineEDL, Track, apply_silence_cut
from agency.security import (
    RateLimiter,
    assert_public_url,
    generate_api_key,
    hash_api_key,
    safe_join,
    sanitize_text,
    validate_extension,
    verify_api_key,
)
from agency.storage import LocalObjectStore, sha256_bytes


def test_api_key_roundtrip():
    key = generate_api_key()
    assert key.startswith("agy_")
    assert verify_api_key(key, hash_api_key(key))
    assert not verify_api_key(key + "x", hash_api_key(key))


def test_safe_join_blocks_traversal(tmp_path):
    base = tmp_path / "storage"
    base.mkdir()
    ok = safe_join(base, "sub", "file.txt")
    assert str(ok).startswith(str(base.resolve()))
    with pytest.raises(ValueError):
        safe_join(base, "..", "etc", "passwd")
    with pytest.raises(ValueError):
        safe_join(base, "a/../../b")


def test_validate_extension():
    assert validate_extension("clip.MP4") == ".mp4"
    with pytest.raises(ValueError):
        validate_extension("script.exe")
    with pytest.raises(ValueError):
        validate_extension("payload.sh")


def test_rate_limiter():
    rl = RateLimiter(per_minute=3)
    assert [rl.allow("ip") for _ in range(3)] == [True, True, True]
    assert rl.allow("ip") is False
    assert rl.allow("other") is True


def test_sanitize_text_strips_control_chars():
    dirty = "hello\x00\x08world\x1b"
    assert sanitize_text(dirty) == "helloworld"


def test_assert_public_url_blocks_private():
    with pytest.raises(ValueError):
        assert_public_url("http://127.0.0.1:8080/admin")
    with pytest.raises(ValueError):
        assert_public_url("http://169.254.169.254/latest/meta-data")
    with pytest.raises(ValueError):
        assert_public_url("ftp://example.com")
    with pytest.raises(ValueError):
        assert_public_url("file:///c:/windows")


def test_local_object_store_roundtrip(tmp_path):
    store = LocalObjectStore(tmp_path / "store")
    data = b"video-bytes-" * 100
    store.put_bytes("proj/a/file.bin", data)
    assert store.exists("proj/a/file.bin")
    assert store.get_bytes("proj/a/file.bin") == data
    stat = store.stat("proj/a/file.bin")
    assert stat["size"] == len(data)
    assert stat["sha256"] == sha256_bytes(data)
    assert list(store.iter_prefix("proj")) == ["proj/a/file.bin"]
    store.delete("proj/a/file.bin")
    assert not store.exists("proj/a/file.bin")
    with pytest.raises(ValueError):
        store.put_bytes("../escape.txt", b"x")


def test_timeline_edl_validation():
    tl = TimelineEDL(fps=30, width=640, height=360)
    tl.tracks.append(Track(type="video", clips=[Clip(src="missing.png", start=0, end=2)]))
    problems = tl.validate()
    assert any("missing source" in p for p in problems)


def test_apply_silence_cut_removes_gaps_and_remaps_timings():
    words = [
        {"word": "Hello", "start": 0.0, "end": 0.5},
        {"word": "world", "start": 1.5, "end": 2.0},
        {"word": "again", "start": 3.5, "end": 4.0},
    ]
    keep, new_words = apply_silence_cut(words, narration_duration=4.2, keep_pad=0.14, min_silence=0.45)
    assert len(keep) >= 2
    total_kept = sum(e - s for s, e in keep)
    assert total_kept < 4.2
    assert new_words[-1]["end"] < words[-1]["end"]


def test_caption_grouping_limits():
    words = []
    t = 0.0
    for w in "one two three four five six seven eight nine ten eleven twelve".split():
        words.append({"word": w, "start": t, "end": t + 0.3})
        t += 0.35
    cues = group_words_into_cues(words, max_chars=20, max_words=4)
    assert all(len(c["text"]) <= 30 or len(c["text"].split()) <= 4 for c in cues)
    validation = validate_captions(words, media_duration=t + 1.0, video_height=1080)
    assert validation["passed"] is True


def test_build_ass_and_srt(tmp_path):
    words = [{"word": "hello", "start": 0.0, "end": 0.4}, {"word": "world", "start": 0.5, "end": 0.9}]
    ass = build_ass(tmp_path / "cap.ass", words, width=1920, height=1080)
    srt = build_srt(tmp_path / "cap.srt", words)
    ass_text = ass.read_text(encoding="utf-8")
    assert "Dialogue: 0" in ass_text
    assert "PlayResX: 1920" in ass_text
    srt_text = srt.read_text(encoding="utf-8")
    assert "-->" in srt_text and "hello world" in srt_text


def test_concept_coverage_scoring():
    brief = ["Increase deployment speed with zero downtime rollouts and instant rollback safety"]
    corpus = "CloudFlow cuts deployment time. Zero downtime rollouts. One click rollback keeps production safe."
    score = concept_coverage(brief, corpus)
    assert score >= 0.6


def test_concept_coverage_ignores_stopwords():
    brief = ["The team that will ship this with the new platform"]
    corpus = "team ships new platform"
    assert concept_coverage(brief, corpus) >= 0.5
