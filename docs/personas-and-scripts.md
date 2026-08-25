# Synthetic personas and multilingual scripts

All personas are **synthetic**. They are not real citizens.

Source: `config/seed/personas.yaml` (loaded by `MockIdentityProvider`).

OTP is generated dynamically per login/registration challenge and delivered only through the local phone simulator. Personas do not store a fixed OTP.

Language is selected per session/application (not stored on the persona). The same citizen credentials can be used with English, Hindi, or Kannada.

## Personas

| Persona ID | Name | Mobile |
|------------|------|--------|
| persona-lakshmi | Lakshmi Devi | 9876543210 |
| persona-ramesh | Ramesh Kumar | 9123456780 |
| persona-anita | Anita Sharma | 9988776655 |
| persona-gautam | Gautam Prakash | 7204609155 |

Unknown valid 10-digit numbers follow the **new citizen registration** flow, then become existing synthetic citizens for the rest of the demo.

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
| Mobile | `9876543210` | OTP prompt + local phone simulator |
| OTP | generated 6-digit code from the phone simulator | Consent prompt |
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
| Bad OTP | wrong 6-digit code | Stay in authenticate; new OTP after 3 failures |
| Invalid date | `99/99/9999` | Stay in form; validation message |
| Doc mismatch | filename contains `mismatch` | `DOCUMENT_REJECTED` → RETRY |
| Payment fail | `FAIL` | `PAYMENT_FAILED` → RETRY/PAY |
| Payment timeout | `TIMEOUT` | Parked → RETRY |
| Escalate | `HELP` / `ESCALATE` | `ESCALATED` + officer visibility |
