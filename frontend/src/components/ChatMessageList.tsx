import type { ReactNode } from "react";

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

type Props = {
  messages: ChatMessage[];
  emptyHint?: string;
};

function renderContentWithLinks(content: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
  let last = 0;
  let idx = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(content)) !== null) {
    if (m.index > last) {
      out.push(content.slice(last, m.index));
    }
    const label = m[1];
    const href = m[2];
    out.push(
      <a key={`link-${idx}`} href={href} target="_blank" rel="noopener noreferrer">
        {label}
      </a>,
    );
    last = re.lastIndex;
    idx += 1;
  }
  if (last < content.length) {
    out.push(content.slice(last));
  }
  return out;
}

export default function ChatMessageList({ messages, emptyHint }: Props) {
  if (messages.length === 0) {
    return (
      <div className="chat-empty muted" role="status">
        {emptyHint ?? "Ask about your calendar, meetings, or request email drafts."}
      </div>
    );
  }

  return (
    <ul className="chat-list" aria-live="polite">
      {messages.map((m, i) => (
        <li
          key={`${i}-${m.role}`}
          className={`chat-bubble chat-bubble-${m.role}`}
        >
          <span className="chat-role">{m.role === "user" ? "You" : "Assistant"}</span>
          <div className="chat-content">
            {m.content
              ? renderContentWithLinks(m.content)
              : m.role === "assistant"
                ? "…"
                : ""}
          </div>
        </li>
      ))}
    </ul>
  );
}
