"use client";
/** One radar event: what happened, why it matters, what to do, the evidence, and the next step in one click
 *  (send for approval, open in the studio, add to the planner, answer in the inbox or dismiss). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon } from "@/components/icon";
import { Chip, onError, useFormat } from "@/components/planning/ui";
import { HourlyBars, Legend } from "@/components/radar/charts";
import { KIND_ICONS, MentionCard, SeverityBadge } from "@/components/radar/shared";
import type { ActAction, Feedback, RadarEvent } from "@/components/radar/types";
import { Badge, Button, Card, EmptyState, SectionTitle, Spinner, Textarea, cx, toast } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";

export default function RadarEventPage() {
  const params = useParams<{ id: string }>();
  const id = /^\d+$/.test(params.id ?? "") ? Number(params.id) : null;
  const t = useTranslations("radar");
  const event = useQuery({
    queryKey: ["radar", "event", id],
    queryFn: () => api.get<RadarEvent>(`/listening/events/${id}`),
    enabled: !!id,
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });
  if (!id || event.isError) {
    return (
      <Card>
        <EmptyState icon="search" title={t("event.notFound")} action={<Link href="/radar"><Button icon="arrow_back">{t("event.back")}</Button></Link>} />
      </Card>
    );
  }
  if (!event.data) return <div className="flex justify-center py-24"><Spinner size={28} /></div>;
  // keyed by id so the draft editor starts from this event's text
  return <EventView key={event.data.id} event={event.data} />;
}

function EventView({ event }: { event: RadarEvent }) {
  const t = useTranslations("radar");
  const fmt = useFormat();
  const router = useRouter();
  const qc = useQueryClient();
  const canEdit = useSession((s) => s.can("editor"));
  const [draft, setDraft] = useState(event.draft || event.suggestion || "");
  const update = (row: RadarEvent) => {
    qc.setQueryData(["radar", "event", event.id], (old: RadarEvent | undefined) => ({ ...old, ...row }));
    qc.invalidateQueries({ queryKey: ["radar", "events"] });
    qc.invalidateQueries({ queryKey: ["radar", "overview"] });
  };
  const act = useMutation({
    mutationFn: (action: ActAction) => api.post<{ url: string; event: RadarEvent }>(`/listening/events/${event.id}/act`,
      action === "dismiss" || action === "inbox" ? { action } : { action, text: draft.trim() || undefined }),
    onSuccess: (r, action) => {
      update(r.event);
      toast.success(t(`event.done.${action}`));
      router.push(r.url);
    },
    onError,
  });
  const feedback = useMutation({
    mutationFn: (value: Feedback) => api.post<RadarEvent>(`/listening/events/${event.id}/feedback`, { feedback: value }),
    onSuccess: (row) => { update(row); toast.success(t("event.thanks")); },
    onError,
  });

  const m = event.metrics;
  const hourly = Array.isArray(m.hourly) ? m.hourly : null;
  const usualPerHour = typeof m.usual === "number" ? m.usual / 6 : null; // "usual" is per 6 hours
  const now = new Date();
  const hourLabels = hourly?.map((_, i) => {
    const d = new Date(now.getTime() - (hourly.length - 1 - i) * 3600_000);
    return `${String(d.getHours()).padStart(2, "0")}:00`;
  }) ?? [];
  const evidence = event.evidence ?? [];
  const total = typeof m.count === "number" ? m.count : event.evidence_count;
  const canInbox = evidence.some((e) => e.can_inbox || e.conversation_id);
  const open = event.state === "open";
  const postRef = event.acted_ref?.startsWith("post:") ? event.acted_ref.slice(5) : null;
  const crisis = event.kind === "crisis";

  return (
    <div className="flex flex-col gap-5">
      <Link href="/radar" className="inline-flex w-max items-center gap-1 text-sm font-medium text-text-2 hover:text-text">
        <Icon name="arrow_back" size={16} className="rtl:-scale-x-100" />{t("event.back")}
      </Link>

      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={event.severity} kind={event.kind} />
          {event.brand && <Badge><Icon name="flag" size={11} /><span className="bidi">{event.brand}</span></Badge>}
          {event.ai_written && <Badge><Icon name="auto_awesome" size={11} />{t("event.aiWritten")}</Badge>}
          {event.state === "acted" && <Badge tone="ok"><Icon name="check" size={11} />{t("event.acted", { action: t(`event.actions.${event.acted_action ?? "studio"}`) })}</Badge>}
          {event.state === "dismissed" && <Badge>{t("events.states.dismissed")}</Badge>}
        </div>
        <h2 className="bidi mt-3 text-xl font-bold leading-snug tracking-tight">{event.title}</h2>
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[13px] text-muted">
          <span>{t("event.started", { date: fmt.dateTime(event.started_at) })}</span>
          {total > 0 && <span>· {t("event.mentionsCount", { n: fmt.number(total) })}</span>}
          {typeof m.reach === "number" && m.reach > 0 && <span>· {t("event.reach", { n: fmt.compact(m.reach) })}</span>}
          {event.topic && <span className="bidi">· {event.topic}</span>}
        </div>
        {postRef && (
          <Link href={`/studio?post=${postRef}`} className="mt-3 inline-flex items-center gap-1 text-sm font-medium underline underline-offset-2">
            {t("event.openPost")}<Icon name="open_in_new" size={12} />
          </Link>
        )}
        {(event.links?.inbox || event.links?.ideas) && (
          <div className="mt-3 flex flex-wrap gap-3 text-sm">
            {event.links.inbox && <Link href={event.links.inbox} className="inline-flex items-center gap-1 font-medium underline underline-offset-2"><Icon name="inbox" size={13} />{t("event.goInbox")}</Link>}
            {event.links.ideas && <Link href={event.links.ideas} className="inline-flex items-center gap-1 font-medium underline underline-offset-2"><Icon name="lightbulb" size={13} />{t("event.goIdeas")}</Link>}
          </div>
        )}
      </Card>

      {hourly && (
        <Card>
          <SectionTitle icon={KIND_ICONS[event.kind] ?? "show_chart"} actions={usualPerHour ? (
            <Legend items={[
              { color: crisis ? "var(--bad-solid)" : "var(--ink)", label: crisis ? t("event.negativePerHour") : t("event.perHour") },
              { color: "var(--ink-2)", label: t("event.usualLine") },
            ]} />
          ) : undefined}>{crisis ? t("event.hourlyNegative") : t("event.hourly")}</SectionTitle>
          <HourlyBars values={hourly} usual={usualPerHour} labels={hourLabels} color={crisis ? "var(--bad-solid)" : "var(--ink)"}
            tip={(i) => `${hourLabels[i]} · ${t("event.mentionsCount", { n: hourly[i] })}`} />
        </Card>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {([["what", "info", event.what], ["why", "lightbulb", event.why], ["suggestion", "wand_stars", event.suggestion]] as const).map(([key, icon, text]) => text && (
          <Card key={key} className={cx(key === "suggestion" && "!bg-ink text-white")}>
            <div className={cx("mb-1.5 flex items-center gap-1.5 text-xs font-semibold", key === "suggestion" ? "text-white/70" : "text-muted")}>
              <Icon name={icon} size={14} />{t(`event.${key}`)}
            </div>
            <p className="bidi whitespace-pre-wrap text-sm leading-relaxed">{text}</p>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <Card>
          <SectionTitle icon="view_list" actions={total > 0 && <span className="text-xs text-muted">{t("event.evidenceOf", { shown: evidence.length, total: fmt.number(total) })}</span>}>
            {t("event.evidence")}
          </SectionTitle>
          {!evidence.length ? <p className="text-sm text-muted">{t("event.noEvidence")}</p> : (
            <div className="divide-y divide-line">
              {evidence.map((e) => <MentionCard key={e.id} mention={e} compact />)}
            </div>
          )}
        </Card>

        <Card className="flex flex-col gap-3 self-start">
          <SectionTitle icon="edit_square">{t("event.draft")}</SectionTitle>
          {canEdit ? (
            <Textarea rows={7} value={draft} maxLength={5000} onChange={(e) => setDraft(e.target.value)} placeholder={t("event.draftPlaceholder")} />
          ) : (
            <p className="bidi whitespace-pre-wrap rounded-2xl bg-fill p-3 text-sm leading-relaxed">{draft || "—"}</p>
          )}
          {canEdit && open && (
            <div className="flex flex-col gap-2">
              <Button variant="primary" icon="verified_user" loading={act.isPending && act.variables === "approval"} disabled={act.isPending || !draft.trim()} onClick={() => act.mutate("approval")}>{t("event.actions.approval")}</Button>
              <div className="grid grid-cols-2 gap-2">
                <Button icon="wand_stars" loading={act.isPending && act.variables === "studio"} disabled={act.isPending} onClick={() => act.mutate("studio")}>{t("event.actions.studio")}</Button>
                <Button icon="calendar_today" loading={act.isPending && act.variables === "planner"} disabled={act.isPending} onClick={() => act.mutate("planner")}>{t("event.actions.planner")}</Button>
              </div>
              {canInbox && <Button icon="inbox" loading={act.isPending && act.variables === "inbox"} disabled={act.isPending} onClick={() => act.mutate("inbox")}>{t("event.actions.inbox")}</Button>}
              <Button variant="ghost" icon="close" loading={act.isPending && act.variables === "dismiss"} disabled={act.isPending} onClick={() => act.mutate("dismiss")}>{t("event.actions.dismiss")}</Button>
              <p className="text-xs leading-relaxed text-muted">{t("event.actionsHint")}</p>
            </div>
          )}
          {canEdit && (
            <div className="border-t border-line pt-3">
              <div className="mb-2 text-[13px] font-medium text-text-2">{t("event.feedbackQuestion")}</div>
              <div className="flex flex-wrap gap-2">
                {(["useful", "not_useful", "wrong"] as const).map((f) => (
                  <Chip key={f} active={event.feedback === f} onClick={() => feedback.mutate(f)}>
                    <Icon name={f === "useful" ? "thumb_up" : f === "not_useful" ? "thumb_down" : "block"} size={14} />{t(`event.feedback.${f}`)}
                  </Chip>
                ))}
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
