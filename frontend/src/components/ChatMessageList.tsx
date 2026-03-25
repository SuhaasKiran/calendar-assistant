export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

type Props = {
  messages: ChatMessage[];
  emptyHint?: string;
};

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
            {m.content || (m.role === "assistant" ? "…" : "")}
          </div>
        </li>
      ))}
    </ul>
  );
}
