"""Identity provider interface and mock implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from app.adapters.otp import DemoSms, OtpChallenge, OtpChallengeStore, generate_otp_code


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    mobile: str


@dataclass
class AuthChallenge:
    persona_id: str | None
    mobile: str
    challenge_id: str
    # OTP is never returned to callers of public APIs / never logged


@dataclass
class AuthResult:
    success: bool
    persona: Persona | None = None
    reason: str | None = None
    reissued: bool = False


class IdentityProvider(ABC):
    @abstractmethod
    def find_by_mobile(self, mobile: str) -> Persona | None: ...

    @abstractmethod
    def request_otp(self, mobile: str) -> AuthChallenge:
        """Start a dynamic OTP challenge for any valid mobile (existing or new)."""

    @abstractmethod
    def verify_otp(self, mobile: str, otp: str) -> AuthResult: ...

    @abstractmethod
    def register_citizen(self, *, name: str, mobile: str) -> Persona: ...

    @abstractmethod
    def get_demo_sms(self, mobile: str) -> DemoSms | None: ...

    @abstractmethod
    def clear_demo_sms(self, mobile: str) -> None: ...


class MockIdentityProvider(IdentityProvider):
    """Seeded synthetic personas plus locally registered demo citizens."""

    def __init__(
        self,
        personas: list[Persona],
        *,
        otp_ttl_seconds: int = 300,
        otp_max_attempts: int = 3,
        now=None,
        generate_otp=generate_otp_code,
    ) -> None:
        self._by_mobile = {_normalize_mobile(p.mobile): p for p in personas}
        self._otp = OtpChallengeStore(
            ttl_seconds=otp_ttl_seconds,
            max_attempts=otp_max_attempts,
            now=now,
            generate=generate_otp,
        )

    def find_by_mobile(self, mobile: str) -> Persona | None:
        return self._by_mobile.get(_normalize_mobile(mobile))

    def merge_personas(self, extra: list[Persona]) -> None:
        for persona in extra:
            self._by_mobile[_normalize_mobile(persona.mobile)] = persona

    def request_otp(self, mobile: str) -> AuthChallenge:
        compact = _normalize_mobile(mobile)
        persona = self.find_by_mobile(compact)
        challenge, _sms = self._otp.issue(compact)
        return AuthChallenge(
            persona_id=persona.id if persona else None,
            mobile=compact,
            challenge_id=challenge.id,
        )

    def latest_challenge(self, mobile: str) -> OtpChallenge | None:
        return self._otp._by_mobile.get(_normalize_mobile(mobile))

    def get_demo_sms(self, mobile: str) -> DemoSms | None:
        return self._otp.peek_sms(_normalize_mobile(mobile))

    def clear_demo_sms(self, mobile: str) -> None:
        self._otp.clear_sms(_normalize_mobile(mobile))

    def verify_otp(self, mobile: str, otp: str) -> AuthResult:
        compact = _normalize_mobile(mobile)
        outcome = self._otp.verify(compact, (otp or "").strip())
        if not outcome.success:
            return AuthResult(success=False, reason=outcome.reason, reissued=outcome.reissued)
        persona = self.find_by_mobile(compact)
        if not persona:
            # OTP proved the number; registration name still required.
            return AuthResult(success=True, persona=None, reason="registration_required")
        return AuthResult(success=True, persona=persona)

    def register_citizen(self, *, name: str, mobile: str) -> Persona:
        compact = _normalize_mobile(mobile)
        existing = self.find_by_mobile(compact)
        if existing:
            return existing
        display = (name or "").strip()
        persona = Persona(
            id=f"persona-synth-{uuid4().hex[:12]}",
            name=display,
            mobile=compact,
        )
        self._by_mobile[compact] = persona
        return persona


def _normalize_mobile(mobile: str) -> str:
    return "".join(ch for ch in (mobile or "") if ch.isdigit())


def _personas_path() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "seed" / "personas.yaml"
        if candidate.exists():
            return candidate
    return Path.cwd() / "config" / "seed" / "personas.yaml"


def load_personas(path: Path | None = None) -> list[Persona]:
    file_path = path or _personas_path()
    with file_path.open(encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}
    personas: list[Persona] = []
    for item in raw.get("personas", []):
        personas.append(
            Persona(
                id=item["id"],
                name=item["name"],
                mobile=str(item["mobile"]),
            )
        )
    return personas


@lru_cache
def get_identity_provider() -> IdentityProvider:
    from app.core.config import get_settings

    settings = get_settings()
    return MockIdentityProvider(
        load_personas(),
        otp_ttl_seconds=settings.otp_ttl_seconds,
        otp_max_attempts=settings.otp_max_attempts,
    )
