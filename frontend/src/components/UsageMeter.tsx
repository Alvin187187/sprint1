import { formatNumber } from "../lib/format";
import type { Usage } from "../lib/types";
import { cx } from "./ui";

export function UsageMeter({ usage }: { usage: Usage | null }) {
  if (!usage) return null;

  const rows = [
    { label: "Messages", used: usage.messages_used, cap: usage.message_cap },
    { label: "Tokens", used: usage.tokens_used, cap: usage.token_cap },
  ].filter((row) => row.cap && row.cap > 0);

  if (rows.length === 0) return null;

  return (
    <div className="px-3 py-3 border-t border-[var(--color-border)]">
      <div className="flex items-baseline justify-between mb-2 gap-2">
        <h2 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--color-fg-subtle)]">
          Today
        </h2>
        <span className="text-[12px] text-[var(--color-fg-subtle)] tabular">
          resets {usage.timezone.split("/")[1]?.replace("_", " ") ?? usage.timezone}
        </span>
      </div>

      <div className="flex flex-col gap-2.5">
        {rows.map((row) => {
          const cap = row.cap as number;
          const ratio = Math.min(1, row.used / cap);
          const low = ratio >= 0.85;
          const mid = ratio >= 0.6 && !low;
          return (
            <div key={row.label}>
              <div className="flex items-center justify-between text-[14px] mb-1">
                <span className="text-[var(--color-fg-muted)]">{row.label}</span>
                <span
                  className={cx(
                    "tabular font-medium",
                    low ? "text-[var(--color-warn-fg)]" : "text-[var(--color-fg)]",
                  )}
                >
                  {formatNumber(Math.max(0, cap - row.used))} left
                </span>
              </div>
              <div
                role="progressbar"
                aria-label={`${row.label} used`}
                aria-valuemin={0}
                aria-valuemax={cap}
                aria-valuenow={row.used}
                aria-valuetext={`${formatNumber(row.used)} of ${formatNumber(cap)} ${row.label.toLowerCase()} used`}
                className="h-1.5 w-full bg-[var(--color-bg)] rounded-[var(--radius-xs)] overflow-hidden"
              >
                <div
                  className={cx(
                    "h-full transition-[width] duration-200",
                    low
                      ? "bg-[var(--color-warn)]"
                      : mid
                        ? "bg-[var(--color-accent)]"
                        : "bg-[var(--color-ok)]",
                  )}
                  style={{ width: `${ratio * 100}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
