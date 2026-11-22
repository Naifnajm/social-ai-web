"use client";
/**
 * Ideas of the day: data hooks, formatting in the workspace time zone and the small pieces every ideas screen uses.
 *
 *   const ideas = useIdeas("new");          const settings = useIdeaSettings();
 *   const fmt = useIdeaFormat();  fmt.slot(idea.suggested_at)   // "Thursday · 8:00 PM"
 *   const { approve, reject, save, renderSlides } = useIdeaActions();
 *   <FormatChip format="carousel" />  <ReasonPill reason={r} />  <AccountStack accounts={…} />
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useMemo } from "react";
import { create } from "zustand";
import { Icon, PlatformBadge } from "@/components/icon";
import { errorText } from "@/components/planning/ui";
import { useFormat as usePublishingFormat } from "@/components/publishing/util";
import { Avatar, cx, toast } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { ApproveMode, ApproveResult, Idea, IdeaAccount, IdeaFormat, IdeaPatch, IdeaSettings, RejectReason } from "./types";

// ----------------------------------------------------------------------------------------------- data
export const ideasKey = ["ideas", "list"] as const;

export const useIdeas = (state: "new" | "handled") =>
  useQuery({ queryKey: [...ideasKey, state], queryFn: () => api.get<Idea[]>("/ideas", { state, limit: state === "new" ? 30 : 60 }) });

export const useIdeaSettings = () =>
  useQuery({ queryKey: ["ideas", "settings"], queryFn: () => api.get<IdeaSettings>("/ideas/settings"), staleTime: 60_000 });

type BrandKit = { name: string; logo_url: string | null; color_primary: string; color_secondary: string; color_text: string; color_accent: string | null };
export type BrandLook = { background: string; text: string; accent: string; name: string; logo: string | null };

/** Colours of the default brand kit, the same way the API renders the real slides (black and white without a kit). */
export function useBrandLook(): BrandLook {
  const workspace = useSession((s) => s.workspace);
  const kit = useQuery({ queryKey: ["brand-kits", "default"], queryFn: () => api.get<BrandKit | null>("/brand-kits/default"), staleTime: 5 * 60_000 });
  const k = kit.data;
  return {
    background: k?.color_primary || "#111111",
    text: k?.color_text || "#ffffff",
    accent: k?.color_accent || k?.color_secondary || k?.color_text || "#ffffff",
    name: k?.name || workspace?.name || "",
    logo: k?.logo_url || null,
  };
}

/** Results of the approvals done on this page, so a card can show its "scheduled" state after it left the list. */
type Done = { results: Record<number, ApproveResult>; skipped: Record<number, boolean>; set: (id: number, r: ApproveResult) => void; skip: (id: number) => void };
export const useDone = create<Done>((set) => ({
  results: {},
  skipped: {},
  set: (id, r) => set((s) => ({ results: { ...s.results, [id]: r } })),
  skip: (id) => set((s) => ({ skipped: { ...s.skipped, [id]: true } })),
}));

export function useIdeaActions() {
  const qc = useQueryClient();
  const t = useTranslations("ideas");
  const put = (idea: Idea) => {
    qc.setQueriesData<Idea[]>({ queryKey: ideasKey }, (old) => old?.map((i) => (i.id === idea.id ? idea : i)));
    qc.setQueryData(["ideas", "one", idea.id], idea);
  };
  const fail = (err: unknown) => toast.error(errorText(err));
  const save = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: IdeaPatch }) => api.patch<Idea>(`/ideas/${id}`, patch),
    onSuccess: put,
    onError: fail,
  });
  const approve = useMutation({
    mutationFn: ({ id, mode, when, account_ids }: { id: number; mode: ApproveMode; when?: string | null; account_ids?: number[] }) =>
      api.post<ApproveResult>(`/ideas/${id}/approve`, { mode, when: when || undefined, account_ids }),
    onSuccess: (r) => {
      if (r.skipped_accounts?.length) toast.info(t("skippedAccounts", { names: r.skipped_accounts.join(", ") }));
      useDone.getState().set(r.idea.id, r);
      put(r.idea);
      qc.invalidateQueries({ queryKey: [...ideasKey, "handled"] });
    },
    onError: fail,
  });
  const reject = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: RejectReason }) => api.post<Idea>(`/ideas/${id}/reject`, { reason }),
    onSuccess: (idea) => {
      useDone.getState().skip(idea.id);
      toast.info(t("card.skipped"));
      // the card plays its leave animation first, then it goes away
      setTimeout(() => {
        qc.setQueryData<Idea[]>([...ideasKey, "new"], (old) => old?.filter((i) => i.id !== idea.id));
        qc.invalidateQueries({ queryKey: [...ideasKey, "handled"] });
      }, 240);
    },
    onError: fail,
  });
  const renderSlides = useMutation({
    mutationFn: (id: number) => api.post<Idea>(`/ideas/${id}/slides`),
    onSuccess: put,
    onError: fail,
  });
  return { save, approve, reject, renderSlides };
}

// ----------------------------------------------------------------------------------------- formatting
const TAGS: Record<string, string> = { ar: "ar-SA-u-nu-latn-ca-gregory", en: "en-US", nl: "nl-NL", de: "de-DE", fr: "fr-FR" };

/** Dates and times in the UI language and the workspace time zone. */
export function useIdeaFormat() {
  const locale = useLocale();
  const t = useTranslations("ideas.time");
  const base = usePublishingFormat();
  const timeZone = base.timeZone;
  return useMemo(() => {
    const tag = TAGS[locale] || locale;
    const dayKey = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" });
    const time = new Intl.DateTimeFormat(tag, { hour: "numeric", minute: "2-digit", timeZone });
    const weekday = new Intl.DateTimeFormat(tag, { weekday: "long", timeZone });
    const dayMonth = new Intl.DateTimeFormat(tag, { weekday: "short", day: "numeric", month: "short", timeZone });
    const longDate = new Intl.DateTimeFormat(tag, { weekday: "long", day: "numeric", month: "long", timeZone });
    const short = new Intl.DateTimeFormat(tag, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone });
    const hourOnly = (h: number) => new Intl.DateTimeFormat(tag, { hour: "numeric", minute: "2-digit", timeZone: "UTC" }).format(Date.UTC(2024, 0, 1, h));
    const list = new Intl.ListFormat(tag, { style: "long", type: "conjunction" });
    const daysBetween = (a: Date, b: Date) =>
      Math.round((Date.parse(dayKey.format(b)) - Date.parse(dayKey.format(a))) / 86_400_000);
    /** "Today · 8:00 PM", "Tomorrow · 8:00 PM", "Thursday · 8:00 PM" or "Thu 20 Nov · 8:00 PM". */
    const slot = (iso: string | null | undefined, now: number) => {
      if (!iso) return "";
      const d = new Date(iso);
      const diff = daysBetween(new Date(now), d);
      const at = time.format(d);
      if (diff === 0) return t("today", { time: at });
      if (diff === 1) return t("tomorrow", { time: at });
      return t("on", { day: diff > 1 && diff < 7 ? weekday.format(d) : dayMonth.format(d), time: at });
    };
    /** Hour of the day in the workspace time zone, for the greeting. */
    const hourNow = (now: number) => Number(new Intl.DateTimeFormat("en-GB", { hour: "2-digit", hourCycle: "h23", timeZone }).format(now));
    return {
      timeZone, tag, slot, hourNow, hourOnly,
      today: (now: number) => longDate.format(now),
      short: (iso: string | null | undefined) => (iso ? short.format(new Date(iso)) : ""),
      list: (items: string[]) => list.format(items),
      toLocalInput: base.toLocalInput,
      fromLocalInput: base.fromLocalInput,
    };
  }, [locale, timeZone, t, base]);
}

// ------------------------------------------------------------------------------------------- pieces
export const FORMAT_ICON: Record<IdeaFormat, string> = { post: "text_fields", carousel: "photo_library", video: "movie" };

export const REASON_ICON: Record<string, string> = {
  question: "forum", rising: "trending_up", event: "bolt", voice: "mode_comment", pillar: "flag", product: "storefront", format: "aspect_ratio",
  top_post: "trophy", best_time: "schedule", brief: "edit_square",
};

export function FormatChip({ format, className }: { format: IdeaFormat; className?: string }) {
  const t = useTranslations("ideas.formats");
  return (
    <span className={cx("inline-flex h-7 items-center gap-1.5 rounded-full bg-fill-2 px-2.5 text-[12px] font-semibold text-text-2", className)}>
      <Icon name={FORMAT_ICON[format] ?? "lightbulb"} size={14} />
      {t(format)}
    </span>
  );
}

export function ReasonPill({ reason }: { reason: { kind: string; label: string } }) {
  return (
    <span className="inline-flex max-w-full items-start gap-1.5 rounded-xl bg-accent-soft/60 px-2.5 py-1.5 text-[12px] leading-snug text-text-2">
      <Icon name={REASON_ICON[reason.kind] ?? "lightbulb"} size={14} className="mt-px text-accent-deep" />
      <span dir="auto" className="min-w-0">{reason.label}</span>
    </span>
  );
}

/** Avatars of the accounts an idea will be published on, each with its network in the corner. */
export function AccountStack({ accounts, size = 26, max = 5 }: { accounts: IdeaAccount[]; size?: number; max?: number }) {
  if (!accounts.length) return null;
  return (
    <span className="inline-flex items-center -space-x-1.5 rtl:space-x-reverse">
      {accounts.slice(0, max).map((a) => (
        <span key={a.id} title={a.name} className="relative inline-flex rounded-full bg-white ring-2 ring-white">
          <Avatar name={a.name} src={a.avatar_url} size={size} />
          <span className="absolute -bottom-0.5 -end-0.5 rounded-[6px] ring-[1.5px] ring-white">
            <PlatformBadge platform={a.platform} size={Math.max(12, Math.round(size * 0.48))} />
          </span>
        </span>
      ))}
      {accounts.length > max && <span className="ms-2.5 text-[11px] font-medium text-muted">+{accounts.length - max}</span>}
    </span>
  );
}

/** Where a handled idea lives now: the planner, the approvals list or the studio. */
export function postLink(idea: Idea): string | null {
  if (!idea.post) return null;
  if (idea.state === "draft" || idea.post.state === "draft") return `/studio?post=${idea.post.id}`;
  if (idea.post.state === "to_approve") return `/approvals?post=${idea.post.id}`;
  if (["posted", "partial", "failed"].includes(idea.post.state)) return `/posts?post=${idea.post.id}`;
  return `/planner?post=${idea.post.id}`;
}

/** The "why" of an idea: its reasons without the best time (the time chip says it), at most three. */
export function whyOf(idea: Idea) {
  const rest = idea.reasons.filter((r) => r.kind !== "best_time");
  return (rest.length ? rest : idea.reasons).slice(0, 3);
}

export const hasBestTime = (idea: Idea) => idea.reasons.some((r) => r.kind === "best_time");
