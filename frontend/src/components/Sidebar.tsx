import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { formatRelative } from "../lib/format";
import type { ConversationSummary, Session, Usage } from "../lib/types";
import { CloseIcon, GaugeIcon, LogOutIcon, PlusIcon, TrashIcon } from "./icons";
import { UsageMeter } from "./UsageMeter";
import { Button, ConfirmDialog, Spinner, cx } from "./ui";

/**
 * Fixed 256px rail, solid surface, single border-right. On narrow viewports it
 * becomes a left drawer with an overlay — never a floating rounded shell.
 */
export function Sidebar({
  session,
  usage,
  conversations,
  loading,
  activeId,
  onNew,
  onArchive,
  onSignOut,
  creating,
  open,
  onClose,
}: {
  session: Session;
  usage: Usage | null;
  conversations: ConversationSummary[];
  loading: boolean;
  activeId: string | null;
  onNew: () => void;
  onArchive: (id: string) => void;
  onSignOut: () => void;
  creating: boolean;
  open: boolean;
  onClose: () => void;
}) {
  const [pendingArchive, setPendingArchive] = useState<ConversationSummary | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <>
      <button
        type="button"
        aria-label="Close conversation list"
        className={cx(
          "fixed inset-0 z-30 bg-[color-mix(in_srgb,var(--color-bg)_45%,black)] md:hidden",
          "transition-opacity duration-[180ms] ease-out",
          open ? "opacity-100" : "opacity-0 pointer-events-none",
        )}
        onClick={onClose}
      />

      <nav
        aria-label="Conversations"
        className={cx(
          "w-72 shrink-0 h-full flex flex-col border-r border-[var(--color-border)] bg-[var(--color-surface)]",
          "overscroll-contain drawer",
          "max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-40",
          open ? "max-md:translate-x-0" : "max-md:-translate-x-full max-md:pointer-events-none",
        )}
      >
        <div className="px-3 h-14 flex items-center justify-between gap-2 border-b border-[var(--color-border)]">
          <div className="min-w-0">
            <p className="font-display text-[20px] leading-tight truncate">{session.advisor.name}</p>
            <p className="text-[13px] text-[var(--color-fg-subtle)]">Console</p>
          </div>
          <button
            type="button"
            className="md:hidden inline-flex items-center justify-center w-11 h-11 rounded-[var(--radius-sm)] text-[var(--color-fg-muted)] hover:bg-[var(--color-muted)]"
            aria-label="Close conversation list"
            onClick={onClose}
          >
            <CloseIcon />
          </button>
        </div>

        <div className="p-2">
          <Button onClick={onNew} disabled={creating} className="w-full">
            <PlusIcon />
            {creating ? "Starting…" : "New conversation"}
          </Button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto scroll-thin px-2 pb-2">
          <h2 className="px-1 py-1 text-[13px] font-semibold uppercase tracking-wide text-[var(--color-fg-subtle)]">
            History
          </h2>

          {loading && (
            <div className="px-1 py-2">
              <Spinner label="Loading conversations…" />
            </div>
          )}

          {!loading && conversations.length === 0 && (
            <p className="px-1 py-2 text-[12.5px] text-[var(--color-fg-subtle)]">
              No conversations yet. Start one.
            </p>
          )}

          <ul className="flex flex-col gap-0.5">
            {conversations.map((conversation) => {
              const active = conversation.id === activeId;
              return (
                <li key={conversation.id} className="relative">
                  <NavLink
                    to={`/c/${conversation.id}`}
                    onClick={onClose}
                    className={cx(
                      "block pl-2 pr-11 py-2 rounded-[var(--radius-sm)] transition-colors duration-150",
                      active
                        ? "bg-[var(--color-muted)] text-[var(--color-fg)]"
                        : "text-[var(--color-fg-muted)] hover:bg-[var(--color-muted)] hover:text-[var(--color-fg)]",
                    )}
                    aria-current={active ? "page" : undefined}
                  >
                    <span className="block text-[15px] font-medium truncate">{conversation.title}</span>
                    <span className="block text-[13px] text-[var(--color-fg-subtle)] tabular">
                      {formatRelative(conversation.last_message_at ?? conversation.created_at)}
                      {conversation.message_count > 0 && ` · ${conversation.message_count} msg`}
                    </span>
                  </NavLink>

                  <button
                    type="button"
                    onClick={() => setPendingArchive(conversation)}
                    aria-label={`Archive “${conversation.title}”`}
                    className={cx(
                      "absolute right-1 top-1.5 w-8 h-8 inline-flex items-center justify-center",
                      "rounded-[var(--radius-xs)] text-[var(--color-fg-subtle)]",
                      "hover:text-[var(--color-danger-fg)] hover:bg-[var(--color-danger-muted)]",
                      "transition-colors duration-150",
                    )}
                  >
                    <TrashIcon />
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        <UsageMeter usage={usage} />

        <div className="border-t border-[var(--color-border)] p-2 flex flex-col gap-1">
          <div className="px-1 pb-1">
            <p className="text-[15px] font-medium truncate">{session.user.display_name}</p>
            <p className="text-[13px] text-[var(--color-fg-subtle)] truncate">{session.user.email}</p>
          </div>

          {session.user.role === "admin" && (
            <NavLink
              to="/admin"
              onClick={onClose}
              className={({ isActive }) =>
                cx(
                  "inline-flex items-center gap-2 h-11 px-2 rounded-[var(--radius-sm)] text-[15px]",
                  "transition-colors duration-150",
                  isActive
                    ? "bg-[var(--color-muted)]"
                    : "text-[var(--color-fg-muted)] hover:bg-[var(--color-muted)] hover:text-[var(--color-fg)]",
                )
              }
            >
              <GaugeIcon />
              Admin
            </NavLink>
          )}

          <button
            type="button"
            onClick={onSignOut}
            className={cx(
              "inline-flex items-center gap-2 h-11 px-2 rounded-[var(--radius-sm)] text-[15px]",
              "text-[var(--color-fg-muted)] hover:bg-[var(--color-muted)] hover:text-[var(--color-fg)]",
              "transition-colors duration-150",
            )}
          >
            <LogOutIcon />
            Sign out
          </button>
        </div>
      </nav>

      <ConfirmDialog
        open={pendingArchive !== null}
        title="Archive this conversation?"
        description="It leaves your history list. You can still ask an admin to look it up from the logs if you need it later."
        confirmLabel="Archive"
        danger
        onCancel={() => setPendingArchive(null)}
        onConfirm={() => {
          if (pendingArchive) onArchive(pendingArchive.id);
          setPendingArchive(null);
        }}
      />
    </>
  );
}
