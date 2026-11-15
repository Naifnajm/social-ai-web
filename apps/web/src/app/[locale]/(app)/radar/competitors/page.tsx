"use client";
/** Competitors: who owns the conversation (weekly share of voice), how strongly people feel about each brand
 *  (passion matrix) and what drives each one (table). */
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useFormat } from "@/components/planning/ui";
import { BRAND_COLORS, Legend, PassionMatrix, ShareColumns, signed } from "@/components/radar/charts";
import { useRadarQueries, useScope } from "@/components/radar/shared";
import type { Competitors } from "@/components/radar/types";
import { Button, Card, EmptyState, SectionTitle, Spinner, cx } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

export default function RadarCompetitorsPage() {
  const t = useTranslations("radar");
  const fmt = useFormat();
  const canEdit = useSession((s) => s.can("editor"));
  const { queryId, days } = useScope();
  const queries = useRadarQueries();
  const setup = queries.data?.find((q) => q.id === queryId);
  const data = useQuery({
    queryKey: ["radar", "competitors", queryId, days],
    queryFn: () => api.get<Competitors>("/listening/competitors", { query_id: queryId, days }),
    enabled: !!queryId && !!setup?.competitors.length,
  });
  if (!setup) return <div className="flex justify-center py-24"><Spinner size={28} /></div>;
  if (!setup.competitors.length) {
    return (
      <Card>
        <EmptyState icon="flag" title={t("competitors.emptyTitle")} text={t("competitors.emptyText")}
          action={canEdit && <Link href="/radar/setup"><Button variant="primary" icon="add">{t("competitors.add")}</Button></Link>} />
      </Card>
    );
  }
  const d = data.data;
  if (!d) return <div className="flex justify-center py-24"><Spinner size={28} /></div>;
  const ownName = (b: string, own: boolean) => (own ? t("competitors.you", { name: b }) : b);
  const legend = d.brands.map((b, i) => ({ color: BRAND_COLORS[i % BRAND_COLORS.length], label: <span className="bidi">{ownName(b, i === 0)}</span> }));

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Card>
          <SectionTitle icon="bar_chart" actions={<span className="text-xs text-muted">{t("competitors.sovHint")}</span>}>{t("competitors.sov")}</SectionTitle>
          <ShareColumns weeks={d.weeks} brands={d.brands} weekLabel={(iso) => fmt.date(iso, { day: "numeric", month: "short" })} />
          <div className="mt-3"><Legend items={legend} /></div>
        </Card>
        <Card>
          <SectionTitle icon="favorite" actions={<span className="text-xs text-muted">{t("competitors.passionHint")}</span>}>{t("competitors.passion")}</SectionTitle>
          <PassionMatrix rows={d.table} labels={{
            x: t("competitors.netAxis"),
            lovedStrongly: t("competitors.lovedStrongly"),
            hatedStrongly: t("competitors.hatedStrongly"),
            mildlyLiked: t("competitors.mildlyLiked"),
            mildlyDisliked: t("competitors.mildlyDisliked"),
            tip: (r) => t("competitors.passionTip", { brand: r.brand, net: signed(r.net_sentiment), passion: r.passion, n: fmt.number(r.mentions) }),
          }} />
          <p className="mt-2 text-xs leading-relaxed text-muted">{t("competitors.passionExplain")}</p>
        </Card>
      </div>

      <Card>
        <SectionTitle icon="table">{t("competitors.compare")}</SectionTitle>
        <div className="-mx-5 overflow-x-auto px-5">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="text-xs text-muted">
                {(["brand", "mentions", "sov", "net", "passion", "topTopic", "topComplaint"] as const).map((h) => (
                  <th key={h} className="pb-2 text-start font-medium">{t(`competitors.cols.${h}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {d.table.map((r, i) => (
                <tr key={r.brand} className={cx(r.own && "font-semibold")}>
                  <td className="py-2.5">
                    <span className="flex items-center gap-2">
                      <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: BRAND_COLORS[i % BRAND_COLORS.length] }} />
                      <span className="bidi">{ownName(r.brand, r.own)}</span>
                    </span>
                  </td>
                  <td className="tabular-nums">{fmt.number(r.mentions)}</td>
                  <td className="tabular-nums">{r.share_of_voice}%</td>
                  <td className={cx("tabular-nums", r.net_sentiment > 0 ? "text-ok" : r.net_sentiment < 0 ? "text-bad" : "")}><span className="bidi">{signed(r.net_sentiment)}</span></td>
                  <td className="tabular-nums">{r.passion}</td>
                  <td className="bidi font-normal">{r.top_topic ?? "—"}</td>
                  <td className="bidi font-normal">{r.top_complaint ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
