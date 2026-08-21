"""P2 state machine tests."""

from app.services.state_machine import (
    InvalidTransitionError,
    JourneyState,
    assert_transition,
    can_transition,
    initial_state,
)


def test_initial_state_is_language_select():
    assert initial_state() == JourneyState.LANGUAGE_SELECT


def test_valid_happy_path_transitions():
    path = [
        (JourneyState.LANGUAGE_SELECT, JourneyState.AUTHENTICATE),
        (JourneyState.AUTHENTICATE, JourneyState.CONSENT),
        (JourneyState.CONSENT, JourneyState.SERVICE_SELECT),
        (JourneyState.SERVICE_SELECT, JourneyState.FORM_CAPTURE),
        (JourneyState.FORM_CAPTURE, JourneyState.DOCUMENT_CAPTURE),
        (JourneyState.DOCUMENT_CAPTURE, JourneyState.REVIEW_CONFIRM),
        (JourneyState.REVIEW_CONFIRM, JourneyState.SUBMITTED),
    ]
    for current, target in path:
        assert can_transition(current, target)
        assert_transition(current, target)


def test_invalid_transition_rejected():
    assert not can_transition(JourneyState.LANGUAGE_SELECT, JourneyState.SUBMITTED)
    try:
        assert_transition(JourneyState.LANGUAGE_SELECT, JourneyState.SUBMITTED)
        raise AssertionError("expected InvalidTransitionError")
    except InvalidTransitionError as exc:
        assert exc.current == JourneyState.LANGUAGE_SELECT
        assert exc.target == JourneyState.SUBMITTED


def test_recovery_transitions():
    assert can_transition(JourneyState.AUTHENTICATE, JourneyState.AUTH_FAILED)
    assert can_transition(JourneyState.AUTH_FAILED, JourneyState.AUTHENTICATE)
    assert can_transition(JourneyState.DOCUMENT_CAPTURE, JourneyState.DOCUMENT_REJECTED)
    assert can_transition(JourneyState.DOCUMENT_REJECTED, JourneyState.DOCUMENT_CAPTURE)
    assert can_transition(JourneyState.REVIEW_CONFIRM, JourneyState.CORRECTION)
    assert can_transition(JourneyState.CORRECTION, JourneyState.FORM_CAPTURE)
    assert can_transition(JourneyState.FORM_CAPTURE, JourneyState.ESCALATED)


def test_submitted_is_terminal():
    assert not can_transition(JourneyState.SUBMITTED, JourneyState.FORM_CAPTURE)
