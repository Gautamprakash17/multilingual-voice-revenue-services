# Multilingual Voice-First Revenue Services Platform

> **Hackathon POC** — not a production system. Built for the AI Club / Revenue Department case: voice-first, multilingual, channel-agnostic certificate services with **enforced local processing of restricted mock citizen/government data**.

## Project purpose

A voice-first platform that guides citizens through certificate journeys (income and related catalogue services) across web, WhatsApp, and IVR channels, while proving that restricted mock citizen and government-like data never leaves the local trust zone.

## Current POC Scope

### Implemented Capabilities

| Capability | Notes |
|------------|--------|
| FastAPI backend and health/readiness | `/api/v1/health`, `/api/v1/ready` |
| Data classification and Data Boundary Gateway | Fail-closed `RESTRICTED` / `INTERNAL` / `PUBLIC_SAFE` |
| PostgreSQL and Alembic | Application, session, document, and audit schema |
| Append-only audit logging | Safe metadata only; no raw restricted payloads |
| Income Certificate application journey | Deterministic conversation state machine |
| Mock OTP authentication | Seeded synthetic personas only |
| Consent handling | Explicit grant required before form capture |
| Form capture and validation | Config-driven rules from service catalogue |
| Document upload | Local storage, MIME/size/checksum, `RESTRICTED` |
| Multilingual support | English, Hindi, Telugu (i18n prompt bundles) |
| Channel-agnostic message envelope | Shared contract for all channels |
| Web text and voice interaction | Push-to-talk / record-style voice for the POC |
| WhatsApp simulator | Realistic adapter UI; not real WhatsApp |
| IVR simulator | DTMF + simulated speech; not real telephony |
| Local / mock STT and TTS | Optional faster-whisper if installed; mock default |
| Local rule-based NLU | Deterministic intent/slot extraction; no external LLM |
| Cross-channel session resume | Continue an application across channels |
| Operational metrics | Lightweight in-process metrics API |
| Docker Compose deployment | Reproducible local stack |

### Planned / Optional Extensions

| Extension | Notes |
|-----------|--------|
| Payment adapter | Mock or real treasury/UPI integration |
| OCR and document verification | Local OCR + verification adapters |
| Officer dashboard | Escalation queue and application review |
| Richer local speech models | Higher-accuracy on-prem STT/TTS |
| Production WhatsApp / telephony | Swap simulators for real channel providers |
| Additional certificate journeys | Same engine; catalogue-driven definitions |
| Optional cloud AI | Only for approved `PUBLIC_SAFE` content via the gateway |

Cloud AI is optional. The current implementation uses local processing for restricted data and does not require external AI services.

## Architecture summary

Modular monolith:

- **Trust Zone A (local):** API, channel adapters, orchestrator, boundary gateway, Postgres, audit, local STT/NLU/TTS providers
- **Trust Zone B (optional cloud):** Provider stubs only; egress is policy-gated. Restricted data is never sent to public cloud

Classifications: `RESTRICTED` · `INTERNAL` · `PUBLIC_SAFE` (fail-closed → `RESTRICTED`).

See [docs/architecture.md](docs/architecture.md) and [docs/data-classification.md](docs/data-classification.md).

## Local setup

### Prerequisites

- Python 3.12+
- Node.js 20+
- Docker + Docker Compose

### Backend (without Docker)

```bash
cp .env.example .env
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# Start Postgres (or use Compose postgres service), then:
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Tests

```bash
cd backend
pytest -q
ruff check app tests
```

```bash
cd frontend
npm run typecheck
npm run lint
npm run build
```

## Docker commands

```bash
# Validate compose file
docker compose config

# Build and start (postgres + backend + frontend)
docker compose up --build -d

# Health / ready (host ports: backend 8080, frontend 5174)
curl -s http://localhost:8080/api/v1/health
curl -s http://localhost:8080/api/v1/ready

# Citizen journey UI
open http://localhost:5174/journey

# Channel simulators
open http://localhost:5174/whatsapp
open http://localhost:5174/ivr

# Stop
docker compose down
```

Demo persona (synthetic): mobile `9876543210`, OTP `123456` (Lakshmi Devi).

Postgres is reachable from the backend on the Compose network only (not published to the host by default). Host ports `8080` (API) and `5174` (UI) avoid common local conflicts with other projects.

## Security / data classification summary

- No secrets in git (`.env` ignored; use `.env.example`)
- Fail-closed classification; `RESTRICTED` never allowed to cloud
- Boundary allow/deny decisions audited; raw restricted content not stored in audit metadata
- Structured logs redact passwords, tokens, API keys, OTPs, transcripts, and audio payloads
- API errors never return stack traces to clients
- CORS + basic security headers enabled

## Repository layout

```
backend/app/{api,core,boundary,channels,speech,nlu,platform,models,services,adapters}
frontend/                 # React + Vite + TypeScript
config/boundary/          # policies.yaml
config/i18n/              # en / hi / te prompt bundles
config/services/          # certificate service definitions
docs/                     # architecture + ADRs
docker-compose.yml
```

## Explicit statement

This repository is a **hackathon proof-of-concept**. It prioritizes a demoable end-to-end journey, data sovereignty invariants, and a clean modular foundation over production-scale infrastructure.
