"use client";
/** Ideas of the day: a few ready-to-publish suggestions every morning, built from the workspace's own signals. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Icon } from "@/components/icon";
import { MoreIdeas, SettingsButton } from "@/components/ideas/controls";
import { IdeaEditor } from "@/components/ideas/editor";
import { IdeaCard, IdeaSkeleton } from "@/components/ideas/idea-card";
import { FORMAT_ICON, ideasKey, postLink, useIdeaFormat, useIdeaSettings, useIdeas } from "@/components/ideas/shared";
import type { GenerateIn, Idea } from "@/components/ideas/types";
import { onError } from "@/components/planning/ui";
import { Badge, Button, Card, EmptyState, Segmented, Spinner, cx, toast } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

type Tab = "new" | "handled";
const BASED_ON = ["question", "rising", "event", "pillar", "product", "top_post", "format", "best_time", "brief"];
const LOADING_LINES = 6;

export default function IdeasPage() {
  const t = useTranslations("ideas");
  const fmt = useIdeaFormat();
  const qc = useQueryClient();
  const { me, can } = useSession();
  const canEdit = can("editor");
  const [now] = useState(() => Date.now());
  const [tab, setTab] = useState<Tab>("new");
  const [editing, setEditing] = useState<Idea | null>(null);
  const [pending, setPending] = useState(0);
  const settings = useIdeaSettings();
  const fresh = useIdeas("new");
  const handled = useIdeas("handled");

  const generate = useMutation({
    mutationFn: (body: GenerateIn) => api.post<Idea[]>("/ideas/generate", body),
    onMutate: (body) => {
      setTab("new");
      setPending(body.count ?? settings.data?.count ?? 3);
    },
    onSuccess: (ideas) => {
      qc.setQueryData<Idea[]>([...ideasKey, "new"], (old) => [...ideas, ...(old ?? []).filter((i) => !ideas.some((n) => n.id === i.id))]);
      toast.success(t("generated", { n: ideas.length }));
    },
    onError,
    onSettled: () => setPending(0),
  });

  const accounts = settings.data?.accounts ?? [];
  const list = fresh.data ?? [];
  const waiting = list.filter((i) => i.state === "new");
  const kinds = BASED_ON.filter((k) => waiting.some((i) => i.reasons.some((r) => r.kind === k)));
  const hour = fmt.hourNow(now);
  const part = hour < 5 ? "evening" : hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
  const first = me?.user.name.split(" ")[0];
  // isolated so an Arabic name reads right inside an English sentence (and the other way round)
  const name = first ? `\u2068${first}\u2069` : "none";

  return (
    <div className="pt-2">
      <header className="mb-6 flex flex-wrap items-end gap-4">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex items-center gap-1.5 text-[13px] font-medium text-muted">
            <Icon name="lightbulb" size={15} className="text-accent-deep" />
            {fmt.today(now)}
          </div>
          <h1 className="text-2xl font-bold tracking-tight sm:text-[28px]">
            {t(`greeting.${part}`, { name })}
            {fresh.data && (
              <span className="text-muted"> — {waiting.length ? t("header.count", { n: waiting.length }) : t("header.none")}</span>
            )}
          </h1>
          <p className="mt-1.5 max-w-2xl text-sm text-muted">
            {kinds.length ? t("basedOn.line", { list: fmt.list(kinds.map((k) => t(`basedOn.kinds.${k}`))) }) : t("basedOn.default")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {canEdit && <MoreIdeas settings={settings.data} busy={generate.isPending} onGenerate={(body) => generate.mutate(body)} />}
          {can("admin") && <SettingsButton settings={settings.data} />}
        </div>
      </header>

      <Notes />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Segmented value={tab} onChange={setTab} options={[
          { value: "new", label: <>{t("tabs.new")}{waiting.length > 0 && <Count n={waiting.length} active={tab === "new"} />}</> },
          { value: "handled", label: t("tabs.handled") },
        ]} />
        {!canEdit && <span className="inline-flex items-center gap-1 text-[12px] text-muted"><Icon name="visibility" size={14} />{t("readOnly")}</span>}
      </div>

      {tab === "new" ? (
        <>
          {generate.isPending && <Thinking />}
          {fresh.isLoading ? (
            <div className="flex justify-center py-20"><Spinner size={28} /></div>
          ) : !list.length && !pending ? (
            <Card>
              <EmptyState icon="lightbulb" title={t("empty.title")}
                text={settings.data?.daily ? t("empty.textDaily", { time: fmt.hourOnly(settings.data.hour) }) : t("empty.text")}
                action={canEdit && <Button variant="primary" size="lg" icon="auto_awesome" onClick={() => generate.mutate({})}>{t("empty.action")}</Button>} />
            </Card>
          ) : (
            <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: pending }, (_, i) => <IdeaSkeleton key={`s${i}`} index={i} />)}
              {list.map((idea, i) => (
                <IdeaCard key={idea.id} idea={idea} accounts={accounts} canEdit={canEdit} now={now} index={i + pending} onEdit={setEditing} />
              ))}
            </div>
          )}
          {list.length > 0 && !waiting.length && !pending && (
            <p className="mt-6 text-center text-sm text-muted">{t("allDone")}</p>
          )}
          {settings.data?.daily && list.length > 0 && (
            <p className="mt-6 flex items-center justify-center gap-1.5 text-center text-[12.5px] text-faint">
              <Icon name="schedule" size={14} />{t("nextBatch", { time: fmt.hourOnly(settings.data.hour) })}
            </p>
          )}
        </>
      ) : (
        <HandledList ideas={handled.data} loading={handled.isLoading} />
      )}

      {editing && <IdeaEditor key={editing.id} idea={editing} accounts={accounts} now={now} onClose={() => setEditing(null)} />}
    </div>
  );
}

function Count({ n, active }: { n: number; active: boolean }) {
  return <span className={cx("ms-1 rounded-full px-1.5 text-[11px] font-semibold tabular-nums", active ? "bg-ink text-white" : "bg-fill-2")}>{n}</span>;
}

/** Gentle notes when something is missing: no AI provider, no connected account. */
function Notes() {
  const t = useTranslations("ideas.notes");
  const settings = useIdeaSettings();
  const { can } = useSession();
  const s = settings.data;
  if (!s) return null;
  const notes = [
    !s.accounts.length && { icon: "link", text: t("noAccounts"), href: "/settings/accounts", action: t("connect") },
    !s.has_ai && { icon: "smart_toy", text: t("noAi"), href: "/settings/ai", action: t("addAi") },
  ].filter(Boolean) as { icon: string; text: string; href: string; action: string }[];
  if (!notes.length) return null;
  return (
    <div className="mb-5 flex flex-col gap-2">
      {notes.map((n) => (
        <div key={n.href} className="glass flex flex-wrap items-center gap-3 rounded-[18px] px-4 py-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-fill-2 text-text-2"><Icon name={n.icon} size={17} /></span>
          <p className="min-w-0 flex-1 text-[13px] text-text-2">{n.text}</p>
          {can("admin") && (
            <Link href={n.href} className="inline-flex items-center gap-1 text-[13px] font-semibold text-text hover:underline">
              {n.action}<Icon name="east" size={14} className="rtl:-scale-x-100" />
            </Link>
          )}
        </div>
      ))}
    </div>
  );
}

/** While ideas are being prepared: a friendly line that changes every few seconds. */
function Thinking() {
  const t = useTranslations("ideas.thinking");
  const [line, setLine] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setLine((l) => (l + 1) % LOADING_LINES), 2800);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="mb-4 flex justify-center">
      <div role="status" aria-live="polite" className="glass inline-flex items-center gap-2 rounded-full px-4 py-2 text-[13px] text-text-2">
        <Icon name="auto_awesome" size={16} className="text-accent-deep" />
        <span key={line} className="pop-in">{t(`l${line + 1}`)}</span>
      </div>
    </div>
  );
}

function HandledList({ ideas, loading }: { ideas?: Idea[]; loading: boolean }) {
  const t = useTranslations("ideas");
  const fmt = useIdeaFormat();
  if (loading) return <div className="flex justify-center py-20"><Spinner size={28} /></div>;
  if (!ideas?.length) return <Card><EmptyState icon="history" title={t("handled.emptyTitle")} text={t("handled.empty")} /></Card>;
  return (
    <Card padded={false} className="divide-y divide-[var(--line)] overflow-hidden">
      {ideas.map((idea) => {
        const href = postLink(idea);
        const status = statusOf(idea);
        const at = idea.post?.scheduled_at;
        return (
          <div key={idea.id} className="flex items-center gap-3 px-4 py-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-fill-2 text-text-2">
              <Icon name={FORMAT_ICON[idea.format]} size={18} />
            </span>
            <div className="min-w-0 flex-1">
              <div dir="auto" className="truncate text-[14px] font-semibold">{idea.title}</div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-muted">
                <Badge tone={status.tone}>{t(`handled.states.${status.key}`)}</Badge>
                {at && idea.state === "scheduled" ? <span>{fmt.short(at)}</span> : <span>{t("handled.created", { when: fmt.short(idea.created_at) })}</span>}
              </div>
            </div>
            {href && (
              <Link href={href} className="inline-flex h-8 shrink-0 items-center gap-1 rounded-full bg-fill-2 px-3 text-[12.5px] font-medium text-text-2 hover:bg-ink hover:text-white">
                {t("handled.open")}<Icon name="east" size={14} className="rtl:-scale-x-100" />
              </Link>
            )}
          </div>
        );
      })}
    </Card>
  );
}

function statusOf(idea: Idea): { key: string; tone: "neutral" | "ok" | "warn" | "bad" | "ink" } {
  if (idea.state === "rejected") return { key: "skipped", tone: "neutral" };
  if (idea.state === "draft") return { key: "draft", tone: "neutral" };
  const s = idea.post?.state;
  if (s === "to_approve") return { key: "toApprove", tone: "warn" };
  if (s === "posted") return { key: "posted", tone: "ok" };
  if (s === "partial") return { key: "partial", tone: "warn" };
  if (s === "failed") return { key: "failed", tone: "bad" };
  if (s === "draft") return { key: "draft", tone: "neutral" };
  return { key: "scheduled", tone: "ink" };
}
