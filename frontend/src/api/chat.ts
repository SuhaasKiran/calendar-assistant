import type { StreamEvent } from "../types/sse";
import { parseStreamEvent } from "../types/sse";
import { apiFetch } from "./client";

export type ChatRequestBody = {
  message?: string | null;
  user_preferences?: string | null;
  conversation_id?: string | null;
  resume?: boolean;
  resume_value?: unknown;
};

export type ConversationSummary = {
  id: string;
  created_at: string;
  last_activity_at: string;
  last_message_preview: string | null;
};

export type ConversationMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};

export type ApiError = Error & {
  status?: number;
  code?: string;
  requestId?: string;
  retryable?: boolean;
};

const GENERIC_SERVER_ERROR = "Something went wrong on our side. Please try again.";
const GENERIC_REQUEST_ERROR = "Request failed. Please try again.";

function fallbackErrorMessage(status: number, statusText: string): string {
  if (status >= 500) return GENERIC_SERVER_ERROR;
  if (status === 401) return "Your session has expired. Please sign in again.";
  if (status === 403) return "You do not have permission to perform this action.";
  if (status === 404) return "Conversation not found";
  if (status === 429) return "Too many requests. Please wait and try again.";
  return statusText || GENERIC_REQUEST_ERROR;
}

async function responseError(response: Response): Promise<ApiError> {
  const text = await response.text();
  let message = fallbackErrorMessage(response.status, response.statusText);
  let code: string | undefined;
  let retryable: boolean | undefined;
  let requestId: string | undefined;
  if (response.status >= 500) message = GENERIC_SERVER_ERROR;
  if (text) {
    try {
      const parsed = JSON.parse(text) as {
        detail?: unknown;
        code?: unknown;
        retryable?: unknown;
        request_id?: unknown;
      };
      if (typeof parsed.detail === "string" && parsed.detail.trim()) message = parsed.detail.trim();
      if (typeof parsed.code === "string") code = parsed.code;
      if (typeof parsed.retryable === "boolean") retryable = parsed.retryable;
      if (typeof parsed.request_id === "string") requestId = parsed.request_id;
    } catch {
      // ignore parse errors
    }
  }
  const err = new Error(message) as ApiError;
  err.status = response.status;
  err.code = code;
  err.retryable = retryable;
  err.requestId = requestId;
  return err;
}

export async function listConversations(signal?: AbortSignal): Promise<ConversationSummary[]> {
  const response = await apiFetch("/chat/conversations", { signal });
  if (!response.ok) {
    throw await responseError(response);
  }
  return (await response.json()) as ConversationSummary[];
}

export async function getConversationMessages(
  conversationId: string,
  signal?: AbortSignal,
): Promise<ConversationMessage[]> {
  const response = await apiFetch(`/chat/conversations/${conversationId}/messages`, { signal });
  if (!response.ok) {
    const error = await responseError(response);
    throw error;
  }
  return (await response.json()) as ConversationMessage[];
}

export async function deleteConversation(
  conversationId: string,
  signal?: AbortSignal,
): Promise<void> {
  const response = await apiFetch(`/chat/conversations/${conversationId}`, {
    method: "DELETE",
    signal,
  });
  if (!response.ok) {
    throw await responseError(response);
  }
}

/**
 * POST `/chat` with SSE body. Invokes `onEvent` for each parsed JSON event until the stream ends.
 */
export async function postChatStream(
  body: ChatRequestBody,
  onEvent: (evt: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await apiFetch("/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!r.ok) {
    throw await responseError(r);
  }

  if (!r.body) {
    throw new Error("No response body");
  }

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const blocks = buffer.split(/\n\n/);
      buffer = blocks.pop() ?? "";

      for (const block of blocks) {
        for (const line of block.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;
          try {
            const parsed: unknown = JSON.parse(raw);
            const evt = parseStreamEvent(parsed);
            if (evt) onEvent(evt);
          } catch {
            /* ignore malformed JSON line */
          }
        }
      }
    }

    if (buffer.trim()) {
      for (const line of buffer.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        const raw = line.slice(6).trim();
        if (!raw) continue;
        try {
          const parsed: unknown = JSON.parse(raw);
          const evt = parseStreamEvent(parsed);
          if (evt) onEvent(evt);
        } catch {
          /* ignore */
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
