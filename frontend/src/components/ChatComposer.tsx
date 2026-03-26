import { useState, type FormEvent } from "react";

type Props = {
  onSend: (text: string) => void | Promise<void>;
  disabled?: boolean;
  placeholder?: string;
};

export default function ChatComposer({
  onSend,
  disabled,
  placeholder = "Message the assistant…",
}: Props) {
  const [text, setText] = useState("");

  async function submit() {
    const t = text.trim();
    if (!t || disabled) return;
    setText("");
    await onSend(t);
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    void submit();
  }

  return (
    <form className="chat-composer" onSubmit={handleSubmit}>
      <textarea
        className="chat-input"
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            void submit();
          }
        }}
      />
      <div className="chat-composer-actions">
        <button type="submit" className="btn primary" disabled={disabled || !text.trim()}>
          Send
        </button>
      </div>
    </form>
  );
}
