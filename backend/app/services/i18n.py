"""Local i18n loader for en / hi / te journey prompts."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_LANGUAGES = ("en", "hi", "te")
REQUIRED_KEYS = (
    "language_select",
    "auth_mobile",
    "auth_otp",
    "auth_success",
    "consent",
    "consent_recorded",
    "consent_declined",
    "service_select",
    "field_applicant_name",
    "field_date_of_birth",
    "field_mobile_number",
    "field_address",
    "field_district",
    "field_annual_income",
    "field_income_source",
    "form_complete",
    "document_prompt",
    "document_next",
    "review_intro",
    "correction_which",
    "correction_updating",
    "submitted",
    "application_id_label",
    "validation_failed",
    "escalation",
    "resume_ok",
    "welcome",
    "unknown_intent",
    "error_generic",
)

FIELD_KEY_MAP = {
    "applicant_name": "field_applicant_name",
    "date_of_birth": "field_date_of_birth",
    "mobile_number": "field_mobile_number",
    "address": "field_address",
    "district": "field_district",
    "annual_income": "field_annual_income",
    "income_source": "field_income_source",
}


def _i18n_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "i18n"
        if candidate.exists():
            return candidate
    return Path.cwd() / "config" / "i18n"


@lru_cache
def load_translations(language: str = "en") -> dict[str, str]:
    lang = (language or "en").lower()
    if lang not in SUPPORTED_LANGUAGES:
        lang = "en"
    path = _i18n_dir() / f"{lang}.yaml"
    with path.open(encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh) or {}
    return {str(k): str(v) for k, v in data.items()}


def t(key: str, language: str = "en", **kwargs: Any) -> str:
    """Translate a key; fall back to English then the key itself."""
    bundle = load_translations(language)
    text = bundle.get(key)
    if text is None:
        text = load_translations("en").get(key, key)
    try:
        return text.format(**kwargs) if kwargs else text
    except (KeyError, ValueError):
        return text


def field_prompt(field_name: str, language: str = "en") -> str:
    key = FIELD_KEY_MAP.get(field_name, f"field_{field_name}")
    return t(key, language)


def assert_all_keys_present() -> dict[str, list[str]]:
    """Return missing keys per language (empty lists = complete)."""
    missing: dict[str, list[str]] = {}
    for lang in SUPPORTED_LANGUAGES:
        bundle = load_translations(lang)
        missing[lang] = [k for k in REQUIRED_KEYS if k not in bundle]
    return missing
