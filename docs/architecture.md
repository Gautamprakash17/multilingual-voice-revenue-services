# Architecture — P1 Foundation

**Status:** Hackathon POC foundation (Phase P1)  
**Style:** Modular monolith (not microservices)

## Purpose

Foundation for a multilingual voice-first Revenue Department certificate platform. P1 delivers:

- FastAPI application skeleton with `/api/v1/health` and `/api/v1/ready`
- PostgreSQL + SQLAlchemy + Alembic
- Data classification (`RESTRICTED` / `INTERNAL` / `PUBLIC_SAFE`) with fail-closed defaults
- Data Boundary Gateway + declarative policy engine
- Append-only audit trail
- JSON structured logging with request correlation
- React/Vite frontend shell (health + placeholders)
- Docker Compose local stack

**Not in P1:** certificate journeys, voice, WhatsApp/IVR, payments, OCR, multilingual UI.

## Trust zones

```
┌─────────────────────────────────────────────┐
│ Trust Zone A — Local / On-prem              │
│  Channels (later) → Orchestrator (later)    │
│  Boundary Gateway (policy + audit)          │
│  Local providers · Postgres · Audit         │
└──────────────────────┬──────────────────────┘
                       │ only PUBLIC_SAFE + approved
═══════════════════════╪═══════════════════════
                       ▼
              Trust Zone B — optional cloud
              (stub only in P1; no real calls)
```

## Module map

| Module | Responsibility |
|--------|----------------|
| `app/api` | Versioned HTTP routes |
| `app/core` | Config, DB, security helpers |
| `app/boundary` | Classification, policy, gateway, providers |
| `app/platform` | Audit, logging, middleware |
| `app/models` | ORM models |

## Configuration

Environment-driven via `.env` (see `.env.example`). Secrets are never committed. Provider mode defaults to `local`; `CLOUD_AI_ENABLED=false`.

## Related docs

- [Data classification](./data-classification.md)
- [ADR-001 Modular monolith](./adr/ADR-001-modular-monolith.md)
- [ADR-002 Local-first data processing](./adr/ADR-002-local-first-data-processing.md)
- [ADR-003 Fail-closed data boundary](./adr/ADR-003-fail-closed-data-boundary.md)
