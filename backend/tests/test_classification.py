"""Classification invariants — fail-closed by design."""

from app.boundary.classification import (
    Classification,
    default_classification,
    is_cloud_eligible,
    merge_classifications,
    parse_classification,
    requires_local_processing,
)


def test_missing_classification_defaults_to_restricted():
    assert parse_classification(None) == Classification.RESTRICTED
    assert default_classification() == Classification.RESTRICTED


def test_unknown_classification_defaults_to_restricted():
    assert parse_classification("TOP_SECRET") == Classification.RESTRICTED
    assert parse_classification("") == Classification.RESTRICTED
    assert parse_classification("  ") == Classification.RESTRICTED


def test_merge_restricted_and_public_safe_is_restricted():
    result = merge_classifications(
        Classification.RESTRICTED, Classification.PUBLIC_SAFE
    )
    assert result == Classification.RESTRICTED


def test_merge_internal_and_public_safe_is_internal():
    result = merge_classifications(
        Classification.INTERNAL, Classification.PUBLIC_SAFE
    )
    assert result == Classification.INTERNAL


def test_merge_empty_defaults_to_restricted():
    assert merge_classifications() == Classification.RESTRICTED


def test_only_public_safe_is_cloud_eligible():
    assert is_cloud_eligible(Classification.PUBLIC_SAFE) is True
    assert is_cloud_eligible(Classification.RESTRICTED) is False
    assert is_cloud_eligible(Classification.INTERNAL) is False
    assert is_cloud_eligible(None) is False


def test_restricted_and_internal_require_local_processing():
    assert requires_local_processing(Classification.RESTRICTED) is True
    assert requires_local_processing(Classification.INTERNAL) is True
    assert requires_local_processing(Classification.PUBLIC_SAFE) is False
