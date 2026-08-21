"""Deterministic journey state machine for certificate applications."""

from __future__ import annotations

from enum import StrEnum


class JourneyState(StrEnum):
    LANGUAGE_SELECT = "LANGUAGE_SELECT"
    AUTHENTICATE = "AUTHENTICATE"
    CONSENT = "CONSENT"
    SERVICE_SELECT = "SERVICE_SELECT"
    FORM_CAPTURE = "FORM_CAPTURE"
    DOCUMENT_CAPTURE = "DOCUMENT_CAPTURE"
    REVIEW_CONFIRM = "REVIEW_CONFIRM"
    SUBMITTED = "SUBMITTED"
    CORRECTION = "CORRECTION"
    ESCALATED = "ESCALATED"
    AUTH_FAILED = "AUTH_FAILED"
    DOCUMENT_REJECTED = "DOCUMENT_REJECTED"


# Allowed directed edges. Invalid transitions are rejected.
ALLOWED_TRANSITIONS: dict[JourneyState, frozenset[JourneyState]] = {
    JourneyState.LANGUAGE_SELECT: frozenset(
        {JourneyState.AUTHENTICATE, JourneyState.ESCALATED}
    ),
    JourneyState.AUTHENTICATE: frozenset(
        {JourneyState.CONSENT, JourneyState.AUTH_FAILED, JourneyState.ESCALATED}
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
            JourneyState.DOCUMENT_CAPTURE,
            JourneyState.CORRECTION,
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
            JourneyState.SUBMITTED,
            JourneyState.CORRECTION,
            JourneyState.ESCALATED,
        }
    ),
    JourneyState.CORRECTION: frozenset(
        {JourneyState.FORM_CAPTURE, JourneyState.ESCALATED}
    ),
    JourneyState.SUBMITTED: frozenset(),
    JourneyState.ESCALATED: frozenset(),
}

NORMAL_CONVERSATIONAL_STATES = frozenset(
    {
        JourneyState.LANGUAGE_SELECT,
        JourneyState.AUTHENTICATE,
        JourneyState.CONSENT,
        JourneyState.SERVICE_SELECT,
        JourneyState.FORM_CAPTURE,
        JourneyState.DOCUMENT_CAPTURE,
        JourneyState.REVIEW_CONFIRM,
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
