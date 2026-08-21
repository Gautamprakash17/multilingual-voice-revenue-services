# ADR-002: Local-First Data Processing

**Status:** Accepted  
**Context:** Problem requires separating restricted local processing from optional cloud speech/AI, and proving mock citizen/government data is not sent to public cloud.

**Decision:** Default `PROVIDER_MODE=local` and `CLOUD_AI_ENABLED=false`. Local providers process data in-process. Any future cloud provider may only be invoked through the Data Boundary Gateway after policy ALLOW. External cloud AI is optional and is not a dependency of the current POC.

**Consequences:** Fully on-premise-ready demo path. Cloud remains a gated option for approved `PUBLIC_SAFE` content only.
