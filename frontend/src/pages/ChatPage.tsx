import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Composer, Thread } from "../components/Thread";
import { Sidebar } from "../components/Sidebar";
import { MenuIcon } from "../components/icons";
import { Notice, SkipLink, Spinner, ThemeToggle, Toast } from "../components/ui";
import { BlockedError, api, streamMessage } from "../lib/api";
import type { BlockedPayload, ConversationSummary, Message } from "../lib/types";
import { useSession } from "../state/session";

export function ChatPage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const navigate = useNavigate();
  const { session, usage, setUsage, signOut, refreshUsage } = useSession();

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [creating, setCreating] = useState(false);

  const [messages, setMessages] = useState<Message[]>([]);
  const [loadingThread, setLoadingThread] = useState(false);
  const [streaming, setStreaming] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [blocked, setBlocked] = useState<BlockedPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  const [draft, setDraft] = useState({ key: 0, text: "" });
  const [toast, setToast] = useState<string | null>(null);
  const [retryIn, setRetryIn] = useState<number | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  const loadConversations = useCallback(async () => {
    try {
      setConversations(await api.conversations());
    } catch {
      setError("Couldn't load your conversation history.");
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  // Resume (FR-04): the conversation id lives in the URL, so a bookmark or a
  // reload reopens the same thread with its full history.
  useEffect(() => {
    if (!conversationId) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    setLoadingThread(true);
    setError(null);
    setBlocked(null);
    (async () => {
      try {
        const detail = await api.conversation(conversationId);
        if (!cancelled) setMessages(detail.messages);
      } catch {
        if (!cancelled) {
          setError("That conversation couldn't be opened.");
          navigate("/", { replace: true });
        }
      } finally {
        if (!cancelled) setLoadingThread(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [conversationId, navigate]);

  // Abandon an in-flight stream when the user switches threads.
  useEffect(() => () => abortRef.current?.abort(), [conversationId]);

  const startConversation = useCallback(async () => {
    setCreating(true);
    try {
      const created = await api.createConversation();
      await loadConversations();
      navigate(`/c/${created.id}`);
      setNavOpen(false);
    } catch {
      setError("Couldn't start a new conversation.");
    } finally {
      setCreating(false);
    }
  }, [loadConversations, navigate]);

  const archive = useCallback(
    async (id: string) => {
      await api.archiveConversation(id).catch(() => undefined);
      await loadConversations();
      if (id === conversationId) navigate("/", { replace: true });
      setToast("Conversation archived");
    },
    [conversationId, loadConversations, navigate],
  );

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (blocked?.reason !== "rate_limited" || !blocked.retry_after_seconds) {
      setRetryIn(null);
      return;
    }
    setRetryIn(blocked.retry_after_seconds);
    const timer = window.setInterval(() => {
      setRetryIn((current) => {
        if (current === null || current <= 1) {
          window.clearInterval(timer);
          return 0;
        }
        return current - 1;
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [blocked]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable;
      if (typing) return;
      if (event.key === "/" || (event.key === "k" && (event.metaKey || event.ctrlKey))) {
        event.preventDefault();
        document.getElementById("composer")?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const send = useCallback(
    async (text: string) => {
      let targetId = conversationId;
      if (!targetId) {
        const created = await api.createConversation();
        targetId = created.id;
        navigate(`/c/${created.id}`);
      }

      // Idempotency key: a double-click or a retry replays the stored turn
      // instead of charging the learner's cap twice.
      const requestId = crypto.randomUUID();
      const controller = new AbortController();
      abortRef.current = controller;

      setPending(text);
      setStreaming("");
      setBlocked(null);
      setError(null);

      try {
        await streamMessage(
          targetId,
          text,
          requestId,
          {
            onDelta: (piece) => setStreaming((previous) => previous + piece),
            onDone: (payload) => {
              setMessages((previous) => [
                ...previous,
                payload.user_message,
                payload.assistant_message,
              ]);
              setStreaming("");
              setPending(null);
              setUsage(payload.usage);
              void loadConversations();
            },
            onError: (message) => {
              setStreaming("");
              setPending(null);
              setError(message);
              void refreshUsage();
            },
          },
          controller.signal,
        );
      } catch (caught) {
        setStreaming("");
        setPending(null);
        if (caught instanceof BlockedError) {
          setBlocked(caught.payload);
          setUsage(caught.payload.usage);
          // The blocked turn is persisted server-side, so pull it in to keep the
          // thread an accurate record of what happened.
          if (targetId) {
            const detail = await api.conversation(targetId).catch(() => null);
            if (detail) setMessages(detail.messages);
          }
        } else if ((caught as Error)?.name !== "AbortError") {
          setError((caught as Error).message || "Something went wrong sending that message.");
          void refreshUsage();
        }
      } finally {
        abortRef.current = null;
      }
    },
    [conversationId, loadConversations, navigate, refreshUsage, setUsage],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming("");
    setPending(null);
  }, []);

  if (!session) return null;

  const busy = pending !== null;
  const capBlocked = blocked !== null && blocked.reason !== "rate_limited";
  const active = conversations.find((item) => item.id === conversationId);
  const heading = active?.title ?? "New conversation";

  return (
    <div className="h-full min-h-0 flex">
      <SkipLink />
      <Sidebar
        session={session}
        usage={usage}
        conversations={conversations}
        loading={loadingList}
        activeId={conversationId ?? null}
        onNew={startConversation}
        onArchive={archive}
        onSignOut={signOut}
        creating={creating}
        open={navOpen}
        onClose={() => setNavOpen(false)}
      />

      <div className="flex-1 min-w-0 min-h-0 flex flex-col">
        <header className="h-14 shrink-0 flex items-center gap-2 px-2 md:px-4 border-b border-[var(--color-border)] bg-[var(--color-surface)]">
          <button
            type="button"
            className="md:hidden inline-flex items-center justify-center w-11 h-11 rounded-[var(--radius-sm)] text-[var(--color-fg-muted)] hover:bg-[var(--color-muted)]"
            aria-label="Open conversation list"
            aria-expanded={navOpen}
            onClick={() => setNavOpen(true)}
          >
            <MenuIcon />
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="text-[22px] leading-none truncate">{heading}</h1>
            <p className="text-[13px] text-[var(--color-fg-subtle)] truncate">
              {session.advisor.name}
            </p>
          </div>
          <ThemeToggle />
        </header>

        <main id="main" className="flex-1 min-h-0 flex flex-col">
          {loadingThread ? (
            <div className="flex-1 flex items-center justify-center">
              <Spinner label="Opening conversation…" />
            </div>
          ) : (
            <Thread
              messages={messages}
              streaming={streaming}
              pending={pending}
              error={error}
              onUsePrompt={(text) => setDraft((previous) => ({ key: previous.key + 1, text }))}
              notice={
                blocked && (
                  <Notice
                    tone={blocked.reason === "rate_limited" ? "info" : "warn"}
                    title={
                      blocked.reason === "rate_limited"
                        ? "Slow down a moment"
                        : "Daily limit reached"
                    }
                  >
                    <p>{blocked.message}</p>
                    {blocked.reason === "rate_limited" && retryIn !== null && (
                      <p className="mt-1 tabular">
                        {retryIn > 0 ? `Try again in ${retryIn}s` : "You can send again now."}
                      </p>
                    )}
                    {blocked.reason !== "rate_limited" && (
                      <p className="mt-1">
                        You can still read your past conversations while you wait.
                      </p>
                    )}
                  </Notice>
                )
              }
            />
          )}

          <Composer
            onSend={send}
            onStop={stop}
            seed={`${draft.key}:${draft.text}`}
            busy={busy}
            disabled={capBlocked}
            disabledReason={
              capBlocked
                ? "Your daily limit is reached — sending resumes after it resets."
                : undefined
            }
          />
        </main>
      </div>
      <Toast message={toast} />
    </div>
  );
}
