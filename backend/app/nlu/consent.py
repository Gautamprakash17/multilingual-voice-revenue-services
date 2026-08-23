"""Consent utterance parsing — shared by NLU and journey handlers."""

from __future__ import annotations

import re

# Decline first — must not treat "I don't agree" as acceptance.
_CONSENT_DECLINE = re.compile(
    r"^\s*(no|n|nope|decline|refuse|i don'?t agree|don'?t agree|i refuse|not agree|"
    r"नहीं|ಇಲ್ಲ)\b",
    re.I,
)

# A trailing separator or end-of-string is required, so a longer word that merely
# starts with an affirmative (e.g. "ಸರಿಪಡಿಸಿ") is not mistaken for acceptance.
_CONSENT_ACCEPT = re.compile(
    r"^\s*(?:yes|y|yeah|yep|yup|ok|okay|sure|agree|i agree|i consent|"
    r"that'?s okay|that is okay|that'?s correct|that is correct|that'?s right|"
    r"confirm|haan|han|हाँ|हां|जी|ठीक|ಹೌದು|ಸರಿ)"
    r"(?:[\s,.!?].*)?$",
    re.I,
)

# Leading affirmative — handles STT echo of the consent prompt or natural phrasing.
_CONSENT_ACCEPT_LEADING = re.compile(
    r"^\s*(yes\s*,?\s*)?(i agree|i consent|agree)\b",
    re.I,
)

# Field confirmation — broader than consent so "try again" / "that's wrong" decline.
_CONFIRM_TAIL = r"(?:[\s,.!?].*)?$"
_FIELD_CONFIRM_NO = re.compile(
    r"^\s*(?:no|n|nope|nah|not correct|not right|incorrect|wrong|that'?s wrong|"
    r"that is wrong|try again|change it|nahi|nahin|नहीं|ना|ಇಲ್ಲ|ಬೇಡ|ತಪ್ಪು)"
    + _CONFIRM_TAIL,
    re.I,
)
_FIELD_CONFIRM_YES = re.compile(
    r"^\s*(?:yes|yeah|yep|yup|y|okay|ok|correct|right|true|"
    r"that'?s correct|that is correct|that'?s right|that is right|"
    r"haan|han|sahi|हाँ|हां|जी|ठीक|ಹೌದು|ಸರಿ)"
    + _CONFIRM_TAIL,
    re.I,
)


def parse_consent_response(text: str) -> bool | None:
    """Return True (grant), False (decline), or None if unclear."""
    raw = (text or "").strip()
    if not raw:
        return None
    if _CONSENT_DECLINE.search(raw):
        return False
    if _CONSENT_ACCEPT.match(raw):
        return True
    if _CONSENT_ACCEPT_LEADING.search(raw):
        return True
    return None


def parse_field_confirmation_response(text: str) -> bool | None:
    """Return True (accept value), False (reject/retry), or None if unclear."""
    raw = (text or "").strip()
    if not raw:
        return None
    token = raw.upper()
    if token in {"YES", "Y"}:
        return True
    if token in {"NO", "N"}:
        return False
    # Decline first so "no, that is wrong" is never read as acceptance.
    if _FIELD_CONFIRM_NO.match(raw):
        return False
    if _FIELD_CONFIRM_YES.match(raw):
        return True
    return parse_consent_response(raw)
