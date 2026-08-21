"""Provider abstractions — local default; cloud is a stub only in P1.

OpenAI / any real cloud provider is OPTIONAL and NOT wired in P1.
No cloud HTTP calls are made by OptionalCloudProvider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderResult:
    """Structured provider response (no real cloud I/O in P1)."""

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
    """Cloud provider stub for P1.

    Does NOT make any external HTTP calls.
    Real cloud integrations (e.g. optional OpenAI) may be added later
    ONLY when invoked through the Data Boundary Gateway.
    """

    name = "cloud-stub"
    call_count: int = 0

    def process(self, payload: dict[str, Any], purpose: str) -> ProviderResult:
        # Intentionally no network I/O in P1.
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
