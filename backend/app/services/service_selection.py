"""Catalogue-driven service selection from citizen utterances."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from app.services.catalogue import ServiceDefinition, get_service_catalogue

_MATCH_CODE = 1
_MATCH_DISPLAY = 2
_MATCH_ALIAS = 3
_MATCH_PHRASE = 4
_MATCH_NORMALIZED = 5

_FILLER_PREFIX = re.compile(
    r"^(?:"
    r"i(?:\s+would\s+like\s+to|\s+want(?:\s+to)?(?:\s+apply\s+for(?:\s+an?)?|\s+an?)?|\s+need(?:\s+an?)?)"
    r"|apply(?:\s+for)?(?:\s+an?)?"
    r"|please"
    r"|can\s+i\s+(?:get|apply\s+for)(?:\s+an?)?"
    r"|get(?:\s+an?)?"
    r")(?:\s+|$)+",
    re.IGNORECASE | re.UNICODE,
)


class ServiceSelectionStatus(StrEnum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    NONE = "none"


@dataclass(frozen=True)
class ServiceSelectionResult:
    status: ServiceSelectionStatus
    service_code: str | None = None
    matches: tuple[str, ...] = ()


def normalize_service_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace (Unicode-safe)."""
    raw = unicodedata.normalize("NFKC", (text or "").strip())
    if not raw:
        return ""
    cleaned = re.sub(r"[^\w\s]", " ", raw, flags=re.UNICODE)
    return re.sub(r"\s+", " ", cleaned).strip().casefold()


def normalize_service_code(text: str) -> str:
    return normalize_service_text(text).upper().replace(" ", "_")


def strip_selection_fillers(text: str) -> str:
    normalized = normalize_service_text(text)
    if not normalized:
        return ""
    current = normalized
    while True:
        stripped = _FILLER_PREFIX.sub("", current, count=1).strip()
        if stripped == current:
            break
        current = stripped
    return current


def _display_names(defn: ServiceDefinition) -> list[str]:
    names = [defn.display_name]
    if defn.selection and defn.selection.display_names:
        names.extend(defn.selection.display_names.values())
    return names


def _aliases(defn: ServiceDefinition, language: str | None) -> list[str]:
    if not defn.selection:
        return []
    aliases = defn.selection.aliases
    ordered: list[str] = []
    if language and language in aliases:
        ordered.extend(aliases[language])
    for lang, items in sorted(aliases.items()):
        if lang != language:
            ordered.extend(items)
    return ordered


def _spoken_phrases(defn: ServiceDefinition, language: str | None) -> list[str]:
    if not defn.selection:
        return []
    phrases = defn.selection.spoken_phrases
    ordered: list[str] = []
    if language and language in phrases:
        ordered.extend(phrases[language])
    for lang, items in sorted(phrases.items()):
        if lang != language:
            ordered.extend(items)
    return ordered


def _is_specific_term(term: str) -> bool:
    normalized = normalize_service_text(term)
    if not normalized:
        return False
    if " " in normalized:
        return True
    return len(normalized) >= 10


def _collect_matches(
    utterance: str,
    *,
    language: str | None = None,
    catalogue: dict[str, ServiceDefinition] | None = None,
) -> dict[str, int]:
    normalized = normalize_service_text(utterance)
    normalized_code = normalize_service_code(utterance)
    stripped = strip_selection_fillers(utterance)
    if not normalized and not normalized_code:
        return {}

    items = catalogue or get_service_catalogue()
    best: dict[str, int] = {}

    def record(code: str, priority: int) -> None:
        current = best.get(code)
        if current is None or priority < current:
            best[code] = priority

    for code, defn in items.items():
        if normalized_code and normalized_code == code:
            record(code, _MATCH_CODE)
            continue

        for name in _display_names(defn):
            name_norm = normalize_service_text(name)
            if not name_norm:
                continue
            if normalized == name_norm:
                record(code, _MATCH_DISPLAY)
            elif stripped == name_norm and _is_specific_term(name):
                record(code, _MATCH_NORMALIZED)

        for alias in _aliases(defn, language):
            alias_norm = normalize_service_text(alias)
            if not alias_norm:
                continue
            if normalized == alias_norm:
                record(code, _MATCH_ALIAS)
            elif stripped == alias_norm and _is_specific_term(alias):
                record(code, _MATCH_NORMALIZED)

        for phrase in _spoken_phrases(defn, language):
            phrase_norm = normalize_service_text(phrase)
            if phrase_norm and normalized == phrase_norm:
                record(code, _MATCH_PHRASE)

    return best


def resolve_service_utterance(
    utterance: str,
    *,
    language: str | None = None,
    catalogue: dict[str, ServiceDefinition] | None = None,
) -> ServiceSelectionResult:
    """Resolve a citizen utterance to a catalogue service code."""
    matches = _collect_matches(utterance, language=language, catalogue=catalogue)
    if not matches:
        return ServiceSelectionResult(status=ServiceSelectionStatus.NONE)

    ranked = sorted(matches.items(), key=lambda item: (item[1], item[0]))
    best_priority = ranked[0][1]
    winners = [code for code, priority in ranked if priority == best_priority]
    if len(winners) == 1:
        return ServiceSelectionResult(
            status=ServiceSelectionStatus.MATCHED,
            service_code=winners[0],
            matches=tuple(winners),
        )
    return ServiceSelectionResult(
        status=ServiceSelectionStatus.AMBIGUOUS,
        matches=tuple(sorted(winners)),
    )


def resolve_service_affirmative(
    catalogue: dict[str, ServiceDefinition] | None = None,
) -> ServiceSelectionResult:
    """When the citizen says yes, select the only available service if unambiguous."""
    items = catalogue or get_service_catalogue()
    codes = sorted(items)
    if len(codes) == 1:
        return ServiceSelectionResult(
            status=ServiceSelectionStatus.MATCHED,
            service_code=codes[0],
            matches=(codes[0],),
        )
    return ServiceSelectionResult(status=ServiceSelectionStatus.NONE)
