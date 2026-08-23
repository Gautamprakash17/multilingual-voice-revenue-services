# Limitations and scope

This document separates **intentional POC scope**, **realistic mock adapters**, and **production extensions**. Intentional scope is not listed as a defect.

## Current POC implementation

| Area | What works today |
|------|------------------|
| Architecture | Modular monolith (FastAPI + React + Postgres) via Docker Compose |
| Data sovereignty | Fail-closed classification; Data Boundary Gateway; restricted bytes local |
| Certificate journey | One complete catalogue service: Income Certificate |
| Channels | Web (text + voice UI), WhatsApp **simulator**, IVR **simulator** |
| Speech / NLU | Local faster-whisper STT; **local eSpeak NG TTS** (en/hi/kn, offline, may sound robotic); rule-based NLU. Mock TTS remains for unit tests. No external LLM for restricted data. |
| Documents | Local upload + deterministic mock OCR/verification |
| Payment | Mock provider with SUCCESS / FAILURE / TIMEOUT |
| Receipt | Local plain-text receipt |
| Officer | Queue + approve / reject / request correction / escalate (shared token RBAC) |
| Observability | Structured JSON logs, append-only audit, in-process metrics API |
| Multilingual | English, Hindi, Kannada prompt bundles |

## Realistic mock adapters (by design)

These are **deliberate substitutes** for production systems so the demo is reproducible without live credentials:

- Mock OTP identity (`config/seed/personas.yaml`)
- Mock payment / treasury
- Mock OCR and document verification (filename-driven outcomes)
- WhatsApp and IVR **simulators** (not Meta Business or PSTN)
- Optional cloud provider **stub** (no unrestricted egress; restricted always denied)

## Production extensions (out of scope for this POC)

- Kubernetes, service mesh, multi-region HA
- Microservices / event bus / ELK / Grafana / Prometheus stack
- Real WhatsApp Business, real telephony, real Aadhaar, real payment gateways
- Enterprise IdP / full RBAC directory integration
- Heavy PDF certificate rendering and digital signatures
- Full WCAG accessibility certification and field usability studies
- Additional certificate types beyond the catalogue pattern (engine is ready; definitions not all authored)

## Accessibility and low-literacy support

**Partially addressed in the POC:** guided turn-by-turn conversation, language choice (en/hi/kn), voice **and** text modalities, explicit prompts and recovery messages (RETRY, CORRECT, HELP/ESCALATE).

**Speech synthesis:** Citizen prompts are spoken locally with **eSpeak NG** (installed in the backend Docker image). Synthesis is fully offline — no cloud TTS. Quality is lightweight and may sound robotic; this is intentional POC scope, not neural/natural TTS. Unit tests may still inject `MockTTSProvider` (tone WAV).

**Not claimed:** formal WCAG audit, screen-reader certification, field usability study artifacts, or natural-sounding neural TTS.

## Observability honesty

Metrics are **lightweight and in-process** (`GET /api/v1/metrics`). They support demo and regression evidence. They are not a production observability platform.
