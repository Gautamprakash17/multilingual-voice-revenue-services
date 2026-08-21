"""Local rule-based NLU — no external LLM."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NLUResult:
    intent: str
    slots: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


class NLUProvider(ABC):
    @abstractmethod
    def parse(self, text: str, *, expected_field: str | None = None) -> NLUResult:
        """Extract intent/slots. Never log raw text at call sites."""


class LocalRuleNLUProvider(NLUProvider):
    """Deterministic regex/keyword NLU for Income Certificate POC."""

    _CONFIRM = re.compile(r"^\s*(confirm|yes|y|हाँ|हां|అవును|ok)\s*$", re.I)
    _CORRECT = re.compile(r"^\s*(correct|edit|change|सुधार|సరిదిద్దు)\s*$", re.I)
    _CONSENT = re.compile(
        r"^\s*(yes|y|i agree|agree|हाँ|हां|అవును)\s*$", re.I
    )
    _DECLINE = re.compile(r"^\s*(no|n|decline|नहीं|కాదు)\s*$", re.I)
    _ESCALATE = re.compile(r"^\s*(escalate|help|agent|officer|सहायता|సహాయం)\s*$", re.I)
    _STATUS = re.compile(r"^\s*(status|track|स्थिति|స్థితి)\s*$", re.I)
    _START = re.compile(
        r"^\s*(start|begin|apply|income\s*certificate|आवेदन|దరఖాస్తు)\s*$", re.I
    )
    _DOB = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
    _MOBILE = re.compile(r"\b([6-9]\d{9})\b")
    _INCOME = re.compile(r"(?:₹|rs\.?\s*)?([\d,]+(?:\.\d+)?)", re.I)

    def parse(self, text: str, *, expected_field: str | None = None) -> NLUResult:
        raw = (text or "").strip()
        if not raw:
            return NLUResult(intent="UNKNOWN", confidence=0.0)

        if self._ESCALATE.match(raw):
            return NLUResult(intent="ESCALATE", confidence=0.95)
        if self._STATUS.match(raw):
            return NLUResult(intent="STATUS", confidence=0.9)
        if self._START.match(raw):
            return NLUResult(intent="START_APPLICATION", confidence=0.9)
        if self._CONFIRM.match(raw):
            return NLUResult(intent="CONFIRM", confidence=0.95)
        if self._CORRECT.match(raw):
            return NLUResult(intent="CORRECT", confidence=0.95)
        if self._CONSENT.match(raw):
            return NLUResult(intent="CONSENT", slots={"granted": True}, confidence=0.95)
        if self._DECLINE.match(raw):
            return NLUResult(intent="CONSENT", slots={"granted": False}, confidence=0.95)

        # Field-oriented extraction
        if expected_field == "date_of_birth" or self._DOB.search(raw):
            m = self._DOB.search(raw)
            if m:
                return NLUResult(
                    intent="PROVIDE_DOB",
                    slots={"date_of_birth": m.group(1).replace("-", "/")},
                    confidence=0.9,
                )

        if expected_field == "mobile_number" or (
            expected_field is None and self._MOBILE.search(raw)
        ):
            m = self._MOBILE.search(raw)
            if m:
                return NLUResult(
                    intent="PROVIDE_MOBILE",
                    slots={"mobile_number": m.group(1)},
                    confidence=0.9,
                )

        if expected_field == "annual_income":
            m = self._INCOME.search(raw.replace(",", ""))
            if m:
                return NLUResult(
                    intent="PROVIDE_INCOME",
                    slots={"annual_income": m.group(1).replace(",", "")},
                    confidence=0.85,
                )

        intent_map = {
            "applicant_name": "PROVIDE_NAME",
            "address": "PROVIDE_ADDRESS",
            "district": "PROVIDE_DISTRICT",
            "income_source": "PROVIDE_INCOME_SOURCE",
            "annual_income": "PROVIDE_INCOME",
            "mobile_number": "PROVIDE_MOBILE",
            "date_of_birth": "PROVIDE_DOB",
        }
        if expected_field in intent_map:
            return NLUResult(
                intent=intent_map[expected_field],
                slots={expected_field: raw},
                confidence=0.75,
            )

        return NLUResult(intent="UNKNOWN", slots={"text": raw}, confidence=0.2)


def get_nlu_provider() -> NLUProvider:
    return LocalRuleNLUProvider()
