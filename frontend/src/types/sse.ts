/** Parsed JSON payloads from `POST /chat` SSE `data:` lines. */
export type StreamEvent =
  | { type: "meta"; conversation_id: string }
  | {
      type: "interrupt";
      interrupts: Array<{ id: string; value: unknown }>;
    }
  | { type: "content"; text: string }
  | { type: "done" }
  | { type: "error"; message: string };

export function parseStreamEvent(data: unknown): StreamEvent | null {
  if (!data || typeof data !== "object" || !("type" in data)) return null;
  const t = (data as { type: string }).type;
  switch (t) {
    case "meta":
    case "interrupt":
    case "content":
    case "done":
    case "error":
      return data as StreamEvent;
    default:
      return null;
  }
}
