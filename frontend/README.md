# AI Company Knowledge Assistant — React frontend

A React + TypeScript client for the same FastAPI backend, using **Redux
Toolkit** and **RTK Query**.

This is a migration of the Streamlit client in [`../frontend`](../frontend),
which is still present and still works. Both talk to the same API and can run
side by side; nothing about the backend prefers one over the other.

## Why a second client

Streamlit re-executes the whole script on every interaction. That model fought
the two things this app most needs — rendering tokens as they stream in, and
not repainting the page when a single control changes — and the workarounds
(fragments, scoped reruns, state written before network calls) were load-bearing
rather than incidental. A normal SPA gets both for free, and the API was
already a plain JSON service with no server-rendered state.

What is genuinely better here, rather than just different:

- **Streaming.** Tokens append to store state as lines arrive. No fragment
  tricks, and the transcript survives navigating to another page and back.
- **Cache invalidation.** RTK Query tags mean uploading a document updates the
  document list and the metrics without a manual refetch anywhere.
- **One refresh, not one per request.** Concurrent 401s share a single token
  refresh (see below) — the Streamlit client refreshed per call.

What is worse: it needs a build step and CORS.

## Prerequisites

- Node.js 20+ (developed on 24) and npm
- The backend running and reachable — see [`../backend/README.md`](../backend/README.md)
- The backend must allow this app's **browser origin** in `CORS_ORIGINS`.
  Unlike the Streamlit client, which calls the API server-side, this one is
  subject to CORS. `backend/.env.example` already lists ports 5173 (dev), 4173 (preview)
  and 5174 (container); an existing `backend/.env` may need updating.

## Setup

```bash
cd frontend-react
npm install
cp .env.example .env      # optional: the default backend URL is localhost:8001
npm run dev
```

Opens at `http://localhost:5173`.

| Script | Purpose |
|---|---|
| `npm run dev` | Dev server with hot reload |
| `npm run build` | Type-check, then bundle to `dist/` |
| `npm run preview` | Serve the built bundle (port 4173) |
| `npm test` | Run the store/API tests |
| `npm run typecheck` | Type-check only |

| Variable | Purpose | Default |
|---|---|---|
| `VITE_API_BASE_URL` | Backend base URL. Read by the **browser**, so in Docker this is the published host address, never a Compose service name. | `http://localhost:8001` |

## Architecture

```
src/
├── api/
│   ├── types.ts        # Mirrors the backend's Pydantic schemas
│   ├── baseQuery.ts    # Envelope unwrapping + single-flight token refresh
│   └── apiSlice.ts     # Every endpoint, with cache tags
├── store/
│   ├── index.ts        # configureStore
│   ├── hooks.ts        # Typed useAppDispatch / useAppSelector
│   ├── authSlice.ts    # Tokens only
│   ├── session.ts      # useSession(): who is signed in
│   ├── chatSlice.ts    # The conversation + streaming thunks
│   ├── modelsSlice.ts  # Model selection, persisted
│   └── uiSlice.ts      # Theme, toasts, mobile drawer
├── styles/             # Design tokens and component styles
├── components/
│   ├── ui/             # Primitives: Button, Field, Card, Alert, Icon...
│   ├── Sidebar.tsx
│   ├── ChatHistory.tsx
│   └── ToastHost.tsx   # Toast rendering + theme application
└── pages/              # SignIn, Chat, KnowledgeBase, Administration, Account
```

### What lives where, and why

**RTK Query owns anything with a settled result** — profile, providers,
documents, projects, chats, metrics, audit, the model catalogue. Mutations
declare the tags they invalidate, so the UI refreshes itself.

**Redux slices own state RTK Query cannot model.** A streamed answer has no
single result until it finishes: expressing it as a query would mean buffering
every token and rendering nothing until the end — exactly the behaviour this
app exists to avoid. So `chatSlice` holds the transcript and a thunk dispatches
tokens into it as they arrive.

**The envelope is unwrapped in `baseQuery`.** The API always replies
`{success, message, data, errors}`; endpoints are typed as the payload they
actually return instead of every component reaching through `.data.data`. A
`success: false` body becomes an error even on a 2xx, so a failure can never be
mistaken for data.

**Token refresh is single-flight.** The backend rotates and revokes the refresh
token when it is used, so several concurrent 401s must not each try to refresh —
the first would succeed and the rest would present a token that had just been
revoked, signing the user out mid page load. One shared promise prevents that.

**Restoring a session needs no special code.** Asking for the profile with a
stored refresh token but no access token produces a 401, which the base query
refreshes and retries. So "am I signed in?" is just "did the profile query
succeed?", with no second copy of that state to keep in sync.

### Tokens

The access token is held in the store, in memory. Only the refresh token is
mirrored into `localStorage`, so closing the tab does not destroy the session
while a stolen snapshot yields a credential the server can revoke.

A cookie-based scheme would resist XSS better. It would also need CSRF
protection, which the API deliberately does not implement because nothing
authenticates from a cookie today — so switching would be a backend change
too, not a frontend one.

Signing out resets the RTK Query cache. Without that, the next account to sign
in on the same browser would briefly see the previous one's cached documents,
chats and metrics.

## Design

There is no component library and no CSS framework. The UI is about twenty
screens over a JSON API; a framework would be more to install, learn and keep
current than that justifies, and a token-based stylesheet is easier to audit
than a config file plus utility soup.

```
src/styles/
├── tokens.css      # every colour, space, size, radius, shadow, duration
├── base.css        # reset, typography, focus, scrollbars, utilities
├── components.css  # button, field, card, alert, badge, tabs, table, toast...
└── layout.css      # app shell, sidebar, chat surface, responsive rules
```

**Everything resolves to a token.** No component hard-codes a hex value or a
pixel, so the product can be retuned from one file and light/dark cannot drift
apart. Palettes are declared three times deliberately: on bare `:root` (light),
under `prefers-color-scheme: dark` guarded by `:not([data-theme="light"])`, and
under `[data-theme="dark"]` — so the in-app toggle beats the OS in *both*
directions, and a viewer who has chosen light does not get a dark flash.

Dark is not the light palette with values inverted. The accent lifts from
indigo-600 to indigo-400, because mid-tone indigo on a near-black surface does
not clear contrast requirements for text or icons, and shadows are deepened
because the light ones are invisible on dark surfaces.

**Primitives wrap real elements.** `Button` is a `<button>` with classes, not a
re-implementation — native form submission, focus and disabled semantics are
kept for free. `Field` takes a render function so the generated `id` reaches
the control, which is what stops an unlabelled input reaching a screen reader.

**Icons are inline SVG** on a 24-unit grid at a single stroke weight, coloured
by `currentColor`. Twenty-odd glyphs is not worth a dependency, and a
hand-drawn set stays consistent in weight next to the type.

### Details that matter in use

- **Streaming** shows a spinner labelled with what is happening during
  retrieval — which is seconds on a local embedding model — then a blinking
  caret while tokens arrive. An empty bubble reads as broken.
- **Autoscroll only while you are at the bottom.** Scroll up to re-read
  something and the view stays put; a "Jump to latest" button appears instead.
  Yanking the viewport mid-read is worse than a stale one.
- **Destructive actions get a real dialog**, not `window.confirm`, so the
  wording can say what is actually at stake — clearing the knowledge base
  affects every user, and deleting an embedding model strands the documents
  indexed with it.
- **Skeletons shaped like the content**, not a spinner, so layout does not jump
  when data lands.
- **Empty states explain the next action** rather than saying "no data".
- **Optimism is avoided where it would lie.** Mutations show a spinner on their
  own button and a toast on success; nothing renders as done before the server
  agrees.
- **Row actions appear on hover or focus** on the desktop and are always
  visible on touch, where there is no hover to reveal them.
- **Accessibility**: focus rings only for keyboard users (`:focus-visible`),
  labelled controls throughout, `aria-label` on every icon-only button,
  `role="alert"` on errors, and `prefers-reduced-motion` honoured — every
  animation here is decorative.
- **Responsive**: below 900px the sidebar becomes a drawer over the content
  with a scrim, rather than a column that squeezes the conversation; tap
  targets grow to 40px.

## Feature parity

Everything the Streamlit client does: sign in and registration, forgotten
password and reset, email confirmation, streaming chat with sources, copy and
retry, projects with search and rename/move/delete, admin knowledge base
(upload, manage, per-document retrieval testing), administration (metrics,
model catalogue, audit trail), and the account page with sign-in history.

Authorization is unchanged and unchanged-able from here: admin routes are
simply absent for a non-admin, and the backend refuses admin endpoints
regardless of what this client renders.

## Tests

`npm test` covers the logic where a bug would be invisible until it corrupted
an answer or signed someone out:

- NDJSON framing, including an event split across a network chunk boundary,
  several events in one chunk, a final line with no trailing newline, and a
  malformed line
- retract handling, and keeping the question on screen when an answer fails
- single-flight refresh, session end on rejection, session **kept** on a
  network failure
- envelope unwrapping and `success: false` on a 2xx
- model selection repair when a stored model is no longer offered

The screens themselves are verified by using them; these tests deliberately
target the parts that are hard to eyeball.

> Tests run in the `node` environment, not jsdom. jsdom supplies its own
> `AbortSignal`, a different realm from the one Node's `fetch` expects, and
> `fetchBaseQuery` passes a signal on every request — under jsdom every call
> fails with "Expected signal to be an instance of AbortSignal". Nothing under
> test needs a DOM, only `fetch` and `localStorage`; `src/test/setup.ts`
> provides the latter.

## Deployment

`npm run build` emits static files in `dist/`. Serve them from any static host
and point `VITE_API_BASE_URL` at the API. Two things to get right:

- **History fallback.** Client-side routes such as `/reset-password` must serve
  `index.html` rather than 404, or emailed links break on a page reload.
- **CORS.** Add the deployed origin to the backend's `CORS_ORIGINS`.
