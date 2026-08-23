"""Normalize spoken mobile numbers from local STT transcripts.

Uses the generic digit-stream parser (app.speech.digits) plus Indian mobile
format validation. Account/persona lookup remains in the identity layer.
"""

from __future__ import annotations

import re

from app.speech.digits import (
    clear_digit_speech_config_cache,
    get_digit_speech_config,
    parse_spoken_digit_stream,
)

_INDIAN_MOBILE_RE = re.compile(r"^[6-9]\d{9}$")

# Back-compat aliases for existing imports/tests.
clear_mobile_speech_config_cache = clear_digit_speech_config_cache
get_mobile_speech_config = get_digit_speech_config


def is_valid_indian_mobile(digits: str) -> bool:
    return bool(_INDIAN_MOBILE_RE.match(digits or ""))


def normalize_indian_mobile_digits(raw: str) -> str:
    """Normalize digit text for Indian mobile lookup/validation.

    Only strips a single leading trunk ``0`` when the input is exactly 11 digits
    and the remaining 10 digits are a valid Indian mobile. No other rewriting.
    """
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) == 11 and digits[0] == "0" and is_valid_indian_mobile(digits[1:]):
        return digits[1:]
    return digits


def looks_like_mobile_attempt(text: str) -> bool:
    """True when input is plausibly a citizen reading a mobile number aloud."""
    config = get_digit_speech_config()
    raw = (text or "").strip()
    if not raw:
        return False

    compact = normalize_indian_mobile_digits(raw)
    if is_valid_indian_mobile(compact):
        return True

    if sum(ch.isdigit() for ch in raw) >= 6:
        return True

    stream = parse_spoken_digit_stream(raw, config=config)
    if len(stream) >= 6:
        return True

    word_hits = sum(
        1
        for word in config.number_words
        if (
            re.search(rf"\b{re.escape(word)}\b", raw, flags=re.IGNORECASE)
            if word.isascii()
            else word in raw
        )
    )
    if word_hits >= 6:
        return True

    # Repetition-only utterances (e.g. "double five") are digit attempts.
    lowered = raw.lower()
    for rule in config.repetitions:
        for marker in rule.markers:
            if marker.isascii():
                if re.search(rf"\b{re.escape(marker.lower())}\b", lowered):
                    return True
            elif marker in raw:
                return True
    return False


def extract_spoken_mobile(text: str) -> str | None:
    """Extract a 10-digit Indian mobile from spoken/text input, else None."""
    raw = (text or "").strip()
    if not raw or not looks_like_mobile_attempt(raw):
        return None

    digits = normalize_indian_mobile_digits(parse_spoken_digit_stream(raw))
    if is_valid_indian_mobile(digits):
        return digits
    return None
