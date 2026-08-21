"""Identity provider interface and mock implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    mobile: str
    otp: str
    language: str = "en"


@dataclass
class AuthChallenge:
    persona_id: str
    mobile: str
    # OTP is never returned to callers of public APIs / never logged


@dataclass
class AuthResult:
    success: bool
    persona: Persona | None = None
    reason: str | None = None


class IdentityProvider(ABC):
    @abstractmethod
    def find_by_mobile(self, mobile: str) -> Persona | None: ...

    @abstractmethod
    def request_otp(self, mobile: str) -> AuthChallenge | None:
        """Start mock OTP challenge. Returns None if persona unknown."""

    @abstractmethod
    def verify_otp(self, mobile: str, otp: str) -> AuthResult: ...


class MockIdentityProvider(IdentityProvider):
    """Seeded synthetic personas only — never real citizens."""

    def __init__(self, personas: list[Persona]) -> None:
        self._by_mobile = {p.mobile: p for p in personas}

    def find_by_mobile(self, mobile: str) -> Persona | None:
        return self._by_mobile.get(_normalize_mobile(mobile))

    def request_otp(self, mobile: str) -> AuthChallenge | None:
        persona = self.find_by_mobile(mobile)
        if not persona:
            return None
        return AuthChallenge(persona_id=persona.id, mobile=persona.mobile)

    def verify_otp(self, mobile: str, otp: str) -> AuthResult:
        persona = self.find_by_mobile(mobile)
        if not persona:
            return AuthResult(success=False, reason="unknown_mobile")
        if (otp or "").strip() != persona.otp:
            return AuthResult(success=False, reason="invalid_otp")
        return AuthResult(success=True, persona=persona)


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
                otp=str(item["otp"]),
                language=str(item.get("language", "en")),
            )
        )
    return personas


@lru_cache
def get_identity_provider() -> IdentityProvider:
    return MockIdentityProvider(load_personas())
