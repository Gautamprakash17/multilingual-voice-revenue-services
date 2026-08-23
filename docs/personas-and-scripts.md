# Synthetic personas and multilingual scripts

All personas are **synthetic**. They are not real citizens. OTPs are fixed for reproducible demos.

Source: `config/seed/personas.yaml` (loaded by `MockIdentityProvider`).

Language is selected per session/application (not stored on the persona). The same citizen credentials can be used with English, Hindi, or Kannada.

## Personas

| Persona ID | Name | Mobile | OTP |
|------------|------|--------|-----|
| persona-lakshmi | Lakshmi Devi | 9876543210 | 123456 |
| persona-ramesh | Ramesh Kumar | 9123456780 | 654321 |
| persona-anita | Anita Sharma | 9988776655 | 112233 |
| persona-Gautam | Gautam Prakash | 7204609155 | 123456 |

## Languages

Prompt bundles: `config/i18n/{en,hi,kn}.yaml`
Catalog: `config/languages.yaml`
Service languages: `config/services/income_certificate.yaml` → `en`, `hi`, `kn`.

## Sample conversational script (Income Certificate, English)

Use Lakshmi’s credentials with any selected language for demo simplicity.

| Step | Citizen input | Expected system behaviour |
|------|---------------|---------------------------|
| Start | (UI Start) | Application id `INC-…`, language prompt |
| Language | `en` | Auth mobile prompt |
| Mobile | `9876543210` | OTP prompt |
| OTP | `123456` | Consent prompt |
| Consent | YES / I agree | Service select |
| Service | `INCOME_CERTIFICATE` | First form field |
| Fields | name, DOB `12/04/1995`, mobile, address, district, income, source | Document capture |
| Documents | Upload three proofs | Review |
| Review | `CONFIRM` | Fee quote |
| Fee | `PAY` | Payment prompt |
| Pay | `PAY` | Submitted + receipt |
| Status | Refresh / STATUS | `UNDER_REVIEW` / receipt id |

### Hindi / Kannada

Select `hi` or `kn` at language select. Prompts switch via i18n bundles. Field validation rules remain the same (catalogue-driven). Authentication identity is unchanged.

### Voice (web)

Use the Apply page voice control. The POC STT path accepts local/mock transcripts; restricted audio is not sent to cloud.

### WhatsApp / IVR simulators

Same application engine via channel envelope. Typical IVR: DTMF for language/yes-no; WhatsApp sim: text turns. Resume with `POST /api/v1/channels/resume`.

## Negative script snippets

| Scenario | Input | Recovery |
|----------|-------|----------|
| Bad OTP | `000000` | `AUTH_FAILED` → RETRY |
| Invalid date | `99/99/9999` | Stay in form; validation message |
| Doc mismatch | filename contains `mismatch` | `DOCUMENT_REJECTED` → RETRY |
| Payment fail | `FAIL` | `PAYMENT_FAILED` → RETRY/PAY |
| Payment timeout | `TIMEOUT` | Parked → RETRY |
| Escalate | `HELP` / `ESCALATE` | `ESCALATED` + officer visibility |
