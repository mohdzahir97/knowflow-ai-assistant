/** Response and request shapes, mirroring the backend's Pydantic schemas. */

/** Every endpoint returns this envelope. */
export interface ApiEnvelope<T> {
  success: boolean;
  message: string;
  data: T;
  errors?: string[] | null;
  request_id?: string;
}

export type Role = "admin" | "user";

export interface Profile {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_verified: boolean;
  role: Role;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface ProviderInfo {
  provider: string;
  display_name: string;
  models: string[];
  is_configured: boolean;
}

export interface SourceCitation {
  document: string;
  page: number;
  chunk_id: string;
}

export interface DocumentRead {
  id: string;
  filename: string;
  status: string;
  page_count: number | null;
  chunk_count: number | null;
  embedding_provider: string | null;
  embedding_model: string | null;
  file_size_bytes: number;
  /** Why indexing failed, when `status` is not "indexed". */
  failure_reason: string | null;
  created_at: string;
}

export interface ProjectRead {
  id: string;
  name: string;
  chat_count: number;
  created_at: string;
}

export interface ChatSummary {
  id: string;
  title: string;
  project_id: string | null;
  document_id: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ChatMessageRead {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: SourceCitation[] | null;
  provider: string | null;
  model: string | null;
  created_at: string;
}

export interface ChatSessionRead {
  id: string;
  title: string;
  document_id: string | null;
  created_at: string;
  messages: ChatMessageRead[];
}

export interface CragDiagnostics {
  context_verdict: string | null;
  context_quality: number | null;
  correction_attempts: number;
  rewritten_query: string | null;
  groundedness_verdict: string | null;
}

export interface ChatResponse {
  session_id: string;
  document_id: string | null;
  answer: string;
  sources: SourceCitation[];
  provider: string;
  model: string;
  retrieval_time_ms: number;
  llm_time_ms: number;
  total_time_ms: number;
  token_usage: { total_tokens?: number | null } | null;
  crag: CragDiagnostics | null;
}

/** One line of the NDJSON answer stream. */
export type StreamEvent =
  | { type: "token"; content: string }
  | { type: "retract"; content: string }
  | {
      type: "done";
      session_id: string;
      sources?: SourceCitation[] | null;
      total_time_ms?: number;
      token_usage?: { total_tokens?: number | null } | null;
    }
  | { type: "error"; message: string };

export interface LoginHistoryEntry {
  action: string;
  ip_address: string | null;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  user_id: string | null;
  user_email: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  ip_address: string | null;
  request_id: string | null;
  detail: Record<string, unknown> | null;
  created_at: string;
}

export interface Metrics {
  users_total: number;
  users_admin: number;
  documents_total: number;
  document_chunks_total: number;
  chat_sessions_total: number;
  chat_messages_total: number;
  projects_total: number;
  audit_events_total: number;
  logins_failed_last_24h: number;
}

export interface ProviderModel {
  id: string;
  kind: "chat" | "embedding";
  provider: string;
  model_name: string;
  display_name: string | null;
  is_enabled: boolean;
  sort_order: number;
}
