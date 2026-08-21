# Document samples (POC)

Restricted document **bytes** are stored only on the local document volume at runtime (`DOCUMENT_STORAGE_PATH`). This folder provides **safe synthetic placeholders** for demos and naming conventions for verification outcomes.

## Catalogue requirements

From `config/services/income_certificate.yaml`:

| Code | Purpose | Allowed types | Max size |
|------|---------|---------------|----------|
| IDENTITY_PROOF | Identity proof | PDF, JPEG, PNG | 5 MiB |
| ADDRESS_PROOF | Address proof | PDF, JPEG, PNG | 5 MiB |
| INCOME_PROOF | Income proof | PDF, JPEG, PNG | 5 MiB |

## Verification outcomes (mock OCR / verifier)

Deterministic adapters in `backend/app/adapters/documents.py`:

| Filename marker | Outcome | Journey effect |
|-----------------|---------|----------------|
| (none / normal name) | `VERIFIED` | Continue |
| contains `mismatch` | `MISMATCH` | `DOCUMENT_REJECTED` → RETRY |
| contains `unreadable` or `corrupt` | `UNREADABLE` | `DOCUMENT_REJECTED` → RETRY |

Classification remains **`RESTRICTED`**. Document bytes are never sent to cloud (gateway deny + tests).

## Sample files in this repository

Located under `config/samples/documents/`:

| File | Use |
|------|-----|
| `identity_proof_ok.pdf` | Happy-path identity upload |
| `address_proof_ok.pdf` | Happy-path address upload |
| `income_proof_ok.pdf` | Happy-path income upload |
| `identity_proof_mismatch.pdf` | Verification mismatch demo |
| `identity_proof_unreadable.pdf` | Unreadable demo |

These are minimal synthetic PDF placeholders (not real IDs). Do not treat them as government documents.

## Upload during demo

Citizen Apply UI → document state → choose code → select one of the sample files above.
