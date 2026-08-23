"""Tests for spoken OTP normalization via the generic digit-stream parser."""

from __future__ import annotations

import pytest
from app.speech.digits import (
    format_digits_for_speech,
    normalize_spoken_otp,
    parse_spoken_digit_stream,
    speech_value_for_confirmation,
)
from app.speech.mobile import extract_spoken_mobile

LAKSHMI_OTP = "123456"

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
        "123456",
        "1 2 3 4 5 6",
        "1, 2, 3, 4, 5, 6",
        "one two three four five six",
        "one, two, three, four, five, six",
    ],
)
def test_normalize_spoken_otp_basic_formats(spoken: str):
    assert normalize_spoken_otp(spoken) == LAKSHMI_OTP


@pytest.mark.parametrize("digit,word", ENGLISH_DIGIT_WORDS.items())
def test_otp_digit_stream_double_and_triple(digit: str, word: str):
    assert parse_spoken_digit_stream(f"double {word}") == digit * 2
    assert parse_spoken_digit_stream(f"double {digit}") == digit * 2
    assert parse_spoken_digit_stream(f"triple {word}") == digit * 3
    assert parse_spoken_digit_stream(f"triple {digit}") == digit * 3


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("double two double three", "2233"),
        ("333 555", "333555"),
        ("22 33", "2233"),
        ("double 1 double 2 double 3", "112233"),
        ("one double two three four five", "122345"),
    ],
)
def test_otp_digit_stream_composition(spoken: str, expected: str):
    assert parse_spoken_digit_stream(spoken) == expected


def test_normalize_otp_from_repetition_composition():
    # double 1 + double 2 + double 3 → 112233 (valid 6-digit format)
    assert normalize_spoken_otp("double 1 double 2 double 3") == "112233"


def test_hindi_otp_number_words():
    assert normalize_spoken_otp("एक दो तीन चार पांच छह") == "123456"


def test_kannada_otp_number_words():
    assert normalize_spoken_otp("ಒಂದು ಎರಡು ಮೂರು ನಾಲ್ಕು ಐದು ಆರು") == "123456"


def test_hindi_repetition_in_digit_stream():
    assert parse_spoken_digit_stream("डबल दो") == "22"


@pytest.mark.parametrize(
    "spoken",
    [
        "1 2 3 4",
        "1234567",
        "abcdef",
        "I need help with my application",
        "1 2 3 and the whole",
    ],
)
def test_normalize_spoken_otp_rejects_invalid(spoken: str):
    assert normalize_spoken_otp(spoken) is None


def test_mobile_normalization_still_works_alongside_otp_parser():
    assert extract_spoken_mobile("9 8 7 6 5 4 3 2 1 0") == "9876543210"
    assert normalize_spoken_otp("1 2 3 4 5 6") == "123456"


@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        ("7204609155", "7 2 0 4 6 0 9 1 5 5"),
        ("123456", "1 2 3 4 5 6"),
        ("9876543210", "9 8 7 6 5 4 3 2 1 0"),
    ],
)
def test_format_digits_for_speech(raw: str, spoken: str):
    assert format_digits_for_speech(raw) == spoken


def test_speech_value_for_confirmation_digit_fields_only():
    assert speech_value_for_confirmation("mobile_number", "7204609155") == (
        "7 2 0 4 6 0 9 1 5 5"
    )
    assert speech_value_for_confirmation("otp", "123456") == "1 2 3 4 5 6"
    assert speech_value_for_confirmation("applicant_name", "Gotham") == "Gotham"
    assert speech_value_for_confirmation("annual_income", "120000") == "120000"

