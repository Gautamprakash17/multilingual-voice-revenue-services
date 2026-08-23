"""Speech-to-text providers — local by default; mock when models unavailable."""

from __future__ import annotations

import base64
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)


@dataclass
class STTResult:
    transcript: str
    language: str | None
    confidence: float
    provider: str
    duration_ms: float = 0.0


class STTProvider(ABC):
    name: str

    @abstractmethod
    def transcribe(
        self, audio_bytes: bytes, *, language_hint: str | None = None
    ) -> STTResult:
        """Transcribe audio locally. Never send to cloud."""


def audio_file_suffix(audio_bytes: bytes) -> str:
    """Pick a temp-file suffix so decoders (faster-whisper/ffmpeg) can read the payload."""
    if len(audio_bytes) >= 4 and audio_bytes[:4] == b"RIFF":
        return ".wav"
    if len(audio_bytes) >= 4 and audio_bytes[:4] == b"fLaC":
        return ".flac"
    if len(audio_bytes) >= 3 and audio_bytes[:3] == b"ID3":
        return ".mp3"
    if len(audio_bytes) >= 2 and audio_bytes[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
        return ".mp3"
    if len(audio_bytes) >= 4 and audio_bytes[:4] == b"OggS":
        return ".ogg"
    if len(audio_bytes) >= 4 and audio_bytes[:4] == bytes([0x1A, 0x45, 0xDF, 0xA3]):
        return ".webm"
    return ".wav"


class MockSTTProvider(STTProvider):
    """Deterministic POC STT — maps audio hash / embedded markers to phrases.

    Keeps the project runnable without downloading models.
    Frontend may also send a client-side transcript for demo; this provider
    is used when only audio bytes are supplied.
    """

    name = "mock-stt"

    def transcribe(
        self, audio_bytes: bytes, *, language_hint: str | None = None
    ) -> STTResult:
        if not audio_bytes:
            return STTResult(
                transcript="", language=language_hint, confidence=0.0, provider=self.name
            )
        # Allow demo clients to prefix UTF-8 marker: b"POCSTT:<phrase>"
        if audio_bytes.startswith(b"POCSTT:"):
            phrase = audio_bytes[7:].decode("utf-8", errors="ignore").strip()
            return STTResult(
                transcript=phrase,
                language=language_hint or "en",
                confidence=0.92,
                provider=self.name,
            )
        # Without a local ASR model, raw mic bytes cannot be transcribed.
        return STTResult(
            transcript="",
            language=language_hint or "en",
            confidence=0.0,
            provider=self.name,
        )


class LocalSTTProvider(STTProvider):
    """Prefer faster-whisper when installed; otherwise fall back to mock."""

    name = "local-stt"

    def __init__(self) -> None:
        self._backend: STTProvider
        try:
            import faster_whisper  # noqa: F401

            self._backend = WhisperSTTProvider()
            self.name = "faster-whisper"
        except Exception:
            logger.info("faster-whisper unavailable; using mock-stt fallback")
            self._backend = MockSTTProvider()
            self.name = "mock-stt"

    def transcribe(
        self, audio_bytes: bytes, *, language_hint: str | None = None
    ) -> STTResult:
        return self._backend.transcribe(audio_bytes, language_hint=language_hint)


class WhisperSTTProvider(STTProvider):
    """Optional faster-whisper backend (not required for tests)."""

    name = "faster-whisper"

    def __init__(self) -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel("tiny", device="cpu", compute_type="int8")

    def transcribe(
        self, audio_bytes: bytes, *, language_hint: str | None = None
    ) -> STTResult:
        import tempfile
        from pathlib import Path

        if not audio_bytes or len(audio_bytes) < 64:
            return STTResult(
                transcript="",
                language=language_hint,
                confidence=0.0,
                provider=self.name,
            )

        suffix = audio_file_suffix(audio_bytes)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            path = Path(tmp.name)
        try:
            segments, info = self._model.transcribe(
                str(path),
                language=language_hint or None,
                vad_filter=True,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return STTResult(
                transcript=text,
                language=getattr(info, "language", language_hint),
                confidence=0.8 if text else 0.0,
                provider=self.name,
            )
        except Exception:
            logger.exception("faster-whisper transcription failed")
            return STTResult(
                transcript="",
                language=language_hint,
                confidence=0.0,
                provider=self.name,
            )
        finally:
            path.unlink(missing_ok=True)


def decode_audio_b64(audio_b64: str) -> bytes:
    return base64.b64decode(audio_b64)


@lru_cache
def get_stt_provider() -> STTProvider:
    return LocalSTTProvider()
