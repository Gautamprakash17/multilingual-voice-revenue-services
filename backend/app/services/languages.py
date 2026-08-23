"""Load supported languages from config/languages.yaml — single source of truth."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ScriptRange:
    code: str
    start: int
    end: int


@dataclass(frozen=True)
class LanguageDefinition:
    code: str
    display_name: str
    native_name: str
    stt_code: str
    tts_code: str
    script: str
    aliases: tuple[str, ...]
    spoken_phrases: tuple[str, ...]

    def all_patterns(self) -> tuple[str, ...]:
        return self.aliases + self.spoken_phrases

    def to_api_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "display_name": self.display_name,
            "native_name": self.native_name,
            "stt_code": self.stt_code,
            "tts_code": self.tts_code,
        }


@dataclass(frozen=True)
class LanguageCatalog:
    default_code: str
    languages: tuple[LanguageDefinition, ...]
    script_ranges: tuple[ScriptRange, ...]

    @property
    def codes(self) -> frozenset[str]:
        return frozenset(lang.code for lang in self.languages)

    def get(self, code: str | None) -> LanguageDefinition | None:
        if not code:
            return None
        key = code.strip().lower()
        for lang in self.languages:
            if lang.code == key:
                return lang
        return None

    def is_supported(self, code: str | None) -> bool:
        return bool(code and code.strip().lower() in self.codes)

    def stt_code(self, code: str | None) -> str | None:
        lang = self.get(code)
        return lang.stt_code if lang else None

    def tts_code(self, code: str | None) -> str | None:
        lang = self.get(code)
        return lang.tts_code if lang else None

    def format_language_list(self, *, native: bool = True) -> str:
        names = [lang.native_name if native else lang.display_name for lang in self.languages]
        return ", ".join(names)


def _config_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config"
        if (candidate / "languages.yaml").exists():
            return candidate
    return Path.cwd() / "config"


def _languages_config_path() -> Path:
    override = os.environ.get("LANGUAGES_CONFIG_PATH")
    if override:
        return Path(override)
    return _config_root() / "languages.yaml"


def _parse_language_catalog(raw: dict[str, Any]) -> LanguageCatalog:
    default_code = str(raw.get("default") or "en").lower()
    script_ranges: list[ScriptRange] = []
    for _name, spec in (raw.get("script_ranges") or {}).items():
        script_ranges.append(
            ScriptRange(
                code=str(spec["code"]).lower(),
                start=int(spec["start"]),
                end=int(spec["end"]),
            )
        )

    languages: list[LanguageDefinition] = []
    for code, spec in (raw.get("languages") or {}).items():
        languages.append(
            LanguageDefinition(
                code=str(code).lower(),
                display_name=str(spec.get("display_name") or code),
                native_name=str(spec.get("native_name") or spec.get("display_name") or code),
                stt_code=str(spec.get("stt_code") or code).lower(),
                tts_code=str(spec.get("tts_code") or code).lower(),
                script=str(spec.get("script") or "latin"),
                aliases=tuple(str(a) for a in (spec.get("aliases") or [])),
                spoken_phrases=tuple(str(p) for p in (spec.get("spoken_phrases") or [])),
            )
        )

    languages.sort(key=lambda item: item.code)
    return LanguageCatalog(
        default_code=default_code,
        languages=tuple(languages),
        script_ranges=tuple(script_ranges),
    )


@lru_cache
def get_language_catalog() -> LanguageCatalog:
    path = _languages_config_path()
    with path.open(encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}
    return _parse_language_catalog(raw)


def clear_language_catalog_cache() -> None:
    get_language_catalog.cache_clear()
