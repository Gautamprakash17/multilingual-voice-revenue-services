"""Deterministic journey state machine for certificate applications."""

from __future__ import annotations

from enum import StrEnum


class JourneyState(StrEnum):
    LANGUAGE_SELECT = "LANGUAGE_SELECT"
    AUTHENTICATE = "AUTHENTICATE"
    CONSENT = "CONSENT"
    SERVICE_SELECT = "SERVICE_SELECT"
    FORM_CAPTURE = "FORM_CAPTURE"
    FIELD_CONFIRMATION = "FIELD_CONFIRMATION"
    DOCUMENT_CAPTURE = "DOCUMENT_CAPTURE"
    REVIEW_CONFIRM = "REVIEW_CONFIRM"
    FEE_QUOTE = "FEE_QUOTE"
    PAYMENT = "PAYMENT"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    SUBMITTED = "SUBMITTED"
    CORRECTION = "CORRECTION"
    ESCALATED = "ESCALATED"
    AUTH_FAILED = "AUTH_FAILED"
    DOCUMENT_REJECTED = "DOCUMENT_REJECTED"


class ProcessingStatus(StrEnum):
    """Post-submission processing lifecycle (officer-facing)."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_CORRECTION = "NEEDS_CORRECTION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ISSUED = "ISSUED"


# Allowed directed edges. Invalid transitions are rejected.
ALLOWED_TRANSITIONS: dict[JourneyState, frozenset[JourneyState]] = {
    JourneyState.LANGUAGE_SELECT: frozenset(
        {JourneyState.AUTHENTICATE, JourneyState.ESCALATED}
    ),
    JourneyState.AUTHENTICATE: frozenset(
        {
            JourneyState.CONSENT,
            JourneyState.AUTH_FAILED,
            JourneyState.ESCALATED,
            JourneyState.FIELD_CONFIRMATION,
        }
    ),
    JourneyState.AUTH_FAILED: frozenset(
        {JourneyState.AUTHENTICATE, JourneyState.ESCALATED}
    ),
    JourneyState.CONSENT: frozenset(
        {JourneyState.SERVICE_SELECT, JourneyState.ESCALATED}
    ),
    JourneyState.SERVICE_SELECT: frozenset(
        {JourneyState.FORM_CAPTURE, JourneyState.ESCALATED}
    ),
    JourneyState.FORM_CAPTURE: frozenset(
        {
            JourneyState.FIELD_CONFIRMATION,
            JourneyState.DOCUMENT_CAPTURE,
            JourneyState.CORRECTION,
            JourneyState.ESCALATED,
            JourneyState.REVIEW_CONFIRM,
        }
    ),
    JourneyState.FIELD_CONFIRMATION: frozenset(
        {
            JourneyState.FORM_CAPTURE,
            JourneyState.AUTHENTICATE,
            JourneyState.CONSENT,
            JourneyState.ESCALATED,
        }
    ),
    JourneyState.DOCUMENT_CAPTURE: frozenset(
        {
            JourneyState.REVIEW_CONFIRM,
            JourneyState.DOCUMENT_REJECTED,
            JourneyState.ESCALATED,
        }
    ),
    JourneyState.DOCUMENT_REJECTED: frozenset(
        {JourneyState.DOCUMENT_CAPTURE, JourneyState.ESCALATED}
    ),
    JourneyState.REVIEW_CONFIRM: frozenset(
        {
            JourneyState.FEE_QUOTE,
            JourneyState.CORRECTION,
            JourneyState.ESCALATED,
            # Re-submit after correction when payment already completed
            JourneyState.SUBMITTED,
        }
    ),
    JourneyState.FEE_QUOTE: frozenset(
        {
            JourneyState.PAYMENT,
            JourneyState.CORRECTION,
            JourneyState.REVIEW_CONFIRM,
            JourneyState.ESCALATED,
        }
    ),
    JourneyState.PAYMENT: frozenset(
        {
            JourneyState.SUBMITTED,
            JourneyState.PAYMENT_FAILED,
            JourneyState.FEE_QUOTE,
            JourneyState.ESCALATED,
        }
    ),
    JourneyState.PAYMENT_FAILED: frozenset(
        {JourneyState.PAYMENT, JourneyState.FEE_QUOTE, JourneyState.ESCALATED}
    ),
    JourneyState.CORRECTION: frozenset(
        {JourneyState.FORM_CAPTURE, JourneyState.DOCUMENT_CAPTURE, JourneyState.ESCALATED}
    ),
    # Officer-driven reopen for targeted correction after submission
    JourneyState.SUBMITTED: frozenset({JourneyState.CORRECTION}),
    JourneyState.ESCALATED: frozenset(
        {JourneyState.REVIEW_CONFIRM, JourneyState.SUBMITTED}
    ),
}

NORMAL_CONVERSATIONAL_STATES = frozenset(
    {
        JourneyState.LANGUAGE_SELECT,
        JourneyState.AUTHENTICATE,
        JourneyState.CONSENT,
        JourneyState.SERVICE_SELECT,
        JourneyState.FORM_CAPTURE,
        JourneyState.FIELD_CONFIRMATION,
        JourneyState.DOCUMENT_CAPTURE,
        JourneyState.REVIEW_CONFIRM,
        JourneyState.FEE_QUOTE,
        JourneyState.PAYMENT,
        JourneyState.PAYMENT_FAILED,
        JourneyState.CORRECTION,
        JourneyState.AUTH_FAILED,
        JourneyState.DOCUMENT_REJECTED,
    }
)


class InvalidTransitionError(ValueError):
    """Raised when a state transition is not allowed."""

    def __init__(self, current: JourneyState, target: JourneyState) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Invalid transition: {current.value} → {target.value}")


def can_transition(current: JourneyState | str, target: JourneyState | str) -> bool:
    cur = JourneyState(current)
    tgt = JourneyState(target)
    return tgt in ALLOWED_TRANSITIONS.get(cur, frozenset())


def assert_transition(current: JourneyState | str, target: JourneyState | str) -> None:
    cur = JourneyState(current)
    tgt = JourneyState(target)
    if not can_transition(cur, tgt):
        raise InvalidTransitionError(cur, tgt)


def initial_state() -> JourneyState:
    return JourneyState.LANGUAGE_SELECT
