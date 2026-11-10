"use client";
/** Links & sales › Overview: KPIs vs the previous period, daily clicks, results per network / campaign / post. */
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { type ReactNode, useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import { Button, Card, EmptyState, SectionTitle, Segmented, Spinner } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import type { LinksSummary, ResultRow } from "./types";
import { ColorDot, MiniBars, PlatformStack, StatTile, useFormat } from "./ui";

const delta = (now: number, before: number) => (before ? Math.round((1000 * (now - before)) / before) / 10 : null);

export function OverviewTab({ onSetup }: { onSetup: () => void }) {
  const t = useTranslations("links");
  const fmt = useFormat();
  const [days, setDays] = useState(30);
  const { data, isLoading } = useQuery({ queryKey: ["links-summary", days], queryFn: () => api.get<LinksSummary>("/links/summary", { days }) });
  if (isLoading || !data) return <div className="flex justify-center py-16"><Spinner /></div>;
  const { totals, previous, currency } = data;
  const empty = !totals.clicks && !totals.conversions;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented size="sm" value={days} onChange={setDays} options={[7, 30, 90].map((d) => ({ value: d, label: t("lastDays", { count: d }) }))} />
        {!data.enabled && (
          <button onClick={onSetup} className="inline-flex items-center gap-1.5 rounded-full bg-warn-bg px-3 py-1.5 text-[12px] font-medium text-warn">
            <Icon name="warning" size={14} /> {t("trackingOff")}
          </button>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile dark icon="link" label={t("kpi.clicks")} value={fmt.number(totals.clicks)} delta={delta(totals.clicks, previous.clicks)} />
        <StatTile icon="shopping_cart" label={t("kpi.conversions")} value={fmt.number(totals.conversions)} delta={delta(totals.conversions, previous.conversions)}
          hint={totals.leads ? t("kpi.leads", { count: totals.leads }) : undefined} />
        <StatTile icon="payments" label={t("kpi.revenue")} value={fmt.money(totals.revenue, currency)} delta={delta(totals.revenue, previous.revenue)} />
        <StatTile icon="percent" label={t("kpi.rate")} value={`${fmt.number(totals.conversion_rate, 2)}%`} hint={t("kpi.rateHint")} />
      </div>

      {empty ? (
        <Card>
          <EmptyState icon="link" title={t("emptyTitle")} text={t("emptyText")}
            action={<Button variant="primary" icon="settings" onClick={onSetup}>{t("setupTracking")}</Button>} />
        </Card>
      ) : (
        <>
          <Card>
            <SectionTitle icon="show_chart">{t("dailyClicks")}</SectionTitle>
            <MiniBars values={data.daily.map((d) => d.clicks)} labels={data.daily.map((d) => fmt.date(d.date, { day: "numeric", month: "short" }))} height={110} />
            <div className="mt-1 flex justify-between text-[11px] text-faint">
              <span>{fmt.date(data.daily[0]?.date, { day: "numeric", month: "short" })}</span>
              <span>{fmt.date(data.daily[data.daily.length - 1]?.date, { day: "numeric", month: "short" })}</span>
            </div>
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <SectionTitle icon="bar_chart">{t("byNetwork")}</SectionTitle>
              <Rows rows={data.by_platform} currency={currency} lead={(r) => <PlatformBadge platform={r.key} size={28} />} />
            </Card>
            <Card>
              <SectionTitle icon="campaign">{t("byCampaign")}</SectionTitle>
              <Rows rows={data.by_campaign} currency={currency} lead={(r) => <ColorDot color={r.color || "#0a0a0a"} size={12} />}
                href={(r) => `/campaigns/${r.key}`} empty={t("noCampaigns")} />
            </Card>
          </div>
          <Card>
            <SectionTitle icon="trophy">{t("topPosts")}</SectionTitle>
            <ul className="-mx-2 flex flex-col">
              {data.top_posts.map((p, i) => (
                <li key={p.id}>
                  <Link href={`/planner?post=${p.id}`} className="flex items-center gap-3 rounded-xl px-2 py-2 hover:bg-fill">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink text-[11px] font-bold text-white">{i + 1}</span>
                    {p.thumb_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={p.thumb_url} alt="" className="h-10 w-10 shrink-0 rounded-xl object-cover" />
                    ) : <span className="h-10 w-10 shrink-0 rounded-xl bg-fill-2" />}
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13.5px] font-semibold bidi">{p.name || t("untitled")}</div>
                      <PlatformStack platforms={p.platforms} size={15} />
                    </div>
                    <div className="text-end text-[12px]">
                      <div className="font-semibold bidi">{fmt.money(p.revenue, currency)}</div>
                      <div className="text-muted">{t("clicksShort", { count: p.clicks })} · {t("conversionsShort", { count: p.conversions })}</div>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}

function Rows({ rows, currency, lead, href, empty }: {
  rows: ResultRow[]; currency: string; lead: (r: ResultRow) => ReactNode; href?: (r: ResultRow) => string; empty?: string;
}) {
  const t = useTranslations("links");
  const fmt = useFormat();
  if (!rows.length) return <p className="py-6 text-center text-[13px] text-faint">{empty || t("noData")}</p>;
  const max = Math.max(1, ...rows.map((r) => r.clicks));
  return (
    <ul className="flex flex-col gap-3">
      {rows.map((r) => {
        const body = (
          <div className="flex items-center gap-3">
            {lead(r)}
            <div className="min-w-0 flex-1">
              <div className="flex justify-between gap-2 text-[13px]">
                <span className="truncate font-semibold bidi">{r.label}</span>
                <span className="shrink-0 font-semibold bidi">{r.revenue ? fmt.money(r.revenue, currency) : "—"}</span>
              </div>
              <div className="mt-1 h-1.5 rounded-full bg-track"><div className="h-full rounded-full bg-ink" style={{ width: `${(100 * r.clicks) / max}%` }} /></div>
              <div className="mt-1 text-[11px] text-muted">{t("clicksShort", { count: r.clicks })} · {t("conversionsShort", { count: r.conversions })}</div>
            </div>
          </div>
        );
        return <li key={r.key}>{href ? <Link href={href(r)} className="block rounded-xl hover:bg-fill">{body}</Link> : body}</li>;
      })}
    </ul>
  );
}
