import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ArrowLeftIcon, RefreshIcon, ShieldIcon } from "../components/icons";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  Notice,
  Panel,
  SkipLink,
  Spinner,
  StatusBadge,
  ThemeToggle,
  cx,
  td,
  tdRight,
} from "../components/ui";
import { api } from "../lib/api";
import { formatCost, formatLatency, formatNumber, formatRelative, formatTimestamp } from "../lib/format";
import type {
  AdminConversation,
  AdminEvent,
  AdminOverview,
  AdminTurn,
  AdminUsageRow,
} from "../lib/types";

type Tab = "turns" | "usage" | "conversations" | "events";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "turns", label: "Turns" },
  { id: "usage", label: "Usage" },
  { id: "conversations", label: "Conversations" },
  { id: "events", label: "Events" },
];

/** Label/value pairs in one dense strip — the numbers are reference figures, not
 *  the point of the page, so they don't get a card grid. */
function StatStrip({ items }: { items: Array<{ label: string; value: string; tone?: "warn" | "danger" }> }) {
  return (
    <dl className="flex flex-wrap gap-x-8 gap-y-3 px-4 py-3">
      {items.map((item) => (
        <div key={item.label}>
          <dt className="text-[13px] text-[var(--color-fg-muted)]">{item.label}</dt>
          <dd
            className={cx(
              "text-[18px] font-semibold tabular leading-tight",
              item.tone === "danger" && "text-[var(--color-danger-fg)]",
              item.tone === "warn" && "text-[var(--color-warn-fg)]",
            )}
          >
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function AdminPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const tab: Tab = TABS.some((item) => item.id === tabParam) ? (tabParam as Tab) : "turns";
  const setTab = (next: Tab) => {
    const params = new URLSearchParams(searchParams);
    if (next === "turns") params.delete("tab");
    else params.set("tab", next);
    setSearchParams(params, { replace: true });
  };

  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [turns, setTurns] = useState<AdminTurn[]>([]);
  const [usage, setUsage] = useState<AdminUsageRow[]>([]);
  const [conversations, setConversations] = useState<AdminConversation[]>([]);
  const [events, setEvents] = useState<AdminEvent[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshNote, setRefreshNote] = useState<string | null>(null);

  const loadOverview = useCallback(async () => {
    try {
      setOverview(await api.admin.overview());
    } catch (caught) {
      setError((caught as Error).message);
    }
  }, []);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        if (tab === "turns") {
          const rows = await api.admin.turns({ limit: 100, status: statusFilter || undefined });
          if (!cancelled) setTurns(rows);
        } else if (tab === "usage") {
          const rows = await api.admin.usage(7);
          if (!cancelled) setUsage(rows);
        } else if (tab === "conversations") {
          const rows = await api.admin.conversations(60);
          if (!cancelled) setConversations(rows);
        } else {
          const rows = await api.admin.events({ limit: 120 });
          if (!cancelled) setEvents(rows);
        }
      } catch (caught) {
        if (!cancelled) setError((caught as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tab, statusFilter]);

  const refreshDocs = async () => {
    setRefreshNote(null);
    try {
      const result = await api.admin.refreshDocs();
      setRefreshNote(
        `Re-read from source in ${result.elapsed_ms}ms · prompt ${result.prompt_revision ?? "—"} · grounding ${result.grounding_revision ?? "—"}${
          result.stale.length ? ` · serving last-good for ${result.stale.join(", ")}` : ""
        }`,
      );
      await loadOverview();
    } catch (caught) {
      setError((caught as Error).message);
    }
  };

  const totals = overview?.totals;

  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <SkipLink />
      <header className="sticky top-0 z-10 flex items-center justify-between gap-3 min-h-14 py-1 px-3 md:px-4 border-b border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="flex items-center gap-3 min-w-0">
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 min-h-11 md:min-h-0 text-[13px] text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] transition-colors duration-150"
          >
            <ArrowLeftIcon />
            Chat
          </Link>
          <span aria-hidden className="text-[var(--color-border-strong)]">
            /
          </span>
          <h1 className="text-[22px] leading-none">Admin</h1>
        </div>
        <div className="flex items-center gap-1">
          <ThemeToggle />
          <Button size="sm" onClick={refreshDocs}>
            <RefreshIcon />
            Re-read docs
          </Button>
        </div>
      </header>

      <main id="main" className="p-4 flex flex-col gap-4 max-w-[1400px]">
        {error && (
          <Notice tone="danger" title="Something failed to load">
            {error}
          </Notice>
        )}

        {refreshNote && (
          <Notice tone="ok" title="Prompt and grounding re-read from source">
            <span className="font-mono text-[12px]">{refreshNote}</span>
          </Notice>
        )}

        <Panel
          title="Activity"
          description={
            totals
              ? `${totals.model} · docs via ${totals.doc_provider} · ${totals.doc_cache_ttl_seconds}s cache TTL · caps reset midnight ${totals.timezone}`
              : undefined
          }
        >
          {totals ? (
            <StatStrip
              items={[
                { label: "Users", value: formatNumber(totals.users) },
                { label: "Conversations", value: formatNumber(totals.conversations) },
                { label: "Messages", value: formatNumber(totals.messages) },
                { label: "Tokens", value: formatNumber(totals.tokens) },
                { label: "Estimated spend", value: formatCost(totals.est_cost_usd) },
                {
                  label: "Blocked",
                  value: formatNumber(totals.blocked),
                  tone: totals.blocked > 0 ? "warn" : undefined,
                },
                {
                  label: "Errored",
                  value: formatNumber(totals.errored),
                  tone: totals.errored > 0 ? "danger" : undefined,
                },
                { label: "Median-ish latency", value: formatLatency(totals.avg_latency_ms) },
                {
                  label: "Default caps",
                  value: `${formatNumber(totals.default_message_cap)} msg / ${formatNumber(totals.default_token_cap)} tok`,
                },
                { label: "Rate limit", value: `${totals.rate_limit_per_minute}/min` },
              ]}
            />
          ) : (
            <div className="px-3.5 py-3">
              <Spinner label="Loading" />
            </div>
          )}
        </Panel>

        <Panel
          title="Prompt & grounding control plane"
          description="Revision hashes only — document bodies are never served to a client."
        >
          {overview && overview.docs.length > 0 ? (
            <DataTable
              caption="Current prompt and grounding document revisions"
              columns={[
                { key: "kind", label: "Document" },
                { key: "source", label: "Source" },
                { key: "revision", label: "Revision" },
                { key: "chars", label: "Size", align: "right" },
                { key: "cache", label: "Cache" },
                { key: "fetched", label: "Last read" },
              ]}
            >
              {overview.docs.map((doc) => (
                <tr key={doc.kind}>
                  <td className={td}>
                    <span className="inline-flex items-center gap-1.5">
                      <ShieldIcon className="text-[var(--color-fg-subtle)]" />
                      {doc.kind}
                    </span>
                  </td>
                  <td className={td}>{doc.source}</td>
                  <td className={td}>
                    <Badge>{doc.revision}</Badge>
                  </td>
                  <td className={tdRight}>{formatNumber(doc.char_count)}</td>
                  <td className={td}>
                    {doc.stale ? (
                      <Badge tone="danger">last-good (source failing)</Badge>
                    ) : doc.cache_expires_in_seconds !== null &&
                      doc.cache_expires_in_seconds !== undefined ? (
                      <span className="tabular text-[var(--color-fg-muted)]">
                        expires in {doc.cache_expires_in_seconds}s
                      </span>
                    ) : (
                      <span className="text-[var(--color-fg-subtle)]">not cached</span>
                    )}
                  </td>
                  <td className={td}>{formatRelative(doc.fetched_at)}</td>
                </tr>
              ))}
            </DataTable>
          ) : (
            <EmptyState title="No document revisions recorded yet">
              Send one message, or use “Re-read docs”, to populate the snapshot registry.
            </EmptyState>
          )}
        </Panel>

        <Panel
          title="Logs"
          actions={
            <>
              {tab === "turns" && (
                <>
                  <label htmlFor="status-filter" className="sr-only">
                    Filter by status
                  </label>
                  <select
                    id="status-filter"
                    value={statusFilter}
                    onChange={(event) => setStatusFilter(event.target.value)}
                    className="h-8 px-2 text-[12.5px] rounded-[var(--radius-sm)] bg-[var(--color-bg)] border border-[var(--color-border-strong)]"
                  >
                    <option value="">All statuses</option>
                    <option value="ok">ok</option>
                    <option value="blocked_cap">blocked_cap</option>
                    <option value="blocked_rate">blocked_rate</option>
                    <option value="provider_error">provider_error</option>
                    <option value="doc_error">doc_error</option>
                    <option value="redacted">redacted</option>
                    <option value="truncated">truncated</option>
                  </select>
                </>
              )}
              <div
                role="tablist"
                aria-label="Log view"
                className="flex items-end gap-0 border-b border-[var(--color-border)]"
                onKeyDown={(event) => {
                  const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
                  if (!keys.includes(event.key)) return;
                  event.preventDefault();
                  const index = TABS.findIndex((item) => item.id === tab);
                  let next = index;
                  if (event.key === "ArrowRight") next = (index + 1) % TABS.length;
                  if (event.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
                  if (event.key === "Home") next = 0;
                  if (event.key === "End") next = TABS.length - 1;
                  setTab(TABS[next].id);
                }}
              >
                {TABS.map((item) => (
                  <button
                    key={item.id}
                    role="tab"
                    id={`tab-${item.id}`}
                    aria-selected={tab === item.id}
                    tabIndex={tab === item.id ? 0 : -1}
                    onClick={() => setTab(item.id)}
                    className={cx(
                      "h-10 px-3 text-[14px] border-b-2 -mb-px transition-colors duration-150",
                      tab === item.id
                        ? "border-[var(--color-fg)] text-[var(--color-fg)]"
                        : "border-transparent text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]",
                    )}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </>
          }
        >
          {loading ? (
            <div className="px-3.5 py-4">
              <Spinner label="Loading" />
            </div>
          ) : tab === "turns" ? (
            turns.length === 0 ? (
              <EmptyState title="No turns match this filter" />
            ) : (
              <DataTable
                caption="Recent logged turns with token counts, cost, and the prompt revision used"
                columns={[
                  { key: "when", label: "When" },
                  { key: "user", label: "User" },
                  { key: "role", label: "Role" },
                  { key: "status", label: "Status" },
                  { key: "content", label: "Content" },
                  { key: "prompt", label: "Prompt rev" },
                  { key: "chunks", label: "Grounding chunks" },
                  { key: "tokens", label: "Tokens", align: "right" },
                  { key: "cost", label: "Cost", align: "right" },
                  { key: "latency", label: "Latency", align: "right" },
                ]}
              >
                {turns.map((turn) => (
                  <tr key={turn.message_id}>
                    <td className={`${td} whitespace-nowrap text-[var(--color-fg-muted)]`}>
                      {formatTimestamp(turn.created_at)}
                    </td>
                    <td className={`${td} whitespace-nowrap`}>{turn.user_email}</td>
                    <td className={td}>{turn.role}</td>
                    <td className={td}>
                      <StatusBadge status={turn.status} />
                    </td>
                    <td className={`${td} min-w-[26rem] max-w-[34rem] text-[var(--color-fg-muted)]`}>
                      {turn.content_excerpt}
                    </td>
                    <td className={td}>
                      {turn.prompt_revision ? <Badge>{turn.prompt_revision}</Badge> : "—"}
                    </td>
                    <td className={`${td} font-mono text-[11.5px] text-[var(--color-fg-muted)]`}>
                      {turn.grounding_chunk_ids.length ? turn.grounding_chunk_ids.join(", ") : "—"}
                    </td>
                    <td className={tdRight}>{formatNumber(turn.tokens)}</td>
                    <td className={tdRight}>{formatCost(turn.est_cost_usd)}</td>
                    <td className={tdRight}>{formatLatency(turn.latency_ms)}</td>
                  </tr>
                ))}
              </DataTable>
            )
          ) : tab === "usage" ? (
            usage.length === 0 ? (
              <EmptyState title="No usage recorded in the last 7 days" />
            ) : (
              <DataTable
                caption="Per-user daily usage against caps"
                columns={[
                  { key: "day", label: "Day" },
                  { key: "user", label: "User" },
                  { key: "messages", label: "Messages", align: "right" },
                  { key: "tokens", label: "Tokens", align: "right" },
                  { key: "spend", label: "Spend", align: "right" },
                  { key: "caps", label: "Caps", align: "right" },
                ]}
              >
                {usage.map((row, index) => {
                  const atCap =
                    row.daily_message_cap > 0 && row.messages_used >= row.daily_message_cap;
                  return (
                    <tr key={`${row.user_id}-${row.usage_date ?? index}`}>
                      <td className={`${td} whitespace-nowrap tabular`}>{row.usage_date ?? "—"}</td>
                      <td className={td}>
                        <span className="block">{row.display_name}</span>
                        <span className="block text-[11.5px] text-[var(--color-fg-subtle)]">
                          {row.email}
                        </span>
                      </td>
                      <td className={cx(tdRight, atCap && "text-[var(--color-warn-fg)]")}>
                        {formatNumber(row.messages_used)}
                      </td>
                      <td className={tdRight}>{formatNumber(row.tokens_used)}</td>
                      <td className={tdRight}>{formatCost(row.est_spend_usd)}</td>
                      <td className={`${tdRight} text-[var(--color-fg-muted)]`}>
                        {row.daily_message_cap || "∞"} / {formatNumber(row.daily_token_cap) || "∞"}
                      </td>
                    </tr>
                  );
                })}
              </DataTable>
            )
          ) : tab === "conversations" ? (
            conversations.length === 0 ? (
              <EmptyState title="No conversations yet" />
            ) : (
              <DataTable
                caption="Recent conversations across all users"
                columns={[
                  { key: "last", label: "Last activity" },
                  { key: "user", label: "User" },
                  { key: "title", label: "Title" },
                  { key: "messages", label: "Messages", align: "right" },
                  { key: "tokens", label: "Tokens", align: "right" },
                  { key: "cost", label: "Cost", align: "right" },
                ]}
              >
                {conversations.map((row) => (
                  <tr key={row.id}>
                    <td className={`${td} whitespace-nowrap text-[var(--color-fg-muted)]`}>
                      {formatRelative(row.last_message_at ?? row.created_at)}
                    </td>
                    <td className={`${td} whitespace-nowrap`}>{row.user_email}</td>
                    <td className={`${td} max-w-[28rem]`}>{row.title}</td>
                    <td className={tdRight}>{formatNumber(row.message_count)}</td>
                    <td className={tdRight}>{formatNumber(row.total_tokens)}</td>
                    <td className={tdRight}>{formatCost(row.total_est_cost_usd)}</td>
                  </tr>
                ))}
              </DataTable>
            )
          ) : events.length === 0 ? (
            <EmptyState title="No events logged yet" />
          ) : (
            <DataTable
              caption="Telemetry event log"
              columns={[
                { key: "when", label: "When" },
                { key: "type", label: "Event" },
                { key: "sev", label: "Severity" },
                { key: "user", label: "User" },
                { key: "payload", label: "Payload" },
              ]}
            >
              {events.map((row) => (
                <tr key={row.id}>
                  <td className={`${td} whitespace-nowrap text-[var(--color-fg-muted)]`}>
                    {formatTimestamp(row.created_at)}
                  </td>
                  <td className={`${td} whitespace-nowrap font-mono text-[11.5px]`}>
                    {row.event_type}
                  </td>
                  <td className={td}>
                    <Badge
                      tone={
                        row.severity === "error"
                          ? "danger"
                          : row.severity === "warn"
                            ? "warn"
                            : "neutral"
                      }
                    >
                      {row.severity}
                    </Badge>
                  </td>
                  <td className={`${td} whitespace-nowrap`}>{row.user_email ?? "—"}</td>
                  <td className={`${td} font-mono text-[11.5px] text-[var(--color-fg-muted)] max-w-[40rem] break-words`}>
                    {JSON.stringify(row.payload)}
                  </td>
                </tr>
              ))}
            </DataTable>
          )}
        </Panel>
      </main>
    </div>
  );
}
