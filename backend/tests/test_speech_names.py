"""Spoken person-name prefix stripping — unit tests."""

from __future__ import annotations

import pytest
from app.speech.names import (
    is_person_name_field,
    normalize_spoken_person_name,
)


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("My name is Gautam Prakash", "Gautam Prakash"),
        ("My name's Gautam Prakash", "Gautam Prakash"),
        ("I am Gautam Prakash", "Gautam Prakash"),
        ("Gautam Prakash", "Gautam Prakash"),
        ("I'm Gautam Prakash", "Gautam Prakash"),
        ("this is Gautam Prakash", "Gautam Prakash"),
        ("My name is Gautam Prakash.", "Gautam Prakash"),
        ("  My name is   Gautam Prakash  ", "Gautam Prakash"),
        ("my name is: Gautam Prakash", "Gautam Prakash"),
    ],
)
def test_normalize_spoken_person_name_prefixes(spoken: str, expected: str):
    assert normalize_spoken_person_name(spoken) == expected


@pytest.mark.parametrize(
    "spoken",
    [
        "",
        "   ",
        "My name is",
        "My name's",
        "I am",
        "I'm",
        "this is",
        "My name is 12",
    ],
)
def test_normalize_spoken_person_name_uncertain_returns_none(spoken: str):
    assert normalize_spoken_person_name(spoken) is None


def test_normalize_does_not_hardcode_specific_names():
    assert normalize_spoken_person_name("My name is Ada Lovelace") == "Ada Lovelace"
    assert normalize_spoken_person_name("I am Priya Sharma") == "Priya Sharma"


def test_person_name_field_allowlist():
    assert is_person_name_field("applicant_name") is True
    assert is_person_name_field("register_name") is True
    assert is_person_name_field("address") is False
    assert is_person_name_field("occupation") is False
    assert is_person_name_field(None) is False
