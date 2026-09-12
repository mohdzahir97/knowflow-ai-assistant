# AI Company Knowledge Assistant — Backend

FastAPI backend implementing local JWT authentication and a Corrective
Retrieval-Augmented Generation (CRAG) pipeline over a **single shared knowledge
base**, with runtime-switchable chat and embedding providers.

- **Chat providers:** OpenAI, Google Gemini, Groq, Ollama (local)
- **Embedding providers:** OpenAI, Google Gemini, Ollama (local)

Chat and embedding providers are selected independently per request — e.g. chat
with Groq while embedding with OpenAI. Note that Groq offers chat models only;
Ollama offers both chat and embedding models and runs entirely on your machine.

## Two roles

The knowledge base is shared by everyone, not private per account:

| | Administrator | End user |
|---|---|---|
| Ask questions | yes | yes |
| Own chats, projects, history | yes | yes |
| Upload / delete documents | yes | **no endpoints at all** |
| Choose the embedding model | yes | no — selected for them |
| See that retrieval exists | yes | no |

End users never learn which documents exist. Retrieval happens invisibly inside
the chat pipeline, and there is no document API reachable by a non-admin.

**Authorization is enforced server-side on every admin route.** The Streamlit
client hides admin navigation for ordinary users, but that is a convenience
only — calling an admin endpoint directly with a user token returns `403`.

## Prerequisites

- Python 3.12+
- pip
- API keys for whichever cloud providers you intend to use (OpenAI and/or Google
  Gemini and/or Groq). None are required to start the server — auth, health checks,
  and document management all work without any key — but asking a question requires
  at least one configured chat provider and one configured embedding provider.
- (Optional) A running [Ollama](https://ollama.com) instance if you want to use
  local models. Ollama needs no API key — only a reachable base URL — but you must
  pull any model before using it (e.g. `ollama pull llama3.1`,
  `ollama pull nomic-embed-text`).
- (Optional) Docker + Docker Compose, if you'd rather run the full stack in
  containers instead of a local virtualenv — see [Running with Docker](#running-with-docker).

## 1. Create a virtual environment

```bash
cd backend
python -m venv .venv
```

Activate it:

```bash
# Windows (Git Bash)
source .venv/Scripts/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

## 2. Install dependencies

```bash
pip install -r requirements.txt
```

For running the test suite, install the dev dependencies instead (this includes
everything in `requirements.txt` plus `pytest`/`pytest-cov`):

```bash
pip install -r requirements-dev.txt
```

> **Windows note:** `chromadb` depends on `chroma-hnswlib`, which needs a C++
> compiler to build from source on Windows if no prebuilt wheel is available for
> your exact Python version. If `pip install` fails on that package, either
> install the [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
> or run the backend via Docker instead, where the Linux base image installs
> prebuilt wheels with no compiler needed.

## 3. Configure environment variables

Copy the example file and fill in your own values:

```bash
cp .env.example .env
```

All configuration is centralized in `.env` — nothing is hardcoded in source. Key
variables:

| Variable | Purpose | Default |
|---|---|---|
| `JWT_SECRET_KEY` | Signing key for access/refresh tokens. **Change this to a random value** before any real deployment. | placeholder |
| `DATABASE_URL` | SQLAlchemy database URL (SQLite by default). | `sqlite:///./data/app.db` |
| `OPENAI_API_KEY` / `GOOGLE_API_KEY` / `GROQ_API_KEY` | Cloud provider API keys. Only set the ones you plan to use — each provider reports itself as "not configured" if its key is empty, rather than failing at startup. | empty |
| `OLLAMA_BASE_URL` | Base URL of your local Ollama server. Ollama uses no API key, so it reports as "configured" whenever this is set. Inside Docker, use `http://host.docker.internal:11434` to reach Ollama on the host. | `http://localhost:11434` |
| `CORS_ORIGINS` | JSON array of allowed **browser** origins. The React client is subject to CORS. | `["http://localhost:5173", ...]` |
| `UPLOAD_DIR` / `CHROMA_PERSIST_DIR` | Where uploaded PDFs and the vector store are persisted on disk. | `./data/uploads`, `./data/chroma` |
| `MAX_UPLOAD_SIZE_MB` / `MAX_REQUEST_BODY_MB` | Per-file and per-request size ceilings. | `25`, `100` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` / `RETRIEVAL_TOP_K` | RAG chunking and retrieval tuning. | `1000`, `150`, `4` |
| `HYBRID_SEARCH_ENABLED` / `HYBRID_RRF_K` | Combine vector search with BM25 keyword search, fused by Reciprocal Rank Fusion. Helps with exact terms (policy numbers, proper nouns) that embeddings alone miss. | `true`, `60` |
| `CRAG_*` | Corrective RAG: grading threshold, minimum relevant chunks, correction attempts, groundedness verification. See [Corrective RAG](#corrective-rag). | see `.env.example` |
| `GUARDRAILS_ENABLED` / `GUARDRAIL_*` | Input/output safety checks, question length ceiling, PII redaction in queries and answers. | `true` |
| `RATE_LIMIT_ENABLED` / `RATE_LIMIT_*` | Sliding-window limits for chat, auth and upload routes. | `true`, `20`/min, `10`/min, `50`/hr |
| `LANGSMITH_TRACING` / `LANGSMITH_*` | Optional LangSmith tracing. `LANGSMITH_REDACT_CONTENT` strips document text and questions from traces. | `false` |
| `OCR_ENABLED` / `OCR_DPI` | OCR fallback for scanned/image-only PDFs. When enabled, pages with no native text layer are rendered and read with RapidOCR (no system binary needed). | `true`, `200` |
| `EMAIL_BACKEND` / `EMAIL_FROM` / `SMTP_*` | How password-reset and confirmation emails are delivered. `console` logs them (works out of the box, no signup); `smtp` sends via any SMTP server. See [Account recovery](#account-recovery). | `console` |
| `FRONTEND_BASE_URL` | Where emailed links point — the React app, not the API. | `http://localhost:5173` |
| `REQUIRE_EMAIL_VERIFICATION` | Whether an unconfirmed address may sign in. Off by default so enabling it later never locks out existing accounts. | `false` |
| `EMBEDDING_CACHE_ENABLED` | Cache question embeddings in memory. See [Caching](#caching). | `true` |
| `SECURITY_HEADERS_ENABLED` / `HSTS_MAX_AGE_SECONDS` | Hardening headers on every response (CSP, frame/sniff/referrer/permissions policies). HSTS is only sent over HTTPS. See [Security headers](#security-headers). | `true`, `31536000` |
| `LOG_LEVEL` / `LOG_DIR` | Logging verbosity and where rotating log files are written. | `INFO`, `./logs` |

See `.env.example` for the full list (JWT expiry, default provider/model, LLM
temperature/max tokens, request timeout, log rotation size).

## 4. Apply database migrations

```bash
alembic upgrade head
```

This creates `data/app.db` (SQLite) with the full schema — users (with roles
and verification state), documents, chat sessions/messages, projects, revoked
tokens, single-use account-recovery tokens, and the audit log. Whenever you
pull changes that include new migrations, re-run this command.

## 5. Create the first administrator

Every account registers as an ordinary **user**: self-signup must never grant
knowledge-base management rights. So a fresh installation has no administrator,
and therefore no way to upload documents until you promote someone.

Register an account through the app or the API, then:

```bash
python scripts/promote_to_admin.py you@example.com
```

Other options:

```bash
python scripts/promote_to_admin.py --list              # every account and its role
python scripts/promote_to_admin.py them@example.com --revoke
```

Deliberately a script and not an endpoint — a role change requires access to the
server, which is the trust boundary intended. Revoking the last administrator is
refused, since it would leave the knowledge base unmanageable. A signed-in user
should sign out and back in for a role change to take effect.

## 6. Run the development server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001 --no-server-header
```

> `--no-server-header` stops uvicorn advertising itself and its version.
> It is a launch flag rather than application code because uvicorn appends
> that header *after* the app has responded, so middleware cannot replace it.
> `run_backend.bat` and the Docker entrypoint already pass it.

- API base URL: `http://localhost:8001`
- Interactive docs (Swagger UI): `http://localhost:8001/docs`
- ReDoc: `http://localhost:8001/redoc`
- Health check: `http://localhost:8001/health`

> Interactive docs are automatically disabled when `ENVIRONMENT=production` in
> your `.env` — `/health` remains available regardless.

### Quick smoke test

```bash
curl -X POST http://localhost:8001/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"password123"}'

curl -X POST http://localhost:8001/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"password123"}'
```

Use the returned `access_token` as an `Authorization: Bearer <token>` header for
every other endpoint.

## API overview

All routes are prefixed with `/api/v1`.

| Area | Routes | Access |
|---|---|---|
| Auth | `POST /auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `GET /auth/me` | public / signed in |
| Account recovery | `POST /auth/forgot-password`, `/auth/reset-password`, `/auth/verify-email`, `/auth/resend-verification`, `GET /auth/login-history` | public / own account |
| Observability | `GET /admin/audit`, `GET /admin/metrics` | **admin only** |
| Model catalogue | `GET|POST /admin/models`, `PATCH|DELETE /admin/models/{id}`, `POST /admin/models/seed` | **admin only** |
| Providers | `GET /providers/chat`, `/providers/embeddings` | signed in |
| Knowledge base | `POST /documents/upload`, `GET /documents`, `DELETE /documents/{id}`, `DELETE /documents` | **admin only** |
| Chat | `POST /chat/ask`, `POST /chat/ask/stream` | signed in |
| History | `GET /chat/sessions`, `GET /chat/sessions/{id}`, `DELETE /chat/sessions/{id}`, `DELETE /chat/messages/{id}` | own data only |
| Projects | `GET|POST /projects`, `PATCH|DELETE /projects/{id}`, `GET /projects/{id}/chats` | own data only |
| Chat organisation | `GET /chats`, `PATCH /chats/{id}`, `PATCH /chats/{id}/project` | own data only |

`POST /chat/ask/stream` returns newline-delimited JSON (`application/x-ndjson`),
one object per line, with `type` of `token`, `retract`, `done` or `error`.
`retract` means an answer was shown and then failed groundedness verification —
clients must replace what they displayed rather than append to it.

For projects and chats, an id belonging to another user returns `404`, identical
to one that does not exist, so responses cannot be used to probe for valid ids.

## Corrective RAG

Retrieval and generation run as an explicit, inspectable pipeline
(`app/rag/pipeline/`), each step tracing itself:

1. **Input guardrail** — refuses harmful questions before any retrieval or model
   call, so a refused question costs nothing.
2. **Retrieve** — vector search, optionally fused with BM25 keyword search via
   Reciprocal Rank Fusion.
3. **Grade context** — scores whether what came back is actually relevant.
4. **Corrective retrieval** — on poor context, rewrites the query and retries, up
   to `CRAG_MAX_CORRECTION_ATTEMPTS`, keeping the best result found.
5. **Re-rank** — reorders chunks by relevance (skipped when hybrid fusion has
   already ranked them).
6. **Generate** — answers strictly from the retrieved context.
7. **Verify groundedness** — checks the answer is supported by that context, and
   retracts it if not.
8. **Output guardrail** — withholds unsafe answers and redacts PII.

The model is instructed to answer only from retrieved context and to reply
`"I couldn't find that information in the uploaded documents."` when the answer
is not there.

### Prompt-injection containment

Retrieved documents are untrusted input. A malicious PDF must not be able to
issue instructions or forge a citation to a file that was never uploaded.
`app/rag/prompt_builder.py` therefore:

- wraps retrieved context in a block tagged with a **fresh random nonce** per
  request, so a document cannot close a block whose identifier it cannot predict;
- neutralises forged source markers, role prefixes (`Assistant:`) and injected
  closing tags inside document text;
- carries conversation history as real message objects rather than a flattened
  string, so a typed question cannot fabricate a prior turn.

The pattern detectors in `app/guardrails/` are a cheap first filter on hostile
input, not the main defence — pattern matching is evadable by paraphrase. The
structural protections above are what actually contain a malicious document.
`tests/test_guardrails.py` pins the exact attack this was built to stop.

## Model catalogue

Which models each provider offers is **configuration in the database**, not
a list in Python. Model line-ups change constantly — providers deprecate
names and add new ones, and an operator may want to restrict an installation
to an approved subset — and none of that should need a code change and a
redeploy.

Manage it from **Administration → Models** in the UI, or via
`/admin/models` (admin-only). Adding, disabling or removing a model takes
effect on the next request; there is nothing to restart.

The provider classes still declare `default_models`. That is **seed data** —
what a fresh installation starts with — not the source of truth:

- While the catalogue table is **entirely empty**, those defaults are used,
  so a new database is usable immediately rather than refusing every model
  until someone seeds it.
- Once the table has **any row**, the database is authoritative. Otherwise
  disabling a provider's last model would silently resurrect the built-in
  list, and an operator's restriction would be quietly ignored.

The catalogue is cached in memory and re-read when it changes, because
`validate_model` runs on every question and every upload — a query there
would sit in the hot path of the whole application.

```bash
python scripts/seed_models.py           # add any missing defaults (additive)
python scripts/seed_models.py --list    # show the catalogue
python scripts/seed_models.py --reset   # wipe and re-seed (destructive)
```

Seeding never removes your own entries and never re-enables a model you
disabled deliberately.

**Disable rather than delete an embedding model.** Documents are indexed
into a collection keyed by embedding provider and model, so removing one
that documents were indexed with leaves those documents unsearchable.
Disabling hides it from the picker while keeping existing documents
queryable.

## Account recovery

Password reset and email confirmation work on a fresh checkout with nothing
to configure: the default `console` backend writes the message to the log and
stdout, so you can copy the link straight out of your terminal. It is not for
production — the log then contains single-use links. Set `EMAIL_BACKEND=smtp`
and the `SMTP_*` variables to deliver for real, through any SMTP server.
**No third-party email or identity service is integrated.**

How the flow is built:

- **No account enumeration.** `POST /auth/forgot-password` returns the same
  response whether or not the address exists. An endpoint that answers "no
  such user" is a free membership oracle.
- **Tokens are single-use, expiring, and stored only as a SHA-256 hash.** The
  plaintext exists in the email and nowhere else, so a leaked database yields
  nothing presentable. Requesting a second link invalidates the first.
- **A reset ends every existing session.** Each user has a `session_epoch`
  that a reset increments; tokens carry the epoch they were minted under, and
  any token with an older one is refused — access *and* refresh. If an
  account was taken over, changing the password while the attacker keeps a
  working refresh token would accomplish nothing.

  A counter rather than a "valid from" timestamp on purpose: JWT `iat` is an
  integer number of seconds, so a timestamp cutoff cannot order a token
  against a reset that happened in the same second. It either rejects the
  token the user has just obtained, or keeps honouring one issued moments
  before. A counter has no granularity to lose.

- **Sign-in history** (`GET /auth/login-history`) shows the account's own
  successes *and failures*, reading the audit trail rather than duplicating
  it. The owner is the person best placed to spot an unfamiliar sign-in.

## Audit trail and metrics

`GET /admin/audit` records authentication outcomes, role changes, and every
change to the shared knowledge base. Deliberately narrow: an audit log that
records everything is one nobody reads.

Two rules it is built around:

- **No content, ever.** A row records that a document was uploaded and its
  filename, never its text; that a login failed, never the password tried.
  The log stays safe to export and read.
- **No deletes.** `user_id` is not a foreign key, so an event survives the
  account it describes — precisely when it matters most.

Writing an event never breaks the request that triggered it; a failed insert
is logged and swallowed rather than turning observability into an outage.

`GET /admin/metrics` reports counts (documents, chunks, conversations,
accounts, failed sign-ins in the last 24 hours) as SQL aggregates, so it
stays cheap as the tables grow. Both routes are admin-only — an audit trail
naming who did what from where must not be readable by its own subjects.

## Caching

Embedding the question is the slowest step before an answer can begin —
several seconds on a local CPU model — and it is a pure function of
`(provider, model, text)`. Repeat questions are common in a knowledge
assistant, so `CachingEmbeddings` memoizes `embed_query` in a bounded TTL/LRU
cache, wrapped at the provider factory so every consumer shares it.

Keyed by provider and model as well as text, since serving one model's vector
to another would silently corrupt retrieval. `embed_documents` is *not*
cached: chunk text is unique per document, so caching it would only consume
memory. The cache is in-process and bounded — a cold cache costs latency, not
correctness, and an unbounded cache keyed by user input is a memory leak with
extra steps.

## Security headers

Every response — including errors and rejections — carries a strict
`Content-Security-Policy` (`default-src 'none'`), `X-Content-Type-Options`,
`X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` and the
cross-origin isolation headers. `Strict-Transport-Security` is added only when
the request arrived over HTTPS (directly or via `X-Forwarded-Proto`), so a
local dev server never pins a hostname to HTTPS before a certificate exists.

Swagger UI and ReDoc get their own, looser policy — the API's "load nothing"
policy would render them blank — and that relaxation does not apply to any
other path.

**There are no CSRF tokens, deliberately.** This API authenticates with a
Bearer token the client attaches explicitly and sets no cookies, so a
cross-site request carries no ambient credentials to abuse — the condition
CSRF tokens exist to address. A test asserts that no endpoint reads auth from
a cookie, so if that ever changes the reasoning gets revisited rather than
silently outlived.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

Tests run against a fully isolated SQLite database and ChromaDB directory
(created fresh under `tests/_test_data/` and cleaned up automatically) and
register fake chat/embedding providers, so no real API keys or network access
are required to run the suite.

For a coverage report:

```bash
pytest --cov=app --cov-report=term-missing
```

`tests/test_frontend_contract.py` additionally checks that every endpoint the
Streamlit client calls actually exists on the API, so a renamed route fails here
rather than becoming a runtime error a user discovers.

## Running with Docker

From the **repository root** (not this `backend/` directory):

```bash
cp backend/.env.example backend/.env    # fill in your API keys
docker compose up --build
```

This builds and starts both the backend (`http://localhost:8001`) and the
React frontend (`http://localhost:5173`) together, with the SQLite database,
uploaded files, and ChromaDB persisted in named Docker volumes. Database
migrations run automatically on container startup.

You still need to promote an administrator (step 5) — run it inside the
container:

```bash
docker compose exec backend python scripts/promote_to_admin.py you@example.com
```

## Project structure

```
backend/
├── app/
│   ├── api/v1/          # Route handlers (auth, documents, chat, projects, admin, providers, health)
│   ├── core/            # Config, logging, security, exceptions, middleware, rate limiting,
│   │                    #   tracing, email, caching
│   ├── db/              # SQLAlchemy models and session management
│   ├── guardrails/      # Pattern detectors for injection, PII and harmful content
│   ├── providers/       # Chat & embedding provider factories (OpenAI/Gemini/Groq/Ollama)
│   ├── rag/
│   │   ├── pipeline/    # Composable CRAG steps (retrieve, grade, correct, generate, verify)
│   │   ├── keyword_index.py  # BM25 index for hybrid search
│   │   └── prompt_builder.py # Untrusted-context containment
│   ├── schemas/         # Pydantic request/response models
│   ├── services/        # Business logic (auth, account recovery, documents, chat,
│   │                    #   projects, audit, vector store)
│   └── main.py          # FastAPI app factory
├── alembic/             # Database migrations
├── scripts/             # Operational scripts (admin promotion, shared-KB migration)
├── tests/               # pytest suite
├── requirements.txt
├── requirements-dev.txt
└── Dockerfile
```

## Migrating an older installation

Earlier versions gave every user a private knowledge base. If you have such an
installation, `scripts/migrate_to_shared_kb.py` copies the existing embeddings
into the shared collection without re-embedding anything. It is idempotent and
runs as a dry run by default:

```bash
python scripts/migrate_to_shared_kb.py            # report what would change
python scripts/migrate_to_shared_kb.py --apply    # perform the migration
```
