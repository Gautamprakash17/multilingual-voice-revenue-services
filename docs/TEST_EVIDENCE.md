# Test and measurement evidence

Numbers below are from **actual** repository commands and runtime checks. Do not treat placeholders as measurements.

## Automated test suite

Command (from `backend/`):

```bash
pytest -q
ruff check app tests
```

**Latest collected/executed count in this submission preparation:** **85 tests passed** (`pytest -q`).

### Coverage by concern (test modules)

| Concern | Primary modules |
|---------|-----------------|
| Classification fail-closed | `tests/test_classification.py` |
| Policy fail-closed | `tests/test_policy.py` |
| Gateway deny / zero cloud HTTP / audit safety | `tests/test_gateway.py` |
| Audit, log redaction, health/ready | `tests/test_platform.py` |
| State machine transitions / recovery | `tests/test_state_machine.py` |
| Auth, consent, form, documents, access isolation | `tests/test_journey.py` |
| Channels, i18n, NLU, STT/TTS, resume, metrics | `tests/test_p3_channels.py` |
| OCR/payment/officer/receipt/RBAC/boundary | `tests/test_p4_workflow.py` |

### Negative / recovery cases exercised in tests

- Invalid OTP → `AUTH_FAILED` with retry
- Invalid field formats stay in capture state
- Document MIME/size rejection and verification `MISMATCH` / `UNREADABLE`
- Payment `FAILURE` and `TIMEOUT` with safe retry
- Invalid state transitions rejected
- Citizen cannot call officer APIs without officer token
- Restricted → cloud evaluated as **denied**; cloud stub call count remains 0
- Audit metadata omits raw OTP / restricted field values / transcripts

## Frontend quality gates

From `frontend/`:

```bash
npm run typecheck
npm run lint
npm run build
```

These must pass for submission readiness (executed during final verification).

## Runtime endpoints

With Compose up (host ports **8080** API / **5174** UI):

| Check | Endpoint | Observed during final verification |
|-------|----------|-------------------------------------|
| Liveness | `GET /api/v1/health` | `{"status":"ok",...}` |
| Readiness (DB) | `GET /api/v1/ready` | `{"status":"ready","checks":{"database":"ok"}}` |
| Metrics snapshot | `GET /api/v1/metrics` | See measured sample below |

### Metrics fields available in code

`sessions_by_channel`, `sessions_by_language`, `stt_success` / `stt_failure`, `nlu_success` / `nlu_failure`, `channel_errors`, `escalations`, `corrections`, `payments.{success,failure,timeout}`, `document_verification.{verified,mismatch,unreadable}`, `status_distribution`, `latency_ms.{count,avg,p50}`.

**Latency note:** `latency_ms` is populated when STT paths record timing in the orchestrator. Values depend on live traffic after process start; they are not hard-coded. Report the JSON returned by `/api/v1/metrics` during the demo rather than inventing figures.

### Measured sample after live demo scripts (same Compose process)

After exercising happy-path submit, payment failure→retry, officer approve, and channel resume against `localhost:8080`, `/api/v1/metrics` included (excerpt):

- `payments`: `{"success": 2, "failure": 1, "timeout": 0}`
- `document_verification`: `{"verified": 6, "mismatch": 0, "unreadable": 0}`

These counters reset when the backend process restarts; re-run the [demo runbook](./DEMO_RUNBOOK.md) to regenerate live evidence.

## Reproducible deployment check

```bash
docker compose config
docker compose up --build -d
```

Postgres is internal-only; API and UI are published on 8080 / 5174.
