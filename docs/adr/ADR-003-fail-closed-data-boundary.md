# ADR-003: Fail-Closed Data Boundary

**Status:** Accepted
**Context:** Sovereignty scoring requires enforced isolation, not convention.

**Decision:**

- Unlabeled/unknown data = `RESTRICTED`
- Policy engine DENYs missing/unknown rules
- Gateway hard-denies non-cloud-eligible classifications before provider invocation
- Every decision is audited without storing restricted payload values

**Consequences:** Stronger demo proof and safer defaults. Slightly more rejections until content is explicitly approved — acceptable for a government-facing POC.
