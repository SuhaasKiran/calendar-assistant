import type { StreamEvent } from "../types/sse";
import { parseStreamEvent } from "../types/sse";
import { apiFetch } from "./client";

export type ChatRequestBody = {
  message?: string | null;
  conversation_id?: string | null;
  resume?: boolean;
  resume_value?: unknown;
};

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
    const t = await r.text();
    throw new Error(t || r.statusText);
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
