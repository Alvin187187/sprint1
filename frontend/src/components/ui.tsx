import { forwardRef, useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { MoonIcon, SunIcon } from "./icons";
import { useTheme } from "../state/theme";

/**
 * Small set of primitives. Solid fills, 1px borders, 5–8px radii, colour-only
 * transitions. No gradients, no shadows beyond a hairline, no transforms.
 */

const cx = (...parts: Array<string | false | undefined>) => parts.filter(Boolean).join(" ");

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "default" | "ghost" | "danger";
  size?: "sm" | "md";
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "default", size = "md", className, children, ...rest },
  ref,
) {
  const variants: Record<string, string> = {
    primary:
      "bg-[var(--color-cta)] text-[var(--color-cta-fg)] border-[var(--color-cta)] hover:bg-[color-mix(in_srgb,var(--color-cta)_88%,black)]",
    default:
      "bg-[var(--color-surface-raised)] text-[var(--color-fg)] border-[var(--color-border-strong)] hover:bg-[var(--color-muted)]",
    ghost:
      "bg-transparent text-[var(--color-fg-muted)] border-transparent hover:bg-[var(--color-muted)] hover:text-[var(--color-fg)]",
    danger:
      "bg-transparent text-[var(--color-danger-fg)] border-[var(--color-border-strong)] hover:bg-[var(--color-danger-muted)]",
  };
  return (
    <button
      ref={ref}
      className={cx(
        "inline-flex items-center justify-center gap-2 border rounded-[var(--radius-sm)] font-medium",
        "transition-[background-color,color,border-color,opacity,transform] duration-150",
        "active:translate-y-px disabled:opacity-45 disabled:cursor-not-allowed disabled:active:translate-y-0",
        size === "md" ? "h-11 px-4 text-[15px]" : "h-9 px-3 text-[14px]",
        variants[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
});

export function Field({
  label,
  hint,
  error,
  htmlFor,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  htmlFor: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      {/* Label above the field, always visible — never a placeholder-only label. */}
      <label htmlFor={htmlFor} className="text-[14px] font-medium text-[var(--color-fg)]">
        {label}
      </label>
      {children}
      {hint && !error && <p className="text-[12.5px] text-[var(--color-fg-muted)]">{hint}</p>}
      {/* Error sits next to the field it belongs to, not in a summary at the top. */}
      {error && (
        <p id={`${htmlFor}-error`} className="text-[12.5px] text-[var(--color-danger-fg)]">
          {error}
        </p>
      )}
    </div>
  );
}

export const inputClass = cx(
  "w-full min-h-12 h-12 px-3 rounded-[var(--radius-sm)] bg-[var(--color-bg)]",
  "border border-[var(--color-border-strong)] text-[16px]",
  "transition-[border-color] duration-150 hover:border-[var(--color-fg-subtle)]",
  "disabled:opacity-50",
);

export function Panel({
  title,
  description,
  actions,
  children,
  className,
}: {
  title?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cx(
        "border border-[var(--color-border)] rounded-[var(--radius-md)] bg-[var(--color-surface)]",
        className,
      )}
    >
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 px-3.5 py-2.5 border-b border-[var(--color-border)]">
          <div className="min-w-0">
            {title && <h2 className="font-display text-[18px] leading-tight">{title}</h2>}
            {description && (
              <p className="mt-0.5 text-[14px] text-[var(--color-fg-muted)] text-pretty">
                {description}
              </p>
            )}
          </div>
          {actions && <div className="flex items-center gap-2 shrink-0 flex-wrap justify-end">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

type Tone = "neutral" | "ok" | "warn" | "danger" | "info";

export function Badge({
  tone = "neutral",
  children,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  const tones: Record<Tone, string> = {
    neutral: "text-[var(--color-fg-muted)] border-[var(--color-border-strong)]",
    ok: "text-[var(--color-ok-fg)] border-[var(--color-ok)] bg-[var(--color-ok-muted)]",
    warn: "text-[var(--color-warn-fg)] border-[var(--color-warn)] bg-[var(--color-warn-muted)]",
    danger: "text-[var(--color-danger-fg)] border-[var(--color-danger)] bg-[var(--color-danger-muted)]",
    info: "text-[var(--color-info-fg)] border-[var(--color-info-fg)]",
  };
  return (
    <span
      className={cx(
        "h-6 px-2 rounded-[var(--radius-xs)] border",
        "font-mono text-[12px] leading-none",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Status words carry a text label as well as colour — colour alone is never the signal. */
export function StatusBadge({ status }: { status: string }) {
  const tone: Tone = status === "ok"
    ? "ok"
    : status.startsWith("blocked")
      ? "warn"
      : status === "truncated"
        ? "info"
        : "danger";
  return <Badge tone={tone}>{status}</Badge>;
}

export function Notice({
  tone = "warn",
  title,
  children,
  actions,
}: {
  tone?: Tone;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  const tones: Record<Tone, string> = {
    neutral: "border-[var(--color-border-strong)] bg-[var(--color-surface-raised)]",
    ok: "border-[var(--color-ok)] bg-[var(--color-ok-muted)]",
    warn: "border-[var(--color-warn)] bg-[var(--color-warn-muted)]",
    danger: "border-[var(--color-danger)] bg-[var(--color-danger-muted)]",
    info: "border-[var(--color-info-fg)] bg-[var(--color-surface-raised)]",
  };
  return (
    <div
      role="status"
      className={cx("border rounded-[var(--radius-sm)] px-3.5 py-3 text-[15px]", tones[tone])}
    >
      <p className="font-medium">{title}</p>
      {children && <div className="mt-0.5 text-[var(--color-fg-muted)]">{children}</div>}
      {actions && <div className="mt-2 flex gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="px-4 py-8 text-center">
      <p className="text-[17px] font-semibold">{title}</p>
      {children && (
        <div className="mt-1 text-[15px] text-[var(--color-fg-muted)] max-w-lg mx-auto">
          {children}
        </div>
      )}
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-[15px] text-[var(--color-fg-muted)]">
      <span
        aria-hidden
        className="w-3 h-3 border rounded-full border-[var(--color-border-strong)] border-t-[var(--color-fg-muted)] animate-spin"
      />
      {label}
    </span>
  );
}

/** Dense scrollable table shell. */
export function DataTable({
  columns,
  children,
  caption,
}: {
  columns: Array<{ key: string; label: string; align?: "right" }>;
  children: ReactNode;
  caption: string;
}) {
  return (
    <div className="overflow-x-auto scroll-thin">
      <table className="w-full border-collapse text-[14px]">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 z-[1] bg-[var(--color-surface)]">
          <tr className="text-left text-[var(--color-fg-muted)]">
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={cx(
                  "font-medium px-3 h-9 border-b border-[var(--color-border)] whitespace-nowrap",
                  column.align === "right" && "text-right",
                )}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="[&_tr:hover]:bg-[var(--color-muted)]">{children}</tbody>
      </table>
    </div>
  );
}

export const td = "px-3 py-2 border-b border-[var(--color-border)] align-top";
export const tdRight = `${td} text-right tabular`;
export { cx };

export function SkipLink() {
  return (
    <a href="#main" className="skip-link">
      Skip to main content
    </a>
  );
}

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      className={cx(
        "inline-flex items-center justify-center w-11 h-11 rounded-[var(--radius-sm)]",
        "text-[var(--color-fg-muted)] hover:bg-[var(--color-muted)] hover:text-[var(--color-fg)]",
        "transition-[background-color,color,transform] duration-150 active:rotate-12",
      )}
    >
      {theme === "dark" ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  danger,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const titleId = useId();
  const descId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = originalOverflow;
      previous?.focus();
    };
  }, [open, onCancel]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Dismiss"
        className="scrim absolute inset-0 bg-[color-mix(in_srgb,var(--color-bg)_55%,black)]"
        onClick={onCancel}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
        className="dialog-panel relative w-full max-w-sm border border-[var(--color-border-strong)] rounded-[var(--radius-md)] bg-[var(--color-surface)] p-4 overscroll-contain"
      >
        <h2 id={titleId} className="font-display text-[22px] leading-tight">
          {title}
        </h2>
        <p id={descId} className="mt-2 text-[15px] text-[var(--color-fg-muted)] text-pretty">
          {description}
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button ref={cancelRef} type="button" size="sm" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="button" size="sm" variant={danger ? "danger" : "primary"} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

export function TypingDots({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-[15px] text-[var(--color-fg-muted)]">
      <span className="inline-flex items-end gap-1 h-3" aria-hidden>
        <span className="dot-pulse w-1.5 h-1.5 rounded-full bg-current" />
        <span className="dot-pulse w-1.5 h-1.5 rounded-full bg-current" />
        <span className="dot-pulse w-1.5 h-1.5 rounded-full bg-current" />
      </span>
      {label}
    </span>
  );
}

export function Toast({ message }: { message: string | null }) {
  if (!message) return null;
  return createPortal(
    <div
      role="status"
      className="toast fixed bottom-5 left-1/2 z-50 px-4 py-2.5 rounded-[var(--radius-sm)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] text-[15px] shadow-[0_8px_24px_rgba(0,0,0,0.28)]"
    >
      {message}
    </div>,
    document.body,
  );
}
