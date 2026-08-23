"""Provider abstractions — local default; optional cloud is a no-network stub.

LocalProvider processes data in-process. OptionalCloudProvider never opens
external HTTP connections. Any real cloud integration must only be invoked
through the Data Boundary Gateway after an explicit policy ALLOW.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderResult:
    """Structured provider response (stub makes no external I/O)."""

    success: bool
    provider: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    http_calls_made: int = 0


class BaseProvider(ABC):
    """Interface for speech/AI providers behind the boundary gateway."""

    name: str

    @abstractmethod
    def process(self, payload: dict[str, Any], purpose: str) -> ProviderResult:
        """Process an already-authorized payload. Must not bypass the gateway."""


class LocalProvider(BaseProvider):
    """Default local provider — processes data entirely in-process."""

    name = "local"

    def process(self, payload: dict[str, Any], purpose: str) -> ProviderResult:
        return ProviderResult(
            success=True,
            provider=self.name,
            message=f"Processed locally for purpose '{purpose}'",
            data={"echo_keys": sorted(payload.keys()), "purpose": purpose},
            http_calls_made=0,
        )


class OptionalCloudProvider(BaseProvider):
    """Optional cloud stub used only after gateway ALLOW.

    Does not make any external HTTP calls. Records invocations for tests
    that prove restricted payloads never reach a real cloud client.
    """

    name = "cloud-stub"
    call_count: int = 0

    def process(self, payload: dict[str, Any], purpose: str) -> ProviderResult:
        # Intentional: no network I/O in this POC stub.
        self.call_count += 1
        return ProviderResult(
            success=True,
            provider=self.name,
            message=(
                f"Cloud stub accepted payload for '{purpose}' "
                "(no external HTTP call made)"
            ),
            data={"echo_keys": sorted(payload.keys()), "purpose": purpose},
            http_calls_made=0,
        )

    def reset_call_count(self) -> None:
        self.call_count = 0
