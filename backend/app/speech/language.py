"""Language detection and config-driven language selection normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.languages import LanguageCatalog, get_language_catalog


@dataclass(frozen=True)
class LanguageGuess:
    language: str
    confidence: float


@dataclass(frozen=True)
class LanguageChoiceResult:
    code: str | None
    ambiguous: bool = False
    matched_codes: tuple[str, ...] = ()


def _count_scripts(text: str, catalog: LanguageCatalog) -> dict[str, int]:
    counts = {lang.code: 0 for lang in catalog.languages}
    for ch in text:
        code_point = ord(ch)
        matched = False
        for script in catalog.script_ranges:
            if script.start <= code_point <= script.end:
                counts[script.code] = counts.get(script.code, 0) + 1
                matched = True
                break
        if not matched and ch.isascii() and ch.isalpha():
            counts["en"] = counts.get("en", 0) + 1
    return counts


def detect_language(text: str, fallback: str | None = None) -> LanguageGuess:
    """Detect language from script. Low confidence → keep fallback."""
    catalog = get_language_catalog()
    default = fallback or catalog.default_code
    sample = (text or "").strip()
    if not sample:
        return LanguageGuess(language=default, confidence=0.0)

    counts = _count_scripts(sample, catalog)
    total = sum(counts.values())
    if total == 0:
        return LanguageGuess(language=default, confidence=0.0)

    best_lang = max(counts, key=lambda k: counts[k])
    ratio = counts[best_lang] / total
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
    catalog = get_language_catalog()
    guess = detect_language(text, fallback=selected or catalog.default_code)
    if selected and guess.confidence < min_confidence:
        return LanguageGuess(language=selected, confidence=guess.confidence)
    if selected and guess.language != selected and guess.confidence < 0.85:
        return LanguageGuess(language=selected, confidence=guess.confidence)
    return guess


def _clean_language_choice_text(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = cleaned.strip("\"'“”‘’")
    cleaned = re.sub(r"[.,!?;:…]+$", "", cleaned).strip()
    cleaned = re.sub(r"^[.,!?;:…]+", "", cleaned).strip()
    return cleaned


def _pattern_matches(text_lower: str, text_raw: str, pattern: str) -> bool:
    candidate = pattern.strip()
    if not candidate:
        return False
    if any(ord(ch) > 127 for ch in candidate):
        return candidate in text_raw
    lowered = candidate.lower()
    if len(lowered) <= 3:
        return bool(re.search(rf"\b{re.escape(lowered)}\b", text_lower))
    return lowered in text_lower


def resolve_language_choice(
    text: str,
    *,
    catalog: LanguageCatalog | None = None,
) -> LanguageChoiceResult:
    """Map natural spoken language choices to configured language codes."""
    cat = catalog or get_language_catalog()
    raw = _clean_language_choice_text(text)
    if not raw:
        return LanguageChoiceResult(None)

    lowered = raw.lower()
    if cat.is_supported(lowered):
        return LanguageChoiceResult(lowered)

    matches: set[str] = set()
    for lang in cat.languages:
        for pattern in lang.all_patterns():
            if _pattern_matches(lowered, raw, pattern):
                matches.add(lang.code)

    if len(matches) == 1:
        return LanguageChoiceResult(next(iter(matches)))
    if len(matches) > 1:
        return LanguageChoiceResult(None, ambiguous=True, matched_codes=tuple(sorted(matches)))
    return LanguageChoiceResult(None)


def normalize_language_choice(text: str) -> str | None:
    """Backward-compatible helper returning a single language code if unambiguous."""
    return resolve_language_choice(text).code
