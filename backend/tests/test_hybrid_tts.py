"""Hybrid local TTS routing — Piper for en/hi when available, eSpeak otherwise."""

from __future__ import annotations

from app.speech.tts import (
    LocalTTSProvider,
    MockTTSProvider,
    TTSUnavailableError,
    _tts_language_code,
)


class _RecordingTTS(MockTTSProvider):
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, str]] = []

    def synthesize(self, text: str, *, language: str = "en"):
        from dataclasses import replace

        self.calls.append((language, text))
        result = super().synthesize(text, language=language)
        return replace(result, provider=self.name)


class _FailingTTS(_RecordingTTS):
    def synthesize(self, text: str, *, language: str = "en"):
        self.calls.append((language, text))
        raise TTSUnavailableError("Speech playback is temporarily unavailable.")


def test_language_code_normalizes_locale():
    assert _tts_language_code("en-US") == "en"
    assert _tts_language_code("HI") == "hi"
    assert _tts_language_code(None) == "en"


def test_hybrid_routes_english_and_hindi_to_piper():
    piper_en = _RecordingTTS("piper")
    piper_hi = _RecordingTTS("piper")
    espeak = _RecordingTTS("espeak-ng")
    provider = LocalTTSProvider(espeak=espeak, piper_en=piper_en, piper_hi=piper_hi)

    en = provider.synthesize("Hello", language="en")
    hi = provider.synthesize("नमस्ते", language="hi")
    kn = provider.synthesize("ನಮಸ್ಕಾರ", language="kn")

    assert en.provider == "piper"
    assert hi.provider == "piper"
    assert kn.provider == "espeak-ng"
    assert piper_en.calls == [("en", "Hello")]
    assert piper_hi.calls == [("hi", "नमस्ते")]
    assert espeak.calls == [("kn", "ನಮಸ್ಕಾರ")]


def test_hybrid_falls_back_to_espeak_when_piper_fails():
    piper_en = _FailingTTS("piper")
    espeak = _RecordingTTS("espeak-ng")
    provider = LocalTTSProvider(espeak=espeak, piper_en=piper_en, piper_hi=None)

    result = provider.synthesize("Hello", language="en")
    assert result.provider == "espeak-ng"
    assert espeak.calls == [("en", "Hello")]


def test_injected_backend_still_used():
    mock = MockTTSProvider()
    provider = LocalTTSProvider(backend=mock)
    result = provider.synthesize("hello", language="en")
    assert result.provider == "mock-tts"
