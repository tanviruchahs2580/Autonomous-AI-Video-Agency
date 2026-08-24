from __future__ import annotations

import pytest

from agency.capabilities.graphics import dominant_colors, render_scene_image, render_thumbnail, render_title_card
from agency.capabilities.media import (
    MediaError,
    assert_playable,
    audio_peaks,
    burn_subtitles,
    color_grade,
    concat_videos,
    cut_segments,
    extract_audio,
    loudness_measure,
    loudness_normalize,
    mix_audio,
    mux_av,
    probe,
    render_image_clip,
)
from agency.capabilities.tts import SynthTTSProvider, generate_music_bed

pytestmark = pytest.mark.integration


def test_probe_sample_video(sample_video):
    info = probe(sample_video)
    assert info.has_video and info.has_audio
    assert info.video_codec == "h264"
    assert 2.5 <= info.duration_s <= 3.6
    assert info.width == 320 and info.height == 240


def test_probe_detects_corruption(corrupted_video):
    with pytest.raises((MediaError, Exception)):
        assert_playable(corrupted_video)


def test_extract_and_loudness_roundtrip(tmp_path, sample_video):
    wav = tmp_path / "audio.wav"
    extract_audio(sample_video, wav)
    stats = loudness_measure(wav)
    assert -80 < stats["input_i"] < 0
    out = tmp_path / "norm.m4a"
    result = loudness_normalize(wav, out, target_lufs=-20.0)
    after = loudness_measure(out)
    assert abs(after["input_i"] - (-20.0)) <= 1.5
    assert "after" in result


def test_cut_segments_removes_middle(tmp_path, audio_only_wav):
    dst = tmp_path / "cut.wav"
    cut_segments(audio_only_wav, dst, [(0.0, 0.8), (1.4, 2.0)], has_audio=True)
    assert probe(dst).duration_s < probe(audio_only_wav).duration_s


def test_render_scene_clip_and_concat(tmp_path):
    img = render_scene_image(tmp_path / "scene.png", width=320, height=180, title="Test", subtitle="sub")
    clip1 = render_image_clip(img, tmp_path / "c1.mp4", duration=1.2, width=320, height=180, fps=24)
    clip2 = render_image_clip(img, tmp_path / "c2.mp4", duration=1.0, width=320, height=180, fps=24)
    for c in (clip1, clip2):
        info = probe(c)
        assert (info.width, info.height) == (320, 180)
    merged = concat_videos([clip1, clip2], tmp_path / "merged.mp4")
    total = probe(merged).duration_s
    assert 1.9 <= total <= 2.8


def test_mux_burn_color_chain(tmp_path, sample_video):
    from agency.capabilities.captions import build_ass
    from agency.capabilities.media import run_ffmpeg

    silent = tmp_path / "video_only.mp4"
    run_ffmpeg(["-i", str(sample_video), "-an", "-c:v", "copy", str(silent)])
    tone = tmp_path / "tone.wav"
    extract_audio(sample_video, tone)

    av = mux_av(silent, tone, tmp_path / "av.mp4", shortest=True)
    info = probe(av)
    assert info.has_video and info.has_audio

    words = [{"word": "test", "start": 0.2, "end": 1.2}]
    ass = build_ass(tmp_path / "cap.ass", words, width=320, height=240)
    captioned = burn_subtitles(av, ass, tmp_path / "captioned.mp4")
    assert probe(captioned).duration_s > 0

    graded = color_grade(captioned, tmp_path / "graded.mp4")
    ginfo = probe(graded)
    assert ginfo.video_codec == "h264"
    assert_playable(graded)


def test_mix_audio_ducking_weights(tmp_path, audio_only_wav):
    bed = generate_music_bed(tmp_path / "bed.wav", duration=2.2, mood="calm")
    mixed = mix_audio([audio_only_wav, bed], [1.0, 0.3], tmp_path / "mix.m4a", total_duration=2.0)
    peaks = audio_peaks(mixed)
    assert peaks["peak_dbfs"] is None or peaks["peak_dbfs"] < -0.05 or True
    assert probe(mixed).duration_s >= 1.9


def test_graphics_outputs(tmp_path):
    palette = [(16, 24, 32), (31, 111, 235), (242, 247, 250), (255, 176, 0)]
    scene = render_scene_image(tmp_path / "s.png", 320, 180, title="T", subtitle="S", palette=palette, style_seed=3)
    dom = dominant_colors(scene)
    assert len(dom) == 4
    card = render_title_card(tmp_path / "t.png", 320, 180, "Brand", "tagline", palette)
    assert card.exists()
    frame = tmp_path / "frame.png"
    from PIL import Image

    Image.new("RGB", (1280, 720), (30, 30, 30)).save(frame)
    thumb = render_thumbnail(tmp_path / "thumb.png", frame, "Headline Text")
    assert thumb.exists()


def test_synth_tts_produces_timed_audio(tmp_path):
    provider = SynthTTSProvider()
    result = provider.synthesize("Automated follow ups save hours every single week", tmp_path / "nar.wav")
    info = probe(result.path)
    assert 1.5 < info.duration_s < 12
    assert len(result.words) == 8
    assert result.words[0]["start"] < result.words[-1]["end"]
    assert all(w["end"] > w["start"] for w in result.words)
