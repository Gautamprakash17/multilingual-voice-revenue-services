# Architecture — Multilingual Voice-First Revenue Services Platform

**Status:** Hackathon POC — current implementation (source of truth: repository code)  
**Style:** Modular monolith (not microservices)  
**Deployment:** Local-first / data-sovereign Docker Compose stack

## Purpose

Architecture for a multilingual, voice-first Revenue Department certificate platform. The POC proves an end-to-end Income Certificate journey across **Web**, **WhatsApp simulator**, and **IVR simulator**, with officer review, issued certificate PDF, and simulated citizen status notifications — while keeping restricted mock citizen data local.

### What this is

```
Modular monolith
  + channel-agnostic journey
  + local-first / data-sovereign POC
```

Citizen channels never own their own applications. One **Application** (citizen-facing Application ID) is shared; each channel uses one or more **ConversationSession** rows with internal session tokens.

### Implemented capabilities (current code)

| Area | Implementation |
|------|----------------|
| Catalogue journey | Income Certificate (`config/services/income_certificate.yaml`) |
| Languages | English (`en`), Hindi (`hi`), Kannada (`kn`) |
| Channels | Web, WhatsApp simulator, IVR simulator via one message envelope |
| Auth | Mock OTP (`MockIdentityProvider` + `OtpChallengeStore`); dynamic registration for unknown mobiles |
| Consent | Required before service/form capture |
| Form | Catalogue fields + validation; voice field confirmation (`FIELD_CONFIRMATION`) |
| Documents | Local filesystem store; mock OCR/verification (`VERIFIED` / `MISMATCH` / `UNREADABLE`) |
| Payment | `MockPaymentProvider` (`SUCCESS` / `FAILURE` / `TIMEOUT`) + local receipt |
| Officer | Queue, history, approve & issue, reject, request correction, escalate |
| Certificate | DEMO/POC PDF (`ISSUED_CERTIFICATE`); not an official government document |
| Notifications | `NotificationService` + mock SMS / WhatsApp / email providers → `citizen_notifications` |
| Speech | Local faster-whisper STT; Piper neural TTS (en/hi) with eSpeak NG fallback (kn); rule-based NLU |
| Sovereignty | Data Boundary Gateway; fail-closed `RESTRICTED` / `INTERNAL` / `PUBLIC_SAFE` |
| Audit | Append-only `audit_events` with redacted metadata |
| Frontend | React/Vite: Home, Apply, WhatsApp, IVR, Officer |
| Ops | Docker Compose prod-style + `docker-compose.dev.yml` / `./scripts/dev` hot reload |

### Explicitly not claimed

- Live Meta WhatsApp Business, live PSTN/IVR, Twilio, SMTP, AWS SNS
- Real Aadhaar / UPI / treasury payment gateways
- Cloud STT / cloud TTS / cloud LLM on restricted data
- Unrestricted cross-device resume without a prior session token in that browser
- Official legal certificates (PDF is DEMO / POC only)

### Optional / planned extensions

Production WhatsApp/telephony providers, richer on-prem speech models, additional catalogue services, and optional cloud AI **only** for approved `PUBLIC_SAFE` content through the Data Boundary Gateway.

---

## Trust zones

```
┌─────────────────────────────────────────────┐
│ Trust Zone A — Local / On-prem              │
│  Channels → Orchestrator → Journey engine   │
│  Officer services · NotificationService     │
│  Boundary Gateway (policy + audit)          │
│  Local STT / NLU / TTS · Postgres · Audit   │
│  Local document volume · mock providers     │
└──────────────────────┬──────────────────────┘
                       │ only PUBLIC_SAFE + approved
═══════════════════════╪═══════════════════════
                       ▼
              Trust Zone B — optional cloud stub
              (no unrestricted HTTP; restricted always denied)
```

Restricted citizen text, voice, application data, and documents remain in Trust Zone A. The gateway is the sole egress decision point.

---

## Layered architecture

```
Citizen interfaces
  Web  ·  WhatsApp simulator  ·  IVR simulator
  Officer Portal
        ↓
FastAPI backend  (/api/v1/…)
        ↓
Channel layer (adapters + MessageEnvelope)
        ↓
ChannelOrchestrator  (STT → NLU → journey text → TTS)
        ↓
JourneyService / OfficerService / NotificationService /
Document & payment services / Certificate renderer
        ↓
Data Boundary Gateway
        ↓
PostgreSQL · local document storage · local STT/TTS · mock providers
```

| Layer | Responsibility |
|-------|----------------|
| Citizen / officer UI | React pages; browser mic; DTMF keypad; PhoneSimulator inbox |
| FastAPI | Versioned HTTP: health, journey, channels, officer, demo notifications/SMS |
| Channel adapters | `WebChannelAdapter`, `WhatsAppSimulatorAdapter`, `IVRSimulatorAdapter` |
| Orchestrator | Ingress boundary check, STT, language, NLU, DTMF→journey mapping, TTS |
| Journey / officer | State machine, OTP, form, docs, payment, review actions, certificate |
| Notifications | Status transitions → mock providers → `citizen_notifications` |
| Data / providers | Postgres, filesystem docs, faster-whisper, Piper + eSpeak NG, mocks |
| Boundary | Classification + policy + gateway + audit of allow/deny |

---

## Module map

| Module | Responsibility |
|--------|----------------|
| `app/api` | Versioned HTTP routes (health, journey, channels, officer, demo, metrics) |
| `app/core` | Config, DB, security helpers (redaction) |
| `app/boundary` | Classification, policy, gateway, local/cloud stubs |
| `app/channels` | Message envelope, adapters, `ChannelOrchestrator` |
| `app/speech` | Language helpers, STT (`LocalSTTProvider` / faster-whisper), TTS (Piper en/hi + eSpeak NG fallback) |
| `app/nlu` | Local rule-based intent/slot extraction (`LocalRuleNLUProvider`) |
| `app/services` | Journey, state machine, catalogue, validation, i18n, documents, receipts, officer, notifications, certificate |
| `app/adapters` | Mock identity/OTP, payment, OCR/document verification, notification providers |
| `app/platform` | Audit, logging, middleware, metrics |
| `app/models` | ORM: Application, ConversationSession, DocumentRecord, PaymentRecord, ReceiptRecord, CitizenNotification, SyntheticCitizen, AuditEvent |

---

## Shared application identity

```
Web  ·  WhatsApp  ·  IVR
        ↓
   same Application
   (citizen-facing Application ID, e.g. INC-1657)
        ↓
   ConversationSession(s)
   (per channel / resume; internal access_token)
```

### Rules (as implemented)

| Action | Result |
|--------|--------|
| **Start** a new application (`POST …/channels/{channel}/start` or journey start) | Creates a new `Application` + first `ConversationSession` + new `access_token` |
| **Continue / resume** an existing application | Does **not** create another Application; binds or creates a session for the target channel |
| Channel messages | Update the **same** Application (shared journey state + form/docs/payment) |
| Application ID | Citizen-facing reference (`INC-{1000–9999}` style from `application_ids.py`) |
| Session token (`access_token`) | Internal authorization via `X-Session-Token`; **not** shown as a citizen credential |
| Application ID alone | **Not** an authentication credential — cannot authorize messages, document download, notifications, or certificate download |

### Resume / handoff limitations (actual)

- Resume API: `POST /api/v1/channels/resume` with `{ application_id, channel }` and existing `X-Session-Token`.
- Frontend stores `{ applicationId, accessToken }` in **`sessionStorage`** (`sessionHandoff.ts`) for same-browser handoff (Apply → WhatsApp, IVR → WhatsApp).
- Continuing by Application ID alone works **only** if this browser tab previously saved the handoff for that ID.
- Other browsers/devices, cleared storage, or a brand-new session without a token → resume fails with same-browser messaging. There is **no** unrestricted cross-device resume in the current POC.

---

## Journey lifecycle

Two distinct status dimensions:

| Dimension | Field | Purpose |
|-----------|-------|---------|
| **Journey state** | `ConversationSession` / application conversational state (`JourneyState`) | Where the citizen is in the dialogue |
| **Processing status** | `Application.processing_status` (`ProcessingStatus`) | Officer / post-submit lifecycle |

### Journey states (`JourneyState`)

`LANGUAGE_SELECT` → `AUTHENTICATE` → (`AUTH_FAILED` recovery) → `CONSENT` → `SERVICE_SELECT` → `FORM_CAPTURE` ↔ `FIELD_CONFIRMATION` → `DOCUMENT_CAPTURE` ↔ `DOCUMENT_REJECTED` → `REVIEW_CONFIRM` → `FEE_QUOTE` → `PAYMENT` ↔ `PAYMENT_FAILED` → `SUBMITTED`

Also: `CORRECTION` (officer reopen), `ESCALATED` (officer escalate path).

Typical Income Certificate path:

1. **Language** — `en` / `hi` / `kn`
2. **Authentication** — mobile → OTP (seeded personas) or **register offer** → OTP → name registration (`SyntheticCitizen`) for unknown mobiles
3. **Consent** — required yes
4. **Service selection** — Income Certificate
5. **Form capture** — catalogue fields (`applicant_name`, `date_of_birth`, `mobile_number`, `address`, `district`, `annual_income`, …)
6. **Field confirmation** — voice captures enter `FIELD_CONFIRMATION` (confirm / change)
7. **Document capture** — upload required docs; mock OCR verification
8. **Review** — confirm or correct
9. **Fee quote** → **mock payment** → **receipt**
10. **Submission** — journey → `SUBMITTED`; processing → **`UNDER_REVIEW`** (in one finalize step); notifications for `SUBMITTED` + `UNDER_REVIEW`
11. **Officer processing** — correction / approve & issue / reject / escalate
12. **Correction path** — processing `NEEDS_CORRECTION`, journey `CORRECTION` → citizen fixes → resubmit → `UNDER_REVIEW` again

### Processing statuses (`ProcessingStatus`)

| Value | Meaning in POC |
|-------|----------------|
| `DRAFT` | Application started, not yet submitted |
| `SUBMITTED` | Enum / filters / notifications; happy-path finalize sets processing to `UNDER_REVIEW` |
| `UNDER_REVIEW` | In officer queue after successful payment/submit |
| `NEEDS_CORRECTION` | Officer requested correction |
| `APPROVED` | Brief intermediate during approve (audit), then `ISSUED` |
| `ISSUED` | Certificate generated and stored |
| `REJECTED` | Officer rejected |

---

## Channel architecture

All citizen channels use `ChannelOrchestrator.process_envelope`:

1. Data Boundary Gateway ingress check  
2. Load Application + ConversationSession (`X-Session-Token`)  
3. If `modality=voice`: prefer client `transcript`, else decode `audio_b64` → local STT  
4. Language resolve + local NLU  
5. Map text / DTMF → journey tokens  
6. `JourneyService.handle_message`  
7. Optional local TTS → `audio_b64` in reply  

Channels: `web` | `whatsapp` | `ivr`.

API surface (prefix `/api/v1`):

- `POST /channels/{channel}/start`
- `POST /channels/{channel}/message`
- `POST /channels/resume`
- Journey helpers: start, message, consent, documents, receipt, issued certificate download
- Demo: `GET /demo/sms`, `GET /demo/notifications` (session-authorized; simulated)
- Officer: queue, history, detail, approve / reject / request-correction / escalate, certificate download

---

## IVR architecture (simulator)

The IVR UI is a **call simulator**, not live PSTN.

### Interaction modes

| Mode | Journey context | Input |
|------|-----------------|-------|
| Language menu | `LANGUAGE_SELECT` | DTMF digit → language |
| Mobile | `AUTHENTICATE` (mobile) | Digits, auto-submit at 10 |
| OTP | `AUTHENTICATE` (otp) | Digits, auto-submit at 6 |
| Register | `AUTHENTICATE` (register_offer) | `1` = Register, `2` = another number |
| Yes/No menus | Consent, review, fee/payment | `1` / `2` mapped to YES/NO, CONFIRM/CORRECT, PAY, etc. |
| Service select | `SERVICE_SELECT` | Digit → service |
| Field confirm | `FIELD_CONFIRMATION` | **Press 1 = Confirm · Press 2 = Change** (not `#` / `*`) |
| Free-form | Names, address, etc. | Browser microphone → voice |

### DTMF and voice

- On-screen keypad + physical keyboard digits (`0–9`, `*`, `#` where mode allows)
- Digit buffering with automatic submission for fixed-length and single-key menus
- Backend `_map_ivr_dtmf` maps digits to journey tokens per state
- Microphone: capture → encode mono 16 kHz WAV base64 → `modality=voice` → local STT → transcript → journey
- Silence / mic-denied: retry messaging + optional developer typed fallback
- TTS reply audio with barge-in when recording starts
- Document upload is not done by phone; UI offers **Continue on WhatsApp** (same Application ID + same-browser handoff)

---

## Voice / STT / TTS pipeline

```
Microphone (browser)
  → MediaRecorder / capture
  → encode WAV PCM16 mono 16 kHz (base64)
  → POST /channels/{channel}/message  (modality=voice, audio_b64 [, transcript])
  → LocalSTTProvider (faster-whisper when available; else MockSTT)
  → transcript
  → JourneyService validation / FIELD_CONFIRMATION
  → next state + prompt
  → LocalTTSProvider (Piper en/hi, eSpeak NG fallback) → audio_b64 in reply (optional playback)
```

| Concern | Actual implementation |
|---------|------------------------|
| STT | `faster-whisper` (`small` by default, CPU) via `WhisperSTTProvider` when installed; else `MockSTTProvider` (`POCSTT:` marker) |
| TTS | Piper neural voices for `en` / `hi` when models are present; eSpeak NG fallback (always for `kn` in this POC) |
| NLU | `LocalRuleNLUProvider` — rules/keywords, no cloud LLM |
| Audio persistence | **Not durable** — STT uses ephemeral temp files that are deleted; TTS is response payload only |
| Developer fallback | Typed transcript and/or `encodePocVoice` without claiming live mic |

Distinguish clearly: **real browser mic capture** vs **typed/simulator fallback** vs **STT** vs **TTS**.

---

## Documents and payment

### Documents

```
Upload (multipart)
  → local store under document_storage_path (doc_{uuid})
  → MockOCRProvider + MockDocumentVerificationProvider
  → DocumentRecord metadata in Postgres
  → VERIFIED → continue; MISMATCH/UNREADABLE → DOCUMENT_REJECTED + retry
```

Filename markers drive mock outcomes (`verified` path vs `mismatch` / `unreadable` / `corrupt`). Cloud OCR is hard-denied by the gateway. Issued certificate uses document code **`ISSUED_CERTIFICATE`** (not a citizen upload).

### Payment

```
REVIEW_CONFIRM → FEE_QUOTE → PAYMENT
  → MockPaymentProvider.charge(scenario)
  → SUCCESS → PaymentRecord + receipt (RCP-…) + finalize submit
  → FAILURE / TIMEOUT → PAYMENT_FAILED (retry)
```

Mock only — **no** real UPI or payment gateway.

---

## Officer architecture

The officer portal operates on the **same Application** created by the citizen journey. No separate officer application is created.

| Capability | Behavior |
|------------|----------|
| Queue | Applications in review / correction / escalated visibility |
| History | Completed officer actions (issued, rejected, escalated, corrections) |
| Detail | Application ID, processing status, service, channel, fields present, documents, payment, lifecycle |
| Approve & issue | Generate DEMO PDF → store `ISSUED_CERTIFICATE` → `ISSUED` → notify |
| Reject | `REJECTED` + notes → notify |
| Request correction | Journey `CORRECTION`, processing `NEEDS_CORRECTION` → notify |
| Escalate | `escalated` flag (+ journey `ESCALATED` when allowed by state machine) |
| Audit | Officer actions recorded in `audit_events` |
| Auth | `X-Officer-Token` (POC shared token); citizen session tokens are insufficient |

---

## Certificate issuance

```
Officer Approve & Issue
  → render_income_certificate_pdf (DEMO / POC disclaimer)
  → DocumentRecord ISSUED_CERTIFICATE + local PDF bytes
  → processing_status = ISSUED
  → NotificationService.notify_status(ISSUED)
  → authorized download (citizen session token or officer token)
```

| Fact | Detail |
|------|--------|
| Document code | `ISSUED_CERTIFICATE` |
| Idempotency | Re-approve when already `ISSUED` reuses existing PDF; does not re-audit issuance |
| Citizen download | `GET /api/v1/journey/{id}/documents/ISSUED_CERTIFICATE` + `X-Session-Token` |
| Officer download | `GET /api/v1/officer/{id}/documents/ISSUED_CERTIFICATE` + `X-Officer-Token` |
| Application ID alone | **Cannot** download the certificate |

**Disclaimer (rendered on PDF):** DEMO / POC DOCUMENT — Not an official government certificate. No legal validity. No seals, signatures, QR codes, or legal claims beyond the POC text.

---

## Notification architecture (simulated / local / POC)

```
Application status transition
        ↓
NotificationService
        ↓
MockSmsProvider / MockWhatsAppProvider / MockEmailProvider
        ↓
citizen_notifications (Postgres)
        ↓
GET /api/v1/demo/notifications  (+ session token)
        ↓
PhoneSimulator inbox / WhatsApp notice bubbles / IVR-adjacent surfaces
```

| Item | Actual |
|------|--------|
| Events | `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_CORRECTION`, `ISSUED`, `REJECTED` |
| Delivery | `delivery_status="simulated"` — **not** real SMS/WhatsApp/email |
| Providers | Local mock classes only (no Twilio / Meta / SMTP / SNS in code) |
| Dedup | Cycle-based: same event in a cycle skipped; `NEEDS_CORRECTION` / `ISSUED` / `REJECTED` break the cycle so later resubmit can notify again |
| OTP peek | `GET /api/v1/demo/sms` during authenticate OTP step — synthetic inbox for demos |

---

## Data Boundary Gateway and security

Classifications: **`RESTRICTED`**, **`INTERNAL`**, **`PUBLIC_SAFE`**. Missing/unknown → treat as `RESTRICTED` (fail-closed). Restricted data remains local; cloud egress for restricted/internal is denied.

Security boundaries in the current POC:

| Boundary | Mechanism |
|----------|-----------|
| Citizen APIs | `X-Session-Token` must match session for that Application |
| Officer APIs | `X-Officer-Token` |
| Application ID | Reference only — not a password |
| Document / certificate download | Session or officer token required |
| Notifications / demo SMS | Session token + application ownership |
| Audit / logs | Redact tokens, OTPs, transcripts, audio, raw restricted payloads |

See [data-classification.md](./data-classification.md).

---

## Data stores

| Store | Contents |
|-------|----------|
| PostgreSQL | Applications, sessions, documents metadata, payments, receipts, synthetic citizens, citizen_notifications, audit_events |
| Local filesystem | Uploaded document bytes; issued certificate PDF |
| Ephemeral | STT temp audio (deleted); TTS bytes in HTTP response |

Alembic chain includes migrations through `0006_citizen_notifications` (OTP registration + notifications).

---

## Configuration

Environment-driven via `.env` (see `.env.example`). Secrets are never committed. Provider mode defaults to local; `CLOUD_AI_ENABLED=false`. Officer POC token is configured (not committed as a secret for production — demo value only).

---

## Related docs

- [Diagrams (context, containers, sequences)](./diagrams.md)
- [Data classification](./data-classification.md)
- [Requirement coverage](./REQUIREMENT_COVERAGE.md)
- [Demo runbook](./DEMO_RUNBOOK.md)
- [Limitations](./LIMITATIONS.md)
- [Personas and scripts](./personas-and-scripts.md)
- [Document samples](./document-samples.md)
- [Test evidence](./TEST_EVIDENCE.md)
- [ADR-001 Modular monolith](./adr/ADR-001-modular-monolith.md)
- [ADR-002 Local-first data processing](./adr/ADR-002-local-first-data-processing.md)
- [ADR-003 Fail-closed data boundary](./adr/ADR-003-fail-closed-data-boundary.md)
