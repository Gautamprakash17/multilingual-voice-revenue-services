"""Data classification model — fail-closed by design.

Classifications (exactly as specified for the POC):
  RESTRICTED  — citizen/government mock data; local only; never to cloud
  INTERNAL    — operational/session data; local by default
  PUBLIC_SAFE — non-sensitive content; cloud only after explicit policy approval
"""

from __future__ import annotations

from enum import StrEnum


class Classification(StrEnum):
    """Mandatory data classification labels."""

    RESTRICTED = "RESTRICTED"
    INTERNAL = "INTERNAL"
    PUBLIC_SAFE = "PUBLIC_SAFE"


# Strictness order: higher index = more restrictive.
_STRICTNESS: dict[Classification, int] = {
    Classification.PUBLIC_SAFE: 0,
    Classification.INTERNAL: 1,
    Classification.RESTRICTED: 2,
}

_DEFAULT = Classification.RESTRICTED


def parse_classification(value: str | Classification | None) -> Classification:
    """Parse a classification label. Missing/unknown → RESTRICTED (fail-closed)."""
    if value is None:
        return _DEFAULT
    if isinstance(value, Classification):
        return value
    try:
        return Classification(str(value).strip().upper())
    except ValueError:
        return _DEFAULT


def default_classification() -> Classification:
    """Fail-closed default when no classification is supplied."""
    return _DEFAULT


def merge_classifications(*values: Classification | str | None) -> Classification:
    """Merge classifications: the most restrictive wins.

    Example: RESTRICTED + PUBLIC_SAFE = RESTRICTED
    """
    if not values:
        return _DEFAULT
    parsed = [parse_classification(v) for v in values]
    return max(parsed, key=lambda c: _STRICTNESS[c])


def is_cloud_eligible(classification: Classification | str | None) -> bool:
    """Whether a classification *may* be considered for cloud (still needs policy).

    Only PUBLIC_SAFE is eligible. RESTRICTED and INTERNAL are never cloud-eligible
    at the classification layer.
    """
    return parse_classification(classification) == Classification.PUBLIC_SAFE


def requires_local_processing(classification: Classification | str | None) -> bool:
    """True when data must stay in the local trust zone."""
    return parse_classification(classification) in (
        Classification.RESTRICTED,
        Classification.INTERNAL,
    )
