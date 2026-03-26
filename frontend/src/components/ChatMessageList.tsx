import type { ReactNode } from "react";

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

type Props = {
  messages: ChatMessage[];
  emptyHint?: string;
  assistantName?: string;
};

function renderContentWithFormatting(content: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*([^*]+)\*\*|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\))/g;
  let last = 0;
  let idx = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(content)) !== null) {
    if (m.index > last) {
      out.push(content.slice(last, m.index));
    }
    const boldText = m[2];
    const linkLabel = m[3];
    const linkHref = m[4];
    if (boldText) {
      out.push(<strong key={`bold-${idx}`}>{boldText}</strong>);
    } else if (linkLabel && linkHref) {
      out.push(
        <a key={`link-${idx}`} href={linkHref} target="_blank" rel="noopener noreferrer">
          {linkLabel}
        </a>,
      );
    }
    last = re.lastIndex;
    idx += 1;
  }
  if (last < content.length) {
    out.push(content.slice(last));
  }
  return out;
}

export default function ChatMessageList({
  messages,
  emptyHint,
  assistantName = "Assistant",
}: Props) {
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
          <span className="chat-role">{m.role === "user" ? "You" : assistantName}</span>
          <div className="chat-content">
            {m.content
              ? renderContentWithFormatting(m.content)
              : m.role === "assistant"
                ? (
                    <span className="typing-indicator" aria-label="Assistant is typing">
                      <span className="typing-label">Thinking</span>
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                    </span>
                  )
                : ""}
          </div>
        </li>
      ))}
    </ul>
  );
}
