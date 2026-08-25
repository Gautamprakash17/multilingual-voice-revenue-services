# Architecture diagrams and key sequences

Hackathon POC — Multilingual Voice-First Revenue Services Platform.

Companion to [architecture.md](./architecture.md). Diagrams use Mermaid and reflect the **current codebase** (simulators, mock providers, local STT/TTS, shared Application identity).

## A. System context

```mermaid
flowchart LR
  Citizen[Citizen]
  Officer[Revenue officer]

  subgraph Channels[Citizen channels]
    Web[Web Apply]
    WA[WhatsApp simulator]
    IVR[IVR simulator]
  end

  Backend[Revenue Services backend<br/>modular monolith]
  Cert[Issued certificate PDF<br/>DEMO / POC]
  Notif[Simulated notifications<br/>SMS / WA / email inbox]

  Citizen --> Web
  Citizen --> WA
  Citizen --> IVR
  Web --> Backend
  WA --> Backend
  IVR --> Backend
  Officer --> Backend
  Backend --> Cert
  Backend --> Notif
  Notif --> WA
  Notif --> Citizen
  Cert --> Citizen
  Cert --> Officer
```

Notes: WhatsApp and IVR are **simulators**, not live Meta WhatsApp or PSTN. Notifications are **local/simulated**.

---

## B. Container architecture

```mermaid
flowchart TB
  subgraph UI[React frontend]
    Pages[Journey / WhatsApp / IVR / Officer]
    PhoneSim[PhoneSimulator inbox]
  end

  subgraph API[FastAPI /api/v1]
    Routes[Journey · Channels · Officer · Demo]
  end

  subgraph ChannelLayer[Channel layer]
    Adapters[Web / WhatsApp / IVR adapters]
    Orch[ChannelOrchestrator]
  end

  subgraph Services[Application services]
    Journey[JourneyService]
    OfficerSvc[OfficerService]
    Notify[NotificationService]
    Docs[Documents · Receipts]
    CertSvc[Certificate PDF]
  end

  subgraph Providers[Local providers]
    STT[faster-whisper STT]
    TTS[eSpeak NG TTS]
    NLU[Rule NLU]
    Mocks[Mock OTP · OCR · Payment · Notify]
  end

  GW[Data Boundary Gateway]
  PG[(PostgreSQL)]
  FS[Local document storage]

  Pages --> Routes
  PhoneSim --> Routes
  Routes --> Adapters --> Orch
  Orch --> Journey
  Orch --> STT
  Orch --> TTS
  Orch --> NLU
  Routes --> OfficerSvc
  Journey --> Docs
  OfficerSvc --> CertSvc
  Journey --> Notify
  OfficerSvc --> Notify
  Journey --> GW
  Docs --> GW
  GW --> Mocks
  Journey --> PG
  Notify --> PG
  Docs --> FS
  CertSvc --> FS
```

---

## C. Shared application journey

```mermaid
flowchart TB
  Web[Web channel]
  WA[WhatsApp simulator]
  IVR[IVR simulator]
  App[Application<br/>Application ID INC-xxxx]
  S1[ConversationSession · web]
  S2[ConversationSession · whatsapp]
  S3[ConversationSession · ivr]

  Web --> App
  WA --> App
  IVR --> App
  Web --> S1
  WA --> S2
  IVR --> S3
  S1 --> App
  S2 --> App
  S3 --> App
```

- **Start** creates one Application + first session.  
- **Resume** creates/uses a session for the target channel on the **same** Application.  
- Messages update shared journey state, form data, documents, and payment.

---

## D. Resume / handoff

```mermaid
sequenceDiagram
  participant C as Citizen
  participant UI as Channel UI
  participant SS as sessionStorage handoff
  participant API as POST /channels/resume
  participant DB as Postgres

  Note over C,DB: Same Application ID · token stays inside browser/backend
  C->>UI: Start on Web or IVR
  UI->>DB: Application + ConversationSession + access_token
  UI->>SS: storeSessionHandoff(applicationId, accessToken)
  C->>UI: Continue on WhatsApp
  UI->>SS: lookupSessionHandoff(applicationId)
  alt Token found in this browser
    UI->>API: application_id + X-Session-Token + channel=whatsapp
    API->>DB: New/bound ConversationSession for WhatsApp
    API-->>UI: Same application_id + current journey state
  else No handoff in this browser
    UI-->>C: Same-browser session required (no token field shown)
  end
```

Application ID alone is **not** authentication. Cross-device resume without a prior token is **not** supported.

---

## E. IVR — DTMF and voice

```mermaid
flowchart LR
  subgraph DTMF[DTMF path]
    Key[On-screen / physical keypad]
    Buf[Digit buffer · auto-submit]
    Map[Backend DTMF → journey tokens]
  end

  subgraph Voice[Voice path]
    Mic[Browser microphone]
    Enc[WAV mono 16 kHz base64]
    STT[Local faster-whisper STT]
    Tr[Transcript]
  end

  Journey[JourneyService]

  Key --> Buf --> Map --> Journey
  Mic --> Enc --> STT --> Tr --> Journey
```

Field confirmation on IVR: **Press 1 = Confirm · Press 2 = Change** (not `#` / `*`).  
Menus (language, consent, register, service, pay) use single-digit DTMF. Mobile (10) and OTP (6) auto-submit when complete. Free-form fields use voice.

---

## F. Officer review

```mermaid
flowchart TB
  Submit[Citizen payment success]
  UR[processing UNDER_REVIEW<br/>journey SUBMITTED]
  Officer[Officer Portal]

  Corr[Request correction]
  NC[NEEDS_CORRECTION + journey CORRECTION]
  NotifC[Simulated notification]
  CitizenFix[Citizen corrects · resubmits]
  Back[UNDER_REVIEW again]

  Approve[Approve and issue]
  PDF[DEMO PDF ISSUED_CERTIFICATE]
  Issued[processing ISSUED]
  NotifI[Simulated notification]

  Reject[Reject]
  Rej[processing REJECTED]
  NotifR[Simulated notification]

  Submit --> UR --> Officer
  Officer --> Corr --> NC --> NotifC --> CitizenFix --> Back --> Officer
  Officer --> Approve --> PDF --> Issued --> NotifI
  Officer --> Reject --> Rej --> NotifR
```

Escalate sets an escalated flag (and may move journey to `ESCALATED` when the state machine allows). The officer always acts on the **same** Application.

---

## G. Certificate issuance

```mermaid
sequenceDiagram
  participant O as Officer
  participant API as Officer API
  participant OS as OfficerService
  participant PDF as Certificate renderer
  participant FS as Document store
  participant DB as Postgres
  participant N as NotificationService
  participant C as Citizen

  O->>API: POST /officer/{id}/approve + X-Officer-Token
  API->>OS: approve
  OS->>PDF: render_income_certificate_pdf
  Note over PDF: DEMO / POC — not official
  OS->>FS: store ISSUED_CERTIFICATE PDF
  OS->>DB: processing_status = ISSUED
  OS->>N: notify_status ISSUED
  N->>DB: citizen_notifications row
  C->>API: GET journey documents/ISSUED_CERTIFICATE + X-Session-Token
  API-->>C: PDF bytes
```

Re-approve when already `ISSUED` is idempotent (reuse PDF). Application ID alone cannot download.

---

## H. Notification flow

```mermaid
flowchart TB
  Trans[Status transition<br/>submit / officer action]
  NS[NotificationService]
  Mock[MockSmsProvider<br/>MockWhatsAppProvider<br/>MockEmailProvider]
  Table[(citizen_notifications)]
  API[GET /demo/notifications]
  Inbox[PhoneSimulator / WhatsApp notice bubbles]

  Trans --> NS --> Mock --> Table --> API --> Inbox
```

Events implemented: `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_CORRECTION`, `ISSUED`, `REJECTED`.  
Delivery is **simulated** (`delivery_status=simulated`). Cycle-based deduplication skips repeats until a break event (`NEEDS_CORRECTION` / `ISSUED` / `REJECTED`).

---

## Trust zones and data boundary

```mermaid
flowchart TB
  subgraph zoneA [Trust Zone A — Local]
    CH[Channel adapters]
    OR[Orchestrator]
    JY[Journey / officer / notifications]
    GW[Data Boundary Gateway]
    LP[Local STT / NLU / TTS / OCR / payment / notify mocks]
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

---

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
  P-->>G: DENY fail-closed
  G->>A: BOUNDARY_DENY safe metadata only
  G-->>S: allowed=false
  Note over C: Zero HTTP calls
```

---

## Sequence — authentication and consent

```mermaid
sequenceDiagram
  participant U as Citizen
  participant API as Journey / Channel API
  participant J as JourneyService
  participant ID as MockIdentityProvider
  U->>API: start application
  API->>J: LANGUAGE_SELECT
  U->>API: language en/hi/kn
  U->>API: mobile number
  alt Known seeded persona
    J->>ID: request OTP
    U->>API: OTP
    ID-->>J: success
  else Unknown mobile
    J-->>U: register_offer
    U->>API: Register / another number
    U->>API: OTP + registration name
    ID-->>J: SyntheticCitizen created
  end
  U->>API: consent YES
  J-->>U: SERVICE_SELECT
```

---

## Sequence — voice form capture (web)

```mermaid
sequenceDiagram
  participant U as Citizen mic
  participant UI as Web UI
  participant OR as ChannelOrchestrator
  participant STT as Local faster-whisper / MockSTT
  participant NLU as LocalRuleNLU
  participant J as JourneyService
  U->>UI: Speak — MediaRecorder → WAV base64
  UI->>OR: modality=voice + audio_b64
  OR->>STT: transcribe local ephemeral
  STT-->>OR: transcript
  OR->>NLU: optional intent/slots
  OR->>J: handle_message text
  alt Needs confirmation
    J-->>OR: FIELD_CONFIRMATION
  else Accepted
    J-->>OR: next field or DOCUMENT_CAPTURE
  end
  OR-->>UI: text + optional TTS audio_b64
```

Audio is **not** stored durably after STT.

---

## Sequence — document verification

```mermaid
sequenceDiagram
  participant U as Citizen
  participant API as Journey API
  participant D as Document service
  participant O as Mock OCR
  participant V as Mock verifier
  participant G as Gateway
  U->>API: upload document RESTRICTED
  API->>G: prove cloud OCR blocked
  API->>D: store locally
  D->>O: extract filename/metadata markers
  D->>V: VERIFIED / MISMATCH / UNREADABLE
  alt MISMATCH or UNREADABLE
    API-->>U: DOCUMENT_REJECTED + retry
  else VERIFIED and all docs present
    API-->>U: REVIEW_CONFIRM
  end
```

---

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
    J->>P: charge SUCCESS
    J-->>U: journey SUBMITTED + processing UNDER_REVIEW + receipt
  else FAILURE
    J->>P: charge FAILURE
    J-->>U: PAYMENT_FAILED RETRY
  else TIMEOUT
    J->>P: charge TIMEOUT
    J-->>U: PAYMENT_FAILED RETRY
  end
```

---

## Journey state machine (citizen conversational path)

```mermaid
stateDiagram-v2
  [*] --> LANGUAGE_SELECT
  LANGUAGE_SELECT --> AUTHENTICATE
  AUTHENTICATE --> CONSENT
  AUTHENTICATE --> AUTH_FAILED
  AUTHENTICATE --> FIELD_CONFIRMATION: voice field confirm path
  AUTH_FAILED --> AUTHENTICATE
  CONSENT --> SERVICE_SELECT
  SERVICE_SELECT --> FORM_CAPTURE
  FORM_CAPTURE --> FIELD_CONFIRMATION
  FIELD_CONFIRMATION --> FORM_CAPTURE
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
  CORRECTION --> DOCUMENT_CAPTURE
  SUBMITTED --> CORRECTION: officer reopen
```

Processing after successful payment: **`UNDER_REVIEW`** (officer queue), then officer outcomes `NEEDS_CORRECTION` / `ISSUED` / `REJECTED`.
