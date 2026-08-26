# Data Classification Design

This document is a mandatory POC deliverable: **mock government/citizen data stays local**.

Classification and enforcement match the current codebase (`backend/app/boundary/`, `config/boundary/policies.yaml`). See also [architecture.md](./architecture.md) and [diagrams.md](./diagrams.md).

## Labels

| Classification | Meaning | Cloud egress |
|----------------|---------|--------------|
| `RESTRICTED` | Citizen identity, application fields, documents, raw audio, transcripts of citizen speech | **DENY always** |
| `INTERNAL` | Sessions, metrics, operational state, payment/receipt metadata as treated by services | **DENY** (local by default) |
| `PUBLIC_SAFE` | Approved non-sensitive / synthetic content only | ALLOW only with explicit approval + allowed purpose |

## Fail-closed rules

1. Missing classification → `RESTRICTED`
2. Unknown classification string → `RESTRICTED`
3. Merge of multiple labels → most restrictive wins (`RESTRICTED` + `PUBLIC_SAFE` = `RESTRICTED`)
4. Unknown destination or missing policy → DENY
5. `PUBLIC_SAFE` → cloud requires `approved=true` and purpose on the policy allowlist
6. Local destination → ALLOW under builtin local policy

## Enforcement

| Piece | Location |
|-------|----------|
| Classification helpers | `backend/app/boundary/classification.py` |
| Policy file | `config/boundary/policies.yaml` |
| Gateway | `backend/app/boundary/gateway.py` — sole egress decision point |
| Audit | Allow/deny recorded; **raw restricted payloads are never stored** in audit metadata (keys/counts only) |
| Cloud stub | `OptionalCloudProvider` — **zero** external HTTP calls in the POC |
| Logging | Structured logs redact tokens, OTPs, transcripts, audio, and similar secrets |

Automated tests assert restricted → cloud denied, zero HTTP on deny, audit omits restricted values, and unknown policy/destination fails closed.

---

## Data inventory (actual POC)

### Application / identity data

| Data | Classification | Purpose | Access | Storage / processing | Citizen visibility | Sensitive handling |
|------|----------------|---------|--------|----------------------|--------------------|--------------------|
| Application ID (`INC-…`) | INTERNAL reference (public-facing id) | Track application across channels | Citizen UI; officer UI; APIs | Postgres `applications.application_id` | **Yes** — primary citizen reference | Not a credential; alone cannot authorize actions |
| Applicant name | `RESTRICTED` | Form field / certificate content | Session-authorized journey; officer detail | `form_data` JSON; may appear on DEMO PDF | Entered by citizen; shown in journey | Local only; never cloud |
| Date of birth | `RESTRICTED` | Form validation / certificate | Same | `form_data` | Citizen input | Local only |
| Mobile number | `RESTRICTED` | Auth OTP + contact | Journey auth; mock notify recipient | Application + `synthetic_citizens` | Citizen input; masked in some UI | Local only; OTP separate |
| Address, district | `RESTRICTED` | Form / certificate | Journey; officer | `form_data` | Citizen input | Local only |
| Annual income | `RESTRICTED` | Form / certificate | Journey; officer | `form_data` | Citizen input | Local only |
| Service code / display name | INTERNAL / catalogue | Service selection | All channels; officer | Application + YAML catalogue | Yes | Non-secret catalogue |
| Database `Application.id` (UUID) | INTERNAL | FK joins | Backend only | Postgres PK | **No** — not shown as citizen id | Not used as Application ID |

### Authentication / session data

| Data | Classification | Purpose | Access | Storage / processing | Citizen visibility | Sensitive handling |
|------|----------------|---------|--------|----------------------|--------------------|--------------------|
| Conversation session id | INTERNAL | Bind channel turn to application | Backend | `conversation_sessions` | No | Internal |
| Session `access_token` | `RESTRICTED` / secret | Authorize citizen APIs (`X-Session-Token`) | Browser memory + `sessionStorage` handoff; backend | Postgres on session row | **No** — never presented as a password field | Redacted in logs; required for resume, docs, notifications, certificate |
| OTP challenge (hashed) | `RESTRICTED` | Mock identity verify | Backend OTP store | Hash + salt + TTL; max attempts | Code shown only via **demo SMS peek** API in OTP step | Not real SMS; not logged in clear |
| Officer token | Secret / INTERNAL | Officer RBAC (`X-Officer-Token`) | Officer UI config | Env / settings | Officers only (POC shared token) | Citizen session tokens insufficient |
| Synthetic citizen registry | `RESTRICTED` | Dynamic registration for unknown mobiles | Backend identity adapter | `synthetic_citizens` | Indirect (registration prompts) | Local only |

### Voice data

| Data | Classification | Purpose | Access | Storage / processing | Citizen visibility | Sensitive handling |
|------|----------------|---------|--------|----------------------|--------------------|--------------------|
| Recorded mic audio / `audio_b64` | `RESTRICTED` | Local STT | Channel orchestrator | **Ephemeral** — decoded for STT; temp file deleted; **not** durable storage | Citizen produces it | Never sent to cloud; not kept after STT |
| STT transcript | `RESTRICTED` | Journey input | Orchestrator → JourneyService | In request/reply path; may appear in chat UI | Yes (as recognized text) | Redacted from structured logs |
| TTS audio (`audio_b64` in reply) | INTERNAL / generated prompt audio | Speak prompts | Client playback | Response payload only; not archived | Heard / playable in UI | Generated locally via Piper (en/hi) or eSpeak NG (fallback / kn) |
| Client-supplied transcript fallback | `RESTRICTED` | Dev/fallback when mic denied | Same as text message | Not a stored audio archive | Shown as user text | Local journey processing |

### Documents

| Data | Classification | Purpose | Access | Storage / processing | Citizen visibility | Sensitive handling |
|------|----------------|---------|--------|----------------------|--------------------|--------------------|
| Uploaded document bytes | `RESTRICTED` | Proof for verification | Session upload/download; officer metadata | Local filesystem `doc_{uuid}`; metadata in `documents` | Citizen uploads; limited metadata in UI | Cloud OCR denied; local mock OCR only |
| Document metadata (code, MIME, verification_status) | `RESTRICTED` / INTERNAL mix | Track verification | Journey; officer | Postgres `documents` | Status labels | No raw bytes in audit |
| Issued certificate PDF | `RESTRICTED` DEMO artifact | Proof of issue for demo | Citizen session download; officer download | Filesystem + `ISSUED_CERTIFICATE` row | Yes when `ISSUED` | Marked DEMO / POC; not official; Application ID alone cannot download |
| Storage keys / paths | INTERNAL | Locate files | Backend | Path on disk + DB reference | No | Not exposed as public URLs without auth |

### Payment

| Data | Classification | Purpose | Access | Storage / processing | Citizen visibility | Sensitive handling |
|------|----------------|---------|--------|----------------------|--------------------|--------------------|
| Fee amount / quote | INTERNAL | Fee quote step | Journey | Application / catalogue | Yes in journey | Mock amounts |
| Payment result (`SUCCESS` / `FAILURE` / `TIMEOUT`) | INTERNAL | Advance or retry | Journey; officer sees payment completed | `payments` table | Outcome prompts | Mock provider — no real UPI |
| Payment reference | INTERNAL | Correlation | Journey receipt / officer | `PAY-…` style refs | On receipt when issued | Mock |
| Receipt body | INTERNAL | Citizen proof of mock payment | Session-authorized receipt API | `receipts` (`RCP-…`) | Yes after success | Local plain text |

### Notifications

| Data | Classification | Purpose | Access | Storage / processing | Citizen visibility | Sensitive handling |
|------|----------------|---------|--------|----------------------|--------------------|--------------------|
| Notification rows | INTERNAL operational + status text | Simulated multi-channel inbox | `GET /demo/notifications` + session token | `citizen_notifications` | Yes in PhoneSimulator / WhatsApp notices | `delivery_status=simulated`; not real SMS/WA/email |
| Event type | INTERNAL | `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_CORRECTION`, `ISSUED`, `REJECTED` | Same | Column on notification | Yes (labels) | Cycle dedup in `NotificationService` |
| Channel list (sms/whatsapp/email) | INTERNAL | Which mock providers ran | Same | JSON/list on row | Shown as channel labels | Mock providers only |
| Message / subject copy | May include Application ID + status | Citizen messaging | Same | Stored message text from i18n templates | Yes | Avoids session tokens; leak guards in frontend tests |
| Timestamps | INTERNAL | Ordering / unread | Same | `created_at` | Relative/time display | Non-secret |

### Audit

| Data | Classification | Purpose | Access | Storage / processing | Citizen visibility | Sensitive handling |
|------|----------------|---------|--------|----------------------|--------------------|--------------------|
| Audit events | INTERNAL | Append-only trail of journey, boundary, officer, voice pipeline | Backend / ops | `audit_events` | No raw citizen UI | Metadata redacted — no OTPs, tokens, raw audio, raw docs |
| Officer action events | INTERNAL | Approve, reject, correct, escalate, certificate issued | Officer history derived from audits | Same | Indirect via history labels | Notes may be stored carefully; secrets redacted |
| Boundary allow/deny | INTERNAL | Prove fail-closed | Tests + demo | Same | No | Never stores restricted payload values |

### Technical / internal data

| Data | Classification | Purpose | Access | Storage / processing | Citizen visibility | Sensitive handling |
|------|----------------|---------|--------|----------------------|--------------------|--------------------|
| API env secrets / DB URL | Secret | Runtime config | Operators | `.env` (not in git) | No | `.gitignore` |
| Metrics counters | INTERNAL | `GET /api/v1/metrics` | Ops | In-process / API | No PII intended | Aggregate only |
| Pending voice field buffers | `RESTRICTED` | `FIELD_CONFIRMATION` | Journey | Application columns `pending_voice_field` / `pending_voice_value` | Confirmation prompts | Cleared after confirm/change |
| Auth step flags | INTERNAL | mobile / otp / register_offer / register_name | Journey | `auth_step` | Indirect UX | Not a credential |

---

## Access summary

| Actor | May access | Must not |
|-------|------------|----------|
| Citizen (with session token) | Own application journey, own docs metadata, own receipt, own notifications, own issued PDF | Other applications; officer APIs; raw audit; others’ tokens |
| Citizen (Application ID only) | Display/copy of ID for human reference | Authenticated APIs, certificate download, notification list |
| Officer (officer token) | Queue, history, detail, actions, issued PDF | Citizen session impersonation without officer token |
| Cloud / external AI | Nothing restricted or internal | All RESTRICTED citizen content |

---

## Proof for judges

Automated tests assert:

- restricted → cloud denied
- denied requests make zero HTTP calls
- audit events omit restricted values
- unknown policy/destination fails closed

Live demo: boundary deny step in [DEMO_RUNBOOK.md](./DEMO_RUNBOOK.md). Diagrams: [diagrams.md](./diagrams.md) (boundary sequence).
