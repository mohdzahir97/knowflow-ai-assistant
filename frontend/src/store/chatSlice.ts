/**
 * The open conversation, and the streaming that fills it.
 *
 * Why this is a slice with thunks rather than an RTK Query endpoint: RTK
 * Query caches a *result*, and a streamed answer has no single result until
 * it finishes. Modelling it as a query would mean either buffering every
 * token and rendering nothing until the end - which is exactly the behaviour
 * this app exists to avoid - or abusing the cache as a mutable buffer.
 * Progress belongs in normal Redux state, and the thunk dispatches into it as
 * lines arrive. Everything with a settled result stays in RTK Query.
 *
 * Two behaviours this file guarantees, carried over from the Streamlit client
 * because they were the visible problems there:
 *
 * 1. The question appears the instant Send is pressed and never disappears.
 *    It is dispatched before the request starts.
 * 2. Tokens render as they arrive. Retrieval finishes before the model can
 *    emit anything, which is several seconds on a local embedding model, so
 *    the wait is labelled rather than shown as an empty bubble.
 */
import { createAsyncThunk, createSlice, type PayloadAction } from "@reduxjs/toolkit";

import { API_BASE_URL, refreshSession } from "../api/baseQuery";
import { apiSlice, askBody, type AskArgs } from "../api/apiSlice";
import type { SourceCitation, StreamEvent } from "../api/types";
import type { RootState } from ".";

/**
 * Reads the current access token straight from the store.
 *
 * Needed because a refresh replaces the token *after* the thunk captured its
 * state snapshot; retrying with the captured value would send the token that
 * had just expired. Set once at store creation to avoid importing the store
 * here, which would be a cycle.
 */
let readAccessToken: () => string | null = () => null;

export function bindTokenReader(reader: () => string | null): void {
  readAccessToken = reader;
}

export interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: SourceCitation[];
  meta?: string;
  failed?: boolean;
}

interface ChatState {
  sessionId: string | null;
  messages: Message[];
  streaming: boolean;
  /** The answer so far, while it is still arriving. */
  partial: string | null;
  /** What is happening before the first token, e.g. retrieval. */
  status: string | null;
  error: string | null;
}

const initialState: ChatState = {
  sessionId: null,
  messages: [],
  streaming: false,
  partial: null,
  status: null,
  error: null,
};

/**
 * Reads the NDJSON answer stream.
 *
 * Uses fetch directly rather than the RTK Query base query, which resolves a
 * whole body before returning and so cannot expose a partial response. The
 * access token is read from the store so this stays consistent with every
 * other request.
 */
async function* streamAnswer(
  args: AskArgs,
  auth: { accessToken: string | null; refreshToken: string | null },
  dispatch: (action: { type: string; payload?: unknown }) => void,
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const send = (accessToken: string | null): Promise<Response> => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (accessToken) headers.Authorization = "Bearer " + accessToken;
    return fetch(API_BASE_URL + "/api/v1/chat/ask/stream", {
      method: "POST",
      headers,
      body: JSON.stringify(askBody(args)),
      signal,
    });
  };

  let response = await send(auth.accessToken);

  // A 401 arrives before any body, so refresh-and-retry is still possible.
  // Shares the base query's mutex, so a stream and a query racing on an
  // expired token cause one refresh between them, not two.
  if (response.status === 401) {
    const refreshed = await refreshSession(dispatch, auth.refreshToken);
    if (refreshed) response = await send(readAccessToken());
  }

  if (!response.ok) {
    // Failures before streaming starts still use the normal envelope.
    let message = "Request failed with status " + response.status + ".";
    try {
      const payload = (await response.json()) as { message?: string };
      if (payload?.message) message = payload.message;
    } catch {
      /* keep the generic message */
    }
    throw new Error(message);
  }
  if (!response.body) throw new Error("The server sent no response body.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // One complete JSON object per line. A network chunk can end mid-line, so
    // the remainder stays buffered for the next read.
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        yield JSON.parse(line) as StreamEvent;
      } catch {
        // Skip a malformed line rather than killing the stream.
      }
    }
  }

  if (buffer.trim()) {
    try {
      yield JSON.parse(buffer) as StreamEvent;
    } catch {
      /* ignore a truncated trailing line */
    }
  }
}

/** Streams one answer for a question that is already in the transcript. */
const runStream = createAsyncThunk<
  void,
  { question: string },
  { state: RootState; rejectValue: string }
>("chat/runStream", async ({ question }, { getState, dispatch, signal }) => {
  const state = getState();
  const { chatProvider, chatModel, embeddingProvider, embeddingModel } = state.models;

  dispatch(streamStarted());

  let answer = "";
  let sources: SourceCitation[] = [];
  let meta = "";
  let sessionId: string | null = state.chat.sessionId;
  let failure: string | null = null;

  try {
    for await (const event of streamAnswer(
      {
        question,
        provider: chatProvider,
        model: chatModel,
        embedding_provider: embeddingProvider,
        embedding_model: embeddingModel,
        session_id: state.chat.sessionId,
      },
      { accessToken: state.auth.accessToken, refreshToken: state.auth.refreshToken },
      dispatch,
      signal,
    )) {
      if (event.type === "token") {
        answer += event.content;
        dispatch(tokenReceived(answer));
      } else if (event.type === "retract") {
        // The answer failed groundedness verification after being shown.
        // Replace it rather than leaving unsupported text on screen.
        answer = event.content;
        sources = [];
        dispatch(tokenReceived(answer));
      } else if (event.type === "done") {
        sources = event.sources ?? [];
        sessionId = event.session_id;
        meta = Math.round(event.total_time_ms ?? 0) + " ms";
        const total = event.token_usage?.total_tokens;
        if (total) meta += " - " + total + " tokens";
      } else if (event.type === "error") {
        failure = event.message;
      }
    }
  } catch (caught) {
    // An abort is the user navigating away, not a failure to report.
    if ((caught as Error).name !== "AbortError") failure = (caught as Error).message;
  }

  if (failure) {
    dispatch(streamFailed(failure));
    return;
  }

  dispatch(streamFinished({ content: answer.trim(), sources, meta, sessionId }));
  // A new conversation now exists server-side, so the history list is stale.
  dispatch(apiSlice.util.invalidateTags(["Chat"]));
});

/** Ask a new question. */
export const sendQuestion = createAsyncThunk<void, string, { state: RootState }>(
  "chat/sendQuestion",
  async (question, { dispatch, getState }) => {
    const asked = question.trim();
    if (!asked) return;
    if (!getState().models.ready) {
      dispatch(streamFailed("Select a chat model before asking a question."));
      return;
    }
    // Dispatched before the request starts, which is what makes the question
    // appear instantly.
    dispatch(questionAsked(asked));
    await dispatch(runStream({ question: asked }));
  },
);

/**
 * Redo the last exchange instead of appending a second answer to it.
 *
 * The stored question and answer are removed server-side first. Otherwise the
 * old answer would survive in the database, reappear on reload, and be fed
 * back to the model as conversation history.
 */
export const retryLastAnswer = createAsyncThunk<void, void, { state: RootState }>(
  "chat/retryLastAnswer",
  async (_arg, { dispatch, getState }) => {
    const { sessionId, messages } = getState().chat;
    let question: string | null = null;

    if (sessionId) {
      try {
        const session = await dispatch(
          apiSlice.endpoints.getChatSession.initiate(sessionId, { forceRefetch: true }),
        ).unwrap();

        const stored = [...session.messages];
        const doomed = [];
        // Walk back over the trailing answer(s) - a retracted or failed turn
        // can leave more than one - to the question that produced them.
        while (stored.length > 0 && stored[stored.length - 1]?.role === "assistant") {
          doomed.push(stored.pop()!);
        }
        if (stored.length > 0 && stored[stored.length - 1]?.role === "user") {
          const last = stored.pop()!;
          question = last.content;
          doomed.push(last);
        }
        for (const message of doomed) {
          await dispatch(
            apiSlice.endpoints.deleteMessage.initiate({ messageId: message.id, sessionId }),
          ).unwrap();
        }
      } catch (caught) {
        dispatch(streamFailed((caught as { message?: string }).message ?? "Could not retry."));
        return;
      }
    }

    if (question === null) {
      // No persisted session yet, so fall back to what is on screen.
      question = [...messages].reverse().find((message) => message.role === "user")?.content ?? null;
      if (question === null) return;
    }

    dispatch(trailingAnswersDropped());
    await dispatch(runStream({ question }));
  },
);

/** Open an existing conversation, fetching its messages from the server. */
export const openConversation = createAsyncThunk<void, string, { state: RootState }>(
  "chat/openConversation",
  async (chatId, { dispatch }) => {
    try {
      // Not read from cache: messages can be deleted elsewhere in the UI, and
      // a stale copy would silently show removed content.
      const session = await dispatch(
        apiSlice.endpoints.getChatSession.initiate(chatId, { forceRefetch: true }),
      ).unwrap();

      dispatch(
        conversationOpened({
          sessionId: session.id,
          messages: session.messages.map((message) => ({
            role: message.role,
            content: message.content,
            sources: message.sources ?? [],
          })),
        }),
      );
    } catch (caught) {
      dispatch(streamFailed((caught as { message?: string }).message ?? "Could not open that chat."));
    }
  },
);

const chatSlice = createSlice({
  name: "chat",
  initialState,
  reducers: {
    questionAsked(state, action: PayloadAction<string>) {
      state.messages.push({ role: "user", content: action.payload });
      state.error = null;
    },
    streamStarted(state) {
      state.streaming = true;
      state.error = null;
      state.partial = "";
      state.status = "Searching the knowledge base...";
    },
    tokenReceived(state, action: PayloadAction<string>) {
      state.partial = action.payload;
      state.status = null;
    },
    streamFinished(
      state,
      action: PayloadAction<{
        content: string;
        sources: SourceCitation[];
        meta: string;
        sessionId: string | null;
      }>,
    ) {
      const { content, sources, meta, sessionId } = action.payload;
      state.messages.push({ role: "assistant", content, sources, meta });
      state.sessionId = sessionId;
      state.streaming = false;
      state.partial = null;
      state.status = null;
    },
    streamFailed(state, action: PayloadAction<string>) {
      state.streaming = false;
      state.partial = null;
      state.status = null;
      state.error = action.payload;
      // The question stays in the transcript so it can be retried without
      // retyping; only the failed answer is marked.
      if (state.messages[state.messages.length - 1]?.role === "user") {
        state.messages.push({
          role: "assistant",
          content: "Could not answer: " + action.payload,
          failed: true,
        });
      }
    },
    trailingAnswersDropped(state) {
      while (state.messages[state.messages.length - 1]?.role === "assistant") state.messages.pop();
    },
    conversationOpened(
      state,
      action: PayloadAction<{ sessionId: string; messages: Message[] }>,
    ) {
      state.sessionId = action.payload.sessionId;
      state.messages = action.payload.messages;
      state.partial = null;
      state.status = null;
      state.error = null;
    },
    conversationCleared(state) {
      state.sessionId = null;
      state.messages = [];
      state.partial = null;
      state.status = null;
      state.error = null;
    },
    errorDismissed(state) {
      state.error = null;
    },
  },
});

export const {
  questionAsked,
  streamStarted,
  tokenReceived,
  streamFinished,
  streamFailed,
  trailingAnswersDropped,
  conversationOpened,
  conversationCleared,
  errorDismissed,
} = chatSlice.actions;

export default chatSlice.reducer;
