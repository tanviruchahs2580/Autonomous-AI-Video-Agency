from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("agency.asr")


class TranscriptionResult:
    def __init__(self, text: str, words: list[dict], source: str, confidence: float = 1.0) -> None:
        self.text = text
        self.words = words
        self.source = source
        self.confidence = confidence


class Transcriber:
    name = "base"

    def transcribe(self, audio_path: Path, language: str = "en") -> TranscriptionResult:
        raise NotImplementedError


class TimelineAuthoritativeTranscriber(Transcriber):
    """Uses production-side word timings from our own narration synthesis.

    When the agency generates the narration itself, the synthesis timeline is the
    authoritative transcript source; no external ASR pass is required.
    """

    name = "timeline-authoritative"

    def transcribe_from_timings(self, words: list[dict], expected_text: str | None = None) -> TranscriptionResult:
        text = " ".join(w["word"] for w in words)
        return TranscriptionResult(text=text, words=words, source=self.name)


class FasterWhisperTranscriber(Transcriber):
    name = "faster-whisper"

    def __init__(self, model_size: str = "tiny", device: str = "cpu") -> None:
        from faster_whisper import WhisperModel

        self.model = WhisperModel(model_size, device=device)

    def transcribe(self, audio_path: Path, language: str = "en") -> TranscriptionResult:
        segments, info = self.model.transcribe(str(audio_path), language=language, word_timestamps=True)
        words: list[dict] = []
        texts: list[str] = []
        for seg in segments:
            texts.append(seg.text.strip())
            for w in seg.words or []:
                words.append({"word": w.word.strip(), "start": round(float(w.start), 3), "end": round(float(w.end), 3)})
        return TranscriptionResult(text=" ".join(texts), words=words, source=self.name)


def get_transcriber(prefer_external: bool = False) -> Transcriber:
    if prefer_external:
        try:
            return FasterWhisperTranscriber()
        except Exception as exc:
            logger.warning("faster-whisper unavailable (%s); using timeline-authoritative transcriber", exc)
    return TimelineAuthoritativeTranscriber()


def validate_caption_sync(words: list[dict], media_duration: float, tolerance: float = 0.15) -> dict:
    if not words:
        return {"ok": False, "reason": "no caption cues"}
    last_end = float(words[-1]["end"])
    abs(last_end - min(media_duration, last_end + tolerance))
    ok = last_end <= media_duration + tolerance and all(w["end"] >= w["start"] for w in words)
    monotonic = all(words[i]["start"] <= words[i + 1]["start"] for i in range(len(words) - 1))
    return {"ok": bool(ok and monotonic), "last_end": last_end, "media_duration": media_duration, "monotonic": monotonic}


def parse_timings(raw: str | bytes) -> list[dict]:
    return json.loads(raw)

