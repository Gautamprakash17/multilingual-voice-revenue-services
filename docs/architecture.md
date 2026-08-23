# Architecture — Multilingual Voice-First Revenue Services Platform

**Status:** Hackathon POC — current implementation
**Style:** Modular monolith (not microservices)

## Purpose

Architecture for a multilingual, voice-first Revenue Department certificate platform. The current POC implements:

- FastAPI application with `/api/v1/health`, `/api/v1/ready`, journey and channel APIs
- PostgreSQL + SQLAlchemy + Alembic
- Data classification (`RESTRICTED` / `INTERNAL` / `PUBLIC_SAFE`) with fail-closed defaults
- Data Boundary Gateway + declarative policy engine
- Append-only audit trail and JSON structured logging
- Income Certificate journey (state machine, mock OTP, consent, form, documents, verification, fee/payment, receipt, review/submit)
- Channel-agnostic message envelope with Web, WhatsApp simulator, and IVR simulator adapters
- Multilingual prompts (English, Hindi, Kannada)
- Local faster-whisper STT, **local eSpeak NG TTS** (en / hi / kn; offline; robotic but spoken), and rule-based NLU
- Cross-channel session resume and lightweight operational metrics
- Officer review dashboard (approve / reject / request correction / escalate)
- React/Vite frontend (citizen journey, officer review, channel simulators)
- Docker Compose local stack

### Planned / optional extensions

Production WhatsApp/telephony providers, richer on-prem speech models, additional catalogue services, and optional cloud AI strictly for approved `PUBLIC_SAFE` content.

## Trust zones

```
┌─────────────────────────────────────────────┐
│ Trust Zone A — Local / On-prem              │
│  Channels → Orchestrator → Journey engine   │
│  Boundary Gateway (policy + audit)          │
│  Local STT / NLU / TTS · Postgres · Audit   │
└──────────────────────┬──────────────────────┘
                       │ only PUBLIC_SAFE + approved
═══════════════════════╪═══════════════════════
                       ▼
              Trust Zone B — optional cloud
              (stubs only; no unrestricted calls)
```

Restricted citizen text, voice, application data, and documents remain in Trust Zone A. The gateway is the sole egress decision point.

## Module map

| Module | Responsibility |
|--------|----------------|
| `app/api` | Versioned HTTP routes (health, journey, channels, officer, metrics) |
| `app/core` | Config, DB, security helpers |
| `app/boundary` | Classification, policy, gateway, providers |
| `app/channels` | Message envelope, adapters, orchestrator |
| `app/speech` | Language detection, STT, TTS |
| `app/nlu` | Local rule-based intent/slot extraction |
| `app/services` | Journey engine, catalogue, validation, i18n, documents, receipts, officer |
| `app/adapters` | Mock identity, payment, OCR/document verification |
| `app/platform` | Audit, logging, middleware, metrics |
| `app/models` | ORM models |

## Configuration

Environment-driven via `.env` (see `.env.example`). Secrets are never committed. Provider mode defaults to `local`; `CLOUD_AI_ENABLED=false`.

## Related docs

- [Diagrams (C4 + sequences)](./diagrams.md)
- [Requirement coverage](./REQUIREMENT_COVERAGE.md)
- [Demo runbook](./DEMO_RUNBOOK.md)
- [Limitations](./LIMITATIONS.md)
- [Data classification](./data-classification.md)
- [Personas and scripts](./personas-and-scripts.md)
- [Document samples](./document-samples.md)
- [Test evidence](./TEST_EVIDENCE.md)
- [ADR-001 Modular monolith](./adr/ADR-001-modular-monolith.md)
- [ADR-002 Local-first data processing](./adr/ADR-002-local-first-data-processing.md)
- [ADR-003 Fail-closed data boundary](./adr/ADR-003-fail-closed-data-boundary.md)
