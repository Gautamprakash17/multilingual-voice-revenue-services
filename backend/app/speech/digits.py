"""Generic spoken digit-stream parsing.

Configuration (config/speech/mobile.yaml) provides only fundamental vocabulary:
  - number words → digits
  - repetition markers → count
  - filler words

Python composes those tokens into a digit stream of arbitrary length.
Callers apply domain validation (mobile length, OTP length, etc.).
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# Latin words, Devanagari, Kannada — split on whitespace within script runs.
_TOKEN_RE = re.compile(
    r"\d+|"
    r"[a-zA-Z]+|"
    r"[\u0900-\u097F]+(?:\s+[\u0900-\u097F]+)*|"
    r"[\u0C80-\u0CFF]+(?:\s+[\u0C80-\u0CFF]+)*"
)

# POC seeded OTPs are 6 digits; format gate only — values stay in persona seed.
_OTP_FORMAT_RE = re.compile(r"^\d{6}$")


@dataclass(frozen=True)
class RepetitionRule:
    count: int
    markers: tuple[str, ...]


@dataclass(frozen=True)
class DigitSpeechConfig:
    number_words: dict[str, str]
    filler_words: frozenset[str]
    repetitions: tuple[RepetitionRule, ...]


def _config_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "speech" / "mobile.yaml"
        if candidate.exists():
            return candidate.parent.parent
    return Path.cwd() / "config"


def _digits_config_path() -> Path:
    override = os.environ.get("MOBILE_SPEECH_CONFIG_PATH") or os.environ.get(
        "DIGITS_SPEECH_CONFIG_PATH"
    )
    if override:
        return Path(override)
    return _config_root() / "speech" / "mobile.yaml"


def _parse_digit_config(raw: dict[str, Any]) -> DigitSpeechConfig:
    number_words = {str(k): str(v) for k, v in (raw.get("number_words") or {}).items()}
    filler_words = frozenset(str(w).lower() for w in (raw.get("filler_words") or []))
    repetitions: list[RepetitionRule] = []
    for spec in raw.get("repetitions") or []:
        repetitions.append(
            RepetitionRule(
                count=int(spec["count"]),
                markers=tuple(str(m) for m in (spec.get("markers") or [])),
            )
        )
    repetitions.sort(
        key=lambda rule: max(len(m.split()) for m in rule.markers), reverse=True
    )
    return DigitSpeechConfig(
        number_words=number_words,
        filler_words=filler_words,
        repetitions=tuple(repetitions),
    )


@lru_cache
def get_digit_speech_config() -> DigitSpeechConfig:
    path = _digits_config_path()
    with path.open(encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}
    return _parse_digit_config(raw)


def clear_digit_speech_config_cache() -> None:
    get_digit_speech_config.cache_clear()


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(text):
        piece = match.group(0).strip()
        if not piece:
            continue
        if piece.isdigit():
            tokens.append(piece)
            continue
        if re.fullmatch(r"[a-zA-Z]+", piece):
            tokens.append(piece.lower())
            continue
        tokens.extend(part for part in piece.split() if part)
    return tokens


def _is_filler(token: str, config: DigitSpeechConfig) -> bool:
    return token.lower() in config.filler_words


def _resolve_digit_token(token: str, config: DigitSpeechConfig) -> str | None:
    if len(token) == 1:
        # Unicode Nd digits (ASCII, Devanagari, Kannada, …) → ASCII 0-9
        try:
            return str(unicodedata.digit(token))
        except (TypeError, ValueError):
            pass
    lower = token.lower()
    if lower in config.number_words:
        return config.number_words[lower]
    if token in config.number_words:
        return config.number_words[token]
    if token.isdigit() and token.isascii():
        # Multi-digit ASCII runs handled by caller via list(token); keep single here.
        return token if len(token) == 1 else None
    return None


def _match_repetition(
    tokens: list[str], index: int, config: DigitSpeechConfig
) -> tuple[RepetitionRule, int] | None:
    for rule in config.repetitions:
        for marker in sorted(rule.markers, key=lambda m: len(m.split()), reverse=True):
            marker_tokens = marker.split()
            width = len(marker_tokens)
            if index + width > len(tokens):
                continue
            candidate = tokens[index : index + width]
            if marker_tokens[0].isascii():
                if [t.lower() for t in candidate] != [m.lower() for m in marker_tokens]:
                    continue
            elif candidate != marker_tokens:
                continue
            return rule, width
    return None


def parse_spoken_digit_stream(
    text: str, *, config: DigitSpeechConfig | None = None
) -> str:
    """Parse speech/text into a digit stream using generic composition rules.

    Returns only digits found in the transcript — never invents missing digits.
    Length may be anything (including zero); callers validate domain format.
    """
    cfg = config or get_digit_speech_config()
    tokens = _tokenize((text or "").strip())
    if not tokens:
        return ""

    digits: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _is_filler(token, cfg):
            index += 1
            continue

        matched = _match_repetition(tokens, index, cfg)
        if matched:
            rule, width = matched
            index += width
            if index >= len(tokens):
                break
            digit = _resolve_digit_token(tokens[index], cfg)
            if digit is not None:
                digits.extend([digit] * rule.count)
                index += 1
                continue
            index += 1
            continue

        if token.isdigit():
            for ch in token:
                try:
                    digits.append(str(unicodedata.digit(ch)))
                except (TypeError, ValueError):
                    if ch.isascii() and ch.isdigit():
                        digits.append(ch)
            index += 1
            continue

        digit = _resolve_digit_token(token, cfg)
        if digit is not None:
            digits.append(digit)
            index += 1
            continue

        # Unknown token — skip without inventing a digit.
        index += 1

    return "".join(digits)


def is_valid_otp_format(digits: str) -> bool:
    """POC OTP format gate (6 digits). Does not check persona values."""
    return bool(_OTP_FORMAT_RE.match(digits or ""))


def looks_like_otp_attempt(text: str) -> bool:
    """Conservative gate so normal sentences are not treated as OTPs."""
    raw = (text or "").strip()
    if not raw:
        return False

    compact = re.sub(r"\D", "", raw)
    if is_valid_otp_format(compact):
        return True

    digit_chars = sum(ch.isdigit() for ch in raw)
    if digit_chars >= 4:
        return True

    config = get_digit_speech_config()
    stream = parse_spoken_digit_stream(raw, config=config)
    if 4 <= len(stream) <= 8:
        return True

    tokens = _tokenize(raw)
    for index, _token in enumerate(tokens):
        if _match_repetition(tokens, index, config) is not None:
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
    return word_hits >= 4


def normalize_spoken_otp(text: str) -> str | None:
    """Normalize spoken/typed OTP via the generic digit stream.

    Returns a format-valid OTP digit string, or None when the transcript does
    not yield a valid OTP format. Never invents missing digits.
    """
    raw = (text or "").strip()
    if not raw:
        return None

    # Pure typed OTP (already exact format) — keep working without speech gate.
    if is_valid_otp_format(raw):
        return raw

    if not looks_like_otp_attempt(raw):
        return None

    digits = parse_spoken_digit_stream(raw)
    if is_valid_otp_format(digits):
        return digits
    return None


# Fields whose confirmation value must be spoken digit-by-digit (TTS only).
DIGIT_SPEECH_CONFIRM_FIELDS = frozenset({"mobile_number", "otp"})


def format_digits_for_speech(value: str) -> str:
    """Space-separate digits so local TTS reads them one-by-one.

    Presentation helper only — does not change stored/normalized values.
    Non-digit characters are dropped; empty input returns empty string.
    """
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if not digits:
        return ""
    # Spaces give eSpeak short pauses between digits without SSML.
    return " ".join(digits)


def speech_value_for_confirmation(field_name: str | None, value: str) -> str:
    """Return the value string to embed in a spoken confirmation prompt."""
    if field_name in DIGIT_SPEECH_CONFIRM_FIELDS:
        spaced = format_digits_for_speech(value)
        return spaced if spaced else value
    if field_name == "date_of_birth" or (
        value and re.fullmatch(r"\d{2}/\d{2}/\d{4}", (value or "").strip())
    ):
        from app.speech.dates import format_date_for_citizen

        return format_date_for_citizen(value)
    return value
