import type {
  AdminConversation,
  AdminEvent,
  AdminOverview,
  AdminTurn,
  AdminUsageRow,
  BlockedPayload,
  ConversationDetail,
  ConversationSummary,
  Message,
  Session,
  Usage,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** Raised when guardrails reject a turn, so the UI can render it as a notice
 *  rather than a generic failure. */
export class BlockedError extends Error {
  payload: BlockedPayload;
  constructor(payload: BlockedPayload) {
    super(payload.message);
    this.payload = payload;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: init.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const data = text ? JSON.parse(text) : null;

  if (!response.ok) {
    if (data?.blocked) throw new BlockedError(data as BlockedPayload);
    throw new ApiError(data?.message ?? data?.detail ?? response.statusText, response.status);
  }
  return data as T;
}

export const api = {
  login: (email: string, password: string) =>
    request<Session>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  me: () => request<Session>("/api/auth/me"),

  logout: () => request<void>("/api/auth/logout", { method: "POST" }),

  usage: () => request<Usage>("/api/usage"),

  conversations: () => request<ConversationSummary[]>("/api/conversations"),

  createConversation: () =>
    request<ConversationDetail>("/api/conversations", {
      method: "POST",
      body: JSON.stringify({}),
    }),

  conversation: (id: string) => request<ConversationDetail>(`/api/conversations/${id}`),

  archiveConversation: (id: string) =>
    request<void>(`/api/conversations/${id}`, { method: "DELETE" }),

  admin: {
    overview: () => request<AdminOverview>("/api/admin/overview"),
    turns: (params: { limit?: number; status?: string; user_email?: string } = {}) =>
      request<AdminTurn[]>(`/api/admin/turns?${toQuery(params)}`),
    usage: (days = 7) => request<AdminUsageRow[]>(`/api/admin/usage?days=${days}`),
    conversations: (limit = 60) =>
      request<AdminConversation[]>(`/api/admin/conversations?limit=${limit}`),
    events: (params: { limit?: number; event_type?: string } = {}) =>
      request<AdminEvent[]>(`/api/admin/events?${toQuery(params)}`),
    refreshDocs: () =>
      request<{
        refreshed: boolean;
        elapsed_ms: number;
        prompt_revision: string | null;
        grounding_revision: string | null;
        stale: string[];
      }>("/api/admin/docs/refresh", { method: "POST" }),
  },
};

function toQuery(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  return search.toString();
}

export interface StreamHandlers {
  onDelta: (text: string) => void;
  onDone: (payload: {
    user_message: Message;
    assistant_message: Message;
    usage: Usage;
    redacted: boolean;
    replace_text: string | null;
  }) => void;
  onError: (message: string) => void;
}

/**
 * Send a turn over SSE.
 *
 * Uses fetch + a ReadableStream rather than EventSource because the request is
 * a POST with a body and needs the session cookie; EventSource is GET-only.
 */
export async function streamMessage(
  conversationId: string,
  content: string,
  clientRequestId: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/conversations/${conversationId}/messages/stream`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, client_request_id: clientRequestId }),
    signal,
  });

  if (!response.ok) {
    const text = await response.text();
    const data = text ? JSON.parse(text) : null;
    if (data?.blocked) throw new BlockedError(data as BlockedPayload);
    throw new ApiError(data?.message ?? response.statusText, response.status);
  }

  if (!response.body) throw new ApiError("Streaming is not supported here", 500);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      dispatchFrame(frame, handlers);
      boundary = buffer.indexOf("\n\n");
    }
  }
}

function dispatchFrame(frame: string, handlers: StreamHandlers): void {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return;

  let payload: any;
  try {
    payload = JSON.parse(dataLines.join("\n"));
  } catch {
    return;
  }

  if (event === "delta") handlers.onDelta(payload.text ?? "");
  else if (event === "done") handlers.onDone(payload);
  else if (event === "error") handlers.onError(payload.message ?? "Something went wrong.");
}
