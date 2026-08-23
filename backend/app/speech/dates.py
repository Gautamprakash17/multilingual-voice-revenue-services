"""Generic spoken date normalization for catalogue ``date`` fields.

Composes the shared digit-stream parser plus a small atomic month-word map.
Never invents missing digits. Callers must still run ``validate_field``.
"""

from __future__ import annotations

import re

from app.speech.digits import (
    _is_filler,
    _match_repetition,
    _resolve_digit_token,
    _tokenize,
    get_digit_speech_config,
    parse_spoken_digit_stream,
)

# Atomic month tokens only — not phrase dictionaries.
_MONTH_WORDS: dict[str, str] = {
    # English
    "january": "01",
    "jan": "01",
    "february": "02",
    "feb": "02",
    "march": "03",
    "mar": "03",
    "april": "04",
    "apr": "04",
    "may": "05",
    "june": "06",
    "jun": "06",
    "july": "07",
    "jul": "07",
    "august": "08",
    "aug": "08",
    "september": "09",
    "sept": "09",
    "sep": "09",
    "october": "10",
    "oct": "10",
    "november": "11",
    "nov": "11",
    "december": "12",
    "dec": "12",
    # Hindi (common calendar month names)
    "जनवरी": "01",
    "फरवरी": "02",
    "मार्च": "03",
    "अप्रैल": "04",
    "मई": "05",
    "जून": "06",
    "जुलाई": "07",
    "अगस्त": "08",
    "सितंबर": "09",
    "सितम्बर": "09",
    "अक्टूबर": "10",
    "नवंबर": "11",
    "नवम्बर": "11",
    "दिसंबर": "12",
    "दिसम्बर": "12",
    # Kannada
    "ಜನವರಿ": "01",
    "ಫೆಬ್ರವರಿ": "02",
    "ಮಾರ್ಚ್": "03",
    "ಏಪ್ರಿಲ್": "04",
    "ಮೇ": "05",
    "ಜೂನ್": "06",
    "ಜುಲೈ": "07",
    "ಆಗಸ್ಟ್": "08",
    "ಸೆಪ್ಟೆಂಬರ್": "09",
    "ಅಕ್ಟೋಬರ್": "10",
    "ನವೆಂಬರ್": "11",
    "ಡಿಸೆಂಬರ್": "12",
}

_SEPARATOR_WORDS = re.compile(
    r"\b(slash|dashed?|hyphen|dot|point)\b",
    re.IGNORECASE,
)
_ORDINAL_SUFFIX = re.compile(r"\b(\d+)(st|nd|rd|th)\b", re.IGNORECASE)


def _replace_month_words(text: str) -> str:
    working = text
    for name, month in sorted(_MONTH_WORDS.items(), key=lambda item: len(item[0]), reverse=True):
        if name.isascii():
            working = re.sub(
                rf"\b{re.escape(name)}\b", f" {month} ", working, flags=re.IGNORECASE
            )
        elif name in working:
            working = working.replace(name, f" {month} ")
    return working


def _has_month_word(text: str) -> bool:
    lower = text.lower()
    for name in _MONTH_WORDS:
        if name.isascii():
            if re.search(rf"\b{re.escape(name)}\b", lower):
                return True
        elif name in text:
            return True
    return False


def looks_like_date_attempt(text: str) -> bool:
    """Conservative gate so ordinary sentences are not treated as dates."""
    raw = (text or "").strip()
    if not raw:
        return False
    if _has_month_word(raw):
        return True
    digit_chars = sum(ch.isdigit() for ch in raw)
    if digit_chars >= 6:
        return True
    stream = parse_spoken_digit_stream(_prepare_date_transcript(raw))
    return len(stream) >= 6


def _prepare_date_transcript(text: str) -> str:
    working = (text or "").strip()
    working = _ORDINAL_SUFFIX.sub(r"\1", working)
    working = _replace_month_words(working)
    working = _SEPARATOR_WORDS.sub(" ", working)
    working = re.sub(r"[./\\|,;:+\-]+", " ", working)
    return working


def normalize_spoken_date(text: str) -> str | None:
    """Normalize spoken/STT date input to ``DD/MM/YYYY`` digits, or None.

    Returns None when the transcript is not a clear date attempt or does not
    yield exactly eight digits (DD+MM+YYYY). Does not invent missing digits.
    Calendar/future checks remain in ``validate_field``.
    """
    raw = (text or "").strip()
    if not raw or not looks_like_date_attempt(raw):
        return None

    prepared = _prepare_date_transcript(raw)
    digits = parse_spoken_digit_stream(prepared)
    if len(digits) != 8:
        return None
    return f"{digits[0:2]}/{digits[2:4]}/{digits[4:8]}"


def normalize_spoken_number_field(text: str) -> str | None:
    """Normalize spoken/STT numeric field input to a digit string, or None.

    Reuses the generic digit stream. Rejects ordinary sentences that merely
    contain a few digits. Comma/₹ formatting is left for ``validate_field`` when
    the utterance is already a typed numeric literal.
    """
    raw = (text or "").strip()
    if not raw:
        return None

    if re.fullmatch(r"[₹\s]*[\d,]+(?:\.\d+)?[₹\s]*", raw):
        return raw

    stream = parse_spoken_digit_stream(raw)
    if not stream:
        return None
    if not _looks_like_numeric_utterance(raw, stream):
        return None
    return stream


def _looks_like_numeric_utterance(raw: str, stream: str) -> bool:
    if re.fullmatch(r"[\d\s,./₹\-]+", raw):
        return True
    config = get_digit_speech_config()
    tokens = _tokenize(raw)
    unknown = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _is_filler(token, config):
            index += 1
            continue
        matched = _match_repetition(tokens, index, config)
        if matched:
            _rule, width = matched
            index += width
            if index < len(tokens) and _resolve_digit_token(tokens[index], config):
                index += 1
            continue
        if token.isdigit() or _resolve_digit_token(token, config) is not None:
            index += 1
            continue
        unknown += 1
        index += 1
    if len(stream) >= 4:
        return unknown <= 4
    return unknown <= 2 and len(stream) >= 1


def normalize_spoken_text_field(text: str) -> str:
    """Light STT cleanup for string fields — never reinterpret as numbers/dates."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) > 1 and cleaned.endswith(".") and cleaned.count(".") == 1:
        cleaned = cleaned[:-1].rstrip()
    return cleaned
