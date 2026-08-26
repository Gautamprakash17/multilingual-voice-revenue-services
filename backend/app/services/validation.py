"""Config-driven field validation — no business rules in route handlers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.services.catalogue import FieldDef
from app.speech.dates import normalize_spoken_date
from app.speech.mobile import normalize_indian_mobile_digits


@dataclass
class ValidationResult:
    ok: bool
    value: Any | None = None
    error: str | None = None
    expected_format: str | None = None
    code: str | None = None


def age_in_years(born: date, today: date | None = None) -> int:
    """Whole years completed on ``today`` (not a year-delta that ignores birthday)."""
    on = today or datetime.now().date()
    years = on.year - born.year
    if (on.month, on.day) < (born.month, born.day):
        years -= 1
    return years


def validate_field(field: FieldDef, raw: str) -> ValidationResult:
    text = (raw or "").strip()
    rules = field.validation or {}

    if field.required and not text:
        return ValidationResult(
            ok=False,
            error=f"{field.name} is required",
            expected_format=_expected(field),
        )

    if field.type == "string":
        min_len = int(rules.get("min_length", 0))
        max_len = int(rules.get("max_length", 10_000))
        if len(text) < min_len:
            return ValidationResult(
                ok=False,
                error=f"{field.name} must be at least {min_len} characters",
                expected_format=_expected(field),
            )
        if len(text) > max_len:
            return ValidationResult(
                ok=False,
                error=f"{field.name} must be at most {max_len} characters",
                expected_format=_expected(field),
            )
        return ValidationResult(ok=True, value=text)

    if field.type == "date":
        fmt = str(rules.get("format", "%d/%m/%Y"))
        expected = (
            "Use format "
            + fmt.replace("%d", "DD").replace("%m", "MM").replace("%Y", "YYYY")
        )
        candidates: list[str] = [text]
        normalized = normalize_spoken_date(text)
        if normalized and normalized not in candidates:
            candidates.insert(0, normalized)
        parsed = None
        for candidate in candidates:
            try:
                parsed = datetime.strptime(candidate, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return ValidationResult(
                ok=False,
                error="Invalid date",
                expected_format=expected,
            )
        born = parsed.date()
        today = datetime.now().date()
        if born > today:
            return ValidationResult(
                ok=False,
                error="Date of birth cannot be in the future",
                expected_format="DD/MM/YYYY",
                code="future_date",
            )
        if "max_age" in rules:
            max_age = int(rules["max_age"])
            if age_in_years(born, today) > max_age:
                return ValidationResult(
                    ok=False,
                    error=f"Age cannot be more than {max_age} years",
                    expected_format="DD/MM/YYYY",
                    code="max_age",
                )
        return ValidationResult(ok=True, value=parsed.strftime("%d/%m/%Y"))

    if field.type == "mobile":
        pattern = str(rules.get("pattern", r"^[6-9]\d{9}$"))
        digits = normalize_indian_mobile_digits(text)
        if not re.fullmatch(pattern, digits):
            return ValidationResult(
                ok=False,
                error="Please enter a valid 10-digit mobile number.",
                expected_format="10-digit Indian mobile starting with 6-9",
            )
        return ValidationResult(ok=True, value=digits)

    if field.type == "number":
        cleaned = text.replace(",", "").replace("₹", "").strip()
        try:
            amount = float(cleaned)
        except ValueError:
            return ValidationResult(
                ok=False,
                error="Invalid number",
                expected_format="Enter a non-negative number",
            )
        minimum = float(rules.get("min", 0))
        maximum = float(rules.get("max", 1e12))
        if amount < minimum:
            return ValidationResult(
                ok=False,
                error=f"Value must be >= {minimum}",
                expected_format=f"Number between {minimum} and {maximum}",
            )
        if amount > maximum:
            return ValidationResult(
                ok=False,
                error=f"Value must be <= {maximum}",
                expected_format=f"Number between {minimum} and {maximum}",
            )
        # Store as int when whole number for cleaner review
        value: Any = int(amount) if amount.is_integer() else amount
        return ValidationResult(ok=True, value=value)

    return ValidationResult(ok=True, value=text)


def _expected(field: FieldDef) -> str:
    rules = field.validation or {}
    if field.type == "date":
        return "DD/MM/YYYY"
    if field.type == "mobile":
        return "10-digit mobile number"
    if field.type == "number":
        return f"number >= {rules.get('min', 0)}"
    if "min_length" in rules:
        return f"text, at least {rules['min_length']} characters"
    return "text"
