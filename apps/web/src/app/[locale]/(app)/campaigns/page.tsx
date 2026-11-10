"use client";
/** Campaigns: kanban by state (planned / running / finished) or a list, with results per campaign. */
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Icon } from "@/components/icon";
import { CampaignForm } from "@/components/planning/campaign-form";
import type { Campaign, CampaignState } from "@/components/planning/types";
import { StateBadge, useFormat } from "@/components/planning/ui";
import { Button, Card, EmptyState, Input, PageHeader, Segmented, Spinner, Switch, cx } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

const COLUMNS: CampaignState[] = ["planned", "running", "finished"];
const VIEW_KEY = "sai.campaigns.view";

export default function CampaignsPage() {
  const t = useTranslations("campaigns");
  const states = useTranslations("planning.states");
  const canEdit = useSession((s) => s.can("editor"));
  const [view, setView] = useState<"board" | "list">("board");
  const [q, setQ] = useState("");
  const [archived, setArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ["campaigns", archived],
    queryFn: () => api.get<Campaign[]>("/campaigns", { include_archived: archived }),
  });

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(VIEW_KEY);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- read once from the browser after mount
      if (saved === "list" || saved === "board") setView(saved);
    } catch {
      /* storage unavailable */
    }
  }, []);
  const changeView = (v: "board" | "list") => {
    setView(v);
    try {
      window.localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* storage unavailable */
    }
  };

  const items = (data || []).filter((c) => !q.trim() || c.name.toLowerCase().includes(q.trim().toLowerCase()));

  return (
    <div className="pt-2">
      <PageHeader icon="campaign" title={t("title")} subtitle={t("subtitle")}
        actions={canEdit && <Button variant="primary" icon="add" onClick={() => setCreating(true)}>{t("new")}</Button>} />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 sm:max-w-xs">
          <Icon name="search" size={16} className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-faint" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("search")} className="ps-9" />
        </div>
        <Switch checked={archived} onChange={setArchived} label={<span className="text-[13px] text-text-2">{t("showArchived")}</span>} />
        <Segmented className="ms-auto" size="sm" value={view} onChange={changeView} options={[
          { value: "board", label: t("board"), icon: "view_list" },
          { value: "list", label: t("list"), icon: "table" },
        ]} />
      </div>

      {isLoading ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : !items.length ? (
        <Card><EmptyState icon="campaign" title={t("emptyTitle")} text={t("emptyText")}
          action={canEdit && <Button variant="primary" icon="add" onClick={() => setCreating(true)}>{t("new")}</Button>} /></Card>
      ) : view === "board" ? (
        <div className="grid gap-4 lg:grid-cols-3">
          {COLUMNS.map((state) => {
            const column = items.filter((c) => c.state === state);
            return (
              <div key={state} className="flex min-w-0 flex-col gap-3">
                <div className="flex items-center gap-2 px-1">
                  <span className={cx("h-2 w-2 rounded-full", state === "running" ? "bg-ok" : state === "planned" ? "bg-ink" : "bg-faint")} />
                  <span className="text-[13px] font-semibold">{states(state)}</span>
                  <span className="rounded-full bg-fill-2 px-2 text-[11px] font-semibold text-text-2">{column.length}</span>
                </div>
                {column.map((c) => <CampaignCard key={c.id} campaign={c} />)}
                {!column.length && <div className="rounded-[20px] border border-dashed border-line-strong p-6 text-center text-[12.5px] text-faint">{t("emptyColumn")}</div>}
              </div>
            );
          })}
        </div>
      ) : (
        <CampaignTable items={items} />
      )}

      {creating && <CampaignForm open onClose={() => setCreating(false)} />}
    </div>
  );
}

function Dates({ c }: { c: Campaign }) {
  const t = useTranslations("campaigns");
  const fmt = useFormat();
  if (!c.date_start && !c.date_end) return <span className="text-faint">{t("noDates")}</span>;
  return (
    <span className="bidi">
      {c.date_start ? fmt.date(c.date_start, { day: "numeric", month: "short" }) : "…"} – {c.date_end ? fmt.date(c.date_end, { day: "numeric", month: "short", year: "numeric" }) : "…"}
    </span>
  );
}

function CampaignCard({ campaign: c }: { campaign: Campaign }) {
  const t = useTranslations("campaigns");
  const fmt = useFormat();
  const currency = useSession((s) => s.workspace?.currency || "SAR");
  const progress = c.target_posts ? Math.min(100, (100 * c.stats.published_count) / c.target_posts) : c.stats.progress;
  return (
    <Link href={`/campaigns/${c.id}`} className="block">
      <Card className="relative overflow-hidden !p-4 transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-lift)]">
        <span className="absolute inset-x-0 top-0 h-1" style={{ background: c.color }} />
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="truncate text-[15px] font-semibold bidi">{c.name}</div>
            {c.tagline && <div className="truncate text-[12.5px] text-muted bidi">{c.tagline}</div>}
          </div>
          {c.archived && <span className="rounded-full bg-fill-2 px-2 py-0.5 text-[10.5px] font-semibold text-muted">{t("archived")}</span>}
        </div>
        <div className="mt-2 flex items-center gap-1.5 text-[12px] text-text-2">
          <Icon name="calendar_today" size={13} /> <Dates c={c} />
          {c.days_left !== null && c.state === "running" && <span className="ms-auto rounded-full bg-ink px-2 py-0.5 text-[10.5px] font-semibold text-white">{t("daysLeft", { count: c.days_left })}</span>}
        </div>
        <div className="mt-3">
          <div className="mb-1 flex justify-between text-[11px] text-muted">
            <span>{c.target_posts ? t("publishedOfTarget", { done: c.stats.published_count, target: c.target_posts }) : t("publishedOfPosts", { done: c.stats.published_count, total: c.stats.post_count })}</span>
            <span className="bidi">{Math.round(progress)}%</span>
          </div>
          <div className="h-1.5 rounded-full bg-track"><div className="h-full rounded-full" style={{ width: `${progress}%`, background: c.color }} /></div>
        </div>
        <div className="mt-3 grid grid-cols-4 gap-2 border-t border-line pt-3 text-center">
          <Metric label={t("stats.posts")} value={fmt.number(c.stats.post_count)} />
          <Metric label={t("stats.reach")} value={fmt.compact(c.stats.impressions)} />
          <Metric label={t("stats.clicks")} value={fmt.compact(c.stats.clicks)} />
          <Metric label={t("stats.revenue")} value={c.stats.revenue ? fmt.compact(c.stats.revenue) : "—"} title={fmt.money(c.stats.revenue, currency)} />
        </div>
      </Card>
    </Link>
  );
}

function Metric({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div title={title}>
      <div className="text-[14px] font-bold bidi">{value}</div>
      <div className="truncate text-[10.5px] text-muted">{label}</div>
    </div>
  );
}

function CampaignTable({ items }: { items: Campaign[] }) {
  const t = useTranslations("campaigns");
  const fmt = useFormat();
  const currency = useSession((s) => s.workspace?.currency || "SAR");
  return (
    <Card padded={false} className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-[13px]">
        <thead>
          <tr className="border-b border-line text-[12px] text-muted">
            <th className="px-4 py-3 text-start font-medium">{t("fields.name")}</th>
            <th className="px-3 py-3 text-start font-medium">{t("fields.state")}</th>
            <th className="px-3 py-3 text-start font-medium">{t("dates")}</th>
            <th className="px-3 py-3 text-end font-medium">{t("stats.posts")}</th>
            <th className="px-3 py-3 text-end font-medium">{t("stats.impressions")}</th>
            <th className="px-3 py-3 text-end font-medium">{t("stats.engagementRate")}</th>
            <th className="px-3 py-3 text-end font-medium">{t("stats.clicks")}</th>
            <th className="px-4 py-3 text-end font-medium">{t("stats.revenue")}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((c) => (
            <tr key={c.id} className="border-b border-line last:border-0 hover:bg-fill">
              <td className="px-4 py-3">
                <Link href={`/campaigns/${c.id}`} className="flex items-center gap-2 font-semibold">
                  <span className="h-6 w-1.5 rounded-full" style={{ background: c.color }} />
                  <span className="bidi">{c.name}</span>
                </Link>
              </td>
              <td className="px-3 py-3"><StateBadge state={c.state} /></td>
              <td className="px-3 py-3 text-text-2"><Dates c={c} /></td>
              <td className="px-3 py-3 text-end bidi">{fmt.number(c.stats.published_count)} / {fmt.number(c.stats.post_count)}</td>
              <td className="px-3 py-3 text-end">{fmt.number(c.stats.impressions)}</td>
              <td className="px-3 py-3 text-end bidi">{fmt.number(c.stats.engagement_rate, 2)}%</td>
              <td className="px-3 py-3 text-end">{fmt.number(c.stats.clicks)}</td>
              <td className="px-4 py-3 text-end font-semibold bidi">{c.stats.revenue ? fmt.money(c.stats.revenue, currency) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
