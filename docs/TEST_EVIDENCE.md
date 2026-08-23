# Test and measurement evidence

Numbers below are from **actual** repository commands and runtime checks executed during final submission preparation. Do not treat placeholders as measurements.

## Automated test suite — backend

Commands (from `backend/`):

```bash
pytest -q
ruff check app tests
```

**Result:** **238 passed** (`pytest -q`), **ruff: all checks passed**.

### Test count by module

| Module | Tests | Concern |
|--------|-------|---------|
| `tests/test_p3_channels.py` | 54 | Channels, envelope, i18n, NLU, STT/TTS, resume, metrics, audit safety, full text journey to `SUBMITTED` |
| `tests/test_speech_mobile.py` | 51 | Spoken mobile-number normalization (digit words, separators, noise) |
| `tests/test_speech_otp.py` | 30 | Spoken OTP normalization and rejection of malformed input |
| `tests/test_consent_voice.py` | 23 | Consent recognition via voice/NLU, including browser-transcript regressions |
| `tests/test_journey.py` | 16 | Auth, consent, form capture, documents, correction, submission, access isolation |
| `tests/test_voice_field_confirmation.py` | 14 | Voice-only `FIELD_CONFIRMATION` accept/retry behaviour |
| `tests/test_gateway.py` | 11 | Data Boundary Gateway deny, zero cloud HTTP, audit safety |
| `tests/test_payment_officer_workflow.py` | 10 | Fee/payment outcomes, receipt, officer RBAC, correction + resubmit |
| `tests/test_classification.py` | 7 | Fail-closed classification and label merging |
| `tests/test_platform.py` | 6 | Audit append-only, log redaction, health/ready |
| `tests/test_state_machine.py` | 5 | Allowed/rejected transitions and recovery paths |
| `tests/test_languages_config.py` | 4 | Language catalogue loading (`en`, `hi`, `kn`) and alias resolution |
| `tests/test_document_verification_workflow.py` | 4 | Local mock OCR/verification outcomes and rejection handling |
| `tests/test_policy.py` | 2 | Policy fail-closed on unknown destination/classification |
| `tests/test_voice_journey_smoke.py` | 1 | Browser-equivalent voice journey: language → mobile → OTP → consent → service → field confirmation |
| **Total** | **238** | |

### Negative / recovery cases exercised in tests

- Invalid OTP → `AUTH_FAILED` with retry
- Unrecognised spoken mobile number → retry prompt, no state advance
- Invalid field formats stay in capture state
- Document MIME/size rejection and verification `MISMATCH` / `UNREADABLE`
- Payment `FAILURE` and `TIMEOUT` with safe retry
- Invalid state transitions rejected
- Citizen cannot call officer APIs without officer token
- Restricted → cloud evaluated as **denied**; cloud stub call count remains 0
- Audit metadata omits raw OTP / restricted field values / transcripts
- Unclear consent phrasing does not silently grant consent

## Automated test suite — frontend

Commands (from `frontend/`):

```bash
npm run typecheck
npm run lint
npm test
npm run build
```

**Results:**

| Gate | Result |
|------|--------|
| `npm run typecheck` (`tsc --noEmit`) | pass, no errors |
| `npm run lint` (`eslint .`) | pass, no errors |
| `npm test` (`vitest run`) | **11 passed** across 2 files |
| `npm run build` (`tsc --noEmit && vite build`) | pass, 45 modules transformed |

| Test file | Tests | Concern |
|-----------|-------|---------|
| `src/journey/actions.test.ts` | 5 | Composer/payment/field-confirmation/terminal state gating |
| `src/journey/form.test.ts` | 6 | Draft mapping, required-field detection, backend value formatting |

Frontend coverage is unit-level over journey helper logic. Component and browser end-to-end tests are **not** part of this POC; journey behaviour is covered by the backend channel tests listed above.

## Runtime endpoints

With Compose up (host ports **8080** API / **5174** UI):

| Check | Endpoint | Observed |
|-------|----------|----------|
| Liveness | `GET /api/v1/health` | `{"status":"ok","service":"Multilingual Voice-First Revenue Services Platform","version":"0.1.0","environment":"development"}` |
| Readiness (DB) | `GET /api/v1/ready` | `{"status":"ready","checks":{"database":"ok"}}` |
| Language catalogue | `GET /api/v1/languages` | `default: en`; `en` English, `hi` हिन्दी, `kn` ಕನ್ನಡ |
| Metrics snapshot | `GET /api/v1/metrics` | See measured sample below |

## Metrics

### Fields available in code

`sessions_by_channel`, `sessions_by_language`, `stt_success` / `stt_failure`, `nlu_success` / `nlu_failure`, `channel_errors`, `escalations`, `corrections`, `payments.{success,failure,timeout}`, `document_verification.{verified,mismatch,unreadable}`, `status_distribution`, `latency_ms.{count,avg,p50}`.

**Latency note:** `latency_ms` is populated only when STT paths record timing in the orchestrator. A text-only run leaves it at `count: 0`. Values depend on live traffic after process start; they are not hard-coded. Report the JSON returned by `/api/v1/metrics` during the demo rather than inventing figures.

### Measured sample (same Compose process)

Measured after running two complete text-modality applications against `localhost:8080` — one happy path (`PAY` → `PAY`) and one payment-failure recovery (`PAY` → `FAIL` → `RETRY` → `PAY`), each uploading the three clean sample documents. Both reached `SUBMITTED` / `UNDER_REVIEW`.

```json
{
  "sessions_by_channel": {"web": 6},
  "sessions_by_language": {},
  "stt_success": 0,
  "stt_failure": 0,
  "nlu_success": 26,
  "nlu_failure": 23,
  "channel_errors": 0,
  "escalations": 0,
  "corrections": 0,
  "payments": {"success": 2, "failure": 1, "timeout": 0},
  "document_verification": {"verified": 6, "mismatch": 0, "unreadable": 0},
  "status_distribution": {"UNDER_REVIEW": 2},
  "latency_ms": {"count": 0, "avg": null, "p50": null}
}
```

Reading this sample honestly:

- `stt_success` is `0` because the runs used text modality; voice runs increment it.
- `sessions_by_language` is empty because a session is recorded at channel start, before the citizen picks a language.
- `nlu_failure` counts low-confidence rule-NLU parses (free-text field answers such as an address), not journey errors — `channel_errors` stayed at `0`.

These counters reset when the backend process restarts; re-run the [demo runbook](./DEMO_RUNBOOK.md) to regenerate live evidence.

## Citizen-facing authentication check

Verified against the running stack that successful OTP authentication returns the localized `auth_success` prompt and **no synthetic persona identity**:

| Language | Message returned at `CONSENT` |
|----------|-------------------------------|
| `en` | `Authenticated successfully.` |
| `hi` | `प्रमाणीकरण सफल रहा।` |
| `kn` | `ಪ್ರಾಮಾಣೀಕರಣ ಯಶಸ್ವಿಯಾಗಿದೆ.` |

Persona names, mobiles, and OTPs remain in `config/seed/personas.yaml` and the demo runbook only. The audit trail records the opaque `persona_id` as `actor_id`; OTP values are never logged or returned.

## Local TTS (eSpeak NG)

Citizen prompts are synthesized **offline** with **eSpeak NG** inside the backend container (`apt` package `espeak-ng`). Languages: `en`, `hi`, `kn` via application `tts_code` mapped inside the TTS provider. Cloud TTS is disabled (`config/providers/providers.yaml`).

- Quality is lightweight / robotic formant synthesis — suitable for a POC, not neural natural speech.
- `MockTTSProvider` (tone WAV) remains available for unit tests that inject a TTS backend.
- If eSpeak is configured but missing at runtime, the API returns a citizen-safe 503 — it does **not** silently fall back to the mock tone.

## Reproducible deployment check

```bash
docker compose config
docker compose up --build -d
```

Postgres is internal-only; API and UI are published on 8080 / 5174.
