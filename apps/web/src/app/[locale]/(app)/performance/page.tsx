"use client";
/** Performance: KPIs vs previous period, trends, per-network breakdown, best times, content insights, top posts,
 *  tips and the AI strategy report. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import { AreaChart, BarChart, BarRows, Heatmap } from "@/components/publishing/charts";
import { PUBLISH_PLATFORMS, PLATFORM_LABELS, type Dashboard, type Tip } from "@/components/publishing/types";
import { errorText, useFormat } from "@/components/publishing/util";
import { Button, Card, EmptyState, PageHeader, SectionTitle, Segmented, Select, Spinner, cx, toast } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { mediaUrl, api } from "@/lib/api";

const DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

export default function PerformancePage() {
  const t = useTranslations("publishing.performance");
  const qc = useQueryClient();
  const fmt = useFormat();
  const [days, setDays] = useState(30);
  const [platform, setPlatform] = useState("");
  const [report, setReport] = useState<string | null>(null);
  const dash = useQuery({ queryKey: ["dashboard", days, platform], queryFn: () => api.get<Dashboard>("/analytics/dashboard", { days, platform }) });
  const refresh = useMutation({
    mutationFn: () => api.post<{ posts: number }>("/analytics/refresh", undefined, { platform }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["dashboard"] }); toast.success(t("refreshed", { count: r.posts })); },
    onError: (err) => toast.error(errorText(err)),
  });
  const aiReport = useMutation({
    mutationFn: () => api.post<{ text: string }>("/analytics/ai-report", { days, platform: platform || null }),
    onSuccess: (r) => setReport(r.text),
    onError: (err) => toast.error(errorText(err)),
  });
  const d = dash.data;
  const dayNames = DAY_KEYS.map((k) => t(`days.${k}`));
  const label = (iso: string) => fmt.date(iso + "T12:00:00Z");

  const kpis = d ? [
    { key: "posts", icon: "send", value: fmt.number(d.kpis.posts), delta: d.deltas.posts },
    { key: "impressions", icon: "visibility", value: fmt.compact(d.kpis.impressions), delta: d.deltas.impressions },
    { key: "engagements", icon: "favorite", value: fmt.compact(d.kpis.engagements), delta: d.deltas.engagements },
    { key: "engagement_rate", icon: "percent", value: `${d.kpis.engagement_rate}%`, delta: d.deltas.engagement_rate },
    { key: "followers", icon: "group", value: fmt.compact(d.kpis.followers), sub: d.kpis.followers_growth ? `${d.kpis.followers_growth > 0 ? "+" : ""}${fmt.number(d.kpis.followers_growth)}` : undefined },
    { key: "video_views", icon: "play_circle", value: fmt.compact(d.kpis.video_views), delta: d.deltas.video_views },
    ...("link_clicks" in d.kpis ? [{ key: "link_clicks", icon: "link", value: fmt.compact(d.kpis.link_clicks), delta: d.deltas.link_clicks }] : []),
  ] : [];

  return (
    <div className="pt-2">
      <PageHeader icon="bar_chart" title={t("title")} subtitle={d?.last_sync ? t("lastSync", { date: fmt.dateTime(d.last_sync) }) : t("subtitle")}
        actions={<Button icon="refresh" loading={refresh.isPending} onClick={() => refresh.mutate()}>{t("refresh")}</Button>} />
      <div className="mb-5 flex flex-wrap items-center gap-2">
        <Segmented value={days} onChange={setDays} options={[7, 30, 90].map((n) => ({ value: n, label: t("lastDays", { n }) }))} />
        <Select className="!w-44" value={platform} onChange={(e) => setPlatform(e.target.value)}>
          <option value="">{t("allNetworks")}</option>
          {PUBLISH_PLATFORMS.map((p) => <option key={p} value={p}>{PLATFORM_LABELS[p]}</option>)}
        </Select>
      </div>
      {dash.isLoading || !d ? <div className="flex justify-center py-24"><Spinner size={28} /></div> : (
        <div className="flex flex-col gap-5">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            {kpis.map((k) => (
              <Card key={k.key} className="!p-4">
                <div className="flex items-center gap-1.5 text-xs text-muted"><Icon name={k.icon} size={15} />{t(`kpi.${k.key}`)}</div>
                <div className="mt-1.5 text-2xl font-bold tracking-tight tabular-nums">{k.value}</div>
                {"sub" in k && k.sub ? <div className="mt-0.5 text-xs text-muted">{k.sub}</div> : <Delta value={"delta" in k ? k.delta : null} />}
              </Card>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
            <Card>
              <SectionTitle icon="show_chart">{t("trend")}</SectionTitle>
              <div className="flex flex-col gap-5">
                <div><div className="mb-1 text-xs font-medium text-muted">{t("kpi.impressions")}</div>
                  <AreaChart points={d.series.map((s) => ({ label: label(s.date), value: s.impressions }))} format={fmt.number} emptyLabel={t("noData")} /></div>
                <div><div className="mb-1 text-xs font-medium text-muted">{t("kpi.engagements")}</div>
                  <AreaChart height={110} points={d.series.map((s) => ({ label: label(s.date), value: s.engagements }))} format={fmt.number} emptyLabel={t("noData")} /></div>
                <div><div className="mb-2 text-xs font-medium text-muted">{t("postsPerDay")}</div>
                  <BarChart height={70} points={d.series.map((s) => ({ label: label(s.date), value: s.posts }))} format={fmt.number} /></div>
              </div>
            </Card>
            <Card>
              <SectionTitle icon="lightbulb">{t("tips")}</SectionTitle>
              {!d.tips.length ? <p className="text-sm text-muted">{t("allGood")}</p> : (
                <ul className="flex flex-col gap-2.5">{d.tips.map((tip, i) => <TipRow key={i} tip={tip} onRefresh={() => refresh.mutate()} />)}</ul>
              )}
            </Card>
          </div>

          {d.breakdown.length > 0 && (
            <Card>
              <SectionTitle icon="table">{t("byNetwork")}</SectionTitle>
              <div className="-mx-5 overflow-x-auto px-5">
                <table className="w-full min-w-[640px] text-sm">
                  <thead><tr className="text-start text-xs text-muted">
                    {["network", "posts", "perWeek", "impressions", "engagements", "rate", "followers"].map((h) => <th key={h} className="pb-2 text-start font-medium">{t(`cols.${h}`)}</th>)}
                  </tr></thead>
                  <tbody className="divide-y divide-line">
                    {d.breakdown.map((r) => (
                      <tr key={r.platform}>
                        <td className="py-2.5"><span className="flex items-center gap-2"><PlatformBadge platform={r.platform} size={22} />{r.label}</span></td>
                        <td className="tabular-nums">{r.posts}</td>
                        <td className="tabular-nums">{r.per_week} <span className="text-xs text-muted">({t("ideal", { low: r.rhythm[0], high: r.rhythm[1] })})</span></td>
                        <td className="tabular-nums">{fmt.compact(r.impressions)}</td>
                        <td className="tabular-nums">{fmt.compact(r.engagements)}</td>
                        <td className="tabular-nums">{r.engagement_rate}%</td>
                        <td className="tabular-nums">{fmt.compact(r.followers)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
            <Card>
              <SectionTitle icon="schedule" actions={<span className="text-xs text-muted">{d.best_source === "own" ? t("fromResults") : t("benchmark")}</span>}>{t("bestTimes")}</SectionTitle>
              <Heatmap grid={d.heatmap} days={dayNames}
                cellLabel={(day, hour, score, count) => `${dayNames[day]} ${String(hour).padStart(2, "0")}:00 · ${d.best_source === "own" ? t("cellOwn", { rate: score, count }) : t("cellBench", { score })}`} />
              <div className="mt-2 flex flex-wrap gap-2">
                {d.best_slots.slice(0, 3).map((s) => (
                  <span key={`${s.weekday}-${s.hour}`} className="inline-flex items-center gap-1.5 rounded-full bg-ink px-3 py-1 text-xs font-medium text-white">
                    <Icon name="event_upcoming" size={13} />{dayNames[s.weekday]} {String(s.hour).padStart(2, "0")}:00
                  </span>
                ))}
              </div>
            </Card>
            <Card>
              <SectionTitle icon="group">{t("audience")}</SectionTitle>
              {d.followers_series.length > 1 && <div className="mb-4"><AreaChart height={90} points={d.followers_series.map((s) => ({ label: label(s.date), value: s.followers }))} format={fmt.number} /></div>}
              {!d.accounts.length ? <p className="text-sm text-muted">{t("noAccounts")}</p> : (
                <ul className="flex flex-col gap-2">
                  {d.accounts.map((a) => (
                    <li key={a.id} className="flex items-center gap-2 text-sm">
                      <PlatformBadge platform={a.platform} size={22} />
                      <span className="bidi min-w-0 flex-1 truncate">{a.name}</span>
                      {a.state !== "connected" && <Icon name="warning" size={14} className="text-bad" />}
                      <b className="tabular-nums">{fmt.compact(a.followers)}</b>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
            {(["media", "length", "hashtags"] as const).map((block) => (
              <Card key={block}>
                <SectionTitle icon={block === "media" ? "photo_library" : block === "length" ? "text_fields" : "tag"}>{t(`content.${block}`)}</SectionTitle>
                {!d.content[block].length ? <p className="text-sm text-muted">{t("notEnough")}</p> : (
                  <BarRows rows={d.content[block].map((r) => ({ label: r.label, value: r.engagement_rate, hint: t("postsCount", { count: r.count }) }))} format={(n) => `${n}%`} />
                )}
              </Card>
            ))}
          </div>

          <Card>
            <SectionTitle icon="trophy">{t("topPosts")}</SectionTitle>
            {!d.top_posts.length ? (
              <EmptyState icon="send" title={t("noPosts")} action={<Link href="/studio"><Button variant="primary" icon="wand_stars">{t("writePost")}</Button></Link>} />
            ) : (
              <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                {d.top_posts.map((p, i) => (
                  <li key={`${p.id}-${p.platform}`} className="flex gap-3 rounded-2xl border border-line bg-white/60 p-3">
                    <div className="relative h-16 w-16 shrink-0 overflow-hidden rounded-xl bg-fill-2">
                      {p.media_id ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={mediaUrl(p.media_id)} alt="" className="h-full w-full object-cover" />
                      ) : <span className="flex h-full items-center justify-center text-faint"><Icon name="text_fields" size={20} /></span>}
                      <span className="absolute start-1 top-1 rounded-full bg-ink px-1.5 text-[10px] font-bold text-white">{i + 1}</span>
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5"><PlatformBadge platform={p.platform} size={16} /><span className="bidi truncate text-sm font-semibold">{p.name}</span></div>
                      <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted">
                        <span>{fmt.date(p.date)}</span>
                        <span className="flex items-center gap-1"><Icon name="visibility" size={12} />{fmt.compact(p.impressions)}</span>
                        <span className="flex items-center gap-1"><Icon name="favorite" size={12} />{fmt.compact(p.engagements)}</span>
                        <span>{p.engagement_rate}%</span>
                      </div>
                      {p.url && <a href={p.url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs font-medium underline underline-offset-2">{t("open")}<Icon name="open_in_new" size={11} /></a>}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <SectionTitle icon="auto_awesome" actions={
              <>
                {report && <Button size="sm" variant="ghost" icon="content_copy" onClick={() => navigator.clipboard?.writeText(report).then(() => toast.success(t("copied")))}>{t("copy")}</Button>}
                <Button size="sm" variant="primary" icon="wand_stars" loading={aiReport.isPending} onClick={() => aiReport.mutate()}>{report ? t("regenerate") : t("generateReport")}</Button>
              </>
            }>{t("aiReport")}</SectionTitle>
            {report ? <div className="bidi whitespace-pre-wrap text-sm leading-relaxed">{report}</div> : <p className="text-sm text-muted">{t("aiReportHint")}</p>}
          </Card>
        </div>
      )}
    </div>
  );
}

function Delta({ value }: { value?: number | null }) {
  const t = useTranslations("publishing.performance");
  if (value === null || value === undefined) return <div className="mt-0.5 text-xs text-faint">{t("noComparison")}</div>;
  const up = value >= 0;
  return (
    <div className={cx("mt-0.5 inline-flex items-center gap-0.5 text-xs font-semibold", up ? "text-ok" : "text-bad")}>
      <Icon name={up ? "arrow_upward" : "arrow_downward"} size={12} />{Math.abs(value)}%
      <span className="ms-1 font-normal text-muted">{t("vsPrevious")}</span>
    </div>
  );
}

function TipRow({ tip, onRefresh }: { tip: Tip; onRefresh: () => void }) {
  const t = useTranslations("publishing.performance");
  const href: Record<string, string> = { accounts: "/settings/accounts", failed: "/posts?state=failed", studio: "/studio", schedule: "/studio", brand: "/settings/general" };
  const tone = { danger: "bg-bad-bg text-bad", warning: "bg-warn-bg text-warn", success: "bg-ok-bg text-ok", info: "bg-fill-2 text-text-2" }[tip.level];
  return (
    <li className="flex gap-3">
      <span className={cx("flex h-8 w-8 shrink-0 items-center justify-center rounded-xl", tone)}><Icon name={tip.icon} size={16} /></span>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold">{tip.title}</div>
        <p className="text-xs leading-relaxed text-muted">{tip.text}</p>
        {tip.action === "refresh" ? (
          <button className="mt-1 text-xs font-medium underline underline-offset-2" onClick={onRefresh}>{t("refresh")}</button>
        ) : tip.action && href[tip.action] ? (
          <Link href={href[tip.action]} className="mt-1 inline-block text-xs font-medium underline underline-offset-2">{t(`tipActions.${tip.action}`)}</Link>
        ) : null}
      </div>
    </li>
  );
}
