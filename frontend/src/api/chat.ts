import type { StreamEvent } from "../types/sse";
import { parseStreamEvent } from "../types/sse";
import { apiFetch } from "./client";

export type ChatRequestBody = {
  message?: string | null;
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

async function responseErrorMessage(response: Response): Promise<string> {
  const text = await response.text();
  if (!text) return response.statusText || "Request failed";
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail.trim()) return parsed.detail;
  } catch {
    // fallback to plain-text body
  }
  return text;
}

export async function listConversations(signal?: AbortSignal): Promise<ConversationSummary[]> {
  const response = await apiFetch("/chat/conversations", { signal });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  return (await response.json()) as ConversationSummary[];
}

export async function getConversationMessages(
  conversationId: string,
  signal?: AbortSignal,
): Promise<ConversationMessage[]> {
  const response = await apiFetch(`/chat/conversations/${conversationId}/messages`, { signal });
  if (!response.ok) {
    const message = await responseErrorMessage(response);
    const error = new Error(message);
    (error as Error & { status?: number }).status = response.status;
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
    throw new Error(await responseErrorMessage(response));
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
    throw new Error(await responseErrorMessage(r));
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
