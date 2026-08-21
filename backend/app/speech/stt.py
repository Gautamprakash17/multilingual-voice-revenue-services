"""Speech-to-text providers — local by default; mock when models unavailable."""

from __future__ import annotations

import base64
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass


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


class MockSTTProvider(STTProvider):
    """Deterministic POC STT — maps audio hash / embedded markers to phrases.

    Keeps the project runnable without downloading models.
    Frontend may also send a client-side transcript for demo; this provider
    is used when only audio bytes are supplied.
    """

    name = "mock-stt"

    # Demo phrases keyed by short markers embedded in synthetic audio
    _PHRASES = {
        "en_name": "Lakshmi Devi",
        "en_yes": "YES",
        "en_confirm": "CONFIRM",
        "hi_yes": "हाँ",
        "te_yes": "అవును",
        "income": "120000",
    }

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
        digest = hashlib.sha256(audio_bytes).hexdigest()[:8]
        # Stable fake transcript for unknown audio (never empty for non-empty input)
        return STTResult(
            transcript=f"audio-{digest}",
            language=language_hint or "en",
            confidence=0.4,
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

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            path = Path(tmp.name)
        try:
            segments, info = self._model.transcribe(
                str(path), language=language_hint or None
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return STTResult(
                transcript=text,
                language=getattr(info, "language", language_hint),
                confidence=0.8,
                provider=self.name,
            )
        finally:
            path.unlink(missing_ok=True)


def decode_audio_b64(audio_b64: str) -> bytes:
    return base64.b64decode(audio_b64)


def get_stt_provider() -> STTProvider:
    return LocalSTTProvider()
