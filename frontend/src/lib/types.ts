export type Role = "user" | "assistant";

export type MessageStatus =
  | "ok"
  | "blocked_cap"
  | "blocked_rate"
  | "provider_error"
  | "doc_error"
  | "truncated"
  | "redacted";

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: "user" | "admin";
}

export interface Advisor {
  id: string;
  name: string;
}

export interface Session {
  user: User;
  advisor: Advisor;
}

export interface Usage {
  usage_date: string;
  timezone: string;
  messages_used: number;
  tokens_used: number;
  message_cap: number | null;
  token_cap: number | null;
  messages_remaining: number | null;
  tokens_remaining: number | null;
  rate_limit_per_minute: number;
}

export interface Message {
  id: string;
  role: Role;
  content: string;
  status: MessageStatus;
  created_at: string;
  tokens?: number | null;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  last_message_at: string | null;
  message_count: number;
  preview: string | null;
}

export interface ConversationDetail {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: Message[];
}

export interface BlockedPayload {
  blocked: true;
  reason: "message_cap" | "token_cap" | "spend_cap" | "rate_limited";
  message: string;
  retry_after_seconds: number | null;
  usage: Usage;
}

export interface DocStatus {
  kind: "prompt" | "grounding";
  source: string;
  revision: string;
  char_count: number;
  stale: boolean;
  cache_expires_in_seconds: number | null;
  fetched_at: string;
}

export interface AdminOverview {
  totals: {
    users: number;
    conversations: number;
    messages: number;
    tokens: number;
    est_cost_usd: number;
    blocked: number;
    errored: number;
    avg_latency_ms: number;
    model: string;
    doc_provider: string;
    doc_cache_ttl_seconds: number;
    timezone: string;
    default_message_cap: number;
    default_token_cap: number;
    rate_limit_per_minute: number;
  };
  docs: DocStatus[];
  by_status: Record<string, number>;
  by_event: Record<string, number>;
}

export interface AdminTurn {
  message_id: string;
  conversation_id: string;
  user_email: string;
  role: Role;
  status: MessageStatus;
  model: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  tokens: number;
  est_cost_usd: number;
  latency_ms: number | null;
  prompt_revision: string | null;
  grounding_revision: string | null;
  grounding_chunk_ids: string[];
  content_excerpt: string;
  created_at: string;
}

export interface AdminUsageRow {
  user_id: string;
  email: string;
  display_name: string;
  usage_date: string | null;
  messages_used: number;
  tokens_used: number;
  est_spend_usd: number;
  daily_message_cap: number;
  daily_token_cap: number;
}

export interface AdminConversation {
  id: string;
  user_email: string;
  title: string;
  message_count: number;
  total_tokens: number;
  total_est_cost_usd: number;
  last_message_at: string | null;
  created_at: string;
}

export interface AdminEvent {
  id: number;
  event_type: string;
  severity: "info" | "warn" | "error";
  user_email: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}
