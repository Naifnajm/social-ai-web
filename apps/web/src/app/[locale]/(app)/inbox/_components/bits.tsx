"use client";
import { useFormatter, useNow } from "next-intl";
import { PlatformBadge } from "@/components/icon";
import { Avatar, cx, toast } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { TAG_COLORS, type Tag } from "../_lib/types";

/** Customer avatar with the network badge in the corner. */
export function ConvAvatar({ name, src, platform, size = 44 }: { name: string; src?: string | null; platform: string; size?: number }) {
  return (
    <span className="relative inline-flex shrink-0" style={{ width: size, height: size }}>
      <Avatar name={name} src={src} size={size} />
      <span className="absolute -bottom-0.5 -end-0.5 rounded-[8px] ring-2 ring-white">
        <PlatformBadge platform={platform} size={Math.max(16, Math.round(size * 0.42))} />
      </span>
    </span>
  );
}

export function TagChip({ tag, onRemove, removeLabel }: { tag: Tag; onRemove?: () => void; removeLabel?: string }) {
  const color = TAG_COLORS[tag.color % TAG_COLORS.length];
  return (
    <span className="inline-flex h-6 items-center gap-1 rounded-full ps-2 pe-1.5 text-[11px] font-semibold" style={{ background: `${color}1f`, color }}>
      <span className="bidi">{tag.name}</span>
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label={removeLabel} className="rounded-full px-0.5 opacity-70 hover:opacity-100">
          ×
        </button>
      )}
    </span>
  );
}

/** "3 min" / "Yesterday" style time for lists, refreshed every minute. */
export function useWhen() {
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });
  return (value?: string | null, short = true) => {
    if (!value) return "";
    const date = new Date(value);
    const diff = now.getTime() - date.getTime();
    if (diff < 60_000) return format.relativeTime(date, now);
    if (diff < 24 * 3600_000 && date.getDate() === now.getDate()) {
      return short ? format.dateTime(date, { hour: "2-digit", minute: "2-digit" }) : format.relativeTime(date, now);
    }
    if (diff < 6 * 24 * 3600_000) return format.dateTime(date, { weekday: "short" });
    return format.dateTime(date, { day: "numeric", month: "short" });
  };
}

export const showError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : String(err));

export function Dot({ className }: { className?: string }) {
  return <span className={cx("inline-block h-2 w-2 shrink-0 rounded-full bg-ink", className)} />;
}

export async function copyText(text: string, done: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(done);
  } catch {
    toast.error(text);
  }
}
