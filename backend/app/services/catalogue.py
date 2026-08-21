"""Service catalogue loader — declarative YAML definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@dataclass
class FieldDef:
    name: str
    type: str
    required: bool
    prompt: str
    validation: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentDef:
    code: str
    required: bool
    label: str
    allowed_mime_types: list[str]
    max_size_bytes: int


@dataclass
class FeeDef:
    amount_paise: int
    currency: str
    description: str = ""


@dataclass
class ServiceDefinition:
    service_code: str
    display_name: str
    description: str
    languages: list[str]
    fields: list[FieldDef]
    documents: list[DocumentDef]
    prompts: dict[str, str]
    fee: FeeDef | None = None

    def field_by_name(self, name: str) -> FieldDef | None:
        return next((f for f in self.fields if f.name == name), None)

    def document_by_code(self, code: str) -> DocumentDef | None:
        return next((d for d in self.documents if d.code == code), None)

    def required_field_names(self) -> list[str]:
        return [f.name for f in self.fields if f.required]

    def required_document_codes(self) -> list[str]:
        return [d.code for d in self.documents if d.required]


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "config" / "services").exists():
            return parent
    return Path.cwd()


def resolve_services_dir() -> Path:
    return _repo_root() / "config" / "services"


def load_service_definition(path: Path) -> ServiceDefinition:
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    fields = [
        FieldDef(
            name=f["name"],
            type=f.get("type", "string"),
            required=bool(f.get("required", True)),
            prompt=f.get("prompt", f["name"]),
            validation=dict(f.get("validation") or {}),
        )
        for f in raw.get("fields", [])
    ]
    documents = [
        DocumentDef(
            code=d["code"],
            required=bool(d.get("required", True)),
            label=d.get("label", d["code"]),
            allowed_mime_types=list(d.get("allowed_mime_types") or []),
            max_size_bytes=int(d.get("max_size_bytes", 5_242_880)),
        )
        for d in raw.get("documents", [])
    ]
    fee_raw = raw.get("fee") or {}
    fee = None
    if fee_raw:
        fee = FeeDef(
            amount_paise=int(fee_raw.get("amount_paise", 0)),
            currency=str(fee_raw.get("currency", "INR")),
            description=str(fee_raw.get("description") or ""),
        )
    return ServiceDefinition(
        service_code=raw["service_code"],
        display_name=raw.get("display_name", raw["service_code"]),
        description=str(raw.get("description") or "").strip(),
        languages=list(raw.get("languages") or ["en"]),
        fields=fields,
        documents=documents,
        prompts=dict(raw.get("prompts") or {}),
        fee=fee,
    )


@lru_cache
def get_service_catalogue() -> dict[str, ServiceDefinition]:
    services_dir = resolve_services_dir()
    catalogue: dict[str, ServiceDefinition] = {}
    if not services_dir.exists():
        return catalogue
    for path in sorted(services_dir.glob("*.yaml")):
        defn = load_service_definition(path)
        catalogue[defn.service_code] = defn
    return catalogue


def get_service(service_code: str) -> ServiceDefinition:
    catalogue = get_service_catalogue()
    if service_code not in catalogue:
        raise KeyError(f"Unknown service: {service_code}")
    return catalogue[service_code]
