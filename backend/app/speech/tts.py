"""Text-to-speech providers — local/mock; never cloud for restricted content."""

from __future__ import annotations

import base64
import hashlib
import struct
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from io import BytesIO


@dataclass
class TTSResult:
    audio_b64: str
    mime_type: str
    provider: str
    text_hash: str
    duration_ms: float = 0.0


class TTSProvider(ABC):
    name: str

    @abstractmethod
    def synthesize(self, text: str, *, language: str = "en") -> TTSResult:
        """Synthesize speech locally. Do not log raw text."""


class MockTTSProvider(TTSProvider):
    """Generate a short silent/tone WAV so the UI can play a response."""

    name = "mock-tts"

    def synthesize(self, text: str, *, language: str = "en") -> TTSResult:
        digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
        # ~0.4s mono tone; pitch varies slightly by hash for demo feedback
        freq = 440 + (int(digest[:2], 16) % 200)
        audio = _tone_wav(frequency=freq, duration_ms=400)
        return TTSResult(
            audio_b64=base64.b64encode(audio).decode("ascii"),
            mime_type="audio/wav",
            provider=self.name,
            text_hash=digest[:16],
            duration_ms=400,
        )


class LocalTTSProvider(TTSProvider):
    """Local TTS facade — uses mock WAV in POC (no mandatory model download)."""

    name = "local-tts"

    def __init__(self) -> None:
        self._backend = MockTTSProvider()
        self.name = self._backend.name

    def synthesize(self, text: str, *, language: str = "en") -> TTSResult:
        return self._backend.synthesize(text, language=language)


def _tone_wav(frequency: int = 440, duration_ms: int = 400, rate: int = 16000) -> bytes:
    import math

    n_samples = int(rate * duration_ms / 1000)
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        frames = bytearray()
        for i in range(n_samples):
            value = int(12000 * math.sin(2 * math.pi * frequency * (i / rate)))
            frames += struct.pack("<h", value)
        wf.writeframes(frames)
    return buf.getvalue()


def get_tts_provider() -> TTSProvider:
    return LocalTTSProvider()
