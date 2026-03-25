import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { postChatStream } from "../api/chat";
import { useSession } from "../hooks/useSession";
import type { StreamEvent } from "../types/sse";
import ChatComposer from "./ChatComposer";
import ChatMessageList, { type ChatMessage } from "./ChatMessageList";
import InterruptPanel from "./InterruptPanel";

function storageKey(userId: number) {
  return `calendar_assistant_conversation_id_${userId}`;
}

export default function ChatScreen() {
  const { user, logout } = useSession();
  const navigate = useNavigate();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [interruptPayload, setInterruptPayload] = useState<
    Array<{ id: string; value: unknown }> | null
  >(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!user) return;
    const saved = localStorage.getItem(storageKey(user.id));
    if (saved) setConversationId(saved);
  }, [user]);

  const persistConversationId = useCallback(
    (id: string) => {
      setConversationId(id);
      if (user) localStorage.setItem(storageKey(user.id), id);
    },
    [user],
  );

  const handleStreamEvent = useCallback(
    (evt: StreamEvent) => {
      if (evt.type === "meta") {
        persistConversationId(evt.conversation_id);
      }
      if (evt.type === "content") {
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last?.role === "assistant") {
            next[next.length - 1] = { role: "assistant", content: evt.text };
          }
          return next;
        });
      }
      if (evt.type === "interrupt") {
        setInterruptPayload(evt.interrupts);
      }
      if (evt.type === "error") {
        setError(evt.message);
      }
    },
    [persistConversationId],
  );

  const runChat = useCallback(
    async (body: Parameters<typeof postChatStream>[0]) => {
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      setBusy(true);
      setError(null);
      setInterruptPayload(null);
      try {
        await postChatStream(body, handleStreamEvent, ac.signal);
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        setError(e instanceof Error ? e.message : "Request failed");
      } finally {
        setBusy(false);
      }
    },
    [handleStreamEvent],
  );

  const sendMessage = useCallback(
    async (text: string) => {
      setMessages((m) => [
        ...m,
        { role: "user", content: text },
        { role: "assistant", content: "" },
      ]);
      await runChat({
        message: text,
        conversation_id: conversationId,
      });
    },
    [conversationId, runChat],
  );

  const resumeInterrupt = useCallback(
    async (value: unknown) => {
      if (!conversationId) {
        setError("Missing conversation — start a new chat.");
        return;
      }
      setMessages((m) => {
        const next = [...m];
        const last = next[next.length - 1];
        if (last?.role === "assistant" && last.content === "") {
          return next;
        }
        return [...next, { role: "assistant", content: "" }];
      });
      await runChat({
        resume: true,
        resume_value: value,
        conversation_id: conversationId,
      });
    },
    [conversationId, runChat],
  );

  const newChat = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setConversationId(null);
    setInterruptPayload(null);
    setError(null);
    if (user) localStorage.removeItem(storageKey(user.id));
  }, [user]);

  const signOut = useCallback(async () => {
    abortRef.current?.abort();
    await logout();
    navigate("/login", { replace: true });
  }, [logout, navigate]);

  if (!user) return null;

  return (
    <div className="app-shell chat">
      <header className="app-header chat-header">
        <div>
          <h1 className="app-title">Calendar Assistant</h1>
          <p className="muted small">
            Signed in as {user.email ?? user.google_sub}
          </p>
        </div>
        <div className="header-actions">
          <button type="button" className="btn" onClick={newChat} disabled={busy}>
            New chat
          </button>
          <button type="button" className="btn" onClick={() => void signOut()} disabled={busy}>
            Sign out
          </button>
        </div>
      </header>

      {error && (
        <div className="banner banner-error" role="alert">
          {error}
        </div>
      )}

      <section className="chat-panel">
        <ChatMessageList
          messages={messages}
          emptyHint="Try: “List my meetings next Tuesday” or “Draft an email to schedule time with the team.”"
        />

        {interruptPayload && (
          <InterruptPanel
            interrupts={interruptPayload}
            disabled={busy}
            onResume={(v) => void resumeInterrupt(v)}
          />
        )}

        <ChatComposer onSend={(t) => void sendMessage(t)} disabled={busy} />
      </section>
    </div>
  );
}
