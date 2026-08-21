# Data Classification Design

This document is a mandatory POC deliverable: **mock government/citizen data stays local**.

## Labels

| Classification | Meaning | Cloud egress |
|----------------|---------|--------------|
| `RESTRICTED` | Citizen identity, application fields, documents, raw audio | **DENY always** |
| `INTERNAL` | Sessions, metrics, operational state | **DENY** (local by default) |
| `PUBLIC_SAFE` | Approved non-sensitive / synthetic content | ALLOW only with explicit approval + allowed purpose |

## Fail-closed rules

1. Missing classification → `RESTRICTED`
2. Unknown classification string → `RESTRICTED`
3. Merge of multiple labels → most restrictive wins (`RESTRICTED` + `PUBLIC_SAFE` = `RESTRICTED`)
4. Unknown destination or missing policy → DENY
5. `PUBLIC_SAFE` → cloud requires `approved=true` and purpose on the policy allowlist

## Enforcement

- Classification helpers: `backend/app/boundary/classification.py`
- Policy file: `config/boundary/policies.yaml`
- Gateway: `backend/app/boundary/gateway.py` — sole decision point
- Audit: every allow/deny is recorded; **raw restricted payloads are never stored** in audit metadata (keys/counts only)
- Cloud provider implementations in the current POC are **stubs** that make **zero external HTTP calls**

## Proof for judges

Automated tests assert:

- restricted → cloud denied
- denied requests make zero HTTP calls
- audit events omit restricted values
- unknown policy/destination fails closed
