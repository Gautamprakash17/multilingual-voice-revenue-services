"""Tests for spoken mobile-number normalization — rule-focused, not phrase lists."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from app.speech.mobile import (
    clear_mobile_speech_config_cache,
    extract_spoken_mobile,
    get_mobile_speech_config,
    looks_like_mobile_attempt,
    normalize_indian_mobile_digits,
    parse_spoken_digit_stream,
)

LAKSHMI_MOBILE = "9876543210"

ENGLISH_DIGIT_WORDS = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
}


@pytest.mark.parametrize(
    "spoken",
    [
        LAKSHMI_MOBILE,
        "9 8 7 6 5 4 3 2 1 0",
        "9, 8, 7, 6, 5, 4, 3, 2, 1, 0",
        "nine eight seven six five four three two one zero",
        "nine, eight, seven, six, five, four, three, two, one and zero",
    ],
)
def test_lakshmi_mobile_input_formats(spoken: str):
    assert extract_spoken_mobile(spoken) == LAKSHMI_MOBILE


@pytest.mark.parametrize("digit,word", ENGLISH_DIGIT_WORDS.items())
def test_double_marker_repeats_any_digit(digit: str, word: str):
    assert parse_spoken_digit_stream(f"double {word}") == digit * 2
    assert parse_spoken_digit_stream(f"double {digit}") == digit * 2


@pytest.mark.parametrize("digit,word", ENGLISH_DIGIT_WORDS.items())
def test_triple_marker_repeats_any_digit(digit: str, word: str):
    assert parse_spoken_digit_stream(f"triple {word}") == digit * 3
    assert parse_spoken_digit_stream(f"triple {digit}") == digit * 3


@pytest.mark.parametrize(
    ("spoken", "expected_stream"),
    [
        ("nine eight seven double five", "98755"),
        ("9 8 7 double 5", "98755"),
        ("9876543 double one zero", "9876543110"),
        ("9876543 triple one", "9876543111"),
    ],
)
def test_repetition_composes_with_other_digits(spoken: str, expected_stream: str):
    assert parse_spoken_digit_stream(spoken) == expected_stream


def test_hindi_number_words():
    assert (
        extract_spoken_mobile("नौ आठ सात छह पांच चार तीन दो एक शून्य")
        == LAKSHMI_MOBILE
    )


def test_hindi_repetition_markers_compose_generically():
    assert parse_spoken_digit_stream("डबल पांच") == "55"
    assert parse_spoken_digit_stream("दो बार नौ") == "99"
    assert (
        extract_spoken_mobile("नौ आठ सात छह पांच चार तीन डबल एक शून्य")
        == "9876543110"
    )


def test_kannada_number_words():
    assert (
        extract_spoken_mobile("ಒಂಬತ್ತು ಎಂಟು ಏಳು ಆರು ಐದು ನಾಲ್ಕು ಮೂರು ಎರಡು ಒಂದು ಸೊನ್ನೆ")
        == LAKSHMI_MOBILE
    )


def test_kannada_repetition_marker_compose_generically():
    assert parse_spoken_digit_stream("ಎರಡು ಬಾರಿ ಐದು") == "55"


@pytest.mark.parametrize(
    "spoken",
    [
        "98765",
        "9 8 7 6 5 4 3 2 1 double 0",
        "7, 2, 0, 4, 6, 0, 9, 1 and the whole 5",
        "one two three four five",
    ],
)
def test_invalid_or_incomplete_speech_returns_none(spoken: str):
    assert extract_spoken_mobile(spoken) is None


def test_valid_format_unknown_number_still_normalizes():
    assert extract_spoken_mobile("9123456789") == "9123456789"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9876543210", "9876543210"),
        ("07204609155", "7204609155"),
        ("09876543210", "9876543210"),
        ("9 8 7 6 5 4 3 2 1 0", "9876543210"),
        ("0 7 2 0 4 6 0 9 1 5 5", "7204609155"),
    ],
)
def test_leading_zero_trunk_prefix_normalization(raw: str, expected: str):
    assert normalize_indian_mobile_digits(raw) == expected
    assert extract_spoken_mobile(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "007204609155",  # 12 digits — do not strip
        "01234567890",  # 11 digits but remaining invalid (starts with 1)
        "17204609155",  # 11 digits not starting with 0
        "0720460915",  # 10 digits starting with 0
    ],
)
def test_leading_zero_not_stripped_unless_exact_rule(raw: str):
    digits = "".join(ch for ch in raw if ch.isdigit())
    assert normalize_indian_mobile_digits(raw) == digits
    assert extract_spoken_mobile(raw) is None


def test_normal_sentence_not_treated_as_mobile():
    assert looks_like_mobile_attempt("I need help with my application") is False
    assert extract_spoken_mobile("I need help with my application") is None


def test_config_number_word_alias_without_python_changes(tmp_path, monkeypatch):
    source = yaml.safe_load(
        Path(__file__).resolve().parents[2].joinpath("config/speech/mobile.yaml").read_text(
            encoding="utf-8"
        )
    )
    source["number_words"]["configalias"] = "7"
    temp_path = tmp_path / "mobile.yaml"
    temp_path.write_text(yaml.safe_dump(source), encoding="utf-8")

    monkeypatch.setenv("MOBILE_SPEECH_CONFIG_PATH", str(temp_path))
    clear_mobile_speech_config_cache()
    try:
        assert parse_spoken_digit_stream("configalias") == "7"
    finally:
        monkeypatch.delenv("MOBILE_SPEECH_CONFIG_PATH", raising=False)
        clear_mobile_speech_config_cache()


def test_config_repetition_marker_without_python_changes(tmp_path, monkeypatch):
    source = yaml.safe_load(
        Path(__file__).resolve().parents[2].joinpath("config/speech/mobile.yaml").read_text(
            encoding="utf-8"
        )
    )
    source["repetitions"].append({"count": 2, "markers": ["configdouble"]})
    temp_path = tmp_path / "mobile.yaml"
    temp_path.write_text(yaml.safe_dump(source), encoding="utf-8")

    monkeypatch.setenv("MOBILE_SPEECH_CONFIG_PATH", str(temp_path))
    clear_mobile_speech_config_cache()
    try:
        assert parse_spoken_digit_stream("configdouble nine") == "99"
    finally:
        monkeypatch.delenv("MOBILE_SPEECH_CONFIG_PATH", raising=False)
        clear_mobile_speech_config_cache()


def test_config_is_loaded():
    config = get_mobile_speech_config()
    assert config.number_words["nine"] == "9"
    assert config.number_words["ಒಂಬತ್ತು"] == "9"
    assert any(rule.count == 2 for rule in config.repetitions)
