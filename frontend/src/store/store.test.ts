/**
 * Tests for the store logic that would fail silently.
 *
 * The screens are verified by using them. These cover behaviour where a bug
 * is invisible until it corrupts an answer or signs someone out: NDJSON
 * framing across network chunk boundaries, single-flight token refresh, and
 * envelope unwrapping.
 */
import { configureStore } from "@reduxjs/toolkit";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiSlice } from "../api/apiSlice";
import authReducer, { sessionEnded, tokensReceived } from "./authSlice";
import chatReducer, { bindTokenReader, conversationCleared, sendQuestion } from "./chatSlice";
import modelsReducer, { chatProviderSelected, reconcile } from "./modelsSlice";
import uiReducer from "./uiSlice";
import type { ProviderInfo } from "../api/types";

function makeStore() {
  const store = configureStore({
    reducer: {
      [apiSlice.reducerPath]: apiSlice.reducer,
      auth: authReducer,
      chat: chatReducer,
      models: modelsReducer,
      // Mirrors the real store: a thunk typed against RootState is not
      // assignable to a store whose state shape differs.
      ui: uiReducer,
    },
    middleware: (getDefault) => getDefault().concat(apiSlice.middleware),
  });
  // The real store does this in `store/index.ts`. Without it the retry
  // reads a null token and the assertion below would pass vacuously.
  bindTokenReader(() => store.getState().auth.accessToken);
  return store;
}

type Store = ReturnType<typeof makeStore>;

function envelope<T>(data: T, success = true, message = "ok", errors: string[] | null = null) {
  return { success, message, data, errors };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** A Response whose body streams the given chunks, in order. */
function streamingResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "application/x-ndjson" } });
}

/**
 * Installs a fetch mock that models how RTK Query actually calls fetch.
 *
 * `fetchBaseQuery` passes a single `Request` object rather than (url, init),
 * so a mock that reads `init.headers` sees undefined and one that inspects
 * `String(input)` gets "[object Request]". The handler here is given the
 * resolved url and headers, whichever calling convention was used.
 */
function mockFetch(
  handler: (context: { url: string; headers: Headers; method: string }) => Promise<Response>,
) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const request = input instanceof Request ? input : new Request(String(input), init);
    return handler({
      url: request.url,
      headers: new Headers(request.headers),
      method: request.method,
    });
  });
}

const tokenPair = {
  access_token: "access-1",
  refresh_token: "refresh-1",
  token_type: "bearer",
  expires_in: 3600,
};

/** A ready model selection, so `sendQuestion` is not refused up front. */
function selectModels(store: Store) {
  const chat: ProviderInfo[] = [
    { provider: "testchat", display_name: "Test", models: ["fake-model"], is_configured: true },
  ];
  const embedding: ProviderInfo[] = [
    { provider: "testembed", display_name: "Test", models: ["fake-embed"], is_configured: true },
  ];
  store.dispatch(reconcile({ chat, embedding }));
}

let store: Store;

beforeEach(() => {
  localStorage.clear();
  store = makeStore();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("answer streaming", () => {
  it("reassembles an event split across chunk boundaries", async () => {
    // The realistic failure: a chunk ends mid-JSON. Parsing per chunk would
    // drop this token entirely.
    const line = JSON.stringify({ type: "token", content: "hello world" });
    const cut = Math.floor(line.length / 2);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      streamingResponse([
        line.slice(0, cut),
        line.slice(cut) + "\n" + JSON.stringify({ type: "done", session_id: "s1" }) + "\n",
      ]),
    );

    selectModels(store);
    await store.dispatch(sendQuestion("what is the leave policy?"));

    const { messages, sessionId, streaming } = store.getState().chat;
    expect(messages).toEqual([
      { role: "user", content: "what is the leave policy?" },
      { role: "assistant", content: "hello world", sources: [], meta: "0 ms" },
    ]);
    expect(sessionId).toBe("s1");
    expect(streaming).toBe(false);
  });

  it("accumulates several tokens arriving in one chunk", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      streamingResponse([
        JSON.stringify({ type: "token", content: "a" }) +
          "\n" +
          JSON.stringify({ type: "token", content: "b" }) +
          "\n" +
          JSON.stringify({ type: "done", session_id: "s1" }) +
          "\n",
      ]),
    );

    selectModels(store);
    await store.dispatch(sendQuestion("q"));

    expect(store.getState().chat.messages[1]?.content).toBe("ab");
  });

  it("handles a final event with no trailing newline", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      streamingResponse([
        JSON.stringify({ type: "token", content: "done-ish" }) +
          "\n" +
          JSON.stringify({ type: "done", session_id: "s2" }),
      ]),
    );

    selectModels(store);
    await store.dispatch(sendQuestion("q"));

    expect(store.getState().chat.sessionId).toBe("s2");
  });

  it("skips a malformed line rather than ending the stream", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      streamingResponse([
        "{not json}\n" + JSON.stringify({ type: "token", content: "survived" }) + "\n",
      ]),
    );

    selectModels(store);
    await store.dispatch(sendQuestion("q"));

    expect(store.getState().chat.messages[1]?.content).toBe("survived");
  });

  it("replaces the answer when the backend retracts it", async () => {
    // A retracted answer failed groundedness verification after being shown;
    // appending would leave unsupported text on screen.
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      streamingResponse([
        JSON.stringify({ type: "token", content: "Employees get 40 days." }) +
          "\n" +
          JSON.stringify({ type: "retract", content: "I could not verify that." }) +
          "\n" +
          JSON.stringify({ type: "done", session_id: "s1" }) +
          "\n",
      ]),
    );

    selectModels(store);
    await store.dispatch(sendQuestion("q"));

    const answer = store.getState().chat.messages[1];
    expect(answer?.content).toBe("I could not verify that.");
    expect(answer?.sources).toEqual([]);
  });

  it("keeps the question on screen when the answer fails", async () => {
    // So it can be retried without retyping.
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(envelope(null, false, "The knowledge base is empty."), 404),
    );

    selectModels(store);
    await store.dispatch(sendQuestion("q"));

    const { messages, error } = store.getState().chat;
    expect(messages[0]).toEqual({ role: "user", content: "q" });
    expect(messages[1]?.failed).toBe(true);
    expect(error).toContain("The knowledge base is empty.");
  });

  it("refuses to send before a model has been chosen", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    await store.dispatch(sendQuestion("q"));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(store.getState().chat.error).toMatch(/Select a chat model/);
  });

  it("clears the conversation on request", () => {
    store.dispatch(conversationCleared());
    expect(store.getState().chat).toMatchObject({ sessionId: null, messages: [] });
  });
});

describe("base query", () => {
  it("unwraps the response envelope", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(envelope([{ id: "p1" }])));
    const result = await store.dispatch(apiSlice.endpoints.getProjects.initiate());
    expect(result.data).toEqual([{ id: "p1" }]);
  });

  it("treats a success:false body as an error even with a 200 status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(envelope(null, false, "Something went wrong.")),
    );
    const result = await store.dispatch(apiSlice.endpoints.getProjects.initiate());
    expect(result.error).toMatchObject({ message: "Something went wrong." });
  });

  it("surfaces per-field validation details", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(
        envelope(null, false, "Validation failed.", ["Password must contain a digit."]),
        422,
      ),
    );
    const result = await store.dispatch(
      apiSlice.endpoints.register.initiate({ email: "a@b.c", password: "x", full_name: null }),
    );
    expect(result.error).toMatchObject({
      message: "Validation failed.",
      details: ["Password must contain a digit."],
    });
  });

  it("reports a non-JSON response rather than a parse crash", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("<html>502 Bad Gateway</html>", { status: 502 }),
    );
    const result = await store.dispatch(apiSlice.endpoints.getProjects.initiate());
    expect(result.error).toBeDefined();
  });

  it("sends the access token once one is held", async () => {
    store.dispatch(tokensReceived(tokenPair));
    let seen: string | null = null;
    mockFetch(async ({ headers }) => {
      seen = headers.get("authorization");
      return jsonResponse(envelope([]));
    });

    await store.dispatch(apiSlice.endpoints.getProjects.initiate());

    expect(seen).toBe("Bearer access-1");
  });
});

describe("token refresh", () => {
  it("refreshes then retries with the new token", async () => {
    store.dispatch(tokensReceived(tokenPair));
    const fetchMock = mockFetch(async ({ url, headers }) => {
      if (url.endsWith("/api/v1/auth/refresh")) {
        return jsonResponse(envelope({ ...tokenPair, access_token: "access-2" }));
      }
      return headers.get("authorization") === "Bearer access-1"
        ? jsonResponse(envelope(null, false, "expired"), 401)
        : jsonResponse(envelope([{ id: "p1" }]));
    });

    const result = await store.dispatch(apiSlice.endpoints.getProjects.initiate());

    expect(result.data).toEqual([{ id: "p1" }]);
    expect(store.getState().auth.accessToken).toBe("access-2");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("refreshes only once when several requests get a 401 together", async () => {
    // The backend rotates and revokes the refresh token on use, so a second
    // concurrent refresh would present a token that had just been revoked and
    // sign the user out mid page load.
    store.dispatch(tokensReceived(tokenPair));
    let refreshCalls = 0;

    mockFetch(async ({ url, headers }) => {
      if (url.endsWith("/api/v1/auth/refresh")) {
        refreshCalls += 1;
        return jsonResponse(envelope({ ...tokenPair, access_token: "access-2" }));
      }
      return headers.get("authorization") === "Bearer access-1"
        ? jsonResponse(envelope(null, false, "expired"), 401)
        : jsonResponse(envelope([]));
    });

    await Promise.all([
      store.dispatch(apiSlice.endpoints.getProjects.initiate()),
      store.dispatch(apiSlice.endpoints.getDocuments.initiate()),
      store.dispatch(apiSlice.endpoints.getMetrics.initiate()),
    ]);

    expect(refreshCalls).toBe(1);
  });

  it("ends the session when the server rejects the refresh", async () => {
    store.dispatch(tokensReceived(tokenPair));
    // A fresh Response per call: a body can only be read once, so reusing one
    // instance would hand the refresh an already-consumed body and it would
    // fail as a parse error rather than the 401 this test is about.
    mockFetch(async () => jsonResponse(envelope(null, false, "revoked"), 401));

    await store.dispatch(apiSlice.endpoints.getProjects.initiate());

    expect(store.getState().auth.refreshToken).toBeNull();
    expect(localStorage.getItem("aika.refresh_token")).toBeNull();
  });

  it("keeps the session when refreshing fails on the network", async () => {
    // A brief backend outage must not sign everyone out.
    store.dispatch(tokensReceived(tokenPair));
    mockFetch(async ({ url }) => {
      if (url.endsWith("/api/v1/auth/refresh")) throw new TypeError("network down");
      return jsonResponse(envelope(null, false, "expired"), 401);
    });

    await store.dispatch(apiSlice.endpoints.getProjects.initiate());

    expect(store.getState().auth.refreshToken).toBe("refresh-1");
  });

  it("does not try to refresh when there is no session to repair", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse(envelope(null, false, "Invalid credentials."), 401));

    await store.dispatch(
      apiSlice.endpoints.login.initiate({ email: "a@b.c", password: "wrong" }),
    );

    // One call only: a failed login is not an expired session.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("model selection", () => {
  const chat: ProviderInfo[] = [
    { provider: "openai", display_name: "OpenAI", models: ["gpt-4o"], is_configured: false },
    { provider: "ollama", display_name: "Ollama", models: ["llama3.1"], is_configured: true },
  ];
  const embedding: ProviderInfo[] = [
    { provider: "ollama", display_name: "Ollama", models: ["nomic-embed-text"], is_configured: true },
  ];

  it("prefers a provider that is actually configured", () => {
    store.dispatch(reconcile({ chat, embedding }));
    expect(store.getState().models.chatProvider).toBe("ollama");
    expect(store.getState().models.ready).toBe(true);
  });

  it("replaces a stored model the server no longer offers", () => {
    // The realistic case: an administrator disabled it in the catalogue.
    store.dispatch(reconcile({ chat, embedding }));
    const withoutLlama: ProviderInfo[] = [
      { provider: "ollama", display_name: "Ollama", models: ["mistral"], is_configured: true },
    ];
    store.dispatch(reconcile({ chat: withoutLlama, embedding }));

    expect(store.getState().models.chatModel).toBe("mistral");
  });

  it("picks a valid model when the provider changes", () => {
    store.dispatch(reconcile({ chat, embedding }));
    store.dispatch(chatProviderSelected("openai"));
    // Cleared, then repaired on the next reconcile against the catalogue.
    expect(store.getState().models.chatModel).toBe("");
    store.dispatch(reconcile({ chat, embedding }));
    expect(store.getState().models.chatModel).toBe("gpt-4o");
  });

  it("persists the selection across a reload", () => {
    store.dispatch(reconcile({ chat, embedding }));
    const stored = JSON.parse(localStorage.getItem("aika.model_selection") ?? "{}");
    expect(stored).toMatchObject({ chatProvider: "ollama", chatModel: "llama3.1" });
  });
});

describe("streaming and auth", () => {
  it("refreshes an expired token and retries the stream", async () => {
    // The streaming path bypasses the RTK Query base query, so it does not
    // inherit its refresh-and-retry. Without this, the first question asked
    // after an access token expires fails outright.
    store.dispatch(tokensReceived(tokenPair));
    selectModels(store);
    let refreshCalls = 0;
    let streamAuth: string | null = null;

    mockFetch(async ({ url, headers }) => {
      if (url.endsWith("/api/v1/auth/refresh")) {
        refreshCalls += 1;
        return jsonResponse(envelope({ ...tokenPair, access_token: "access-2" }));
      }
      if (headers.get("authorization") === "Bearer access-1") {
        return jsonResponse(envelope(null, false, "expired"), 401);
      }
      streamAuth = headers.get("authorization");
      return streamingResponse([
        JSON.stringify({ type: "token", content: "fresh answer" }) +
          "\n" +
          JSON.stringify({ type: "done", session_id: "s1" }) +
          "\n",
      ]);
    });

    await store.dispatch(sendQuestion("q"));

    expect(refreshCalls).toBe(1);
    // The retry must present the new token, not the one that just expired.
    expect(streamAuth).toBe("Bearer access-2");
    expect(store.getState().chat.messages[1]?.content).toBe("fresh answer");
    expect(store.getState().chat.messages[1]?.failed).toBeUndefined();
  });
});
describe("signing out", () => {
  /**
   * Mirrors how `useSession` decides the user is signed in.
   *
   * The bug this pins: it used to be derived from the cached profile alone.
   * A failed refresh dispatches `sessionEnded`, which clears the tokens but
   * leaves that cache intact - so the app kept rendering the signed-in shell
   * with no credentials, and every request it made went out without an
   * Authorization header. The backend answers those "Not authenticated".
   */
  const looksSignedIn = (state: ReturnType<typeof store.getState>, profileCached: boolean) =>
    Boolean(state.auth.accessToken || state.auth.refreshToken) && profileCached;

  it("stops looking signed in the moment the tokens are cleared", () => {
    store.dispatch(tokensReceived(tokenPair));
    expect(looksSignedIn(store.getState(), true)).toBe(true);

    store.dispatch(sessionEnded());
    // The profile is still cached at this point - that is the whole point.
    expect(looksSignedIn(store.getState(), true)).toBe(false);
  });

  it("clears the persisted refresh token", () => {
    store.dispatch(tokensReceived(tokenPair));
    expect(localStorage.getItem("aika.refresh_token")).toBe("refresh-1");

    store.dispatch(sessionEnded());
    expect(localStorage.getItem("aika.refresh_token")).toBeNull();
  });

  it("sends no authenticated request once the tokens are gone", async () => {
    store.dispatch(tokensReceived(tokenPair));

    const tokenless: string[] = [];
    mockFetch(async ({ url, headers }) => {
      if (!headers.get("authorization")) tokenless.push(url);
      return jsonResponse(envelope([]));
    });

    const subscription = store.dispatch(apiSlice.endpoints.getLoginHistory.initiate(undefined));
    await subscription;

    store.dispatch(sessionEnded());
    await new Promise((resolve) => setTimeout(resolve, 30));

    expect(tokenless).toEqual([]);
  });
});
