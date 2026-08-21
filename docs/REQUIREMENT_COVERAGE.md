# Requirement coverage matrix

Maps the Revenue Department / AI Club problem themes to this hackathon POC.
Statuses: **IMPLEMENTED** · **PARTIALLY IMPLEMENTED** · **DOCUMENTATION/EVIDENCE GAP** · **NOT REQUIRED FOR POC** · **MISSING**

Evidence paths are relative to the repository root.

---

## A. Enterprise architecture and data isolation

| Requirement | Status | Implementation | Evidence |
|-------------|--------|----------------|----------|
| Restricted data stays local | IMPLEMENTED | `backend/app/boundary/*`, local document store, `CLOUD_AI_ENABLED=false` default | `docs/data-classification.md`, `tests/test_gateway.py`, `tests/test_journey.py` |
| Public-safe cloud boundary | IMPLEMENTED | Gateway allow only `PUBLIC_SAFE` + approved purpose | `config/boundary/policies.yaml`, `tests/test_gateway.py` |
| Fail-closed classification | IMPLEMENTED | Missing/unknown → `RESTRICTED` | `backend/app/boundary/classification.py`, `tests/test_classification.py` |
| Data Boundary Gateway | IMPLEMENTED | Sole egress decision point | `backend/app/boundary/gateway.py`, `docs/diagrams.md` |
| Append-only audit trail | IMPLEMENTED | Audit events; safe metadata only | `backend/app/platform/audit.py`, `tests/test_platform.py` |
| API-first modular architecture | IMPLEMENTED | FastAPI modular monolith | `docs/architecture.md`, `docs/adr/ADR-001-modular-monolith.md` |
| Configuration separation | IMPLEMENTED | `.env`, `config/**` YAML | `.env.example`, `config/services`, `config/boundary`, `config/i18n` |
| Structured logging | IMPLEMENTED | JSON logs + redaction | `backend/app/platform/logging.py`, `tests/test_platform.py` |
| Observability | PARTIALLY IMPLEMENTED | In-process metrics + health/ready (not Prometheus/Grafana) | `GET /api/v1/metrics`, `docs/LIMITATIONS.md`, `docs/TEST_EVIDENCE.md` |

---

## B. Feature completeness

| Requirement | Status | Implementation | Evidence |
|-------------|--------|----------------|----------|
| Voice + text | IMPLEMENTED | Web voice UI + text; channel modalities | `frontend/src/pages/JourneyPage.tsx`, `backend/app/channels/orchestrator.py` |
| Multilingual support | IMPLEMENTED | en / hi / te | `config/i18n/*.yaml`, `docs/personas-and-scripts.md` |
| Web channel | IMPLEMENTED | Citizen Apply UI + web adapter | `/journey`, `WebChannelAdapter` |
| WhatsApp | IMPLEMENTED (simulator) | WhatsApp simulator adapter + UI | `/whatsapp`, `docs/LIMITATIONS.md` |
| IVR | IMPLEMENTED (simulator) | IVR simulator adapter + UI | `/ivr` |
| Authentication | IMPLEMENTED | Mock OTP + seeded personas | `backend/app/adapters/identity.py`, `config/seed/personas.yaml` |
| Consent | IMPLEMENTED | Explicit consent before form | Journey `CONSENT`, consent API |
| Conversational form capture | IMPLEMENTED | Sequential field capture | `backend/app/services/journey.py` |
| Validation | IMPLEMENTED | Catalogue-driven rules | `backend/app/services/validation.py`, `config/services/income_certificate.yaml` |
| Document capture | IMPLEMENTED | Local upload MIME/size/checksum | `backend/app/services/documents.py` |
| Document verification | IMPLEMENTED | Mock OCR + verify outcomes | `backend/app/adapters/documents.py`, `tests/test_p4_workflow.py` |
| Payment | IMPLEMENTED | Mock SUCCESS/FAILURE/TIMEOUT | `backend/app/adapters/payment.py` |
| Receipt | IMPLEMENTED | Local plain-text receipt | `backend/app/services/receipts.py`, receipt API |
| Submission | IMPLEMENTED | After successful payment | Journey → `SUBMITTED` / `UNDER_REVIEW` |
| Status tracking | IMPLEMENTED | Journey state + processing status | `GET /journey/{id}`, officer views |
| Corrections | IMPLEMENTED | Citizen CORRECT + officer targeted correction | Journey + officer API |
| Escalation | IMPLEMENTED | Citizen HELP/ESCALATE + officer escalate | State `ESCALATED`, metrics |
| Officer workflow | IMPLEMENTED | Queue approve/reject/correct/escalate | `/officer`, `backend/app/api/v1/officer.py` |
| Analytics / metrics | PARTIALLY IMPLEMENTED | Lightweight counters API | `/api/v1/metrics` |
| Accessibility / low-literacy | PARTIALLY IMPLEMENTED | Guided prompts, language choice, voice+text | `docs/LIMITATIONS.md` (no WCAG claim) |
| Cross-channel context | IMPLEMENTED | Resume API + shared application | `POST /api/v1/channels/resume` |
| Failure recovery | IMPLEMENTED | Auth, document, payment, validation paths | State machine + tests |
| Certificate / service catalogue | IMPLEMENTED | YAML catalogue (Income Certificate) | `config/services/income_certificate.yaml` |

---

## C. Mandatory deliverables

| Deliverable | Status | Location / evidence |
|-------------|--------|---------------------|
| At least one complete certificate journey | IMPLEMENTED | Income Certificate E2E (auth→…→receipt→officer) |
| Local data classification / processing design | IMPLEMENTED | `docs/data-classification.md` |
| Modular repository | IMPLEMENTED | `backend/app/*` packages + frontend |
| Conversation state machine | IMPLEMENTED | `backend/app/services/state_machine.py`, `docs/diagrams.md` |
| APIs | IMPLEMENTED | `/api/v1/journey`, `/channels`, `/officer`, `/health`, `/ready`, `/metrics` |
| Validation rules | IMPLEMENTED | Service YAML + validation engine |
| Adapters | IMPLEMENTED | Identity, payment, OCR/verify, channels, speech |
| Automated tests | IMPLEMENTED | 85 pytest cases (see `docs/TEST_EVIDENCE.md`) |
| Observability | PARTIALLY IMPLEMENTED | Logs + audit + metrics API |
| Seed data | IMPLEMENTED | `config/seed/personas.yaml` |
| Reproducible deployment | IMPLEMENTED | `docker-compose.yml` |
| Architecture diagrams | IMPLEMENTED | `docs/architecture.md`, `docs/diagrams.md` (Mermaid) |
| Sequence diagrams | IMPLEMENTED | `docs/diagrams.md` |
| Synthetic personas | IMPLEMENTED | Personas YAML + `docs/personas-and-scripts.md` |
| Multilingual scripts | IMPLEMENTED | i18n bundles + script doc |
| Service rules | IMPLEMENTED | `config/services/income_certificate.yaml` |
| Document samples | IMPLEMENTED | `config/samples/documents/`, `docs/document-samples.md` |
| Negative test cases | IMPLEMENTED | Listed in `docs/TEST_EVIDENCE.md` |
| Usability evidence | PARTIALLY IMPLEMENTED | Guided UX + `docs/DEMO_RUNBOOK.md` (not a formal study) |
| Latency / error metrics | PARTIALLY IMPLEMENTED | Live `/api/v1/metrics` (runtime values; not fabricated) |
| Rehearsed omnichannel demo | IMPLEMENTED (runbook) | `docs/DEMO_RUNBOOK.md` |

---

## Intentionally out of scope (not defects)

| Item | Classification |
|------|----------------|
| Kubernetes / microservices / ELK / Grafana | NOT REQUIRED FOR POC |
| Real WhatsApp / telephony / Aadhaar / payment accounts | NOT REQUIRED FOR POC |
| External LLM for restricted citizen data | NOT REQUIRED FOR POC (blocked by design) |

See also [LIMITATIONS.md](./LIMITATIONS.md).
