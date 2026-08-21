# Demo runbook (judge walkthrough)

**Duration:** approximately 8–10 minutes
**Audience:** hackathon judges
**Stack:** Docker Compose (API `http://localhost:8080`, UI `http://localhost:5174`)

This runbook uses only capabilities that exist in the repository. WhatsApp and IVR paths are **simulators**, not live provider accounts.

## Before you start

```bash
docker compose up --build -d
curl -s http://localhost:8080/api/v1/health
curl -s http://localhost:8080/api/v1/ready
```

Open tabs:

| Surface | URL |
|---------|-----|
| Citizen apply | http://localhost:5174/journey |
| Officer | http://localhost:5174/officer |
| WhatsApp simulator | http://localhost:5174/whatsapp |
| IVR simulator | http://localhost:5174/ivr |
| Metrics | http://localhost:8080/api/v1/metrics |

**Primary demo persona (synthetic):** Lakshmi Devi — mobile `9876543210`, OTP `123456`
**Officer token:** `officer-poc-token` (header / UI field)

**Document tip:** use any small PDF/JPEG/PNG. For verification failure demos, include `mismatch` or `unreadable` in the filename (see [document samples](./document-samples.md)).

---

## Minute 0–1 — Problem and trust model (speak while UI loads)

1. State the problem: multilingual voice-first certificate services with **restricted citizen data kept local**.
2. Point to Trust Zone A vs optional cloud stub ([diagrams](./diagrams.md)).
3. Show health/ready responses quickly.

---

## Minute 1–3 — Citizen happy path (web voice/text)

On **Apply** (`/journey`):

1. **Start** application → note `INC-…` id and session.
2. Select language (**en** / **hi** / **te**).
3. Authenticate: mobile `9876543210`, OTP `123456`.
4. Consent: **I agree**.
5. Service: `INCOME_CERTIFICATE`.
6. Fill form fields (guided prompts). Optional: use **voice** with a short spoken answer (mock STT accepts POC voice markers from the UI).
7. Upload three documents: `IDENTITY_PROOF`, `ADDRESS_PROOF`, `INCOME_PROOF` (clean filenames → verified).
8. Review → **CONFIRM** → fee quote → **PAY** → **PAY** (success).
9. Show **receipt** text and `UNDER_REVIEW` status in the reply / refresh status.

---

## Minute 3–4 — Payment failure recovery

Start a second short application (or reuse narrative on a fresh start if time allows):

1. Reach payment.
2. Reply **FAIL** → application stays in `PAYMENT_FAILED` with **RETRY**.
3. Reply **PAY** → success, receipt issued.
4. Optionally mention **TIMEOUT** parks safely without marking payment complete.

---

## Minute 4–5 — Document mismatch recovery

1. On document upload, choose a file named like `identity_mismatch.pdf`.
2. Show `DOCUMENT_REJECTED` / verification failed + **RETRY**.
3. Re-upload a clean file and continue.

---

## Minute 5–6 — Officer review, correction, approval

1. Open **Officer** (`/officer`), token `officer-poc-token`, refresh queue.
2. Select the submitted application.
3. **Request correction** on `annual_income`.
4. Return to citizen **Apply** (same application + session token still in UI if same browser session; otherwise resume via status with stored token).
5. Citizen supplies corrected income → **CONFIRM** (payment already completed; no second charge).
6. Officer **Approve → Issue** → status `ISSUED`.

Optional: **Escalate** on another application to show queue flag.

---

## Minute 6–7 — Cross-channel resume

1. From a web application mid-journey (after auth), copy `application_id` and session token.
2. Open **WhatsApp Sim**, use resume / continue with the same application.
3. Show state continuity (same application id, continued prompts).
4. Optionally tap **IVR Sim** for DTMF/voice-style continuation.

---

## Minute 7–8 — Data-boundary BLOCK

Demonstrate with a one-liner or existing test narrative:

- Restricted application/document traffic **cannot** be sent to cloud.
- Evidence: gateway tests + live policy (`config/boundary/policies.yaml`).
- Optional live check: call a journey path that evaluates cloud destination for `RESTRICTED` and show deny audit / zero cloud calls (see [requirement coverage](./REQUIREMENT_COVERAGE.md)).

Spoken line: “Fail-closed classification — missing or restricted labels never leave the local trust zone.”

---

## Minute 8–9 — Metrics and wrap-up

1. Open `http://localhost:8080/api/v1/metrics`.
2. Point to channel/language counters, STT/NLU success/failure, escalations, and (when recorded) payment/document verification fields after recent actions.
3. Close with: modular monolith, catalogue-driven Income Certificate, mocked adapters, reproducible Docker demo — **not production**.

---

## Backup paths if time is short

| If short on time | Skip to |
|------------------|---------|
| Skip second payment app | Narrate FAIL/RETRY from README |
| Skip IVR | WhatsApp resume only |
| Skip correction | Officer approve only |

## Known demo constraints (honest)

- WhatsApp / IVR / payment / OTP / OCR are **deterministic mocks**.
- Receipts are plain text, not PDF certificates.
- Officer auth is a shared POC token, not enterprise IdP.
