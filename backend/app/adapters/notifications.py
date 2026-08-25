"""Replaceable mock notification providers — local/simulated delivery only.

Swap MockWhatsAppProvider / MockSmsProvider / MockEmailProvider for real
adapters later. Do not import Twilio, Meta, SMTP, or SNS here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class MockDelivery:
    channel: str
    recipient: str
    message: str
    subject: str | None = None


class NotificationProvider(Protocol):
    channel: str

    def deliver(
        self,
        *,
        recipient: str | None,
        message: str,
        subject: str | None = None,
    ) -> bool:
        """Return True when a simulated delivery was recorded."""


@dataclass
class _BaseMockProvider:
    channel: str
    sent: list[MockDelivery] = field(default_factory=list)

    def deliver(
        self,
        *,
        recipient: str | None,
        message: str,
        subject: str | None = None,
    ) -> bool:
        dest = (recipient or "").strip()
        if not dest:
            return False
        self.sent.append(
            MockDelivery(
                channel=self.channel,
                recipient=dest,
                message=message,
                subject=subject,
            )
        )
        return True


class MockSmsProvider(_BaseMockProvider):
    def __init__(self) -> None:
        super().__init__(channel="sms")


class MockWhatsAppProvider(_BaseMockProvider):
    def __init__(self) -> None:
        super().__init__(channel="whatsapp")


class MockEmailProvider(_BaseMockProvider):
    def __init__(self) -> None:
        super().__init__(channel="email")
