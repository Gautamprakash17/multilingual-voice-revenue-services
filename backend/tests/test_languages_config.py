"""Configuration-driven language catalog tests."""

from __future__ import annotations

import yaml
from app.services.i18n import load_translations
from app.services.languages import (
    _languages_config_path,
    clear_language_catalog_cache,
    get_language_catalog,
)
from app.speech.language import resolve_language_choice


def test_language_catalog_is_loaded_from_config():
    catalog = get_language_catalog()
    codes = sorted(catalog.codes)
    assert codes == ["en", "hi", "kn"]
    assert catalog.get("kn") is not None
    assert catalog.get("kn").native_name == "ಕನ್ನಡ"


def test_natural_phrases_resolve_from_config():
    assert resolve_language_choice("I would like to go with English").code == "en"
    assert resolve_language_choice("I would like to go with Hindi").code == "hi"
    assert resolve_language_choice("I would like to go with Kannada").code == "kn"
    assert resolve_language_choice("हिंदी में बात करें").code == "hi"
    assert resolve_language_choice("ಕನ್ನಡದಲ್ಲಿ ಮಾತನಾಡಿ").code == "kn"


def test_config_alias_without_python_changes(tmp_path, monkeypatch):
    source = yaml.safe_load(_languages_config_path().read_text(encoding="utf-8"))
    source["languages"]["en"]["aliases"].append("configtestalias")
    temp_path = tmp_path / "languages.yaml"
    temp_path.write_text(yaml.safe_dump(source), encoding="utf-8")

    monkeypatch.setenv("LANGUAGES_CONFIG_PATH", str(temp_path))
    clear_language_catalog_cache()
    load_translations.cache_clear()

    try:
        result = resolve_language_choice("I want configtestalias please")
        assert result.code == "en"
        assert not result.ambiguous
    finally:
        monkeypatch.delenv("LANGUAGES_CONFIG_PATH", raising=False)
        clear_language_catalog_cache()
        load_translations.cache_clear()


def test_stt_and_tts_codes_from_config():
    catalog = get_language_catalog()
    assert catalog.stt_code("kn") == "kn"
    assert catalog.tts_code("hi") == "hi"
