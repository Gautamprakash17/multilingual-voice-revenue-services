"""OCR and document verification adapters — local/mock only."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class VerificationOutcome(StrEnum):
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    UNREADABLE = "UNREADABLE"


@dataclass
class OCRResult:
    success: bool
    provider: str
    field_hints: dict[str, str] = field(default_factory=dict)
    # Never log or cloud-egress raw extracted citizen values from callers
    confidence: float = 0.0
    notes: str | None = None


@dataclass
class VerificationResult:
    outcome: VerificationOutcome
    provider: str
    reason: str
    matched_fields: list[str] = field(default_factory=list)


class OCRProvider(ABC):
    @abstractmethod
    def extract(
        self,
        *,
        document_code: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        checksum_sha256: str,
    ) -> OCRResult:
        """Extract safe hints from local metadata/filename — no cloud."""


class DocumentVerificationProvider(ABC):
    @abstractmethod
    def verify(
        self,
        *,
        document_code: str,
        filename: str,
        ocr: OCRResult,
        form_data: dict[str, Any],
    ) -> VerificationResult:
        """Deterministic verification for POC seeded documents."""


class MockOCRProvider(OCRProvider):
    """Deterministic OCR stub — uses filename markers; no model download."""

    def extract(
        self,
        *,
        document_code: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        checksum_sha256: str,
    ) -> OCRResult:
        name = (filename or "").lower()
        if "unreadable" in name or "corrupt" in name:
            return OCRResult(
                success=False,
                provider="mock-ocr",
                confidence=0.1,
                notes="unreadable_marker",
            )
        hints: dict[str, str] = {"document_code": document_code}
        if "mismatch" in name:
            hints["marker"] = "mismatch"
        else:
            hints["marker"] = "ok"
        return OCRResult(
            success=True,
            provider="mock-ocr",
            field_hints=hints,
            confidence=0.9,
            notes="deterministic_filename_ocr",
        )


class MockDocumentVerificationProvider(DocumentVerificationProvider):
    def verify(
        self,
        *,
        document_code: str,
        filename: str,
        ocr: OCRResult,
        form_data: dict[str, Any],
    ) -> VerificationResult:
        if not ocr.success or ocr.notes == "unreadable_marker":
            return VerificationResult(
                outcome=VerificationOutcome.UNREADABLE,
                provider="mock-doc-verify",
                reason="Local POC verification failed: document unreadable.",
            )
        name = (filename or "").lower()
        if "mismatch" in name or ocr.field_hints.get("marker") == "mismatch":
            return VerificationResult(
                outcome=VerificationOutcome.MISMATCH,
                provider="mock-doc-verify",
                reason="Local POC verification failed: details do not match.",
                matched_fields=[],
            )
        return VerificationResult(
            outcome=VerificationOutcome.VERIFIED,
            provider="mock-doc-verify",
            reason="Local POC verification passed.",
            matched_fields=[document_code],
        )


def get_ocr_provider() -> OCRProvider:
    return MockOCRProvider()


def get_doc_verify_provider() -> DocumentVerificationProvider:
    return MockDocumentVerificationProvider()
