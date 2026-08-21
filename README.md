# Multilingual Voice-First Revenue Services Platform

> **Hackathon POC** — not a production system. Built for the AI Club / Revenue Department case: voice-first, multilingual, channel-agnostic certificate services with **enforced local processing of restricted mock citizen/government data**.

## Project purpose

Engineer a foundation for a voice-first platform that will later guide citizens through certificate journeys (income, domicile, caste, etc.) across web, WhatsApp, and IVR — while proving that restricted data never leaves the local trust zone.

## POC scope (current phase = P2)

| In P1 + P2 | Out of scope (later) |
|------------|----------------------|
| FastAPI foundation, health/ready | Voice STT/TTS |
| Data classification + boundary gateway | WhatsApp / IVR simulators |
| Audit + structured logging | Payment adapters |
| Postgres + Alembic | OCR / document verification |
| **Income Certificate web text journey** | Officer dashboard |
| Mock identity (OTP) + consent + documents | Real cloud AI / OpenAI |
| React Apply UI | Multilingual UI beyond language placeholder |

OpenAI / cloud AI is **optional** and **not used** in P1/P2.

## Architecture summary

Modular monolith:

- **Trust Zone A (local):** API, boundary gateway, Postgres, audit, local providers
- **Trust Zone B (optional cloud):** stub only in P1; real calls gated later by policy

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

# Frontend
open http://localhost:5174/journey

# Stop
docker compose down
```

Demo persona (synthetic): mobile `9876543210`, OTP `123456` (Lakshmi Devi).

Postgres is reachable from the backend on the Compose network only (not published to the host by default). Host ports `8080` (API) and `5174` (UI) avoid common local conflicts with other projects.

## Security / data classification summary

- No secrets in git (`.env` ignored; use `.env.example`)
- Fail-closed classification; `RESTRICTED` never allowed to cloud
- Boundary allow/deny decisions audited; raw restricted content not stored in audit metadata
- Structured logs redact passwords, tokens, API keys, OTPs
- API errors never return stack traces to clients
- CORS + basic security headers enabled

## Repository layout

```
backend/app/{api,core,boundary,platform,models}
frontend/                 # React + Vite + TypeScript
config/boundary/          # policies.yaml
docs/                     # architecture + ADRs
docker-compose.yml
```

## Explicit statement

This repository is a **hackathon proof-of-concept**. It prioritizes demoable sovereignty invariants and a clean foundation over production-scale infrastructure.
