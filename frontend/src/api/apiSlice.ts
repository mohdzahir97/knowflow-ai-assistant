/**
 * Every endpoint, in one RTK Query slice.
 *
 * Tags are what make the UI stay honest without manual refetching: uploading
 * a document invalidates "Document" and "Metrics", editing the model
 * catalogue invalidates "Model" and "Provider" (so the pickers update), and
 * asking a question invalidates "Chat" (so a new conversation appears in the
 * history). Anything a mutation can change must be listed, or the screen
 * quietly shows stale data.
 */
import { createApi } from "@reduxjs/toolkit/query/react";

import { baseQueryWithReauth, type EnvelopeMeta } from "./baseQuery";
import type {
  AuditEvent,
  ChatResponse,
  ChatSessionRead,
  ChatSummary,
  DocumentRead,
  LoginHistoryEntry,
  Metrics,
  Profile,
  ProjectRead,
  ProviderInfo,
  ProviderModel,
  TokenPair,
} from "./types";

/** Upload returns what was indexed *and* what failed, which can be both. */
export interface UploadResult {
  documents: DocumentRead[];
  warnings: string[];
}

export interface AskArgs {
  question: string;
  provider: string;
  model: string;
  embedding_provider?: string | undefined;
  embedding_model?: string | undefined;
  session_id?: string | null;
  document_id?: string | null;
}

/** Drops empty optional fields so the server sees them as absent. */
export function askBody(args: AskArgs): Record<string, unknown> {
  const body: Record<string, unknown> = {
    question: args.question,
    provider: args.provider,
    model: args.model,
  };
  if (args.embedding_provider) body.embedding_provider = args.embedding_provider;
  if (args.embedding_model) body.embedding_model = args.embedding_model;
  if (args.session_id) body.session_id = args.session_id;
  if (args.document_id) body.document_id = args.document_id;
  return body;
}

export const apiSlice = createApi({
  reducerPath: "api",
  baseQuery: baseQueryWithReauth,
  tagTypes: [
    "Profile",
    "Provider",
    "Document",
    "Project",
    "Chat",
    "ChatSession",
    "Metrics",
    "Audit",
    "Model",
    "LoginHistory",
  ],
  endpoints: (builder) => ({
    // --- Auth ---
    login: builder.mutation<TokenPair, { email: string; password: string }>({
      query: (body) => ({ url: "/api/v1/auth/login", method: "POST", body }),
    }),
    register: builder.mutation<
      Profile,
      { email: string; password: string; full_name: string | null }
    >({
      query: (body) => ({ url: "/api/v1/auth/register", method: "POST", body }),
    }),
    logout: builder.mutation<null, { refresh_token: string }>({
      query: (body) => ({ url: "/api/v1/auth/logout", method: "POST", body }),
    }),
    getProfile: builder.query<Profile, void>({
      query: () => "/api/v1/auth/me",
      providesTags: ["Profile"],
    }),
    forgotPassword: builder.mutation<null, { email: string }>({
      query: (body) => ({ url: "/api/v1/auth/forgot-password", method: "POST", body }),
    }),
    resetPassword: builder.mutation<null, { token: string; new_password: string }>({
      query: (body) => ({ url: "/api/v1/auth/reset-password", method: "POST", body }),
    }),
    verifyEmail: builder.mutation<Profile, { token: string }>({
      query: (body) => ({ url: "/api/v1/auth/verify-email", method: "POST", body }),
      invalidatesTags: ["Profile"],
    }),
    resendVerification: builder.mutation<null, void>({
      query: () => ({ url: "/api/v1/auth/resend-verification", method: "POST", body: {} }),
    }),
    getLoginHistory: builder.query<LoginHistoryEntry[], void>({
      query: () => "/api/v1/auth/login-history",
      providesTags: ["LoginHistory"],
    }),

    // --- Providers ---
    getChatProviders: builder.query<ProviderInfo[], void>({
      query: () => "/api/v1/providers/chat",
      providesTags: ["Provider"],
    }),
    getEmbeddingProviders: builder.query<ProviderInfo[], void>({
      query: () => "/api/v1/providers/embeddings",
      providesTags: ["Provider"],
    }),

    // --- Knowledge base (admin) ---
    getDocuments: builder.query<DocumentRead[], void>({
      query: () => "/api/v1/documents",
      providesTags: ["Document"],
    }),
    uploadDocuments: builder.mutation<
      UploadResult,
      { files: File[]; embedding_provider: string; embedding_model: string }
    >({
      query: ({ files, embedding_provider, embedding_model }) => {
        const form = new FormData();
        for (const file of files) form.append("files", file, file.name);
        form.append("embedding_provider", embedding_provider);
        form.append("embedding_model", embedding_model);
        // No Content-Type header: the browser must set the multipart boundary.
        return { url: "/api/v1/documents/upload", method: "POST", body: form };
      },
      // A mixed batch succeeds with a 201 while reporting the unreadable
      // files in `errors`, so the warnings are lifted out of the envelope
      // rather than discarded with it.
      transformResponse: (documents: DocumentRead[], meta) => ({
        documents,
        warnings: (meta as { envelope?: EnvelopeMeta } | undefined)?.envelope?.errors ?? [],
      }),
      invalidatesTags: ["Document", "Metrics", "Audit"],
    }),
    deleteDocument: builder.mutation<null, string>({
      query: (id) => ({ url: "/api/v1/documents/" + id, method: "DELETE" }),
      invalidatesTags: ["Document", "Metrics", "Audit"],
    }),
    clearDocuments: builder.mutation<null, void>({
      query: () => ({ url: "/api/v1/documents", method: "DELETE" }),
      invalidatesTags: ["Document", "Metrics", "Audit"],
    }),

    // --- Chat ---
    ask: builder.mutation<ChatResponse, AskArgs>({
      query: (args) => ({ url: "/api/v1/chat/ask", method: "POST", body: askBody(args) }),
      invalidatesTags: ["Chat", "Metrics"],
    }),
    getChatSession: builder.query<ChatSessionRead, string>({
      query: (id) => "/api/v1/chat/sessions/" + id,
      providesTags: (_result, _error, id) => [{ type: "ChatSession", id }],
    }),
    deleteChatSession: builder.mutation<null, string>({
      query: (id) => ({ url: "/api/v1/chat/sessions/" + id, method: "DELETE" }),
      invalidatesTags: ["Chat", "Project", "Metrics"],
    }),
    deleteMessage: builder.mutation<null, { messageId: string; sessionId: string | null }>({
      query: ({ messageId }) => ({ url: "/api/v1/chat/messages/" + messageId, method: "DELETE" }),
      invalidatesTags: (_result, _error, { sessionId }) =>
        sessionId ? [{ type: "ChatSession" as const, id: sessionId }] : [],
    }),

    // --- Projects and chat organisation ---
    getProjects: builder.query<ProjectRead[], void>({
      query: () => "/api/v1/projects",
      providesTags: ["Project"],
    }),
    createProject: builder.mutation<ProjectRead, { name: string }>({
      query: (body) => ({ url: "/api/v1/projects", method: "POST", body }),
      invalidatesTags: ["Project"],
    }),
    renameProject: builder.mutation<ProjectRead, { id: string; name: string }>({
      query: ({ id, name }) => ({ url: "/api/v1/projects/" + id, method: "PATCH", body: { name } }),
      invalidatesTags: ["Project"],
    }),
    deleteProject: builder.mutation<null, string>({
      query: (id) => ({ url: "/api/v1/projects/" + id, method: "DELETE" }),
      // Its chats are detached rather than deleted, so the chat list changes too.
      invalidatesTags: ["Project", "Chat"],
    }),
    getProjectChats: builder.query<ChatSummary[], string>({
      query: (id) => "/api/v1/projects/" + id + "/chats",
      providesTags: ["Chat"],
    }),
    getChats: builder.query<ChatSummary[], { ungrouped_only?: boolean; search?: string }>({
      query: ({ ungrouped_only, search }) => {
        const params = new URLSearchParams();
        if (ungrouped_only) params.set("ungrouped_only", "true");
        if (search) params.set("search", search);
        const query = params.toString();
        return "/api/v1/chats" + (query ? "?" + query : "");
      },
      providesTags: ["Chat"],
    }),
    renameChat: builder.mutation<ChatSummary, { id: string; title: string }>({
      query: ({ id, title }) => ({ url: "/api/v1/chats/" + id, method: "PATCH", body: { title } }),
      invalidatesTags: ["Chat"],
    }),
    moveChat: builder.mutation<ChatSummary, { id: string; project_id: string | null }>({
      query: ({ id, project_id }) => ({
        url: "/api/v1/chats/" + id + "/project",
        method: "PATCH",
        body: { project_id },
      }),
      // Project chat counts change as well as the ungrouped list.
      invalidatesTags: ["Chat", "Project"],
    }),

    // --- Administration ---
    getMetrics: builder.query<Metrics, void>({
      query: () => "/api/v1/admin/metrics",
      providesTags: ["Metrics"],
    }),
    getAuditEvents: builder.query<
      AuditEvent[],
      { action?: string | undefined; user_email?: string | undefined; limit?: number }
    >({
      query: ({ action, user_email, limit = 200 }) => {
        const params = new URLSearchParams({ limit: String(limit) });
        if (action) params.set("action", action);
        if (user_email) params.set("user_email", user_email);
        return "/api/v1/admin/audit?" + params.toString();
      },
      providesTags: ["Audit"],
    }),
    getProviderModels: builder.query<ProviderModel[], void>({
      query: () => "/api/v1/admin/models",
      providesTags: ["Model"],
    }),
    addProviderModel: builder.mutation<
      ProviderModel,
      {
        kind: "chat" | "embedding";
        provider: string;
        model_name: string;
        display_name?: string | null;
      }
    >({
      query: (body) => ({ url: "/api/v1/admin/models", method: "POST", body }),
      // "Provider" too: the catalogue is what the model pickers are built from.
      invalidatesTags: ["Model", "Provider", "Audit"],
    }),
    updateProviderModel: builder.mutation<
      ProviderModel,
      { id: string; is_enabled?: boolean; display_name?: string | null }
    >({
      query: ({ id, ...changes }) => ({
        url: "/api/v1/admin/models/" + id,
        method: "PATCH",
        body: changes,
      }),
      invalidatesTags: ["Model", "Provider", "Audit"],
    }),
    deleteProviderModel: builder.mutation<null, string>({
      query: (id) => ({ url: "/api/v1/admin/models/" + id, method: "DELETE" }),
      invalidatesTags: ["Model", "Provider", "Audit"],
    }),
    seedProviderModels: builder.mutation<number, void>({
      query: () => ({ url: "/api/v1/admin/models/seed", method: "POST", body: {} }),
      invalidatesTags: ["Model", "Provider", "Audit"],
    }),
  }),
});

export const {
  useLoginMutation,
  useRegisterMutation,
  useLogoutMutation,
  useGetProfileQuery,
  useForgotPasswordMutation,
  useResetPasswordMutation,
  useVerifyEmailMutation,
  useResendVerificationMutation,
  useGetLoginHistoryQuery,
  useGetChatProvidersQuery,
  useGetEmbeddingProvidersQuery,
  useGetDocumentsQuery,
  useUploadDocumentsMutation,
  useDeleteDocumentMutation,
  useClearDocumentsMutation,
  useAskMutation,
  useGetChatSessionQuery,
  useDeleteChatSessionMutation,
  useDeleteMessageMutation,
  useGetProjectsQuery,
  useCreateProjectMutation,
  useRenameProjectMutation,
  useDeleteProjectMutation,
  useGetProjectChatsQuery,
  useGetChatsQuery,
  useRenameChatMutation,
  useMoveChatMutation,
  useGetMetricsQuery,
  useGetAuditEventsQuery,
  useGetProviderModelsQuery,
  useAddProviderModelMutation,
  useUpdateProviderModelMutation,
  useDeleteProviderModelMutation,
  useSeedProviderModelsMutation,
} = apiSlice;
