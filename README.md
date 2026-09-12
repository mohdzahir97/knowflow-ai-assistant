# AI Knowledge Assistant — React stack

A FastAPI backend and a React SPA over a single shared knowledge base.
Administrators curate the corpus; end users ask questions and get answers drawn
only from it, with citations.

```
ai-knowledge-assistant-react/
├── backend/            FastAPI, SQLite, ChromaDB, CRAG pipeline
├── frontend/           React + TypeScript, Redux Toolkit + RTK Query
├── run_backend.bat     Sets up and starts the API
├── run_frontend.bat    Sets up and starts the dev server
├── start_all.bat       Both, in separate windows
├── docker-compose.yml  Both, containerised
└── SYSTEM_DESIGN.md    End-to-end workflow diagrams
```

## Relationship to the sibling project

This is an **independent project**. A sibling folder,
`ai-company-knowledge-assistant`, pairs the same backend design with a Streamlit
client.

They share no files, no database and no configuration. A change to one backend
does not reach the other — they were split so the two stacks can evolve
separately, and that is the trade-off: identical fixes must be applied twice.

## Quick start (Windows)

```bat
start_all.bat
```

Each launcher creates its own environment on first run and skips that work
afterwards. Or run them separately:

```bat
run_backend.bat      REM API on http://localhost:8001
run_frontend.bat     REM app on http://localhost:5173
```

## Quick start (any platform)

```bash
# Backend
cd backend
python -m venv .venv && source .venv/Scripts/activate   # or bin/activate
pip install -r requirements.txt
cp .env.example .env                                    # if not already present
alembic upgrade head
uvicorn app.main:app --reload --port 8001 --no-server-header

# Frontend, in a second terminal
cd frontend
npm install
npm run dev
```

## First run: create an administrator

Every account registers as an ordinary **user**, and only an administrator can
upload documents — so a fresh installation cannot answer anything until someone
is promoted. Register through the app, then:

```bash
cd backend
python scripts/promote_to_admin.py you@example.com
```

There is deliberately no API for this: a self-service route would let anyone who
can sign up manage the shared corpus. See
[`backend/README.md`](backend/README.md) for the rest of the setup, including
provider keys and SMTP.

## Two things that catch people out

**CORS.** The client runs in the browser, so its origin must appear in the
backend's `CORS_ORIGINS`. Ports 5173 (dev), 4173 (`vite preview`) and 5174 are
already listed in `.env.example`; an existing `.env` may need updating. A working
API paired with a blank screen is almost always this.

**`VITE_API_BASE_URL` is baked in at build time**, not read at runtime, and it is
used by the *browser* — so in Docker it must be the published host address, never
the Compose service name.

## Docker

```bash
docker compose up --build
```

Backend on `:8001`, app on `:5173`. Migrations run on container start; the
database, vector store and uploads live in named volumes. You still need to
promote an administrator:

```bash
docker compose exec backend python scripts/promote_to_admin.py you@example.com
```

## Tests

```bash
cd backend  && pytest        # API, RAG pipeline, guardrails, auth, catalogue
cd frontend && npm test      # streaming, token refresh, envelope handling
```

`backend/tests/test_react_contract.py` parses the RTK Query slices for every
path they call and asserts each exists in the OpenAPI schema — so a renamed
route fails in CI rather than becoming a blank screen someone discovers later.

## Design

[`SYSTEM_DESIGN.md`](SYSTEM_DESIGN.md) has the end-to-end workflow as diagrams:
auth and session lifetime, document ingestion with its OCR fallback, the
Corrective RAG pipeline, prompt-injection containment, streaming, the data
model, the model catalogue, account recovery, and deployment.
