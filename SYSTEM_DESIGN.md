# System design — React stack

End-to-end workflow for the AI Company Knowledge Assistant.

Every diagram below reflects the code as it stands, not an intended design.
Where a decision has a non-obvious reason, the reason is stated — those are
usually the parts that look wrong until you know why.

Diagrams are [Mermaid](https://mermaid.js.org/); GitHub renders them inline.

---

## 1. What the system is

An administrator curates **one shared knowledge base**. End users ask questions
and receive answers drawn only from that corpus, with citations. End users never
see documents, embeddings, or any sign that retrieval is happening.

```mermaid
graph LR
    subgraph clients["Client"]
        RE["React SPA<br/><i>frontend/</i><br/>Redux Toolkit + RTK Query<br/>calls the API from the browser"]
    end

    subgraph api["FastAPI backend"]
        MW["Middleware<br/>security headers · request id<br/>body limit · rate limit"]
        RT["Routes /api/v1"]
        SVC["Services<br/>auth · account · documents<br/>chat · projects · audit · catalogue"]
        RAG["CRAG pipeline"]
    end

    subgraph stores["State"]
        DB[("SQLite<br/>users · documents · chats<br/>projects · audit · tokens<br/>model catalogue")]
        VS[("ChromaDB<br/>shared collections<br/>per embedding config")]
        FS[("Uploaded PDFs<br/>on disk")]
    end

    subgraph ext["Model providers"]
        OA["OpenAI"]
        GE["Gemini"]
        GR["Groq<br/><i>chat only</i>"]
        OL["Ollama<br/><i>local</i>"]
    end

    RE --> MW
    MW --> RT --> SVC
    SVC --> RAG
    SVC --> DB
    SVC --> FS
    RAG --> VS
    RAG --> OA & GE & GR & OL
    SVC -.->|"embeddings"| OA & GE & OL
```

The client runs in the browser, so it is subject to CORS — its origin must
appear in the backend's `CORS_ORIGINS`. That is the main operational difference
from a server-rendered client, and the usual cause of a working API paired with
a blank screen.

> A sibling project, `ai-company-knowledge-assistant`, pairs the same backend
> with a Streamlit client. The two are independent: separate folders, separate
> databases, separate deployments.

---

## 2. Roles

Authorization is enforced **server-side on every request**. Hiding navigation is
presentation, not a control: a client that claims to be an admin gains nothing.

```mermaid
graph TD
    R{"Role on the<br/>access token's user"}
    R -->|USER| U["Ask questions<br/>Own chats, projects, history<br/>Own account page"]
    R -->|ADMIN| A["Everything a user can do, plus:<br/>upload / delete documents<br/>choose the embedding model<br/>metrics · audit trail · model catalogue<br/>per-document retrieval testing"]

    U --- N1["No document endpoints exist for them<br/><i>they never learn what is indexed</i>"]
    A --- N2["require_admin dependency → 403<br/><i>checked per request, not per screen</i>"]
```

Every account registers as `USER`. There is deliberately **no API** that grants
admin — that would let anyone who can sign up manage the shared corpus. Promotion
happens on the server:

```bash
python scripts/promote_to_admin.py you@example.com
```

A fresh install therefore has no admin, and so cannot be populated until someone
is promoted. That is the intended trust boundary, not an oversight.

---

## 3. Authentication and session lifetime

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant API as FastAPI
    participant DB as SQLite

    C->>API: POST /auth/login (email, password)
    API->>DB: verify bcrypt hash, is_active, verification
    API-->>C: access token (short) + refresh token (long)<br/>both carry jti and sev (session epoch)

    Note over C: access token in memory only<br/>refresh token persisted

    C->>API: GET /auth/me (Bearer access)
    API->>DB: jti in revoked list? sev == user.session_epoch?
    API-->>C: profile

    Note over C,API: access token expires
    C->>API: any request → 401
    C->>API: POST /auth/refresh (refresh token)
    API->>DB: revoke the presented jti, issue a new pair
    API-->>C: new access + refresh
    C->>API: retry the original request
```

**The refresh token rotates and the old one is revoked on use.** That single fact
drives a client requirement: concurrent 401s must share **one** refresh. Without
it the first succeeds and the rest present a token that was just revoked, logging
the user out mid page load. The client implements a single-flight refresh, and
the answer stream shares the same mutex — it cannot go through RTK Query, since
it needs a partial response body, but it must still recover from an expired
token.

### Ending every session at once

```mermaid
graph LR
    PR["Password reset"] --> INC["user.session_epoch += 1"]
    INC --> REJ["Every token carrying an older<br/>sev is refused — access and refresh"]
    REJ --> OUT["An attacker holding a<br/>stolen token loses access"]
```

A counter, not a "valid from" timestamp. JWT `iat` is an integer number of
seconds, so a timestamp cutoff cannot order a token against a reset in the same
second: it either rejects the token the user just obtained, or keeps honouring one
issued moments before. A counter has no granularity to lose.

---

## 4. Document ingestion (admin only)

```mermaid
flowchart TD
    UP["POST /documents/upload<br/>files + embedding provider/model"] --> V{"Validate<br/>type · size"}
    V -->|reject| E1["422 — no row, no file"]
    V -->|ok| PROV{"Embedding provider<br/>configured and model allowed?"}
    PROV -->|no| E2["Fail before any disk write"]
    PROV -->|yes| SAVE["Write PDF to disk"]

    SAVE --> LOAD["PdfLoader: extract text per page"]
    LOAD --> OCR{"Page has a<br/>text layer?"}
    OCR -->|yes| CH
    OCR -->|"no (scanned)"| RO["Render page with PyMuPDF<br/>read with RapidOCR (ONNX)"] --> CH

    CH["Chunker<br/>RecursiveCharacterTextSplitter<br/>CHUNK_SIZE / CHUNK_OVERLAP"] --> EMB["Embed every chunk"]
    EMB --> INS["Insert into Chroma collection<br/>kb_shared_&lt;sha1(provider:model)&gt;"]
    INS --> ROW["Create the Document row<br/><b>only now</b>"]
    ROW --> AUD["Audit: document.uploaded<br/>filename + chunk count, never text"]
    ROW --> BM["Invalidate the BM25 index"]

    LOAD -.->|failure| RB
    CH -.->|failure| RB
    EMB -.->|failure| RB
    INS -.->|failure| RB
    RB["Roll back: delete the file<br/>and any vectors written"] --> E3["Reported per file in errors[]"]
```

Two properties worth noting:

- **The database row is created last.** A failure anywhere leaves no row and no
  file, so the knowledge base never contains a half-indexed document.
- **A batch can partly succeed.** Three PDFs where one is unreadable returns
  `201` with `success: true`, the good ones in `data`, and the failure in
  `errors`. A client that ignores `errors` will silently under-report.

OCR is a fallback, not a mode: pages with a text layer never pay for it.

---

## 5. Answering a question — the CRAG pipeline

The pipeline is an explicit list of steps, so the buffered and streaming paths
cannot drift: both build the same retrieval prefix.

```mermaid
flowchart TD
    Q["POST /chat/ask<br/>or /chat/ask/stream"] --> RL{"Rate limit<br/>20/min per identity"}
    RL -->|exceeded| R429["429"]
    RL -->|ok| KB{"Knowledge base<br/>empty?"}
    KB -->|yes| R404["404 — nothing to answer from"]
    KB -->|no| G1

    G1["<b>1. InputGuardrailStep</b><br/>harmful → refuse and halt<br/>injection → log, still answer<br/>PII → redact from the search query"]
    G1 -->|halted| REF["Refusal — no retrieval, no model call"]
    G1 --> RET

    RET["<b>2. RetrieveStep</b>"] --> HY{"HYBRID_SEARCH_ENABLED?"}
    HY -->|yes| VEC["Vector search (Chroma)"] & KW["BM25 keyword search"]
    VEC & KW --> RRF["Reciprocal Rank Fusion (k=60)<br/>dedup on chunk <i>text</i>"]
    HY -->|no| VONLY["Vector search only"]
    RRF --> GR
    VONLY --> GR

    GR["<b>3. GradeContextStep</b><br/>score vs CRAG_RELEVANCE_THRESHOLD"] --> VERD{"Context<br/>good?"}
    VERD -->|good| RR
    VERD -->|poor| CR["<b>4. CorrectiveRetrievalStep</b><br/>LLM rewrites the query, retrieve again<br/>bounded by CRAG_MAX_CORRECTION_ATTEMPTS<br/>keeps the best result seen"]
    CR --> RR

    RR["<b>5. RerankStep</b><br/>no-op when RRF already ranked"] --> GEN
    GEN["<b>6. GenerateStep</b><br/>answer only from context"] --> VG
    VG["<b>7. VerifyGroundednessStep</b><br/><i>optional — one extra LLM call</i>"] --> RETRACT{"Supported by<br/>the context?"}
    RETRACT -->|no| RTR["Retract and replace the answer"]
    RETRACT -->|yes| OG
    RTR --> OG
    OG["<b>8. OutputGuardrailStep</b><br/>withhold unsafe · redact PII"] --> DONE["Answer + citations + diagnostics"]
```

If the answer is not in the corpus, the model is instructed to say
`"I couldn't find that information in the uploaded documents."` rather than guess.

### Why hybrid retrieval

Vector search alone misses exact phrases: a heading in a table of contents can
outrank the section that actually contains the text, because both are topically
similar. BM25 does not share that failure mode — but it over-rewards short lines,
because it normalises by document length. Fusing them handles both.

### Untrusted context

Retrieved document text is **untrusted input**. A malicious PDF must not be able
to issue instructions or forge a citation to a file that was never uploaded.

```mermaid
flowchart LR
    CHUNK["Retrieved chunk"] --> NEU["Neutralise<br/>forged [Source N: x.pdf] markers<br/>role prefixes (Assistant:)<br/>injected closing tags"]
    NEU --> WRAP["Wrap in &lt;untrusted_context id=NONCE&gt;<br/>fresh random nonce per request"]
    WRAP --> SYS["System prompt: this block is<br/>DATA, not instructions"]
    HIST["Conversation history"] --> MSG["Real Human/AI message objects,<br/>never a flattened string"]
    SYS & MSG --> LLM["Chat model"]
```

A document cannot close a block whose identifier it cannot predict, and cannot
fabricate a prior turn because history is carried by message role rather than
parsed out of text. The pattern detectors in `app/guardrails/` are a cheap first
filter on hostile *input*; these structural protections are what actually contain
a malicious document, and they cannot be switched off.

---

## 6. Streaming an answer

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant API as /chat/ask/stream
    participant P as Retrieval pipeline
    participant M as Chat model

    C->>API: POST question
    API->>P: run retrieval to completion
    Note over C: "Searching the knowledge base..."<br/>retrieval is seconds on a local model
    P-->>API: graded, ranked context
    API->>M: generate with the built prompt
    loop as tokens arrive
        M-->>API: token
        API-->>C: {"type":"token","content":"..."}
    end
    opt groundedness check fails
        API-->>C: {"type":"retract","content":"..."}
        Note over C: replace what was shown,<br/>do not append
    end
    API-->>C: {"type":"done", session_id, sources, timings, crag}
    Note over API,C: on failure: {"type":"error","message":"..."}
```

NDJSON, not SSE: one complete JSON object per line, parseable with a readline
loop and no SSE library. **Errors after the first byte arrive as an in-stream
`error` event**, because the HTTP status line is long gone by then.

Client requirement: a chunk can end mid-line, so the remainder must stay buffered
for the next read. Parsing per chunk drops events.

---

## 7. Chats and projects

```mermaid
erDiagram
    USER ||--o{ PROJECT : owns
    USER ||--o{ CHAT_SESSION : owns
    USER ||--o{ AUTH_TOKEN : "reset / verify"
    PROJECT |o--o{ CHAT_SESSION : "groups (optional)"
    CHAT_SESSION ||--o{ CHAT_MESSAGE : contains
    USER ||--o{ DOCUMENT : uploaded
    DOCUMENT |o--o{ CHAT_SESSION : "scoped test chat"

    USER {
        string id PK
        string email UK
        enum role "ADMIN | USER"
        bool is_verified
        int session_epoch
    }
    PROJECT {
        string id PK
        string name "unique per user"
    }
    CHAT_SESSION {
        string id PK
        string project_id FK "null = ungrouped"
        string document_id FK "null = normal chat"
    }
    CHAT_MESSAGE {
        string id PK
        string role "user | assistant"
        json sources
    }
    DOCUMENT {
        string id PK
        string filename
        enum status
        string embedding_provider
        string embedding_model
    }
```

Two deliberate shapes:

- **Deleting a project does not delete its chats.** They are detached
  (`project_id → NULL`) and reappear under Recent. An organisational action must
  not be destructive.
- **A document-scoped chat is excluded from history.** Those are the admin's
  retrieval tests, not part of anyone's conversation list.

Ownership is filtered in the `WHERE` clause, and a chat belonging to someone else
returns **404, not 403** — so responses cannot be used to probe for valid ids.

---

## 8. Model catalogue — configuration, not code

Which models each provider offers lives in the database and is editable at
runtime.

```mermaid
flowchart TD
    ASK["validate_model(provider, name)"] --> CACHE{"Catalogue cached<br/>in memory?"}
    CACHE -->|no| LOAD["Read provider_models (one query)"] --> CACHE
    CACHE -->|yes| SEEDED{"Table has<br/><b>any</b> row?"}
    SEEDED -->|no| DEF["Use the provider class's<br/>default_models (seed data)"]
    SEEDED -->|yes| DBWINS["Database is authoritative<br/>— enabled rows only"]
    DEF & DBWINS --> OK{"Model listed?"}
    OK -->|no| E["400 — not supported"]
    OK -->|yes| GO["Build the model"]

    EDIT["Admin adds / disables / removes<br/>via /admin/models"] --> INV["Invalidate the cache"] --> CACHE
```

Two decisions that look arbitrary and are not:

- **Cached in memory.** `validate_model` runs on every question and every upload,
  on provider objects that hold no database session. A query there would sit in
  the hot path of the whole application.
- **"Any row" decides authority, not "a row for this provider".** Falling back
  per-provider would mean disabling a provider's last model silently resurrects
  the built-in list, and an operator restricting their install to an approved
  subset would find the restriction ignored.

> **Disable rather than delete an embedding model.** Documents are indexed into a
> collection keyed by embedding provider *and* model, so removing one leaves the
> documents indexed with it unsearchable.

---

## 9. Account recovery

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant API as FastAPI
    participant DB as SQLite
    participant M as Email backend

    U->>API: POST /auth/forgot-password (email)
    API->>DB: look up the account
    Note over API: responds identically whether or not<br/>the address exists — otherwise this is a<br/>free membership oracle
    API->>DB: invalidate earlier unused tokens,<br/>store SHA-256 of a new one
    API->>M: send link (console log, or SMTP)
    API-->>U: "If that address has an account..."

    U->>API: POST /auth/reset-password (token, new password)
    API->>DB: match hash · unused · unexpired
    API->>DB: set password, session_epoch += 1
    API-->>U: done — every other session is now dead
```

Only a **hash** of each token is stored: the plaintext exists in the email and
nowhere else, so a leaked database yields nothing presentable. Every failure —
expired, already used, never existed — returns the same message, so an attacker
cannot learn which of their guesses was once real.

Email delivery is pluggable and **no third-party service is integrated**. The
default `console` backend writes the message to the log, so the flow works on a
fresh checkout; `EMAIL_BACKEND=smtp` delivers through any SMTP server.

---

## 10. Cross-cutting concerns

```mermaid
flowchart LR
    REQ["Request"] --> SH["SecurityHeadersMiddleware<br/><i>outermost — covers errors too</i>"]
    SH --> BS["MaxBodySizeMiddleware<br/>reject by Content-Length"]
    BS --> RC["RequestContextMiddleware<br/>request id + timing"]
    RC --> CORS["CORS"]
    CORS --> RLD["Rate limit dependency<br/>chat 20/min · auth 10/min · upload 50/hr"]
    RLD --> ROUTE["Route handler"]
    ROUTE --> AUDIT["Audit (security-relevant actions only)"]
    ROUTE --> LOG["Structured log — never keys,<br/>secrets or document text"]
    ROUTE --> TRACE["LangSmith (optional)<br/>content redacted by default"]
```

- **Security headers are outermost** so a 413 or an unhandled error carries them
  too, not just successful handlers.
- **No CSRF tokens, deliberately.** Auth is Bearer-only and nothing sets a
  cookie, so a cross-site request carries no ambient credentials — the condition
  CSRF tokens exist to address. A test asserts no endpoint reads auth from a
  cookie, so the reasoning cannot silently outlive its premise.
- **The audit log stores no content.** A row records that a document was uploaded
  and its filename, never its text; that a login failed, never the password
  tried. It is append-only, and `user_id` is not a foreign key so an event
  outlives the account it describes.
- **Caching.** Embedding the question is the slowest step before an answer can
  begin and is a pure function of `(provider, model, text)`, so it is memoized in
  a bounded TTL/LRU cache. `embed_documents` is *not* cached — chunk text is
  unique per document.

---

## 11. Deployment

```mermaid
graph TB
    subgraph host["Docker Compose"]
        BE["backend :8001<br/>migrations run on startup"]
        FE["frontend :5173<br/>nginx serving the built bundle"]
        V1[("backend_data volume<br/>SQLite · Chroma · uploads")]
        V2[("backend_logs volume")]
    end
    B["Browser"] --> FE
    B -->|"XHR / fetch"| BE
    BE --- V1
    BE --- V2
```

Note what the arrows say: the browser loads the page from nginx but talks to the
API **directly**. So `VITE_API_BASE_URL` must be an address the *browser* can
reach — never `http://backend:8001`, which resolves only inside the Docker
network — and it is baked in at **build** time, not read at runtime.

Serving the bundle also needs a **history fallback** (`try_files ... /index.html`),
or an emailed `/reset-password` link 404s on reload.

---

## 12. Test topology

| Suite | Count | What it protects |
|---|---:|---|
| `backend/tests` | 263 | API behaviour, RAG pipeline, guardrails, auth, catalogue, migrations |
| `frontend` (vitest) | 23 | NDJSON framing, single-flight refresh, envelope handling, stale-model repair |

The frontend tests deliberately target logic where a bug stays invisible until
it corrupts an answer or signs someone out — an event split across a network
chunk boundary, a concurrent refresh, a `success: false` body arriving with a
2xx status. The screens themselves are verified by using them.

One backend test is structural rather than behavioural, and exists because the
same class of bug happened twice: endpoints that were fully tested while **no UI
called them**. `test_react_contract.py` parses the RTK Query slices for the
paths they issue and asserts each exists in the OpenAPI schema, so a renamed
route fails in CI rather than becoming a blank screen someone discovers later.
