"""Lightweight local language detection via Unicode script blocks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageGuess:
    language: str
    confidence: float


def _count_scripts(text: str) -> dict[str, int]:
    counts = {"hi": 0, "te": 0, "en": 0}
    for ch in text:
        code = ord(ch)
        # Devanagari
        if 0x0900 <= code <= 0x097F:
            counts["hi"] += 1
        # Telugu
        elif 0x0C00 <= code <= 0x0C7F:
            counts["te"] += 1
        elif ch.isascii() and ch.isalpha():
            counts["en"] += 1
    return counts


def detect_language(text: str, fallback: str | None = None) -> LanguageGuess:
    """Detect language from script. Low confidence → keep fallback."""
    sample = (text or "").strip()
    if not sample:
        return LanguageGuess(language=fallback or "en", confidence=0.0)

    counts = _count_scripts(sample)
    total = sum(counts.values())
    if total == 0:
        return LanguageGuess(language=fallback or "en", confidence=0.0)

    best_lang = max(counts, key=lambda k: counts[k])
    ratio = counts[best_lang] / total
    # Require clear majority for auto-switch
    if ratio < 0.55:
        return LanguageGuess(language=fallback or best_lang, confidence=ratio)
    return LanguageGuess(language=best_lang, confidence=round(ratio, 3))


def resolve_language(
    text: str,
    selected: str | None,
    *,
    min_confidence: float = 0.7,
) -> LanguageGuess:
    """Prefer selected language unless detector is highly confident otherwise."""
    guess = detect_language(text, fallback=selected or "en")
    if selected and guess.confidence < min_confidence:
        return LanguageGuess(language=selected, confidence=guess.confidence)
    if selected and guess.language != selected and guess.confidence < 0.85:
        # Do not silently switch citizen language on weak signal
        return LanguageGuess(language=selected, confidence=guess.confidence)
    return guess
