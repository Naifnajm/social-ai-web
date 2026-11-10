"use client";
/** Campaign detail: goal, dates, results (reach, engagement, clicks, revenue), per network and the posts. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import { CampaignForm } from "@/components/planning/campaign-form";
import type { CampaignDetail } from "@/components/planning/types";
import { PLATFORM_LABELS, PlatformStack, StatTile, StateBadge, onError, pct, useFormat } from "@/components/planning/ui";
import { Button, Card, EmptyState, Modal, SectionTitle, Spinner, toast } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

export default function CampaignPage() {
  const t = useTranslations("campaigns");
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const qc = useQueryClient();
  const router = useRouter();
  const fmt = useFormat();
  const { can } = useSession();
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const { data: c, isLoading, error } = useQuery({ queryKey: ["campaign", id], queryFn: () => api.get<CampaignDetail>(`/campaigns/${id}`) });

  const archive = useMutation({
    mutationFn: (archived: boolean) => api.patch(`/campaigns/${id}`, { archived }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["campaign", id] }); qc.invalidateQueries({ queryKey: ["campaigns"] }); toast.success(t("saved")); },
    onError,
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/campaigns/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["campaigns"] }); router.replace("/campaigns"); },
    onError,
  });

  if (isLoading) return <div className="flex justify-center py-20"><Spinner /></div>;
  if (error || !c) return <Card className="mt-4"><EmptyState icon="campaign" title={t("notFound")} action={<Link href="/campaigns"><Button>{t("back")}</Button></Link>} /></Card>;

  const s = c.stats;
  const progress = c.target_posts ? Math.min(100, (100 * s.published_count) / c.target_posts) : s.progress;
  const planner = `/planner?campaign=${c.id}${c.date_start ? `&date=${c.date_start}` : ""}`;

  return (
    <div className="pt-2">
      <Link href="/campaigns" className="mb-3 inline-flex items-center gap-1 text-[13px] text-muted hover:text-text">
        <Icon name="east" size={14} className="rotate-180 rtl:rotate-0" /> {t("title")}
      </Link>

      <Card className="relative mb-4 overflow-hidden">
        <span className="absolute inset-y-0 start-0 w-1.5" style={{ background: c.color }} />
        <div className="flex flex-col gap-4 md:flex-row md:items-start">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-bold tracking-tight bidi">{c.name}</h1>
              <StateBadge state={c.state} />
              {c.archived && <span className="rounded-full bg-fill-2 px-2 py-0.5 text-[11px] font-semibold text-muted">{t("archived")}</span>}
            </div>
            {c.tagline && <p className="mt-1 text-[15px] text-text-2 bidi">{c.tagline}</p>}
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-muted">
              <span className="inline-flex items-center gap-1"><Icon name="calendar_today" size={14} />
                {c.date_start || c.date_end ? <span className="bidi">{fmt.date(c.date_start) || "…"} – {fmt.date(c.date_end) || "…"}</span> : t("noDates")}
              </span>
              {c.days_left !== null && c.state === "running" && <span>{t("daysLeft", { count: c.days_left })}</span>}
              {c.owner_name && <span className="inline-flex items-center gap-1"><Icon name="person" size={14} />{c.owner_name}</span>}
              {c.budget != null && <span className="inline-flex items-center gap-1"><Icon name="payments" size={14} /><span className="bidi">{fmt.money(c.budget, c.currency)}</span></span>}
            </div>
            {c.goal && <p className="mt-3 max-w-3xl whitespace-pre-line rounded-2xl bg-fill px-3.5 py-2.5 text-[13.5px] text-text-2 bidi">{c.goal}</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href={planner}><Button icon="calendar_today">{t("openPlanner")}</Button></Link>
            {can("editor") && <Link href={`/studio?campaign=${c.id}`}><Button variant="primary" icon="add">{t("newPost")}</Button></Link>}
          </div>
        </div>
        <div className="mt-4">
          <div className="mb-1 flex justify-between text-[12px] text-muted">
            <span>{c.target_posts ? t("publishedOfTarget", { done: s.published_count, target: c.target_posts }) : t("publishedOfPosts", { done: s.published_count, total: s.post_count })}</span>
            <span className="bidi">{Math.round(progress)}%</span>
          </div>
          <div className="h-2 rounded-full bg-track"><div className="h-full rounded-full transition-all" style={{ width: `${progress}%`, background: c.color }} /></div>
        </div>
        {can("editor") && (
          <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-3">
            <Button size="sm" variant="ghost" icon="edit_square" onClick={() => setEditing(true)}>{t("edit")}</Button>
            <Button size="sm" variant="ghost" icon="archive" loading={archive.isPending} onClick={() => archive.mutate(!c.archived)}>{c.archived ? t("unarchive") : t("archive")}</Button>
            {can("admin") && <Button size="sm" variant="ghost" icon="delete" className="text-bad" onClick={() => setDeleting(true)}>{t("delete")}</Button>}
          </div>
        )}
      </Card>

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile dark icon="send" label={t("stats.published")} value={fmt.number(s.published_count)} hint={t("stats.planned", { count: s.scheduled_count })} />
        <StatTile icon="visibility" label={t("stats.impressions")} value={fmt.compact(s.impressions)} />
        <StatTile icon="thumb_up" label={t("stats.engagements")} value={fmt.compact(s.engagements)} hint={pct(fmt.number(s.engagement_rate, 2))} />
        <StatTile icon="link" label={t("stats.clicks")} value={fmt.number(s.clicks)} hint={s.impressions ? `CTR ${pct(fmt.number((100 * s.clicks) / s.impressions, 2))}` : undefined} />
        <StatTile icon="shopping_cart" label={t("stats.conversions")} value={fmt.number(s.conversions)} />
        <StatTile icon="payments" label={t("stats.revenue")} value={fmt.money(s.revenue, c.currency)}
          hint={c.budget ? t("stats.roas", { value: fmt.number(s.revenue / c.budget, 1) }) : undefined} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <Card>
          <SectionTitle icon="bar_chart">{t("byNetwork")}</SectionTitle>
          {c.networks.length ? (
            <ul className="flex flex-col gap-3">
              {c.networks.map((n) => {
                const max = Math.max(...c.networks.map((x) => x.impressions), 1);
                return (
                  <li key={n.platform} className="flex items-center gap-3">
                    <PlatformBadge platform={n.platform} size={30} />
                    <div className="min-w-0 flex-1">
                      <div className="flex justify-between text-[12.5px]">
                        <span className="font-semibold">{PLATFORM_LABELS[n.platform] || n.platform}</span>
                        <span className="text-muted">{fmt.compact(n.impressions)} · {pct(fmt.number(n.engagement_rate, 1))}</span>
                      </div>
                      <div className="mt-1 h-1.5 rounded-full bg-track"><div className="h-full rounded-full bg-ink" style={{ width: `${(100 * n.impressions) / max}%` }} /></div>
                      <div className="mt-1 flex gap-3 text-[11px] text-muted">
                        <span>{t("stats.postsCount", { count: n.posts })}</span>
                        <span>{t("stats.clicksCount", { count: n.clicks })}</span>
                        {n.revenue > 0 && <span className="bidi">{fmt.money(n.revenue, c.currency)}</span>}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : <p className="py-6 text-center text-[13px] text-faint">{t("noResults")}</p>}
        </Card>

        <Card>
          <SectionTitle icon="view_list" actions={<Link href={planner} className="text-[12.5px] font-medium text-text-2 hover:text-text">{t("openPlanner")}</Link>}>
            {t("posts")} <span className="text-[12px] font-normal text-muted">({c.posts.length})</span>
          </SectionTitle>
          {c.posts.length ? (
            <ul className="-mx-2 flex flex-col">
              {c.posts.map((p) => (
                <li key={p.id}>
                  <Link href={`/planner?post=${p.id}${p.day ? `&date=${p.day}` : ""}`} className="flex items-center gap-3 rounded-xl px-2 py-2 hover:bg-fill">
                    {p.media?.kind === "image" ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={p.media.url} alt="" className="h-11 w-11 shrink-0 rounded-xl object-cover" />
                    ) : (
                      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-fill-2 text-muted"><Icon name={p.media ? "movie" : "text_fields"} size={18} /></span>
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13.5px] font-semibold bidi">{p.name || p.preview || t("untitled")}</div>
                      <div className="flex items-center gap-2 text-[11.5px] text-muted">
                        <span>{p.day ? fmt.date(p.day, { day: "numeric", month: "short" }) : t("noDate")}{p.time && <> · <span dir="ltr">{p.time}</span></>}</span>
                        <PlatformStack platforms={p.platforms} size={15} />
                      </div>
                    </div>
                    <StateBadge state={p.state} />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState icon="send" title={t("noPosts")} text={t("noPostsText")}
              action={can("editor") && <Link href={`/studio?campaign=${c.id}`}><Button variant="primary" icon="add">{t("newPost")}</Button></Link>} />
          )}
        </Card>
      </div>

      {editing && <CampaignForm key={c.id} campaign={c} open onClose={() => setEditing(false)} />}
      <Modal open={deleting} onClose={() => setDeleting(false)} title={t("deleteTitle")} size="sm"
        footer={<><Button onClick={() => setDeleting(false)}>{t("cancel")}</Button><Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate()}>{t("delete")}</Button></>}>
        <p className="text-sm text-text-2">{t("deleteText")}</p>
      </Modal>
    </div>
  );
}
