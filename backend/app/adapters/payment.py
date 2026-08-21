"""Payment provider interface and deterministic mock implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4


class PaymentOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    TIMEOUT = "TIMEOUT"


@dataclass
class PaymentResult:
    outcome: PaymentOutcome
    payment_ref: str | None
    provider: str
    reason: str | None = None
    # Never store card/UPI secrets — mock uses scenario tokens only


class PaymentProvider(ABC):
    @abstractmethod
    def charge(
        self,
        *,
        amount_paise: int,
        currency: str,
        application_ref: str,
        scenario: str | None = None,
    ) -> PaymentResult:
        """Execute a mock charge. scenario: SUCCESS|FAILURE|TIMEOUT|PAY."""


class MockPaymentProvider(PaymentProvider):
    """Deterministic mock treasury/UPI adapter for the POC."""

    def charge(
        self,
        *,
        amount_paise: int,
        currency: str,
        application_ref: str,
        scenario: str | None = None,
    ) -> PaymentResult:
        key = (scenario or "SUCCESS").strip().upper()
        if key in {"PAY", "YES", "CONFIRM", "SUCCESS", "OK"}:
            return PaymentResult(
                outcome=PaymentOutcome.SUCCESS,
                payment_ref=f"PAY-{uuid4().hex[:8].upper()}",
                provider="mock-payment",
                reason="payment_successful",
            )
        if key in {"FAIL", "FAILURE", "ERROR"}:
            return PaymentResult(
                outcome=PaymentOutcome.FAILURE,
                payment_ref=None,
                provider="mock-payment",
                reason="payment_declined",
            )
        if key in {"TIMEOUT", "TIME_OUT", "PARK"}:
            return PaymentResult(
                outcome=PaymentOutcome.TIMEOUT,
                payment_ref=None,
                provider="mock-payment",
                reason="payment_gateway_timeout",
            )
        # Default unknown command → failure (safe, explicit)
        return PaymentResult(
            outcome=PaymentOutcome.FAILURE,
            payment_ref=None,
            provider="mock-payment",
            reason="unknown_payment_command",
        )


def get_payment_provider() -> PaymentProvider:
    return MockPaymentProvider()
