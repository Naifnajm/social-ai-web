"use client";
/** Small shared pieces of the publishing screens: account avatar, state badge, formatting helpers. */
import { useLocale, useTranslations } from "next-intl";
import { useMemo } from "react";
import { PlatformBadge } from "@/components/icon";
import { Avatar, Badge, cx } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { PostState } from "./types";

export const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

export function stateTone(state: string): "neutral" | "ok" | "warn" | "bad" | "ink" {
  if (state === "posted" || state === "connected") return "ok";
  if (state === "failed" || state === "expired" || state === "error") return "bad";
  if (state === "partial" || state === "to_approve" || state === "draft") return state === "draft" ? "neutral" : "warn";
  if (state === "scheduled" || state === "publishing") return "ink";
  return "neutral";
}

export function StateBadge({ state }: { state: PostState | string }) {
  const t = useTranslations("publishing.states");
  return <Badge tone={stateTone(state)}>{t.has(state) ? t(state) : state}</Badge>;
}

/** Avatar with the network logo in the corner. */
export function AccountAvatar({ name, src, platform, size = 36, dim = false }: { name: string; src?: string | null; platform: string; size?: number; dim?: boolean }) {
  return (
    <span className={cx("relative inline-flex shrink-0 rounded-full bg-white", dim && "opacity-45 grayscale")} style={{ width: size, height: size }}>
      <Avatar name={name} src={src} size={size} />
      <span className="absolute -bottom-1 -end-1 rounded-[8px] ring-2 ring-white">
        <PlatformBadge platform={platform} size={Math.max(14, Math.round(size * 0.46))} />
      </span>
    </span>
  );
}

/** Date/number formatting in the workspace time zone and the UI language. */
export function useFormat() {
  const locale = useLocale();
  const timeZone = useSession((s) => s.workspace?.timezone) || "UTC";
  return useMemo(() => {
    const tag = locale === "ar" ? "ar-SA-u-nu-latn-ca-gregory" : "en-GB";
    const dateTime = new Intl.DateTimeFormat(tag, { dateStyle: "medium", timeStyle: "short", timeZone });
    const date = new Intl.DateTimeFormat(tag, { day: "numeric", month: "short", timeZone });
    const compact = new Intl.NumberFormat(locale === "ar" ? "ar-u-nu-latn" : "en", { notation: "compact", maximumFractionDigits: 1 });
    const number = new Intl.NumberFormat(locale === "ar" ? "ar-u-nu-latn" : "en");
    return {
      timeZone,
      dateTime: (v?: string | null) => (v ? dateTime.format(new Date(v)) : ""),
      date: (v?: string | null) => (v ? date.format(new Date(v)) : ""),
      compact: (n: number) => compact.format(n || 0),
      number: (n: number) => number.format(n || 0),
      /** "YYYY-MM-DDTHH:mm" in the workspace zone, for <input type="datetime-local"> */
      toLocalInput: (v: Date) => {
        const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
          .formatToParts(v).map((p) => [p.type, p.value]));
        return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
      },
      /** inverse of toLocalInput: local wall time in the workspace zone → ISO UTC */
      fromLocalInput: (value: string) => {
        const guess = new Date(`${value}:00Z`);
        const asLocal = new Date(new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" })
          .format(guess).replace(", ", "T") + "Z");
        return new Date(guess.getTime() - (asLocal.getTime() - guess.getTime())).toISOString();
      },
    };
  }, [locale, timeZone]);
}

export const kindOf = (mimetype?: string) => (mimetype || "image/").split("/")[0];
