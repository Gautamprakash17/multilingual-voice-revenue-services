"""Text-to-speech providers — local/mock; never cloud for restricted content.

Default routing (all offline):
  en → Piper neural voice when the model is present
  hi → Piper Hindi (Indic-quality) when the model is present
  kn → eSpeak NG (no official Piper Kannada voice in this POC)
  any miss/failure → eSpeak NG fallback
"""

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
from pathlib import Path

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


def _tts_language_code(language: str | None) -> str:
    code = (language or "en").lower().strip()
    if "-" in code:
        code = code.split("-", 1)[0]
    return code or "en"


class PiperTTSProvider(TTSProvider):
    """Offline Piper neural TTS via CLI — no network at synthesis time."""

    name = "piper"

    def __init__(self, *, binary: str, model_path: str | Path) -> None:
        self._binary = binary
        self._model_path = Path(model_path)

    def available(self) -> bool:
        binary_ok = bool(shutil.which(self._binary) or Path(self._binary).is_file())
        return binary_ok and self._model_path.is_file()

    def synthesize(self, text: str, *, language: str = "en") -> TTSResult:
        spoken = (text or "").strip()
        digest = hashlib.sha256(spoken.encode("utf-8")).hexdigest()
        if not spoken:
            raise TTSUnavailableError("Speech playback is temporarily unavailable.")
        if not self.available():
            logger.error(
                "tts_provider_unavailable",
                extra={"provider": self.name, "reason": "piper_missing"},
            )
            raise TTSUnavailableError("Speech playback is temporarily unavailable.")

        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out = Path(tmp.name)
        try:
            try:
                proc = subprocess.run(
                    [self._binary, "--model", str(self._model_path), "--output_file", str(out)],
                    input=spoken.encode("utf-8"),
                    capture_output=True,
                    check=False,
                    timeout=60,
                    cwd=str(Path(self._binary).resolve().parent)
                    if Path(self._binary).is_file()
                    else None,
                )
            except subprocess.TimeoutExpired as exc:
                logger.error("tts_provider_timeout", extra={"provider": self.name})
                raise TTSUnavailableError("Speech playback is temporarily unavailable.") from exc
            except OSError as exc:
                logger.error(
                    "tts_provider_os_error",
                    extra={"provider": self.name, "errno": getattr(exc, "errno", None)},
                )
                raise TTSUnavailableError("Speech playback is temporarily unavailable.") from exc

            audio = out.read_bytes() if out.is_file() else b""
            if proc.returncode != 0 or len(audio) < 44 or audio[:4] != b"RIFF":
                logger.error(
                    "tts_provider_synthesis_failed",
                    extra={
                        "provider": self.name,
                        "returncode": proc.returncode,
                        "stdout_bytes": len(proc.stdout or b""),
                        "model": self._model_path.name,
                    },
                )
                raise TTSUnavailableError("Speech playback is temporarily unavailable.")

            duration_ms = _wav_duration_ms(audio)
            return TTSResult(
                audio_b64=base64.b64encode(audio).decode("ascii"),
                mime_type="audio/wav",
                provider=self.name,
                text_hash=digest[:16],
                duration_ms=duration_ms,
            )
        finally:
            out.unlink(missing_ok=True)


class LocalTTSProvider(TTSProvider):
    """Local TTS facade — Piper (en/hi) with eSpeak NG fallback; tests may inject a backend."""

    name = "local-tts"

    def __init__(
        self,
        backend: TTSProvider | None = None,
        *,
        espeak: TTSProvider | None = None,
        piper_en: TTSProvider | None = None,
        piper_hi: TTSProvider | None = None,
    ) -> None:
        if backend is not None:
            self._injected = backend
            self.name = backend.name
            self._espeak = None
            self._piper_en = None
            self._piper_hi = None
            return

        self._injected = None
        self._espeak = espeak or EspeakTTSProvider()
        if piper_en is not None or piper_hi is not None:
            self._piper_en = piper_en
            self._piper_hi = piper_hi
        else:
            self._piper_en, self._piper_hi = _load_piper_voices()
        self.name = "local-tts"

    def synthesize(self, text: str, *, language: str = "en") -> TTSResult:
        if self._injected is not None:
            return self._injected.synthesize(text, language=language)

        code = _tts_language_code(language)
        neural = None
        if code == "en":
            neural = self._piper_en
        elif code == "hi":
            neural = self._piper_hi
        if neural is not None:
            try:
                return neural.synthesize(text, language=language)
            except TTSUnavailableError:
                logger.info("tts_neural_fallback_espeak", extra={"language": code})
        assert self._espeak is not None
        return self._espeak.synthesize(text, language=language)


def _load_piper_voices() -> tuple[TTSProvider | None, TTSProvider | None]:
    from app.core.config import get_settings

    settings = get_settings()
    voices = Path(settings.tts_voices_dir)
    binary = settings.piper_bin
    en_path = voices / settings.piper_en_voice
    hi_path = voices / settings.piper_hi_voice
    en = PiperTTSProvider(binary=binary, model_path=en_path)
    hi = PiperTTSProvider(binary=binary, model_path=hi_path)
    return (en if en.available() else None, hi if hi.available() else None)


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
    """Return the configured local TTS provider (Piper + eSpeak fallback)."""
    return LocalTTSProvider()
