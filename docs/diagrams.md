# Architecture diagrams and key sequences

Hackathon POC — Multilingual Voice-First Revenue Services Platform.

Companion to [architecture.md](./architecture.md). Diagrams use Mermaid for judge review.

## C4 — System context

```mermaid
C4Context
    title System context — Revenue Voice Services POC
    Person(citizen, "Citizen", "Applies for certificates via voice or text")
    Person(officer, "Revenue officer", "Reviews, corrects, approves, escalates")
    System(poc, "Revenue Voice Services POC", "Modular monolith: journey, channels, boundary gateway")
    System_Ext(wa, "WhatsApp (simulated)", "Not a live WhatsApp Business account")
    System_Ext(ivr, "IVR / telephony (simulated)", "Not live PSTN")
    System_Ext(cloud, "Optional cloud AI stub", "Only PUBLIC_SAFE + approved; restricted always blocked")
    Rel(citizen, poc, "Web / WhatsApp sim / IVR sim")
    Rel(officer, poc, "Officer dashboard + RBAC token")
    Rel(poc, wa, "Simulator adapter")
    Rel(poc, ivr, "Simulator adapter")
    Rel(poc, cloud, "Data Boundary Gateway (fail-closed)")
```

## C4 — Containers (modular monolith)

```mermaid
C4Container
    title Containers — single deployable stack
    Person(citizen, "Citizen")
    Person(officer, "Officer")
    System_Boundary(poc, "Docker Compose POC") {
        Container(ui, "React frontend", "Vite", "Journey, officer, channel simulators")
        Container(api, "FastAPI backend", "Python", "APIs, orchestrator, journey, gateway")
        ContainerDb(db, "PostgreSQL", "SQL", "Applications, sessions, documents metadata, audit, payments, receipts")
        Container(docs, "Local document volume", "Filesystem", "RESTRICTED document bytes")
    }
    Rel(citizen, ui, "HTTPS")
    Rel(officer, ui, "HTTPS")
    Rel(ui, api, "REST /api/v1")
    Rel(api, db, "SQLAlchemy")
    Rel(api, docs, "Local write/read")
```

## Trust zones and data boundary

```mermaid
flowchart TB
  subgraph zoneA [Trust Zone A — Local]
    CH[Channel adapters]
    OR[Orchestrator]
    JY[Journey / officer services]
    GW[Data Boundary Gateway]
    LP[Local STT / NLU / TTS / OCR / payment mocks]
    PG[(Postgres + audit)]
    FS[Local document store]
  end
  subgraph zoneB [Trust Zone B — Optional cloud stub]
    CL[OptionalCloudProvider — no unrestricted HTTP]
  end
  CH --> OR --> JY
  JY --> GW
  GW -->|RESTRICTED / INTERNAL| LP
  GW -->|PUBLIC_SAFE + approved only| CL
  JY --> PG
  JY --> FS
```

## Sequence — data-boundary deny (restricted → cloud)

```mermaid
sequenceDiagram
  participant S as Service
  participant G as Data Boundary Gateway
  participant P as Policy Engine
  participant A as Audit
  participant C as Cloud stub
  S->>G: evaluate(RESTRICTED, destination=cloud)
  G->>P: match policy
  P-->>G: DENY (fail-closed)
  G->>A: BOUNDARY_DENY (safe metadata only)
  G-->>S: allowed=false
  Note over C: Zero HTTP calls
```

## Sequence — authentication and consent

```mermaid
sequenceDiagram
  participant U as Citizen
  participant API as Journey / Channel API
  participant J as JourneyService
  participant ID as MockIdentityProvider
  U->>API: start application
  API->>J: LANGUAGE_SELECT
  U->>API: language (en/hi/kn)
  U->>API: mobile number
  J->>ID: request OTP (seeded persona)
  U->>API: OTP
  ID-->>J: success / AUTH_FAILED
  U->>API: consent YES
  J-->>U: SERVICE_SELECT
```

## Sequence — voice form capture (web)

```mermaid
sequenceDiagram
  participant U as Citizen (voice)
  participant UI as Web UI
  participant OR as ChannelOrchestrator
  participant STT as Mock/Local STT
  participant NLU as LocalRuleNLU
  participant J as JourneyService
  U->>UI: record / push-to-talk
  UI->>OR: modality=voice + audio marker
  OR->>STT: transcribe (local)
  STT-->>OR: transcript
  OR->>NLU: intent/slots (optional)
  OR->>J: handle_message(text)
  J-->>OR: prompt + state
  OR-->>UI: text (+ optional TTS audio)
```

## Sequence — document verification

```mermaid
sequenceDiagram
  participant U as Citizen
  participant API as Journey API
  participant D as Document service
  participant O as Mock OCR
  participant V as Mock verifier
  participant G as Gateway
  U->>API: upload document (RESTRICTED)
  API->>G: prove cloud OCR blocked
  API->>D: store locally
  D->>O: extract (filename/metadata)
  D->>V: VERIFIED / MISMATCH / UNREADABLE
  alt MISMATCH or UNREADABLE
    API-->>U: DOCUMENT_REJECTED + RETRY
  else VERIFIED and all docs present
    API-->>U: REVIEW_CONFIRM
  end
```

## Sequence — payment and failure recovery

```mermaid
sequenceDiagram
  participant U as Citizen
  participant J as JourneyService
  participant P as MockPaymentProvider
  U->>J: CONFIRM review
  J-->>U: FEE_QUOTE
  U->>J: PAY
  J-->>U: PAYMENT
  alt SUCCESS
    J->>P: charge(SUCCESS)
    J-->>U: SUBMITTED + receipt
  else FAILURE
    J->>P: charge(FAILURE)
    J-->>U: PAYMENT_FAILED (RETRY)
  else TIMEOUT
    J->>P: charge(TIMEOUT)
    J-->>U: parked PAYMENT_FAILED (RETRY)
  end
```

## Sequence — cross-channel resume

```mermaid
sequenceDiagram
  participant U as Citizen
  participant W as Web session
  participant WA as WhatsApp simulator
  participant API as Resume API
  participant DB as Postgres
  U->>W: start + authenticate (session token)
  W->>DB: ConversationSession persisted
  U->>API: POST /channels/resume (application_id + token, channel=whatsapp)
  API->>DB: bind / continue state
  API-->>WA: same application_id + current state
```

## Sequence — correction and officer escalation

```mermaid
sequenceDiagram
  participant C as Citizen
  participant O as Officer
  participant API as APIs
  participant J as Journey / Officer services
  C->>API: submit after payment
  API->>J: processing_status=UNDER_REVIEW
  O->>API: request-correction (target fields)
  API->>J: NEEDS_CORRECTION + CORRECTION state
  C->>API: correct field → CONFIRM (payment already done)
  O->>API: approve
  API->>J: APPROVED → ISSUED
  Note over O,API: escalate sets escalated flag / queue visibility
```

## Journey state machine (citizen conversational path)

```mermaid
stateDiagram-v2
  [*] --> LANGUAGE_SELECT
  LANGUAGE_SELECT --> AUTHENTICATE
  AUTHENTICATE --> CONSENT
  AUTHENTICATE --> AUTH_FAILED
  AUTH_FAILED --> AUTHENTICATE
  CONSENT --> SERVICE_SELECT
  SERVICE_SELECT --> FORM_CAPTURE
  FORM_CAPTURE --> DOCUMENT_CAPTURE
  DOCUMENT_CAPTURE --> REVIEW_CONFIRM
  DOCUMENT_CAPTURE --> DOCUMENT_REJECTED
  DOCUMENT_REJECTED --> DOCUMENT_CAPTURE
  REVIEW_CONFIRM --> FEE_QUOTE
  REVIEW_CONFIRM --> CORRECTION
  FEE_QUOTE --> PAYMENT
  PAYMENT --> SUBMITTED
  PAYMENT --> PAYMENT_FAILED
  PAYMENT_FAILED --> PAYMENT
  CORRECTION --> FORM_CAPTURE
  SUBMITTED --> CORRECTION: officer reopen
```
