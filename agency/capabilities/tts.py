from __future__ import annotations

import logging
import math
import struct
import wave
from pathlib import Path

import numpy as np

logger = logging.getLogger("agency.tts")

SAMPLE_RATE = 24000


class TTSResult:
    def __init__(self, path: Path, duration: float, words: list[dict], provider: str, voice: str) -> None:
        self.path = path
        self.duration = duration
        self.words = words
        self.provider = provider
        self.voice = voice


class TTSProvider:
    name = "base"

    def synthesize(self, text: str, dst: Path, voice: str = "") -> TTSResult:
        raise NotImplementedError


def _estimate_word_durations(text: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for word in text.split():
        base = 0.12 + 0.042 * len(word)
        if word.endswith((".", "!", "?")):
            base += 0.18
        elif word.endswith((",", ";", ":")):
            base += 0.09
        out.append((word.strip(), round(base, 3)))
    return out


def _synthesize_word(freq_profile: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    n = len(freq_profile)
    np.arange(n) / SAMPLE_RATE
    f0 = 118.0 + rng.uniform(-6.0, 10.0)
    signal = np.zeros(n)
    for harmonic, amp in ((1, 1.0), (2, 0.55), (3, 0.34), (4, 0.18), (5, 0.09)):
        freq = f0 * harmonic * (1.0 + freq_profile)
        phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
        signal += amp * np.sin(phase)
    envelope = np.hanning(n) ** 0.7
    breath = rng.normal(0, 0.02, n) * envelope
    return (signal * 0.16 + breath) * envelope


class SynthTTSProvider(TTSProvider):
    """Offline deterministic speech-shaped narration.

    Produces intelligible-timing robotic narration without any network dependency.
    Used as the guaranteed-availability fallback provider; configure a neural
    provider (e.g. edge-tts) for natural voices in production deployments.
    """

    name = "synth-local"
    voice = "synth-neutral-v1"

    def _vowelish(self, ch: str) -> float:
        return 0.35 if ch.lower() in "aeiouy" else 0.0

    def synthesize(self, text: str, dst: Path, voice: str = "") -> TTSResult:
        rng = np.random.default_rng(abs(hash(text)) % (2**32))
        words_est = _estimate_word_durations(text)
        chunks: list[np.ndarray] = []
        timings: list[dict] = []
        cursor = 0.25
        gap = np.zeros(int(0.06 * SAMPLE_RATE))
        for word, dur in words_est:
            n = int(dur * SAMPLE_RATE)
            vowel_levels = [self._vowelish(c) for c in word]
            if not vowel_levels:
                vowel_levels = [0.2]
            profile = np.array(vowel_levels)
            interp = np.interp(np.linspace(0, len(profile) - 1, n), np.arange(len(profile)), profile)
            audio = _synthesize_word(interp, rng)
            chunks.extend([audio, gap])
            timings.append({"word": word, "start": round(cursor, 3), "end": round(cursor + dur, 3)})
            cursor += dur + 0.06
        full = np.concatenate(chunks) if chunks else np.zeros(SAMPLE_RATE // 4)
        peak = float(np.max(np.abs(full))) or 1.0
        full = full / peak * 0.85
        pcm = (full * 32767).astype("<i2")
        dst.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(dst), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm.tobytes())
        duration = len(full) / SAMPLE_RATE
        return TTSResult(path=dst, duration=round(duration, 3), words=timings, provider=self.name, voice=self.voice)


class EdgeTTSProvider(TTSProvider):
    name = "edge-tts"

    def __init__(self, voice: str = "en-US-AriaNeural") -> None:
        self.voice = voice

    def synthesize(self, text: str, dst: Path, voice: str | None = None) -> TTSResult:
        import asyncio

        import edge_tts

        async def _run() -> None:
            communicate = edge_tts.Communicate(text, voice or self.voice)
            await communicate.save(str(dst))

        asyncio.run(_run())
        from agency.capabilities.media import probe

        info = probe(dst)
        timings = _align_words_by_rate(text, info.duration_s)
        return TTSResult(path=dst, duration=info.duration_s, words=timings, provider=self.name, voice=voice or self.voice)


def _align_words_by_rate(text: str, duration: float) -> list[dict]:
    tokens = text.split()
    weights = np.array([len(t) + 2.2 for t in tokens], dtype=float)
    total = float(weights.sum()) or 1.0
    times = (weights / total) * duration
    words: list[dict] = []
    cursor = 0.0
    for tok, span in zip(tokens, times, strict=False):
        words.append({"word": tok, "start": round(cursor, 3), "end": round(cursor + span - 0.01, 3)})
        cursor += span
    return words


def get_tts_provider(preferred: str = "edge") -> tuple[TTSProvider, str | None]:
    if preferred == "edge":
        try:
            import edge_tts  # noqa: F401

            return EdgeTTSProvider(), None
        except Exception as exc:
            logger.warning("edge-tts unavailable (%s); falling back to synth provider", exc)
            fallback_reason = f"edge-tts unavailable: {exc}"
        return SynthTTSProvider(), fallback_reason
    return SynthTTSProvider(), None


def write_wav(path: Path, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Path:
    peak = float(np.max(np.abs(samples))) or 1.0
    normalized = samples / peak * 0.9
    pcm = (normalized * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return path


def synth_tone(freq: float, duration: float, amplitude: float = 0.4, fade: bool = True) -> np.ndarray:
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    wave_form = amplitude * np.sin(2 * math.pi * freq * t)
    if fade:
        env_n = max(len(t) // 50, 1)
        envelope = np.ones_like(wave_form)
        envelope[:env_n] = np.linspace(0, 1, env_n)
        envelope[-env_n:] = np.linspace(1, 0, env_n)
        wave_form *= envelope
    return wave_form


CHORDS: dict[str, list[list[float]]] = {
    "calm": [
        [220.00, 261.63, 329.63],
        [174.61, 220.00, 261.63],
        [196.00, 246.94, 293.66],
        [164.81, 207.65, 246.94],
    ],
    "uplifting": [
        [261.63, 329.63, 392.00],
        [220.00, 261.63, 329.63],
        [174.61, 220.00, 261.63],
        [196.00, 246.94, 392.00],
    ],
    "tense": [
        [233.08, 277.18, 349.23],
        [207.65, 246.94, 311.13],
        [185.00, 233.08, 277.18],
        [155.56, 196.00, 233.08],
    ],
}


def generate_music_bed(dst: Path, duration: float, mood: str = "uplifting", bpm: float = 96.0) -> Path:
    chord_set = CHORDS.get(mood, CHORDS["uplifting"])
    beat = 60.0 / bpm
    total = np.zeros(int((duration + 1) * SAMPLE_RATE))
    t_cursor = 0.0
    idx = 0
    while t_cursor < duration:
        chord = chord_set[idx % len(chord_set)]
        seg_dur = min(beat * 4, duration - t_cursor)
        if seg_dur <= 0.05:
            break
        seg = np.zeros(int(seg_dur * SAMPLE_RATE))
        for f in chord:
            seg += synth_tone(f / 2, seg_dur, amplitude=0.12)
        pad = int(t_cursor * SAMPLE_RATE)
        end = min(pad + len(seg), len(total))
        total[pad:end] += seg[: end - pad]
        t_cursor += seg_dur
        idx += 1
    fade_n = min(int(1.5 * SAMPLE_RATE), len(total) // 4)
    total[:fade_n] *= np.linspace(0, 1, fade_n)
    total[-fade_n:] *= np.linspace(1, 0, fade_n)
    peak = float(np.max(np.abs(total))) or 1.0
    total = total / peak * 0.55
    return write_wav(dst, total)


def wav_bytes_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate() or 1)


__all__ = [
    "TTSProvider",
    "SynthTTSProvider",
    "EdgeTTSProvider",
    "get_tts_provider",
    "generate_music_bed",
    "write_wav",
    "synth_tone",
    "wav_bytes_duration",
    "struct",
]

