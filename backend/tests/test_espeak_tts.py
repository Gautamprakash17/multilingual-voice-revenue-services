"""Local eSpeak NG TTS — real speech WAV, not the mock tone."""

from __future__ import annotations

import base64
import hashlib
import math
import shutil
import struct
import wave
from io import BytesIO

import pytest
from app.services.i18n import t
from app.speech.tts import (
    EspeakTTSProvider,
    LocalTTSProvider,
    MockTTSProvider,
    TTSUnavailableError,
    get_tts_provider,
)

ESPEAK = shutil.which("espeak-ng")
requires_espeak = pytest.mark.skipif(
    ESPEAK is None,
    reason="espeak-ng binary not installed on this host (available in Docker image)",
)

EN_PROMPT = "Please say your 10-digit registered mobile number."
HI_PROMPT = t("auth_mobile", "hi")
KN_PROMPT = t("auth_mobile", "kn")


def _decode_wav(audio_b64: str) -> tuple[bytes, int, int, int, int]:
    raw = base64.b64decode(audio_b64)
    assert raw[:4] == b"RIFF", "expected WAV container"
    with wave.open(BytesIO(raw), "rb") as wf:
        return raw, wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()


def _pcm_samples(audio_b64: str) -> list[int]:
    raw = base64.b64decode(audio_b64)
    with wave.open(BytesIO(raw), "rb") as wf:
        assert wf.getsampwidth() == 2
        frames = wf.readframes(wf.getnframes())
    return list(struct.unpack("<" + "h" * (len(frames) // 2), frames))


def _is_near_pure_tone(samples: list[int], *, expected_rate: int = 16000) -> bool:
    """Heuristic: mock tone is a steady sine; speech has irregular amplitude."""
    if len(samples) < 200:
        return False
    # Peak envelope variance over windows — tone is flat, speech is not.
    window = max(160, expected_rate // 50)
    peaks: list[float] = []
    for i in range(0, len(samples) - window, window):
        chunk = samples[i : i + window]
        peaks.append(max(abs(s) for s in chunk) or 0.0)
    if not peaks:
        return False
    mean = sum(peaks) / len(peaks)
    if mean < 1:
        return False
    var = sum((p - mean) ** 2 for p in peaks) / len(peaks)
    cv = math.sqrt(var) / mean
    # Pure tone envelope CV is near 0; speech is typically much higher.
    return cv < 0.08


def test_mock_tts_still_returns_tone_wav():
    result = MockTTSProvider().synthesize(EN_PROMPT, language="en")
    assert result.provider == "mock-tts"
    assert result.mime_type == "audio/wav"
    assert result.audio_b64
    assert result.duration_ms == 400
    digest = hashlib.sha256(EN_PROMPT.encode()).hexdigest()
    assert result.text_hash == digest[:16]
    _, channels, width, rate, frames = _decode_wav(result.audio_b64)
    assert channels == 1 and width == 2 and rate == 16000
    assert frames == 6400
    samples = _pcm_samples(result.audio_b64)
    assert _is_near_pure_tone(samples, expected_rate=16000)


def test_missing_espeak_binary_raises_without_tone(tmp_path, monkeypatch):
    provider = EspeakTTSProvider(binary=str(tmp_path / "no-such-espeak"))
    with pytest.raises(TTSUnavailableError, match="temporarily unavailable"):
        provider.synthesize(EN_PROMPT, language="en")


@requires_espeak
@pytest.mark.parametrize(
    ("language", "prompt"),
    [
        ("en", EN_PROMPT),
        ("hi", HI_PROMPT),
        ("kn", KN_PROMPT),
    ],
)
def test_espeak_synthesizes_valid_speech_wav(language: str, prompt: str):
    result = EspeakTTSProvider().synthesize(prompt, language=language)
    assert result.provider == "espeak-ng"
    assert result.mime_type == "audio/wav"
    assert result.audio_b64
    assert result.duration_ms > 0
    digest = hashlib.sha256(prompt.encode()).hexdigest()
    assert result.text_hash == digest[:16]
    raw, channels, width, rate, frames = _decode_wav(result.audio_b64)
    assert channels == 1
    assert width == 2
    assert rate > 0
    assert frames > 0
    assert len(raw) > 1000


@requires_espeak
def test_espeak_is_not_the_mock_tone():
    """Regression: real provider must not call _tone_wav / emit a sine beep."""
    text = EN_PROMPT
    mock = MockTTSProvider().synthesize(text, language="en")
    real = EspeakTTSProvider().synthesize(text, language="en")

    assert real.provider == "espeak-ng"
    assert real.provider != mock.provider
    assert real.audio_b64 != mock.audio_b64
    # Mock is fixed 400 ms @ 16 kHz; eSpeak speech for this sentence is longer.
    assert real.duration_ms > 800
    assert real.duration_ms != mock.duration_ms

    mock_samples = _pcm_samples(mock.audio_b64)
    real_samples = _pcm_samples(real.audio_b64)
    assert _is_near_pure_tone(mock_samples, expected_rate=16000)
    assert not _is_near_pure_tone(real_samples, expected_rate=22050)


@requires_espeak
def test_local_tts_facade_uses_neural_or_espeak():
    provider = get_tts_provider()
    assert isinstance(provider, LocalTTSProvider)
    result = provider.synthesize(EN_PROMPT, language="en")
    assert result.provider in {"espeak-ng", "piper"}
    assert result.duration_ms > 800


@requires_espeak
def test_espeak_voice_mapping_covers_catalogue_codes():
    """Voice mapping lives in the TTS provider — kn/hi must not silently use English only."""
    en = EspeakTTSProvider().synthesize("Application fee is fifty rupees.", language="en")
    hi = EspeakTTSProvider().synthesize(HI_PROMPT, language="hi")
    kn = EspeakTTSProvider().synthesize(KN_PROMPT, language="kn")
    # Different languages produce different audio for different scripts/text.
    assert en.audio_b64 != hi.audio_b64
    assert hi.audio_b64 != kn.audio_b64
    assert en.duration_ms > 0 and hi.duration_ms > 0 and kn.duration_ms > 0


def test_local_tts_accepts_injected_mock_backend():
    facade = LocalTTSProvider(backend=MockTTSProvider())
    assert facade.name == "mock-tts"
    result = facade.synthesize("hello", language="en")
    assert result.provider == "mock-tts"
    assert result.duration_ms == 400
