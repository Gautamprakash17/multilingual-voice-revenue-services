# Multilingual Voice-First Revenue Services Platform

> **Hackathon proof of concept — not a production system.**
> Voice-first, multilingual, channel-agnostic certificate services for a Revenue Department scenario, with **enforced local processing of restricted mock citizen and government-like data**.

## Problem

Citizens need guided help to complete certificate applications across languages and channels (web, messaging, telephony). Restricted personal and application data must remain under local control. Production WhatsApp, IVR, payments, and identity networks are unavailable in a hackathon setting, so the POC must still prove an end-to-end, secure, demoable path.

## Solution

A **modular monolith** that:

1. Runs a catalogue-driven **Income Certificate** conversational journey (voice and text)
2. Serves **Web**, **WhatsApp simulator**, and **IVR simulator** through one message envelope
3. Enforces **fail-closed data classification** via a **Data Boundary Gateway**
4. Completes **document verification**, **mock payment**, **receipt**, **status/correction**, and **officer review**
5. Ships with Docker Compose for reproducible demos and automated tests for sovereignty and journey invariants

## POC scope

| In scope | Out of scope |
|----------|--------------|
| One complete certificate journey (Income Certificate) | Multiple live production certificate types |
| Mock OTP, payment, OCR/verification | Real Aadhaar / UPI / treasury accounts |
| WhatsApp & IVR **simulators** | Live Meta WhatsApp / PSTN |
| Local faster-whisper STT + eSpeak NG TTS + rule NLU | Cloud LLM / cloud TTS on restricted data |
| Lightweight metrics + audit | Kubernetes, ELK, Grafana |
| Officer dashboard with shared POC token | Enterprise IdP |

Details: [docs/LIMITATIONS.md](docs/LIMITATIONS.md) · Coverage: [docs/REQUIREMENT_COVERAGE.md](docs/REQUIREMENT_COVERAGE.md)

## Implemented capabilities

| Capability | Notes |
|------------|--------|
| FastAPI health / readiness | `/api/v1/health`, `/api/v1/ready` |
| Data classification + Data Boundary Gateway | `RESTRICTED` / `INTERNAL` / `PUBLIC_SAFE`, fail-closed |
| PostgreSQL + Alembic | Applications, sessions, documents, payments, receipts, audit |
| Append-only audit | Safe metadata only |
| Income Certificate journey | Deterministic state machine |
| Mock OTP authentication | Synthetic personas only |
| Consent | Required before form capture |
| Form capture + validation | Catalogue YAML rules |
| Document upload + verification | Local store; mock OCR filename markers (`VERIFIED` / `MISMATCH` / `UNREADABLE`) — not content matching |
| Fee quote + payment | Mock `SUCCESS` / `FAILURE` / `TIMEOUT` + retry |
| Receipt | Local plain-text receipt |
| Officer review | Approve / reject / request correction / escalate (RBAC token) |
| Status + correction | Citizen + officer paths |
| Multilingual | English, Hindi, Kannada |
| Channel envelope | Web, WhatsApp sim, IVR sim |
| Cross-channel resume | Shared application + session token |
| Local faster-whisper STT + eSpeak NG TTS + rule NLU | Offline; no cloud TTS/LLM for restricted data |
| Operational metrics | `GET /api/v1/metrics` |
| Docker Compose | Reproducible local stack |

## Architecture

Modular monolith with two trust zones:

- **Trust Zone A (local):** API, channels, orchestrator, journey, gateway, Postgres, audit, local providers, document volume
- **Trust Zone B (optional cloud stub):** only `PUBLIC_SAFE` + explicit approval; **restricted always denied**

```
Citizen / Officer UI  →  FastAPI  →  Journey / Officer services
                              ↓
                     Data Boundary Gateway
                              ↓
              Local providers  |  (blocked) Cloud stub
```

- [Architecture overview](docs/architecture.md)
- [Mermaid context, container, and sequence diagrams](docs/diagrams.md)
- [Data classification](docs/data-classification.md)
- ADRs under `docs/adr/`

## Security and data sovereignty

- No secrets in git (`.env` ignored; use `.env.example`)
- Fail-closed classification; restricted never allowed to cloud
- Boundary allow/deny audited without raw restricted payloads
- Structured logs redact tokens, OTPs, transcripts, and audio
- API errors do not return stack traces
- Officer actions require `X-Officer-Token` (citizen session tokens are insufficient)

## Channels and multilingual support

| Channel | UI | Nature |
|---------|----|--------|
| Web | `/journey` | Text + voice |
| WhatsApp | `/whatsapp` | Simulator |
| IVR | `/ivr` | Simulator (DTMF + speech-style) |

Languages: **en**, **hi**, **kn** (`config/languages.yaml`, `config/i18n/`). Scripts and personas: [docs/personas-and-scripts.md](docs/personas-and-scripts.md).

## Certificate journey (Income Certificate)

`LANGUAGE_SELECT → AUTHENTICATE → CONSENT → SERVICE_SELECT → FORM_CAPTURE → DOCUMENT_CAPTURE → REVIEW_CONFIRM → FEE_QUOTE → PAYMENT → SUBMITTED`
Recovery states include `AUTH_FAILED`, `DOCUMENT_REJECTED`, `PAYMENT_FAILED`, `CORRECTION`, `ESCALATED`.
Post-submit processing: `UNDER_REVIEW` → correction / `APPROVED`→`ISSUED` / `REJECTED`.

## Mocked integrations

Identity OTP, payment, OCR/verification, WhatsApp, IVR, and optional cloud AI are **deterministic mocks/stubs** so demos stay offline-safe and reproducible.

## Setup

### Prerequisites

Python 3.12+, Node.js 20+, Docker + Docker Compose.

### Docker (recommended for judges)

```bash
cp .env.example .env
docker compose up --build -d
curl -s http://localhost:8080/api/v1/health
curl -s http://localhost:8080/api/v1/ready
```

| Service | URL |
|---------|-----|
| API | http://localhost:8080 |
| UI | http://localhost:5174 |
| Apply | http://localhost:5174/journey |
| Officer | http://localhost:5174/officer |
| WhatsApp sim | http://localhost:5174/whatsapp |
| IVR sim | http://localhost:5174/ivr |
| Metrics | http://localhost:8080/api/v1/metrics |

Default officer token: `officer-poc-token`.
Demo persona: mobile `9876543210`, OTP `123456` (Lakshmi Devi).

### Backend (without Docker)

```bash
cp .env.example .env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd backend && pip install -e .
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend && npm install && npm run dev
```

## Demo flow

Follow the timed judge script: **[docs/DEMO_RUNBOOK.md](docs/DEMO_RUNBOOK.md)** (~8–10 minutes).

Highlights: language → auth → consent → form → documents → fee/payment → receipt → officer action → cross-channel resume → payment/document failure recovery → boundary deny → metrics.

Document placeholders: [docs/document-samples.md](docs/document-samples.md) (`config/samples/documents/`).

## Testing

```bash
cd backend && pytest -q && ruff check app tests
cd frontend && npm run typecheck && npm run lint && npm run build
docker compose config
```

Evidence summary: [docs/TEST_EVIDENCE.md](docs/TEST_EVIDENCE.md).
Requirement mapping: [docs/REQUIREMENT_COVERAGE.md](docs/REQUIREMENT_COVERAGE.md).

## Repository layout

```
backend/app/{api,core,boundary,channels,speech,nlu,platform,models,services,adapters}
frontend/                 # React + Vite + TypeScript
config/boundary|i18n|services|seed|samples|providers
docs/                     # architecture, diagrams, coverage, demo, limitations
docker-compose.yml
```

## Explicit non-production statement

This repository is a **hackathon POC**. It prioritizes a demoable end-to-end journey, data-sovereignty invariants, modular clarity, and judge-ready evidence over production-scale infrastructure.
