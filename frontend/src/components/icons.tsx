/**
 * Inline 16px monochrome SVGs (Lucide geometry). No icon font, no emoji.
 * Every icon is decorative here — labels always accompany them — so they are
 * marked aria-hidden and never carry meaning on their own.
 */

type Props = { className?: string };

const base = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
  focusable: false as const,
};

export const PlusIcon = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M12 5v14M5 12h14" />
  </svg>
);

export const SendIcon = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="m22 2-7 20-4-9-9-4Z" />
    <path d="M22 2 11 13" />
  </svg>
);

export const TrashIcon = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" />
  </svg>
);

export const GaugeIcon = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M12 14 15.5 9" />
    <path d="M3.3 17a9 9 0 1 1 17.4 0" />
  </svg>
);

export const ShieldIcon = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
  </svg>
);

export const RefreshIcon = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
    <path d="M21 3v5h-5" />
    <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
    <path d="M3 21v-5h5" />
  </svg>
);

export const LogOutIcon = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
    <path d="m16 17 5-5-5-5M21 12H9" />
  </svg>
);

export const ArrowLeftIcon = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M19 12H5M12 19l-7-7 7-7" />
  </svg>
);

export const AlertIcon = ({ className }: Props) => (
  <svg {...base} className={className}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 8v4M12 16h.01" />
  </svg>
);

export const MenuIcon = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M4 7h16M4 12h16M4 17h16" />
  </svg>
);

export const CloseIcon = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
);

export const SunIcon = ({ className }: Props) => (
  <svg {...base} className={className}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 3v1.5M12 19.5V21M4.2 4.2l1.1 1.1M18.7 18.7l1.1 1.1M3 12h1.5M19.5 12H21M4.2 19.8l1.1-1.1M18.7 5.3l1.1-1.1" />
  </svg>
);

export const MoonIcon = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M20 14.5A8.5 8.5 0 1 1 9.5 4 7 7 0 0 0 20 14.5Z" />
  </svg>
);

export const StopIcon = ({ className }: Props) => (
  <svg {...base} className={className}>
    <rect x="7" y="7" width="10" height="10" rx="1" />
  </svg>
);

export const CopyIcon = ({ className }: Props) => (
  <svg {...base} className={className}>
    <rect x="9" y="9" width="11" height="13" rx="1.5" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </svg>
);

export const MessageIcon = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z" />
  </svg>
);
