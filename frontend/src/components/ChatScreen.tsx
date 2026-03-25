import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  deleteConversation,
  getConversationMessages,
  listConversations,
  postChatStream,
  type ConversationSummary,
} from "../api/chat";
import { useSession } from "../hooks/useSession";
import type { StreamEvent } from "../types/sse";
import ChatComposer from "./ChatComposer";
import ChatMessageList, { type ChatMessage } from "./ChatMessageList";
import InterruptPanel from "./InterruptPanel";

function formatThreadTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function ChatScreen() {
  const { user, logout } = useSession();
  const navigate = useNavigate();
  const { conversationId: routeConversationId } = useParams<{ conversationId: string }>();
  const conversationId = routeConversationId ?? null;

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [interruptPayload, setInterruptPayload] = useState<
    Array<{ id: string; value: unknown }> | null
  >(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [threadsError, setThreadsError] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [threadsLoading, setThreadsLoading] = useState(false);
  const [deletingThreadId, setDeletingThreadId] = useState<string | null>(null);
  const [historyRetryToken, setHistoryRetryToken] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const threadsAbortRef = useRef<AbortController | null>(null);
  const skipHydrationThreadIdRef = useRef<string | null>(null);

  const handleStreamEvent = useCallback(
    (evt: StreamEvent) => {
      if (evt.type === "meta") {
        if (conversationId !== evt.conversation_id) {
          if (!conversationId && busy) {
            // First-turn creation: keep live stream UI; avoid immediate history overwrite.
            skipHydrationThreadIdRef.current = evt.conversation_id;
          }
          navigate(`/c/${evt.conversation_id}`, { replace: true });
        }
        void (async () => {
          try {
            const items = await listConversations();
            setConversations(items);
          } catch {
            // Keep stream flow resilient if sidebar refresh fails.
          }
        })();
      }
      if (evt.type === "content") {
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last?.role === "assistant") {
            next[next.length - 1] = { role: "assistant", content: evt.text };
          } else {
            next.push({ role: "assistant", content: evt.text });
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
      if (evt.type === "done") {
        void (async () => {
          try {
            const items = await listConversations();
            setConversations(items);
          } catch {
            // Keep stream completion resilient if sidebar refresh fails.
          }
        })();
      }
    },
    [busy, conversationId, navigate],
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
      if (historyLoading) {
        setError("Please wait for thread history to load.");
        return;
      }
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
    [conversationId, historyLoading, runChat],
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
    setHistoryRetryToken(0);
    setMessages([]);
    setInterruptPayload(null);
    setError(null);
    setHistoryError(null);
    navigate("/");
  }, [navigate]);

  const refreshConversations = useCallback(async () => {
    threadsAbortRef.current?.abort();
    const ac = new AbortController();
    threadsAbortRef.current = ac;
    setThreadsLoading(true);
    setThreadsError(null);
    try {
      const items = await listConversations(ac.signal);
      setConversations(items);
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      setThreadsError(e instanceof Error ? e.message : "Failed to load conversations");
    } finally {
      setThreadsLoading(false);
    }
  }, []);

  const signOut = useCallback(async () => {
    abortRef.current?.abort();
    await logout();
    navigate("/login", { replace: true });
  }, [logout, navigate]);

  const handleDeleteThread = useCallback(
    async (threadId: string) => {
      if (busy || deletingThreadId) return;
      const confirmed = window.confirm("Delete this thread permanently?");
      if (!confirmed) return;
      setThreadsError(null);
      setDeletingThreadId(threadId);
      try {
        await deleteConversation(threadId);
        setConversations((prev) => prev.filter((thread) => thread.id !== threadId));
        if (threadId === conversationId) {
          abortRef.current?.abort();
          setMessages([]);
          setInterruptPayload(null);
          setHistoryError(null);
          setError(null);
          navigate("/", { replace: true });
        }
        await refreshConversations();
      } catch (e) {
        setThreadsError(e instanceof Error ? e.message : "Failed to delete conversation");
      } finally {
        setDeletingThreadId(null);
      }
    },
    [busy, conversationId, deletingThreadId, navigate, refreshConversations],
  );

  useEffect(() => {
    if (!user) return;
    void refreshConversations();
    return () => {
      threadsAbortRef.current?.abort();
    };
  }, [refreshConversations, user]);

  useEffect(() => {
    setInterruptPayload(null);
    setError(null);
    setHistoryError(null);

    if (!conversationId) {
      setHistoryLoading(false);
      setMessages([]);
      return;
    }
    if (skipHydrationThreadIdRef.current === conversationId) {
      skipHydrationThreadIdRef.current = null;
      setHistoryLoading(false);
      return;
    }

    const ac = new AbortController();
    setHistoryLoading(true);
    void (async () => {
      try {
        const history = await getConversationMessages(conversationId, ac.signal);
        const mapped: ChatMessage[] = history.map((msg) => ({
          role: msg.role,
          content: msg.content,
        }));
        setMessages(mapped);
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        const err = e as Error & { status?: number };
        if (err.status === 404) {
          setHistoryError("Conversation not found. Redirected to a new chat.");
          navigate("/", { replace: true });
          setMessages([]);
          void refreshConversations();
          return;
        }
        setHistoryError(err.message || "Failed to load conversation history");
      } finally {
        setHistoryLoading(false);
      }
    })();

    return () => {
      ac.abort();
    };
  }, [conversationId, historyRetryToken, navigate, refreshConversations]);

  if (!user) return null;

  return (
    <div className="app-shell chat">
      <div className="chat-layout">
        <aside className="thread-sidebar">
          <div className="thread-sidebar-header">
            <h2 className="thread-sidebar-title">Threads</h2>
            <button
              type="button"
              className="btn"
              onClick={newChat}
              disabled={busy || historyLoading}
            >
              New chat
            </button>
          </div>
          {threadsError && (
            <div className="banner banner-error" role="alert">
              <span>{threadsError}</span>
              <button type="button" className="btn" onClick={() => void refreshConversations()}>
                Retry
              </button>
            </div>
          )}
          <div className="thread-list" role="navigation" aria-label="Conversation threads">
            {threadsLoading && conversations.length === 0 ? (
              <div className="muted small">Loading threads...</div>
            ) : null}
            {conversations.length === 0 && !threadsLoading ? (
              <div className="muted small">No threads yet.</div>
            ) : null}
            {conversations.map((thread) => (
              <div
                key={thread.id}
                className={`thread-item ${thread.id === conversationId ? "active" : ""}`}
              >
                <button
                  type="button"
                  className="thread-open-btn"
                  onClick={() => navigate(`/c/${thread.id}`)}
                  disabled={busy || deletingThreadId === thread.id}
                >
                  <span className="thread-preview">
                    {thread.last_message_preview?.trim() || "New conversation"}
                  </span>
                  <span className="thread-time">{formatThreadTime(thread.last_activity_at)}</span>
                </button>
                <button
                  type="button"
                  className="thread-delete-btn"
                  onClick={() => void handleDeleteThread(thread.id)}
                  disabled={busy || deletingThreadId !== null}
                  aria-label="Delete thread"
                  title="Delete thread"
                >
                  Delete
                </button>
              </div>
            ))}
          </div>
        </aside>

        <section className="chat-main">
          <header className="app-header chat-header">
            <div>
              <h1 className="app-title">Calendar Assistant</h1>
              <p className="muted small">Signed in as {user.email ?? user.google_sub}</p>
            </div>
            <div className="header-actions">
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

          {historyError && (
            <div className="banner banner-error" role="alert">
              <span>{historyError}</span>
              {conversationId && (
                <button
                  type="button"
                  className="btn"
                  onClick={() => setHistoryRetryToken((v) => v + 1)}
                  disabled={busy}
                >
                  Retry
                </button>
              )}
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

            <ChatComposer
              onSend={(t) => void sendMessage(t)}
              disabled={busy || historyLoading}
            />
          </section>
        </section>
      </div>
    </div>
  );
}
