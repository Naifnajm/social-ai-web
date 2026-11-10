"use client";
/** Small building blocks shared by the planning pages (planner, campaigns, library, links, reports). */
import { useLocale, useTranslations } from "next-intl";
import { type ReactNode, useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import { Badge, cx, toast } from "@/components/ui";
import { ApiError } from "@/lib/api";

export const PLATFORM_LABELS: Record<string, string> = {
  facebook: "Facebook", instagram: "Instagram", linkedin: "LinkedIn", x: "X", tiktok: "TikTok", threads: "Threads",
  telegram: "Telegram", whatsapp: "WhatsApp",
};

export const SWATCHES = ["#0a0a0a", "#52525b", "#2563eb", "#0891b2", "#059669", "#65a30d", "#ca8a04", "#ea580c", "#dc2626", "#db2777", "#7c3aed", "#4f46e5"];

/** A number with "%" kept together and left-to-right inside Arabic text. */
export const pct = (value: number | string) => `\u2066${value}%\u2069`;

export function errorText(err: unknown) {
  return err instanceof ApiError ? err.message : String(err);
}

export const onError = (err: unknown) => toast.error(errorText(err));

export function useFormat() {
  const locale = useLocale();
  const tag = locale === "ar" ? "ar-SA-u-nu-latn" : "en-GB";
  const number = (value: number | null | undefined, digits = 0) =>
    new Intl.NumberFormat(tag, { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(value || 0);
  const compact = (value: number | null | undefined) =>
    new Intl.NumberFormat(tag, { notation: "compact", maximumFractionDigits: 1 }).format(value || 0);
  const money = (value: number | null | undefined, currency: string) => `${number(value, value && value < 100 ? 2 : 0)} ${currency}`;
  const date = (value: string | Date | null | undefined, opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", year: "numeric" }) => {
    if (!value) return "";
    const d = typeof value === "string" ? new Date(value.length === 10 ? `${value}T12:00:00` : value) : value;
    return new Intl.DateTimeFormat(tag, opts).format(d);
  };
  const dateTime = (value: string | null | undefined) =>
    value ? new Intl.DateTimeFormat(tag, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(value)) : "";
  const size = (bytes: number) =>
    bytes > 1024 * 1024 ? `${number(bytes / 1024 / 1024, 1)} MB` : `${number(Math.max(1, bytes / 1024), 0)} KB`;
  return { locale, number, compact, money, date, dateTime, size };
}

export function StatTile({ label, value, icon, delta, hint, dark = false }: {
  label: ReactNode; value: ReactNode; icon?: string; delta?: number | null; hint?: ReactNode; dark?: boolean;
}) {
  return (
    <div className={cx("rounded-[18px] p-4", dark ? "bg-ink text-white shadow-[0_14px_30px_-16px_rgba(0,0,0,.7)]" : "glass")}>
      <div className={cx("flex items-center gap-1.5 text-[12px] font-medium", dark ? "text-white/60" : "text-muted")}>
        {icon && <Icon name={icon} size={15} />} <span className="truncate">{label}</span>
      </div>
      <div className="mt-1.5 text-[22px] font-bold tracking-tight bidi">{value}</div>
      <div className="mt-1 flex min-h-[18px] items-center gap-1.5 text-[11px]">
        {delta !== undefined && delta !== null && (
          <span className={cx("rounded-full px-1.5 py-0.5 font-semibold bidi", delta >= 0 ? (dark ? "bg-white/15" : "bg-ink text-white") : dark ? "bg-white/10 text-white/70" : "bg-fill-2 text-text-2")}>
            {delta >= 0 ? "▲" : "▼"} {Math.abs(delta)}%
          </span>
        )}
        {hint && <span className={dark ? "text-white/50" : "text-faint"}>{hint}</span>}
      </div>
    </div>
  );
}

export function PlatformStack({ platforms, size = 18 }: { platforms: string[]; size?: number }) {
  if (!platforms.length) return null;
  return (
    <span className="inline-flex items-center -space-x-1 rtl:space-x-reverse">
      {platforms.slice(0, 4).map((p) => (
        <span key={p} className="rounded-[7px] ring-2 ring-white"><PlatformBadge platform={p} size={size} /></span>
      ))}
      {platforms.length > 4 && <span className="ms-1.5 text-[10px] text-muted">+{platforms.length - 4}</span>}
    </span>
  );
}

const STATE_TONE: Record<string, "neutral" | "ok" | "warn" | "bad" | "ink"> = {
  draft: "neutral", to_approve: "warn", scheduled: "ink", publishing: "ink", posted: "ok", partial: "warn", failed: "bad",
  planned: "neutral", running: "ok", finished: "neutral",
};

export function StateBadge({ state }: { state: string }) {
  const t = useTranslations("planning.states");
  return <Badge tone={STATE_TONE[state] ?? "neutral"}>{t.has(state) ? t(state) : state}</Badge>;
}

export function ColorDot({ color, size = 10 }: { color: string; size?: number }) {
  return <span className="inline-block shrink-0 rounded-full" style={{ width: size, height: size, background: color }} />;
}

export function ColorPicker({ value, onChange }: { value: string; onChange: (c: string) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {SWATCHES.map((c) => (
        <button key={c} type="button" onClick={() => onChange(c)} aria-label={c}
          className={cx("h-7 w-7 rounded-full transition", value === c ? "ring-2 ring-ink ring-offset-2" : "hover:scale-110")}
          style={{ background: c }} />
      ))}
    </div>
  );
}

/** Minimal vertical bar chart (SVG) — values per day. */
export function MiniBars({ values, labels, height = 96 }: { values: number[]; labels?: string[]; height?: number }) {
  const max = Math.max(1, ...values);
  const w = 100 / Math.max(values.length, 1);
  return (
    <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="w-full rtl:-scale-x-100" style={{ height }} role="img">
      {values.map((v, i) => {
        const h = Math.max(v ? 3 : 1, (v / max) * (height - 6));
        return (
          <rect key={i} x={i * w + w * 0.18} width={w * 0.64} y={height - h} height={h} rx={Math.min(1.2, w * 0.3)}
            className={v ? "fill-ink" : "fill-black/10"}>
            {labels && <title>{`${labels[i]}: ${v}`}</title>}
          </rect>
        );
      })}
    </svg>
  );
}

/** Horizontal share bar with an optional target marker. */
export function ShareBar({ value, target, color }: { value: number; target?: number; color: string }) {
  return (
    <div className="relative h-2 w-full rounded-full bg-track">
      <div className="absolute inset-y-0 start-0 rounded-full transition-all" style={{ width: `${Math.min(100, value)}%`, background: color }} />
      {target !== undefined && <div className="absolute -top-1 h-4 w-0.5 rounded bg-ink/70" style={{ insetInlineStart: `calc(${Math.min(100, target)}% - 1px)` }} />}
    </div>
  );
}

export function CopyField({ value, label, multiline = false }: { value: string; label?: string; multiline?: boolean }) {
  const t = useTranslations("planning");
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    } catch {
      toast.error(t("copyFailed"));
    }
  };
  return (
    <div className="flex items-start gap-2 rounded-xl border border-line bg-white/70 p-2 ps-3">
      {multiline ? (
        <pre dir="ltr" className="min-w-0 flex-1 overflow-x-auto whitespace-pre text-[12px] leading-relaxed text-text-2">{value}</pre>
      ) : (
        <span dir="ltr" className="min-w-0 flex-1 truncate py-1 font-mono text-[12.5px] text-text-2">{value}</span>
      )}
      <button type="button" onClick={copy} className="inline-flex h-8 shrink-0 items-center gap-1 rounded-full bg-ink px-3 text-[12px] font-medium text-white">
        <Icon name={done ? "check" : "content_copy"} size={14} /> {done ? t("copied") : label || t("copy")}
      </button>
    </div>
  );
}

export function Chip({ active, onClick, children, className }: { active?: boolean; onClick?: () => void; children: ReactNode; className?: string }) {
  return (
    <button type="button" onClick={onClick}
      className={cx("inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3 text-[13px] font-medium transition",
        active ? "bg-ink text-white" : "glass text-text-2 hover:text-text", className)}>
      {children}
    </button>
  );
}

/** Weekday names, 0 = Monday (API convention). */
export function useWeekdays(style: "long" | "short" | "narrow" = "short") {
  const locale = useLocale();
  const fmt = new Intl.DateTimeFormat(locale === "ar" ? "ar" : "en-GB", { weekday: style });
  // 2024-01-01 was a Monday
  return Array.from({ length: 7 }, (_, i) => fmt.format(new Date(2024, 0, 1 + i)));
}
