"""Local i18n loader — supported languages derived from config/languages.yaml."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.services.catalogue import ServiceDefinition
from app.services.languages import get_language_catalog

REQUIRED_KEYS = (
    "language_select",
    "language_unsupported",
    "language_ambiguous",
    "auth_mobile",
    "auth_mobile_unrecognized",
    "auth_otp",
    "auth_otp_incorrect",
    "auth_success",
    "consent",
    "consent_recorded",
    "consent_declined",
    "consent_unclear",
    "service_select",
    "service_select_unknown",
    "service_select_ambiguous",
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
    "document_missing_list",
    "document_reupload",
    "document_verification_failed",
    "document_stored",
    "document_uploaded_ok",
    "document_all_uploaded",
    "document_rejected",
    "document_upload_required",
    "document_ivr_continue",
    "document_choose_type",
    "document_type_required",
    "document_type_unsupported",
    "review_intro",
    "fee_quote",
    "payment_prompt",
    "payment_failed",
    "correction_which",
    "correction_updating",
    "submitted",
    "application_id_label",
    "validation_failed",
    "validation_mobile_invalid",
    "field_confirm_heard",
    "field_confirm_retry",
    "field_label_applicant_name",
    "field_label_date_of_birth",
    "field_label_mobile_number",
    "field_label_address",
    "field_label_district",
    "field_label_annual_income",
    "field_label_income_source",
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

FIELD_LABEL_KEY_MAP = {
    "applicant_name": "field_label_applicant_name",
    "date_of_birth": "field_label_date_of_birth",
    "mobile_number": "field_label_mobile_number",
    "address": "field_label_address",
    "district": "field_label_district",
    "annual_income": "field_label_annual_income",
    "income_source": "field_label_income_source",
}


def supported_language_codes() -> tuple[str, ...]:
    return tuple(lang.code for lang in get_language_catalog().languages)


def _i18n_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "i18n"
        if candidate.exists():
            return candidate
    return Path.cwd() / "config" / "i18n"


@lru_cache
def load_translations(language: str = "en") -> dict[str, str]:
    catalog = get_language_catalog()
    lang = (language or catalog.default_code).lower()
    if not catalog.is_supported(lang):
        lang = catalog.default_code
    path = _i18n_dir() / f"{lang}.yaml"
    with path.open(encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh) or {}
    return {str(k): str(v) for k, v in data.items()}


def t(key: str, language: str = "en", **kwargs: Any) -> str:
    """Translate a key; fall back to English then the key itself."""
    bundle = load_translations(language)
    text = bundle.get(key)
    if text is None:
        text = load_translations(get_language_catalog().default_code).get(key, key)
    try:
        return text.format(**kwargs) if kwargs else text
    except (KeyError, ValueError):
        return text


def language_select_prompt(language: str = "en") -> str:
    """Localized language-selection prompt with names from the language catalog."""
    catalog = get_language_catalog()
    return t("language_select", language, language_list=catalog.format_language_list())


def field_prompt(field_name: str, language: str = "en") -> str:
    key = FIELD_KEY_MAP.get(field_name, f"field_{field_name}")
    return t(key, language)


def field_label_for_confirm(field_name: str, language: str = "en") -> str:
    """Short citizen-facing label for voice confirmation retry prompts."""
    key = FIELD_LABEL_KEY_MAP.get(field_name, f"field_label_{field_name}")
    label = t(key, language)
    if label == key:
        return field_name.replace("_", " ")
    return label


def document_label_i18n_key(document_code: str) -> str:
    """Derive an i18n key from a catalogue document code — no hard-coded code list."""
    return f"document_label_{document_code.lower()}"


def document_label(
    document_code: str, service: ServiceDefinition, language: str = "en"
) -> str:
    """Citizen-facing document name from i18n, then the service catalogue label."""
    key = document_label_i18n_key(document_code)
    translated = t(key, language)
    if translated != key:
        return translated
    doc = service.document_by_code(document_code)
    if doc and doc.label:
        return doc.label
    return document_code.replace("_", " ")


def document_type_label(
    document_type: str, service: ServiceDefinition, language: str = "en"
) -> str:
    """Citizen-facing accepted document type label (Aadhaar, PAN, …)."""
    key = f"document_type_{document_type.lower()}"
    translated = t(key, language)
    if translated != key:
        return translated
    for doc in service.documents:
        match = doc.accepted_type_by_code(document_type)
        if match:
            return match.label
    return document_type.replace("_", " ").title()


def document_next_prompt(
    document_code: str, service: ServiceDefinition, language: str = "en"
) -> str:
    name = document_label(document_code, service, language)
    return t("document_next", language, document_name=name)


def document_missing_list(
    document_codes: list[str], service: ServiceDefinition, language: str = "en"
) -> str:
    names = [document_label(code, service, language) for code in document_codes]
    return t("document_missing_list", language, documents=", ".join(names))


def document_reupload_prompt(
    document_code: str, service: ServiceDefinition, language: str = "en"
) -> str:
    name = document_label(document_code, service, language)
    return t("document_reupload", language, document_name=name)


def assert_all_keys_present() -> dict[str, list[str]]:
    """Return missing keys per language (empty lists = complete)."""
    missing: dict[str, list[str]] = {}
    for lang in supported_language_codes():
        bundle = load_translations(lang)
        missing[lang] = [k for k in REQUIRED_KEYS if k not in bundle]
    return missing


def assert_document_labels_present(service: ServiceDefinition) -> dict[str, list[str]]:
    """Return missing document_label_* keys per language for catalogue documents."""
    missing: dict[str, list[str]] = {}
    keys = [document_label_i18n_key(doc.code) for doc in service.documents]
    for lang in supported_language_codes():
        bundle = load_translations(lang)
        missing[lang] = [k for k in keys if k not in bundle]
    return missing
