"""Spoken person-name cleanup for voice/IVR name fields.

Strips common conversational prefixes from STT transcripts. Does not invent
names — if a prefix is matched but no usable name remains, returns None so
callers keep existing validation/retry behavior.
"""

from __future__ import annotations

import re

from app.speech.dates import normalize_spoken_text_field

# Person-name field keys only — never apply to address/occupation/etc.
PERSON_NAME_FIELDS: frozenset[str] = frozenset({"applicant_name", "register_name"})

# Leading conversational wrappers (English STT). Apostrophe variants for STT.
# Matches prefix alone (uncertain) or prefix + separator before the name.
_NAME_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"my\s+name(?:['\u2019\u2032]s|\s+is)"
    r"|i(?:['\u2019\u2032]m|\s+am)"
    r"|this\s+is"
    r")"
    r"(?:\s*[:\-–—]\s*|\s+|$)",
    re.IGNORECASE,
)

_LEADING_PUNCT = re.compile(r"^[:\-–—]\s*")


def is_person_name_field(field_name: str | None) -> bool:
    return bool(field_name) and field_name in PERSON_NAME_FIELDS


def _usable_person_name(value: str) -> bool:
    if len(value) < 2:
        return False
    if value.isdigit():
        return False
    return any(ch.isalpha() for ch in value)


def normalize_spoken_person_name(text: str) -> str | None:
    """Extract a person name from a spoken/typed STT-style transcript.

    Returns:
      - The name after stripping a known prefix, when the remainder looks usable.
      - Light-cleaned original text when no prefix matches.
      - ``None`` when input is empty or a prefix left no usable name
        (caller should retry / fail validation — do not store the sentence).
    """
    cleaned = normalize_spoken_text_field(text or "")
    if not cleaned:
        return None

    match = _NAME_PREFIX_RE.match(cleaned)
    if not match:
        return cleaned

    remainder = cleaned[match.end() :].strip()
    remainder = _LEADING_PUNCT.sub("", remainder).strip()
    if not _usable_person_name(remainder):
        return None
    return remainder
