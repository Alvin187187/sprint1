import { useEffect, useRef, useState } from "react";

import { formatTime } from "../lib/format";
import type { Message } from "../lib/types";
import { AlertIcon, CopyIcon, SendIcon, StopIcon } from "./icons";
import { Badge, Button, TypingDots, cx } from "./ui";

const STARTERS = [
  {
    label: "10 hours a week",
    text: "I have about 10 hours a week. I’m switching from a non-data job in the Philippines — what should I prioritise first?",
  },
  {
    label: "Portfolio, not more courses",
    text: "I already have a few online certificates. Help me plan a portfolio that hiring managers here will actually look at.",
  },
  {
    label: "SQL vs Python first",
    text: "I’m deciding between going deeper on SQL or starting Python. I want a junior data analyst role in Metro Manila.",
  },
];

/** Minimal, deliberate markdown: paragraphs, list items, and **bold**.
 *  Rendering raw HTML from a model response would be an injection vector. */
function renderInline(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={index} className="font-semibold">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <span key={index}>{part}</span>
    ),
  );
}

const LIST_ITEM = /^(\s*)([-*•]|\d+[.)])\s+(.*)$/;

type MessageBlock =
  | { kind: "p"; text: string }
  | { kind: "ol" | "ul"; items: string[] };

/** Blank lines between "1." / "2." items must stay one list. Splitting on
 *  those gaps used to emit a fresh <ol> per step, so every marker was 1. */
function parseMessage(content: string): MessageBlock[] {
  const lines = content.split("\n");
  const blocks: MessageBlock[] = [];
  let i = 0;

  while (i < lines.length) {
    while (i < lines.length && lines[i].trim() === "") i++;
    if (i >= lines.length) break;

    const first = lines[i].match(LIST_ITEM);
    if (first) {
      const ordered = /^\d/.test(first[2]);
      const items: string[] = [];
      while (i < lines.length) {
        if (lines[i].trim() === "") {
          let look = i + 1;
          while (look < lines.length && lines[look].trim() === "") look++;
          const next = look < lines.length ? lines[look].match(LIST_ITEM) : null;
          if (!next || ordered !== /^\d/.test(next[2])) break;
          i = look;
          continue;
        }
        const item = lines[i].match(LIST_ITEM);
        if (!item || ordered !== /^\d/.test(item[2])) break;
        let text = item[3];
        i++;
        while (i < lines.length && lines[i].trim() !== "" && !LIST_ITEM.test(lines[i])) {
          text += ` ${lines[i].trim()}`;
          i++;
        }
        items.push(text);
      }
      blocks.push({ kind: ordered ? "ol" : "ul", items });
      continue;
    }

    const para: string[] = [];
    while (i < lines.length && lines[i].trim() !== "") {
      para.push(lines[i].trim());
      i++;
    }
    blocks.push({ kind: "p", text: para.join(" ") });
  }
  return blocks;
}

function MessageBody({ content }: { content: string }) {
  const blocks = parseMessage(content);
  return (
    <div className="flex flex-col gap-2.5">
      {blocks.map((block, blockIndex) => {
        if (block.kind === "p") {
          return <p key={blockIndex}>{renderInline(block.text)}</p>;
        }
        const Tag = block.kind;
        return (
          <Tag
            key={blockIndex}
            className={cx(
              "pl-5 space-y-1.5 marker:text-[var(--color-fg-subtle)]",
              block.kind === "ol" ? "list-decimal" : "list-disc",
            )}
          >
            {block.items.map((item, itemIndex) => (
              <li key={itemIndex}>{renderInline(item)}</li>
            ))}
          </Tag>
        );
      })}
    </div>
  );
}

function statusNote(status: Message["status"]): string | null {
  switch (status) {
    case "blocked_cap":
      return "Limit reached";
    case "blocked_rate":
      return "Rate limited";
    case "provider_error":
      return "Model unavailable";
    case "doc_error":
      return "Configuration unavailable";
    case "truncated":
      return "Reply cut short";
    case "redacted":
      return "Response withheld";
    default:
      return null;
  }
}

function MessageRow({ message }: { message: Message }) {
  const note = statusNote(message.status);
  const isUser = message.role === "user";
  const problem = note !== null && message.status !== "truncated";
  const [copied, setCopied] = useState(false);
  const fresh = Date.now() - new Date(message.created_at).getTime() < 2500;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard may be denied */
    }
  };

  return (
    <article
      className={cx(
        "px-4 md:px-6 py-3 flex",
        isUser ? "justify-end" : "justify-start",
        fresh && "anim-in",
      )}
    >
      <div className={cx("w-full", isUser ? "max-w-[min(100%,40rem)]" : "max-w-[48rem]")}>
        <header className="flex items-center gap-2 mb-1">
          <h3 className="text-[13px] font-semibold">{isUser ? "You" : "Advisor"}</h3>
          <time
            dateTime={message.created_at}
            className="text-[13px] text-[var(--color-fg-subtle)] tabular"
          >
            {formatTime(message.created_at)}
          </time>
          {note && <Badge tone={problem ? "warn" : "info"}>{note}</Badge>}
          {!isUser && (
            <button
              type="button"
              onClick={() => void copy()}
              className="ml-auto inline-flex items-center gap-1 text-[13px] text-[var(--color-fg-subtle)] hover:text-[var(--color-fg)] transition-colors duration-150"
            >
              <CopyIcon />
              {copied ? "Copied" : "Copy"}
            </button>
          )}
        </header>
        <div
          className={cx(
            "text-[17px] leading-[1.6] text-pretty",
            isUser
              ? "rounded-[var(--radius-md)] bg-[var(--color-surface)] border border-[var(--color-border)] px-3.5 py-3"
              : "text-[var(--color-fg)]",
          )}
        >
          <MessageBody content={message.content} />
        </div>
      </div>
    </article>
  );
}

export function Thread({
  messages,
  streaming,
  pending,
  notice,
  error,
  onUsePrompt,
}: {
  messages: Message[];
  streaming: string;
  pending: string | null;
  notice: React.ReactNode;
  error: string | null;
  onUsePrompt: (text: string) => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  // Follow the stream, but stop fighting the user the moment they scroll up.
  useEffect(() => {
    if (autoScroll) endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, streaming, pending, autoScroll]);

  return (
    <div
      className="flex-1 overflow-y-auto scroll-thin"
      onScroll={(event) => {
        const el = event.currentTarget;
        setAutoScroll(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
      }}
    >
      {messages.length === 0 && !pending && (
        <div className="px-4 md:px-6 py-5 anim-in">
          <h2 className="text-[32px] leading-[1.15]">Where should we start?</h2>
          <p className="mt-2 text-[16px] text-[var(--color-fg-muted)] max-w-[40rem] leading-relaxed">
            Pathway, skill order, portfolio, interviews. Name the constraint: time, money, or a
            target role.
          </p>
          <ul className="mt-4 grid gap-2 sm:grid-cols-3">
            {STARTERS.map((item) => (
              <li key={item.label} className="min-w-0">
                <button
                  type="button"
                  onClick={() => onUsePrompt(item.text)}
                  className={cx(
                    "h-full w-full text-left px-3 py-3 rounded-[var(--radius-sm)] lift",
                    "border border-[var(--color-border)] bg-[var(--color-surface)]",
                    "hover:border-[var(--color-accent)] hover:bg-[var(--color-muted)]",
                    "transition-colors duration-150",
                  )}
                >
                  <span className="block text-[16px] font-semibold">{item.label}</span>
                  <span className="block mt-1 text-[14px] text-[var(--color-fg-muted)] leading-snug">
                    {item.text}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {messages.map((message) => (
        <MessageRow key={message.id} message={message} />
      ))}

      {pending && (
        <MessageRow
          message={{
            id: "pending",
            role: "user",
            content: pending,
            status: "ok",
            created_at: new Date().toISOString(),
          }}
        />
      )}

      {(streaming || pending) && (
        <article className="px-4 md:px-6 py-3 anim-in" aria-busy="true">
          <div className="max-w-[48rem]">
            <header className="flex items-center gap-2 mb-1">
              <h3 className="text-[13px] font-semibold">Advisor</h3>
              {!streaming && <TypingDots label="Thinking…" />}
            </header>
            <div className="text-[17px] leading-[1.6]" aria-live="polite" aria-atomic="false">
              <MessageBody content={streaming} />
              {streaming && <span className="caret" aria-hidden />}
            </div>
          </div>
        </article>
      )}

      {notice && <div className="px-4 md:px-6 py-4">{notice}</div>}

      {error && (
        <div className="px-4 md:px-6 py-4">
          <div
            role="alert"
            className="flex items-start gap-2 border border-[var(--color-danger)] bg-[var(--color-danger-muted)] rounded-[var(--radius-sm)] px-3 py-2.5 text-[13px]"
          >
            <AlertIcon className="mt-0.5 shrink-0 text-[var(--color-danger-fg)]" />
            <p>{error}</p>
          </div>
        </div>
      )}

      <div ref={endRef} />
    </div>
  );
}

export function Composer({
  onSend,
  onStop,
  seed,
  busy,
  disabled,
  disabledReason,
}: {
  onSend: (text: string) => void;
  onStop: () => void;
  seed: string;
  busy: boolean;
  disabled: boolean;
  disabledReason?: string;
}) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  const limit = 4000;
  const tooLong = value.length > limit;

  useEffect(() => {
    const sep = seed.indexOf(":");
    if (sep < 0) return;
    const text = seed.slice(sep + 1);
    if (!text) return;
    setValue(text);
    ref.current?.focus();
  }, [seed]);

  const submit = () => {
    const text = value.trim();
    if (!text || busy || disabled || tooLong) return;
    onSend(text);
    setValue("");
    ref.current?.focus();
  };

  // Grow with content up to a ceiling, so a long message is reviewable before sending.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  return (
    <form
      className="border-t border-[var(--color-border)] bg-[var(--color-surface)] px-3 md:px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div className="flex items-end gap-2">
        <div className="flex-1 min-w-0">
          <label htmlFor="composer" className="sr-only">
            Message the advisor
          </label>
          <textarea
            id="composer"
            name="message"
            ref={ref}
            rows={1}
            value={value}
            disabled={disabled}
            autoComplete="off"
            spellCheck
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder={
              disabled ? (disabledReason ?? "Sending is unavailable") : "Ask the advisor…"
            }
            aria-describedby="composer-hint"
            aria-invalid={tooLong}
            className={cx(
              "w-full resize-none px-3 py-3 rounded-[var(--radius-sm)] bg-[var(--color-surface)]",
              "border text-[16px] leading-relaxed transition-[border-color] duration-150",
              tooLong
                ? "border-[var(--color-danger)]"
                : "border-[var(--color-border-strong)] hover:border-[var(--color-fg-subtle)]",
              "disabled:opacity-55",
            )}
          />
        </div>
        {busy ? (
          <Button type="button" variant="default" onClick={onStop} aria-label="Stop generating">
            <StopIcon />
            Stop
          </Button>
        ) : (
          <Button type="submit" variant="primary" disabled={disabled || !value.trim() || tooLong}>
            <SendIcon />
            Send
          </Button>
        )}
      </div>

      <div className="flex items-center justify-between mt-1.5">
        <p id="composer-hint" className="text-[13px] text-[var(--color-fg-subtle)]">
          {disabled
            ? (disabledReason ?? "")
            : "Enter to send · Shift+Enter for a new line · / to focus"}
        </p>
        {value.length > limit * 0.75 && (
          <p
            className={cx(
              "text-[11.5px] tabular",
              tooLong ? "text-[var(--color-danger-fg)]" : "text-[var(--color-fg-subtle)]",
            )}
          >
            {value.length.toLocaleString()} / {limit.toLocaleString()}
          </p>
        )}
      </div>
    </form>
  );
}
