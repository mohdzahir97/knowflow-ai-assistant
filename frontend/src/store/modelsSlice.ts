/**
 * The chosen chat and embedding models.
 *
 * Shared state rather than page state because the Knowledge base indexes with
 * the selected embedding model while Chat answers with the selected chat
 * model. The choice persists in localStorage so a reload does not reset it.
 *
 * End users never choose an embedding model: it decides which knowledge-base
 * partition is searched, which is an operational concern they should not have
 * to think about. One is selected for them silently.
 */
import { createSlice, type PayloadAction } from "@reduxjs/toolkit";

import type { ProviderInfo } from "../api/types";

const STORAGE_KEY = "aika.model_selection";

export interface ModelsState {
  chatProvider: string;
  chatModel: string;
  embeddingProvider: string;
  embeddingModel: string;
  /** True once a complete, usable selection exists. */
  ready: boolean;
}

function readStored(): Partial<ModelsState> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Partial<ModelsState>) : {};
  } catch {
    return {};
  }
}

function persist(state: ModelsState): void {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        chatProvider: state.chatProvider,
        chatModel: state.chatModel,
        embeddingProvider: state.embeddingProvider,
        embeddingModel: state.embeddingModel,
      }),
    );
  } catch {
    /* the selection simply will not persist */
  }
}

const stored = readStored();

const initialState: ModelsState = {
  chatProvider: stored.chatProvider ?? "",
  chatModel: stored.chatModel ?? "",
  embeddingProvider: stored.embeddingProvider ?? "",
  embeddingModel: stored.embeddingModel ?? "",
  ready: false,
};

/** Prefer a provider that is actually configured on the server. */
function firstConfigured(providers: ProviderInfo[]): ProviderInfo | undefined {
  return providers.find((provider) => provider.is_configured) ?? providers[0];
}

function recomputeReady(state: ModelsState): void {
  state.ready = Boolean(
    state.chatProvider && state.chatModel && state.embeddingProvider && state.embeddingModel,
  );
}

const modelsSlice = createSlice({
  name: "models",
  initialState,
  reducers: {
    /**
     * Fill in or repair the selection against what the server currently offers.
     *
     * A stored choice can name a model an administrator has since disabled, so
     * it is validated rather than trusted - otherwise the app would keep
     * sending a model the server refuses.
     */
    reconcile(
      state,
      action: PayloadAction<{ chat: ProviderInfo[]; embedding: ProviderInfo[] }>,
    ) {
      const { chat, embedding } = action.payload;
      if (chat.length === 0 && embedding.length === 0) return;

      const chatProvider =
        chat.find((provider) => provider.provider === state.chatProvider) ?? firstConfigured(chat);
      state.chatProvider = chatProvider?.provider ?? "";
      if (!chatProvider?.models.includes(state.chatModel)) {
        state.chatModel = chatProvider?.models[0] ?? "";
      }

      const embeddingProvider =
        embedding.find((provider) => provider.provider === state.embeddingProvider) ??
        firstConfigured(embedding);
      state.embeddingProvider = embeddingProvider?.provider ?? "";
      if (!embeddingProvider?.models.includes(state.embeddingModel)) {
        state.embeddingModel = embeddingProvider?.models[0] ?? "";
      }

      recomputeReady(state);
      persist(state);
    },
    chatProviderSelected(state, action: PayloadAction<string>) {
      state.chatProvider = action.payload;
      // Cleared so `reconcile` picks a valid model for the new provider
      // instead of carrying over one it does not offer.
      state.chatModel = "";
      recomputeReady(state);
      persist(state);
    },
    chatModelSelected(state, action: PayloadAction<string>) {
      state.chatModel = action.payload;
      recomputeReady(state);
      persist(state);
    },
    embeddingProviderSelected(state, action: PayloadAction<string>) {
      state.embeddingProvider = action.payload;
      state.embeddingModel = "";
      recomputeReady(state);
      persist(state);
    },
    embeddingModelSelected(state, action: PayloadAction<string>) {
      state.embeddingModel = action.payload;
      recomputeReady(state);
      persist(state);
    },
  },
});

export const {
  reconcile,
  chatProviderSelected,
  chatModelSelected,
  embeddingProviderSelected,
  embeddingModelSelected,
} = modelsSlice.actions;

export default modelsSlice.reducer;
