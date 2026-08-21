# ADR-001: Modular Monolith

**Status:** Accepted  
**Context:** Hackathon POC with limited time; problem asks for modular, scalable architecture without unnecessary platform engineering.

**Decision:** Implement a single FastAPI deployable with clear internal packages (`api`, `core`, `boundary`, `platform`, `models`). No microservices, Kubernetes, or message buses.

**Consequences:** Faster local setup and demos; module boundaries remain extractable later if needed. Avoids distributed-system overhead that does not score marks in this POC.
