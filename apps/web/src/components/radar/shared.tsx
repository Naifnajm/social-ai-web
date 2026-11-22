"use client";
/**
 * Radar building blocks shared by the radar pages: the selected setup and period, data hooks, badges, the
 * mention card and the event card.
 *
 *   const { queryId, days } = useRadarScope();     // chosen in the radar layout (setup switcher, 7/30/90 days)
 *   const status = useRadarStatus();               // GET /listening/status
 *   <MentionCard mention={m} />  <EventCard event={e} />  <SentimentPill value="negative" />
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { type ReactNode, useState } from "react";
import { create } from "zustand";
import { Icon, PlatformBadge } from "@/components/icon";
import { PLATFORM_LABELS, onError, useFormat } from "@/components/planning/ui";
import { Badge, Button, Field, Input, Modal, Segmented, Select, cx, toast } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { SENTIMENT_COLOR } from "./charts";
import { MentionActions } from "./mention-actions";
import { type EventShort, INTENTS, type Intent, type ListeningQuery, type Mention, type RadarStatus, SENTIMENTS, type Sentiment, type Severity } from "./types";

// ------------------------------------------------------------------------------------------------ scope
type Scope = { queryId: number | null; days: number; setQuery: (id: number | null) => void; setDays: (days: number) => void };

export const useRadarScope = create<Scope>((set) => ({
  queryId: null,
  days: 30,
  setQuery: (queryId) => set({ queryId }),
  setDays: (days) => set({ days }),
}));

export const useRadarStatus = () =>
  useQuery({ queryKey: ["radar", "status"], queryFn: () => api.get<RadarStatus>("/listening/status"), staleTime: 60_000 });

/** The setup the radar pages show: the one picked in the switcher, else the first active one. */
export function useScope() {
  const { queryId, days } = useRadarScope();
  const { data } = useRadarStatus();
  const list = data?.queries ?? [];
  const query = list.find((q) => q.id === queryId) ?? list.find((q) => q.active) ?? list[0] ?? null;
  return { queryId: query?.id ?? null, query, days };
}

export const useRadarQueries = (enabled = true) =>
  useQuery({
    queryKey: ["radar", "queries"],
    queryFn: () => api.get<ListeningQuery[]>("/listening/queries"),
    enabled,
    // while a setup waits for its first collection, look again every 20 s
    refetchInterval: (q) => (q.state.data?.some((row) => row.active && !row.mentions) ? 20_000 : false),
  });

/** Ask the worker to collect a setup now. */
export function useCollectNow() {
  const t = useTranslations("radar");
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.post<{ queued?: boolean }>(`/listening/queries/${id}/collect`),
    onSuccess: () => {
      toast.success(t("collect.queued"));
      setTimeout(() => qc.invalidateQueries({ queryKey: ["radar"] }), 8000);
    },
    onError,
  });
}

// --------------------------------------------------------------------------------------------- badges
export function SourceBadge({ source, platform, size = 22 }: { source: string; platform?: string | null; size?: number }) {
  const net = platform && platform !== "news" && platform !== "owned" ? platform : source;
  const network = net === "youtube_comments" ? "youtube" : net;
  if (["facebook", "instagram", "x", "youtube", "google_business", "tiktok", "linkedin", "threads", "telegram"].includes(network)) {
    return <PlatformBadge platform={network} size={size} />;
  }
  return (
    <span className="inline-flex shrink-0 items-center justify-center rounded-[9px] bg-fill-2 text-text-2" style={{ width: size, height: size }}>
      <Icon name={SOURCE_ICONS[network] ?? "campaign"} size={Math.round(size * 0.6)} />
    </span>
  );
}

const SOURCE_ICONS: Record<string, string> = {
  news: "description", web: "search", reddit: "forum", app_store: "smartphone", google_play: "smartphone", snapchat: "block", owned: "campaign",
};

export function useSourceLabel() {
  const t = useTranslations("radar.sources");
  return (source: string) => (t.has(source) ? t(source) : PLATFORM_LABELS[source] ?? source);
}

export function SentimentPill({ value }: { value: Sentiment | null }) {
  const t = useTranslations("radar.sentiments");
  if (!value) return null;
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
      value === "positive" ? "bg-ok-bg text-ok" : value === "negative" ? "bg-bad-bg text-bad" : "bg-fill-2 text-text-2")}>
      <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: SENTIMENT_COLOR[value] }} />
      {t(value)}
    </span>
  );
}

const SEVERITY_TONE: Record<Severity, "bad" | "warn" | "ink" | "neutral"> = { urgent: "bad", high: "warn", normal: "ink", info: "neutral" };

export function SeverityBadge({ severity, kind }: { severity: Severity; kind?: string }) {
  const t = useTranslations("radar");
  return (
    <Badge tone={SEVERITY_TONE[severity] ?? "neutral"}>
      {kind && <Icon name={KIND_ICONS[kind] ?? "info"} size={12} />}
      {kind ? `${t(`kinds.${kind}`)} · ${t(`severities.${severity}`)}` : t(`severities.${severity}`)}
    </Badge>
  );
}

export const KIND_ICONS: Record<string, string> = {
  crisis: "warning", spike: "trending_up", opportunity: "shopping_cart", competitor: "flag", influencer: "verified", rising: "show_chart",
};

/** A labelled number with a change against the previous period. */
export function Kpi({ label, icon, value, change, unit = "%", goodWhenUp = true, hint }: {
  label: ReactNode; icon: string; value: ReactNode; change?: number | null; unit?: string; goodWhenUp?: boolean; hint?: ReactNode;
}) {
  const t = useTranslations("radar");
  return (
    <div className="glass rounded-[18px] p-4">
      <div className="flex items-center gap-1.5 text-xs text-muted"><Icon name={icon} size={15} /><span className="truncate">{label}</span></div>
      <div className="mt-1.5 text-2xl font-bold tracking-tight tabular-nums bidi">{value}</div>
      {change === null || change === undefined ? (
        <div className="mt-0.5 text-xs text-faint">{hint ?? t("noComparison")}</div>
      ) : (
        <div className={cx("mt-0.5 inline-flex items-center gap-0.5 text-xs font-semibold", change === 0 ? "text-muted" : (change > 0) === goodWhenUp ? "text-ok" : "text-bad")}>
          {change !== 0 && <Icon name={change > 0 ? "arrow_upward" : "arrow_downward"} size={12} />}
          <span className="bidi">{unit === "%" ? `${Math.abs(change)}%` : t("points", { n: Math.abs(change) })}</span>
          <span className="ms-1 font-normal text-muted">{t("vsPrevious")}</span>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------------------------ mention card
export function MentionCard({ mention, compact = false, onChanged }: { mention: Mention; compact?: boolean; onChanged?: () => void }) {
  const t = useTranslations("radar");
  const fmt = useFormat();
  const sourceLabel = useSourceLabel();
  const router = useRouter();
  const qc = useQueryClient();
  const canEdit = useSession((s) => s.can("editor"));
  const [correcting, setCorrecting] = useState(false);
  const done = () => { qc.invalidateQueries({ queryKey: ["radar", "mentions"] }); onChanged?.(); };
  const patch = useMutation({
    mutationFn: (body: Partial<Pick<Mention, "status" | "sentiment" | "intent" | "topic">>) => api.patch<Mention>(`/listening/mentions/${mention.id}`, body),
    onSuccess: (_row, body) => {
      done();
      toast.success(body.status === "muted" ? t("mention.muted") : body.status === "spam" ? t("mention.spamSaved") : body.status ? t("mention.saved") : t("mention.corrected"));
    },
    onError,
  });
  const inbox = useMutation({
    mutationFn: () => api.post<{ url: string }>(`/listening/mentions/${mention.id}/inbox`),
    onSuccess: (r) => { done(); router.push(r.url); },
    onError,
  });
  const author = mention.author_name || mention.author_handle || t("mention.unknownAuthor");
  return (
    <article className={cx("flex gap-3", compact ? "py-3" : "py-4", (mention.status === "muted" || mention.status === "spam") && "opacity-60")}>
      <SourceBadge source={mention.source} platform={mention.platform} size={compact ? 26 : 32} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[13px]">
          <span className="bidi font-semibold">{author}</span>
          {mention.author_handle && mention.author_name && <span className="text-muted" dir="ltr">@{mention.author_handle.replace(/^@/, "")}</span>}
          {mention.author_followers > 0 && (
            <span className={cx("text-xs", mention.author_followers >= 10_000 ? "font-semibold text-text-2" : "text-muted")}>
              {t("mention.followers", { n: fmt.compact(mention.author_followers) })}
            </span>
          )}
          <span className="text-xs text-faint">· {sourceLabel(mention.source === "owned" ? mention.platform : mention.source)} · {fmt.dateTime(mention.published_at)}</span>
        </div>
        <p className={cx("bidi mt-1 whitespace-pre-wrap text-sm leading-relaxed", compact && "line-clamp-3")}>{mention.text}</p>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {mention.brand && <Badge tone="ink"><Icon name="flag" size={11} /><span className="bidi">{mention.brand}</span></Badge>}
          <SentimentPill value={mention.sentiment} />
          {mention.intent && mention.intent !== "other" && <Badge>{t(`intents.${mention.intent}`)}</Badge>}
          {mention.topic && <Badge><Icon name="tag" size={11} /><span className="bidi">{mention.topic}</span></Badge>}
          {mention.corrected && <span className="text-[11px] text-faint">{t("mention.correctedByTeam")}</span>}
          {mention.status === "reviewed" && <Badge tone="ok"><Icon name="check" size={11} />{t("mention.reviewed")}</Badge>}
          {mention.status === "converted" && <Badge tone="ok"><Icon name="inbox" size={11} />{t("mention.inInbox")}</Badge>}
          {mention.status === "spam" && <Badge tone="warn"><Icon name="block" size={11} />{t(`mention.spam.${mention.spam_reason ?? "other"}`)}</Badge>}
          {mention.in_report && <Badge tone="ink"><Icon name="description" size={11} />{t("mention.inReport")}</Badge>}
          {mention.also_on.length > 0 && <span className="text-[11px] text-faint">{t("mention.alsoOn", { sources: mention.also_on.map((s) => sourceLabel(s)).join("، ") })}</span>}
          {(mention.reach != null || mention.reach_estimated != null || mention.engagement > 0) && (
            <span className="ms-auto flex items-center gap-2.5 text-xs text-muted">
              {mention.reach != null && mention.reach > 0 && <span className="flex items-center gap-1" title={t("mention.reach")}><Icon name="visibility" size={12} />{fmt.compact(mention.reach)}</span>}
              {mention.reach == null && mention.reach_estimated != null && (
                <span className="flex items-center gap-1" title={t("mention.reachEstimatedHint")}><Icon name="visibility" size={12} />{t("mention.reachEstimated", { n: fmt.compact(mention.reach_estimated) })}</span>
              )}
              {mention.engagement > 0 && <span className="flex items-center gap-1" title={t("mention.engagement")}><Icon name="favorite" size={12} />{fmt.compact(mention.engagement)}</span>}
            </span>
          )}
        </div>
        {!compact && (
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            {mention.conversation_id ? (
              <Link href={`/inbox/${mention.conversation_id}`}><Button size="sm" icon="inbox">{t("mention.openInbox")}</Button></Link>
            ) : canEdit && mention.can_inbox && (
              <Button size="sm" icon="reply" loading={inbox.isPending} onClick={() => inbox.mutate()}>{t("mention.answerInInbox")}</Button>
            )}
            {mention.url && (
              <a href={mention.url} target="_blank" rel="noopener noreferrer"><Button size="sm" variant="ghost" icon="open_in_new">{t("mention.openOriginal")}</Button></a>
            )}
            {canEdit && <MentionActions mention={mention} onChanged={done} />}
            {canEdit && (
              <>
                {mention.status === "new" && <Button size="sm" variant="ghost" icon="check" onClick={() => patch.mutate({ status: "reviewed" })}>{t("mention.markReviewed")}</Button>}
                {mention.status === "spam"
                  ? <Button size="sm" variant="ghost" icon="undo" onClick={() => patch.mutate({ status: "new" })}>{t("mention.notSpam")}</Button>
                  : mention.status === "muted"
                    ? <Button size="sm" variant="ghost" icon="visibility" onClick={() => patch.mutate({ status: "new" })}>{t("mention.unmute")}</Button>
                    : mention.status !== "converted" && (
                      <>
                        <Button size="sm" variant="ghost" icon="visibility_off" onClick={() => patch.mutate({ status: "muted" })}>{t("mention.mute")}</Button>
                        <Button size="sm" variant="ghost" icon="block" onClick={() => patch.mutate({ status: "spam" })}>{t("mention.markSpam")}</Button>
                      </>
                    )}
                <Button size="sm" variant="ghost" icon="edit_square" onClick={() => setCorrecting(true)}>{t("mention.correct")}</Button>
              </>
            )}
          </div>
        )}
      </div>
      {correcting && (
        <CorrectDialog mention={mention} saving={patch.isPending} onClose={() => setCorrecting(false)}
          onSave={(body) => patch.mutate(body, { onSuccess: () => setCorrecting(false) })} />
      )}
    </article>
  );
}

function CorrectDialog({ mention, saving, onClose, onSave }: {
  mention: Mention; saving: boolean; onClose: () => void;
  onSave: (body: { sentiment: Sentiment; intent: Intent; topic?: string }) => void;
}) {
  const t = useTranslations("radar");
  const [sentiment, setSentiment] = useState<Sentiment>(mention.sentiment ?? "neutral");
  const [intent, setIntent] = useState<Intent>(mention.intent ?? "other");
  const [topic, setTopic] = useState(mention.topic ?? "");
  return (
    <Modal open onClose={onClose} title={t("correct.title")}
      footer={<>
        <Button variant="ghost" onClick={onClose}>{t("cancel")}</Button>
        <Button variant="primary" icon="check" loading={saving} onClick={() => onSave({ sentiment, intent, ...(topic.trim() ? { topic: topic.trim() } : {}) })}>{t("correct.save")}</Button>
      </>}>
      <p className="bidi mb-4 line-clamp-4 rounded-2xl bg-fill p-3 text-sm leading-relaxed">{mention.text}</p>
      <div className="flex flex-col gap-4">
        <Field label={t("correct.sentiment")}>
          <Segmented value={sentiment} onChange={setSentiment} options={SENTIMENTS.map((s) => ({ value: s, label: t(`sentiments.${s}`) }))} />
        </Field>
        <Field label={t("correct.intent")}>
          <Select value={intent} onChange={(e) => setIntent(e.target.value as Intent)}>
            {INTENTS.map((i) => <option key={i} value={i}>{t(`intents.${i}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("correct.topic")} hint={t("correct.topicHint")}>
          <Input value={topic} maxLength={60} onChange={(e) => setTopic(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}

// -------------------------------------------------------------------------------------------- event card
export function EventCard({ event }: { event: EventShort }) {
  const t = useTranslations("radar");
  const fmt = useFormat();
  const urgent = event.severity === "urgent";
  return (
    <Link href={`/radar/events/${event.id}`} className="block">
      <div className={cx("h-full rounded-[18px] p-4 transition hover:-translate-y-0.5",
        urgent ? "bg-ink text-white shadow-[0_14px_30px_-16px_rgba(0,0,0,.7)]" : "glass hover:shadow-[var(--shadow-lift)]")}>
        <div className="flex items-center gap-2">
          <span className={cx("flex h-8 w-8 shrink-0 items-center justify-center rounded-xl",
            urgent ? "bg-[var(--bad-solid)] text-white" : event.severity === "high" ? "bg-warn-bg text-warn" : "bg-fill-2 text-text-2")}>
            <Icon name={KIND_ICONS[event.kind] ?? "info"} size={16} />
          </span>
          <span className={cx("text-xs font-semibold", urgent ? "text-white/80" : "text-text-2")}>
            {t(`kinds.${event.kind}`)} · {t(`severities.${event.severity}`)}
          </span>
          <span className={cx("ms-auto text-[11px]", urgent ? "text-white/50" : "text-faint")}>{fmt.dateTime(event.started_at)}</span>
        </div>
        <div className="bidi mt-2.5 text-[15px] font-semibold leading-snug">{event.title}</div>
        {event.what && <p className={cx("bidi mt-1 line-clamp-2 text-[13px] leading-relaxed", urgent ? "text-white/70" : "text-muted")}>{event.what}</p>}
        {event.state === "open" && (
          <span className={cx("mt-3 inline-flex items-center gap-1 text-xs font-semibold", urgent ? "text-white" : "text-text")}>
            {t("events.open")}<Icon name="east" size={13} className="rtl:-scale-x-100" />
          </span>
        )}
      </div>
    </Link>
  );
}
