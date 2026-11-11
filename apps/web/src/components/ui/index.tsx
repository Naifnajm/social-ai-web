"use client";
/**
 * UI kit — glass black design. Use these everywhere so screens look like one product.
 *
 *   <PageHeader icon="inbox" title={t("title")} subtitle={...} actions={<Button>...</Button>} />
 *   <Card>…</Card>   <Button variant="primary|secondary|ghost|danger" icon="send" loading>…</Button>
 *   <Field label="Name"><Input value=… onChange=… /></Field>
 *   <Segmented value={v} onChange={setV} options={[{value:"a",label:"A"}]} />
 *   <Modal open title onClose footer>…</Modal>   toast.success("Saved")   <EmptyState icon title text action />
 */
import clsx from "clsx";
import { type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes,
  type TextareaHTMLAttributes, forwardRef, useEffect } from "react";
import { createPortal } from "react-dom";
import { create } from "zustand";
import { Icon } from "../icon";

export const cx = clsx;

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  icon?: string;
  loading?: boolean;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", icon, loading, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-full font-medium transition select-none",
        "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-black/10 disabled:opacity-50 disabled:pointer-events-none",
        size === "sm" && "h-8 px-3 text-[13px]",
        size === "md" && "h-10 px-4 text-sm",
        size === "lg" && "h-12 px-6 text-[15px]",
        variant === "primary" && "bg-ink text-white shadow-[0_6px_16px_-6px_rgba(0,0,0,.45)] hover:bg-ink-2",
        variant === "secondary" && "glass text-text hover:bg-white/80",
        variant === "ghost" && "text-text-2 hover:bg-fill-2",
        variant === "danger" && "bg-bad-bg text-bad hover:bg-red-500/15",
        className,
      )}
      {...rest}
    >
      {loading ? <Icon name="progress_activity" spin size={size === "sm" ? 14 : 16} /> : icon && <Icon name={icon} size={size === "sm" ? 14 : 16} />}
      {children}
    </button>
  );
});

export function IconButton({ icon, label, className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { icon: string; label: string }) {
  return (
    <button
      aria-label={label}
      title={label}
      className={cx("inline-flex h-9 w-9 items-center justify-center rounded-full text-text-2 transition hover:bg-fill-2 disabled:opacity-40", className)}
      {...rest}
    >
      <Icon name={icon} size={18} />
    </button>
  );
}

const fieldBase =
  "w-full rounded-xl border border-line bg-white/70 px-3 text-sm text-text placeholder:text-faint outline-none transition focus:border-black/30 focus:bg-white focus:ring-4 focus:ring-black/5";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cx(fieldBase, "h-10", className)} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cx(fieldBase, "bidi py-2.5 leading-relaxed", className)} {...rest} />;
});

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cx(fieldBase, "h-10 appearance-none pe-8", className)} {...rest}>
      {children}
    </select>
  );
}

export function Field({ label, hint, error, children, className }: { label?: ReactNode; hint?: ReactNode; error?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cx("flex flex-col gap-1.5", className)}>
      {label && <span className="text-[13px] font-medium text-text-2">{label}</span>}
      {children}
      {error ? <span className="text-xs text-bad">{error}</span> : hint && <span className="text-xs text-muted">{hint}</span>}
    </label>
  );
}

export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; disabled?: boolean }) {
  return (
    <label className={cx("inline-flex cursor-pointer items-center gap-2.5 text-sm", disabled && "opacity-50")}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cx("relative h-6 w-10 shrink-0 rounded-full transition", checked ? "bg-ink" : "bg-track")}
      >
        <span className={cx("absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all", checked ? "start-[18px]" : "start-0.5")} />
      </button>
      {label}
    </label>
  );
}

export function Card({ className, children, padded = true }: { className?: string; children: ReactNode; padded?: boolean }) {
  return <section className={cx("glass rounded-[20px]", padded && "p-5", className)}>{children}</section>;
}

export function SectionTitle({ icon, children, actions }: { icon?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center gap-2">
      {icon && <Icon name={icon} size={18} className="text-text-2" />}
      <h2 className="text-[15px] font-semibold tracking-tight">{children}</h2>
      {actions && <div className="ms-auto flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function PageHeader({ icon, title, subtitle, actions }: { icon?: string; title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-start gap-4">
      {icon && (
        <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[linear-gradient(135deg,#ff5c9d,#b3124f)] text-white shadow-[0_10px_24px_-10px_rgba(224,36,111,.75)]">
          <Icon name={icon} size={22} duo />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Segmented<T extends string | number>({ value, onChange, options, className, size = "md" }: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode; icon?: string }[];
  className?: string;
  size?: "sm" | "md";
}) {
  return (
    <div className={cx("inline-flex rounded-full bg-track p-0.5", className)} role="tablist">
      {options.map((o) => (
        <button
          key={String(o.value)}
          role="tab"
          aria-selected={o.value === value}
          onClick={() => onChange(o.value)}
          className={cx(
            "inline-flex items-center gap-1.5 rounded-full font-medium transition",
            size === "sm" ? "h-7 px-3 text-xs" : "h-8 px-3.5 text-[13px]",
            o.value === value ? "bg-white text-text shadow-[0_1px_3px_rgba(0,0,0,.12)]" : "text-text-2 hover:text-text",
          )}
        >
          {o.icon && <Icon name={o.icon} size={14} />}
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Badge({ tone = "neutral", children, className }: { tone?: "neutral" | "ok" | "warn" | "bad" | "ink"; children: ReactNode; className?: string }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
        tone === "neutral" && "bg-fill-2 text-text-2",
        tone === "ok" && "bg-ok-bg text-ok",
        tone === "warn" && "bg-warn-bg text-warn",
        tone === "bad" && "bg-bad-bg text-bad",
        tone === "ink" && "bg-ink text-white",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Spinner({ size = 20, className }: { size?: number; className?: string }) {
  return <Icon name="progress_activity" spin size={size} className={cx("text-muted", className)} />;
}

export function EmptyState({ icon = "inbox", title, text, action }: { icon?: string; title: ReactNode; text?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <span className="mb-2 flex h-14 w-14 items-center justify-center rounded-2xl bg-[linear-gradient(135deg,#ff5c9d,#b3124f)] text-white">
        <Icon name={icon} size={26} duo />
      </span>
      <div className="text-[15px] font-semibold">{title}</div>
      {text && <p className="max-w-md text-sm text-muted">{text}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export function Avatar({ name, src, size = 32 }: { name: string; src?: string | null; size?: number }) {
  const initials = (name || "?").trim().split(/\s+/).slice(0, 2).map((p) => p[0]).join("").toUpperCase();
  return src ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt="" width={size} height={size} className="shrink-0 rounded-full object-cover" style={{ width: size, height: size }} />
  ) : (
    <span className="inline-flex shrink-0 items-center justify-center rounded-full bg-fill-2 font-semibold text-text-2" style={{ width: size, height: size, fontSize: size * 0.38 }}>
      {initials}
    </span>
  );
}

export function Modal({ open, onClose, title, children, footer, size = "md" }: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open || typeof document === "undefined") return null;
  // portaled to <body>: a backdrop-filter ancestor (.glass) would otherwise trap the fixed overlay
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/30 p-0 backdrop-blur-sm sm:items-center sm:p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        role="dialog"
        aria-modal
        className={cx(
          "glass-strong pop-in flex max-h-[92vh] w-full flex-col rounded-t-[24px] sm:rounded-[24px]",
          size === "sm" && "sm:max-w-sm",
          size === "md" && "sm:max-w-lg",
          size === "lg" && "sm:max-w-3xl",
          size === "xl" && "sm:max-w-5xl",
        )}
      >
        {title && (
          <div className="flex items-center gap-2 px-5 pt-5">
            <h3 className="text-lg font-semibold tracking-tight">{title}</h3>
            <IconButton icon="close" label="Close" className="ms-auto" onClick={onClose} />
          </div>
        )}
        <div className="overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

// ---------------------------------------------------------------- toasts
type Toast = { id: number; tone: "ok" | "bad" | "info"; text: string };
const useToasts = create<{ items: Toast[]; push: (t: Omit<Toast, "id">) => void; drop: (id: number) => void }>((set) => ({
  items: [],
  push: (t) => {
    const id = Date.now() + Math.random();
    set((s) => ({ items: [...s.items, { ...t, id }] }));
    setTimeout(() => set((s) => ({ items: s.items.filter((i) => i.id !== id) })), 4200);
  },
  drop: (id) => set((s) => ({ items: s.items.filter((i) => i.id !== id) })),
}));

export const toast = {
  success: (text: string) => useToasts.getState().push({ tone: "ok", text }),
  error: (text: string) => useToasts.getState().push({ tone: "bad", text }),
  info: (text: string) => useToasts.getState().push({ tone: "info", text }),
};

export function Toaster() {
  const { items, drop } = useToasts();
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[60] flex flex-col items-center gap-2 px-4">
      {items.map((t) => (
        <button
          key={t.id}
          onClick={() => drop(t.id)}
          className="glass-strong pop-in pointer-events-auto flex max-w-md items-center gap-2 rounded-full px-4 py-2.5 text-sm"
        >
          <Icon name={t.tone === "ok" ? "check_circle" : t.tone === "bad" ? "error" : "info"} size={18}
            className={t.tone === "ok" ? "text-ok" : t.tone === "bad" ? "text-bad" : "text-text-2"} />
          <span className="bidi">{t.text}</span>
        </button>
      ))}
    </div>
  );
}
