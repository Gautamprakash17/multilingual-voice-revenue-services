"""Text-to-speech providers — local/mock; never cloud for restricted content."""

from __future__ import annotations

import base64
import hashlib
import logging
import math
import shutil
import struct
import subprocess
import wave
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO

logger = logging.getLogger(__name__)

# Application tts_code → eSpeak NG voice id. Kept inside the TTS layer only.
_ESPEAK_VOICE_BY_TTS_CODE: Mapping[str, str] = {
    "en": "en",
    "hi": "hi",
    "kn": "kn",
}


@dataclass
class TTSResult:
    audio_b64: str
    mime_type: str
    provider: str
    text_hash: str
    duration_ms: float = 0.0


class TTSUnavailableError(RuntimeError):
    """Configured local TTS engine is missing or failed to synthesize."""


class TTSProvider(ABC):
    name: str

    @abstractmethod
    def synthesize(self, text: str, *, language: str = "en") -> TTSResult:
        """Synthesize speech locally. Do not log raw text."""


class MockTTSProvider(TTSProvider):
    """Generate a short tone WAV for unit tests and offline UI plumbing."""

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


class EspeakTTSProvider(TTSProvider):
    """Offline eSpeak NG synthesis via CLI stdout WAV — no network, no cloud."""

    name = "espeak-ng"

    def __init__(self, binary: str = "espeak-ng") -> None:
        self._binary = binary

    def synthesize(self, text: str, *, language: str = "en") -> TTSResult:
        spoken = (text or "").strip()
        digest = hashlib.sha256(spoken.encode("utf-8")).hexdigest()
        if not spoken:
            raise TTSUnavailableError("Speech playback is temporarily unavailable.")

        if shutil.which(self._binary) is None:
            logger.error(
                "tts_provider_unavailable",
                extra={"provider": self.name, "reason": "binary_missing"},
            )
            raise TTSUnavailableError("Speech playback is temporarily unavailable.")

        voice = self._espeak_voice(language)
        try:
            proc = subprocess.run(
                [self._binary, "-v", voice, "--stdout", spoken],
                capture_output=True,
                check=False,
                timeout=45,
            )
        except subprocess.TimeoutExpired as exc:
            logger.error(
                "tts_provider_timeout",
                extra={"provider": self.name, "voice": voice},
            )
            raise TTSUnavailableError(
                "Speech playback is temporarily unavailable."
            ) from exc
        except OSError as exc:
            logger.error(
                "tts_provider_os_error",
                extra={"provider": self.name, "errno": getattr(exc, "errno", None)},
            )
            raise TTSUnavailableError(
                "Speech playback is temporarily unavailable."
            ) from exc

        audio = proc.stdout or b""
        if proc.returncode != 0 or len(audio) < 44 or audio[:4] != b"RIFF":
            logger.error(
                "tts_provider_synthesis_failed",
                extra={
                    "provider": self.name,
                    "voice": voice,
                    "returncode": proc.returncode,
                    "stdout_bytes": len(audio),
                },
            )
            raise TTSUnavailableError("Speech playback is temporarily unavailable.")

        try:
            audio = _normalize_espeak_wav(audio)
        except (wave.Error, struct.error, ValueError) as exc:
            logger.error(
                "tts_provider_wav_normalize_failed",
                extra={"provider": self.name, "voice": voice},
            )
            raise TTSUnavailableError(
                "Speech playback is temporarily unavailable."
            ) from exc

        duration_ms = _wav_duration_ms(audio)
        return TTSResult(
            audio_b64=base64.b64encode(audio).decode("ascii"),
            mime_type="audio/wav",
            provider=self.name,
            text_hash=digest[:16],
            duration_ms=duration_ms,
        )

    @staticmethod
    def _espeak_voice(language: str) -> str:
        code = (language or "en").lower().strip()
        if "-" in code:
            code = code.split("-", 1)[0]
        return _ESPEAK_VOICE_BY_TTS_CODE.get(code, _ESPEAK_VOICE_BY_TTS_CODE["en"])


class LocalTTSProvider(TTSProvider):
    """Local TTS facade — production uses eSpeak NG; tests may inject MockTTSProvider."""

    name = "local-tts"

    def __init__(self, backend: TTSProvider | None = None) -> None:
        self._backend = backend or EspeakTTSProvider()
        self.name = self._backend.name

    def synthesize(self, text: str, *, language: str = "en") -> TTSResult:
        return self._backend.synthesize(text, language=language)


def _tone_wav(frequency: int = 440, duration_ms: int = 400, rate: int = 16000) -> bytes:
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


def _normalize_espeak_wav(audio: bytes) -> bytes:
    """Rewrite eSpeak --stdout WAV headers (often use 0x7fffffff sizes)."""
    data_idx = audio.find(b"data")
    if data_idx < 0 or data_idx + 8 > len(audio):
        raise ValueError("missing data chunk")
    pcm = audio[data_idx + 8 :]
    if len(pcm) < 2:
        raise ValueError("empty pcm")
    # fmt chunk typically starts at offset 12; sample rate at +24 from RIFF start for PCM.
    # Prefer parsing fmt if present; fall back to eSpeak default 22050 Hz mono 16-bit.
    rate = 22050
    channels = 1
    sampwidth = 2
    fmt_idx = audio.find(b"fmt ")
    if fmt_idx >= 0 and fmt_idx + 24 <= len(audio):
        channels = struct.unpack_from("<H", audio, fmt_idx + 8)[0] or 1
        rate = struct.unpack_from("<I", audio, fmt_idx + 12)[0] or 22050
        bits = struct.unpack_from("<H", audio, fmt_idx + 22)[0] or 16
        sampwidth = max(1, bits // 8)
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _wav_duration_ms(audio: bytes) -> float:
    with wave.open(BytesIO(audio), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate() or 1
        return (frames / rate) * 1000.0


def get_tts_provider() -> TTSProvider:
    """Return the configured local TTS provider (eSpeak NG)."""
    return LocalTTSProvider()
