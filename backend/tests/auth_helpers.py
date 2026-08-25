"""Shared helpers for dynamic OTP in journey/channel tests."""

from __future__ import annotations

from app.adapters.identity import MockIdentityProvider
from app.channels.orchestrator import ChannelOrchestrator
from app.services.journey import JourneyService

EN_DIGIT_WORDS = {
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

HI_DIGIT_WORDS = {
    "0": "शून्य",
    "1": "एक",
    "2": "दो",
    "3": "तीन",
    "4": "चार",
    "5": "पांच",
    "6": "छह",
    "7": "सात",
    "8": "आठ",
    "9": "नौ",
}

KN_DIGIT_WORDS = {
    "0": "ಸೊನ್ನೆ",
    "1": "ಒಂದು",
    "2": "ಎರಡು",
    "3": "ಮೂರು",
    "4": "ನಾಲ್ಕು",
    "5": "ಐದು",
    "6": "ಆರು",
    "7": "ಏಳು",
    "8": "ಎಂಟು",
    "9": "ಒಂಬತ್ತು",
}


def current_otp(identity: MockIdentityProvider, mobile: str = "9876543210") -> str:
    sms = identity.get_demo_sms(mobile)
    assert sms is not None, "expected a synthetic demo SMS for this mobile"
    assert len(sms.code) == 6 and sms.code.isdigit()
    return sms.code


def expand_step(identity, step: str, mobile: str = "9876543210") -> str:
    if step in {"__OTP__", "123456"}:
        return current_otp(identity, mobile)
    return step


def spaced_otp(code: str) -> str:
    return " ".join(code)


def words_otp(code: str, table: dict[str, str] = EN_DIGIT_WORDS) -> str:
    return " ".join(table[d] for d in code)


def complete_auth(
    journey: JourneyService,
    app_id: str,
    token: str,
    *,
    language: str = "en",
    mobile: str = "9876543210",
    trace: str = "auth",
) -> object:
    identity = journey.identity
    assert isinstance(identity, MockIdentityProvider)
    journey.handle_message(app_id, token, language, trace_id=trace)
    journey.handle_message(app_id, token, mobile, trace_id=trace)
    return journey.handle_message(app_id, token, current_otp(identity, mobile), trace_id=trace)


def play_script(
    journey: JourneyService,
    app_id: str,
    token: str,
    steps: list[str],
    *,
    mobile: str = "9876543210",
    trace: str = "script",
) -> object:
    identity = journey.identity
    assert isinstance(identity, MockIdentityProvider)
    reply = None
    for step in steps:
        text = current_otp(identity, mobile) if step in {"__OTP__", "123456"} else step
        reply = journey.handle_message(app_id, token, text, trace_id=trace)
    return reply


def submit_current_otp(
    journey: JourneyService,
    app_id: str,
    token: str,
    *,
    mobile: str = "9876543210",
    trace: str = "auth",
) -> object:
    identity = journey.identity
    assert isinstance(identity, MockIdentityProvider)
    return journey.handle_message(app_id, token, current_otp(identity, mobile), trace_id=trace)


def orch_play_script(
    orch: ChannelOrchestrator,
    app_id: str,
    token: str,
    steps: list[str],
    *,
    channel: str = "web",
    mobile: str = "9876543210",
    extra: dict | None = None,
):
    identity = orch.journey.identity
    assert isinstance(identity, MockIdentityProvider)
    last = None
    for step in steps:
        text = current_otp(identity, mobile) if step in {"__OTP__", "123456"} else step
        payload = {
            "application_id": app_id,
            "access_token": token,
            "text": text,
            **(extra or {}),
        }
        last = orch.process_channel_payload(channel, payload)
    return last
