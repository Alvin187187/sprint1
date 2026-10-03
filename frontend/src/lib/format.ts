const numberFormat = new Intl.NumberFormat("en-US");

export const formatNumber = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : numberFormat.format(value);

export const formatCost = (usd: number | null | undefined) => {
  if (usd === null || usd === undefined) return "—";
  if (usd === 0) return "$0.00";
  // Sub-cent figures are the norm on a mini model; rounding to 2dp would show
  // every turn as $0.00 and make the cost column useless.
  return usd < 0.01 ? `$${usd.toFixed(5)}` : `$${usd.toFixed(4)}`;
};

export const formatLatency = (ms: number | null | undefined) =>
  ms === null || ms === undefined ? "—" : ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;

export function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h ago`;
  if (seconds < 604_800) return `${Math.round(seconds / 86_400)}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export const formatTimestamp = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

export const formatTime = (iso: string) =>
  new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
