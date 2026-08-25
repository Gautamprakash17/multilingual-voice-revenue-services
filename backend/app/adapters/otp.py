"""Local dynamic OTP helpers — mock delivery only, never real SMS."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


def generate_otp_code() -> str:
    """Return a cryptographically random 6-digit OTP (leading zeros allowed)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(code: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


def otp_hashes_match(code: str, salt: str, expected_hash: str) -> bool:
    actual = hash_otp(code, salt)
    return hmac.compare_digest(actual, expected_hash)


@dataclass
class OtpChallenge:
    id: str
    mobile: str
    salt: str
    otp_hash: str
    expires_at: datetime
    failed_attempts: int = 0
    verified: bool = False


@dataclass
class DemoSms:
    """Local synthetic SMS payload for the phone simulator only."""

    mobile: str
    code: str
    challenge_id: str
    issued_at: datetime
    sender: str = "Revenue Services"
    label: str = "Synthetic demo OTP"


@dataclass
class OtpVerifyOutcome:
    success: bool
    reason: str | None = None
    reissued: bool = False


class OtpChallengeStore:
    """In-process OTP challenges. No Redis/queue — one active challenge per mobile."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 300,
        max_attempts: int = 3,
        now=None,
        generate=generate_otp_code,
    ) -> None:
        self._ttl = int(ttl_seconds)
        self._max_attempts = int(max_attempts)
        self._now = now or (lambda: datetime.now(UTC))
        self._generate = generate
        self._by_mobile: dict[str, OtpChallenge] = {}
        self._inbox: dict[str, DemoSms] = {}

    def issue(self, mobile: str) -> tuple[OtpChallenge, DemoSms]:
        code = self._generate()
        if not (isinstance(code, str) and len(code) == 6 and code.isdigit()):
            raise ValueError("OTP generator must return exactly 6 digits")
        salt = secrets.token_hex(16)
        challenge_id = secrets.token_hex(8)
        now = self._now()
        challenge = OtpChallenge(
            id=challenge_id,
            mobile=mobile,
            salt=salt,
            otp_hash=hash_otp(code, salt),
            expires_at=now + timedelta(seconds=self._ttl),
        )
        self._by_mobile[mobile] = challenge
        sms = DemoSms(
            mobile=mobile,
            code=code,
            challenge_id=challenge_id,
            issued_at=now,
        )
        self._inbox[mobile] = sms
        return challenge, sms

    def peek_sms(self, mobile: str) -> DemoSms | None:
        return self._inbox.get(mobile)

    def clear_sms(self, mobile: str) -> None:
        self._inbox.pop(mobile, None)

    def invalidate(self, mobile: str) -> None:
        self._by_mobile.pop(mobile, None)
        self._inbox.pop(mobile, None)

    def verify(self, mobile: str, code: str) -> OtpVerifyOutcome:
        challenge = self._by_mobile.get(mobile)
        if challenge is None or challenge.verified:
            return OtpVerifyOutcome(success=False, reason="invalid_otp")
        now = self._now()
        if now > challenge.expires_at:
            self.invalidate(mobile)
            return OtpVerifyOutcome(success=False, reason="otp_expired")
        if not otp_hashes_match(code, challenge.salt, challenge.otp_hash):
            challenge.failed_attempts += 1
            if challenge.failed_attempts >= self._max_attempts:
                self.invalidate(mobile)
                return OtpVerifyOutcome(success=False, reason="otp_max_attempts")
            return OtpVerifyOutcome(success=False, reason="invalid_otp")
        challenge.verified = True
        self._inbox.pop(mobile, None)
        return OtpVerifyOutcome(success=True)
