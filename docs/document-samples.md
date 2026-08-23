# Document samples (POC)

Restricted document **bytes** are stored only on the local document volume at runtime (`DOCUMENT_STORAGE_PATH`). This folder provides **safe synthetic placeholders** for demos and naming conventions for **local mock** verification outcomes.

Verification is **not** real OCR and does **not** compare file contents to application form fields. Outcomes are determined by filename markers in `backend/app/adapters/documents.py`.

## Catalogue requirements

From `config/services/income_certificate.yaml`:

| Code | Purpose | Allowed types | Max size |
|------|---------|---------------|----------|
| IDENTITY_PROOF | Identity proof | PDF, JPEG, PNG | 5 MiB |
| ADDRESS_PROOF | Address proof | PDF, JPEG, PNG | 5 MiB |
| INCOME_PROOF | Income proof | PDF, JPEG, PNG | 5 MiB |

## Verification outcomes (local mock OCR / verifier)

| Filename marker | Outcome | Citizen-facing label | Journey effect |
|-----------------|---------|----------------------|----------------|
| (none / normal name, e.g. `*_ok.pdf`) | `VERIFIED` | Verification passed · Local POC | Continue |
| contains `mismatch` | `MISMATCH` | Verification failed · Details do not match | `DOCUMENT_REJECTED` → RETRY |
| contains `unreadable` or `corrupt` | `UNREADABLE` | Verification failed · Document unreadable | `DOCUMENT_REJECTED` → RETRY |

Classification remains **`RESTRICTED`**. Document bytes are never sent to cloud (gateway deny + tests).

## Sample files in this repository

Located under `config/samples/documents/`:

| File | Use |
|------|-----|
| `identity_proof_ok.pdf` | Happy-path identity upload → VERIFIED |
| `address_proof_ok.pdf` | Happy-path address upload → VERIFIED |
| `income_proof_ok.pdf` | Happy-path income upload → VERIFIED |
| `identity_proof_mismatch.pdf` | Mismatch demo → MISMATCH |
| `identity_proof_unreadable.pdf` | Unreadable demo → UNREADABLE |

These are minimal synthetic PDF placeholders (not real IDs). Do not treat them as government documents.

## Upload during demo

Citizen Apply UI → document state → choose code → select one of the sample files above.
