"use client";
/** Radar › Sources: every place the radar can listen to, grouped by how it is read (your accounts, public search,
 *  data providers), with its status, what it covers, what it costs and the one button that makes it work. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Icon } from "@/components/icon";
import { onError, useFormat } from "@/components/planning/ui";
import { SourceBadge, useScope, useSourceLabel } from "@/components/radar/shared";
import { CostLine, FixButton, StatusPill, useRadarSources } from "@/components/radar/sources";
import type { Access, SourceRow } from "@/components/radar/types";
import { Badge, Card, SectionTitle, Spinner, Switch, cx, toast } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

const GROUPS: { access: Access; icon: string }[] = [
  { access: "owned", icon: "person" },
  { access: "public", icon: "search" },
  { access: "provider", icon: "storefront" },
];

export default function RadarSourcesPage() {
  const t = useTranslations("radar.sourcesPage");
  const fmt = useFormat();
  const { queryId } = useScope();
  const sources = useRadarSources(queryId);
  if (sources.isLoading || !sources.data) return <div className="flex justify-center py-24"><Spinner size={28} /></div>;
  const data = sources.data;
  const ready = data.sources.filter((s) => s.health.status === "ready").length;
  const credits = data.credits;
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Summary icon="check_circle" label={t("summary.ready")} value={t("summary.readyValue", { ready, total: data.sources.length })} />
        <Summary icon="wallet" label={t("summary.credits")}
          value={credits.available_usd == null ? t("summary.unlimited") : `$${fmt.number(credits.available_usd, 2)}`} hint={t("summary.creditsHint")} />
        <Summary icon="payments" label={t("summary.spend")} value={`$${fmt.number(data.spend?.usd ?? 0, 2)}`}
          hint={data.spend?.cap_usd != null ? t("summary.cap", { cap: `$${fmt.number(data.spend.cap_usd, 2)}` }) : t("summary.noCap")} />
      </div>
      {GROUPS.map((g) => {
        const rows = data.sources.filter((s) => s.access === g.access);
        return (
          <Card key={g.access}>
            <SectionTitle icon={g.icon}>{t(`groups.${g.access}.title`)}</SectionTitle>
            <p className="-mt-1 mb-4 text-xs text-muted">{t(`groups.${g.access}.text`)}</p>
            <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {rows.map((row) => <SourceCard key={row.key} row={row} queryId={data.query_id} />)}
            </ul>
          </Card>
        );
      })}
    </div>
  );
}

function Summary({ icon, label, value, hint }: { icon: string; label: string; value: string; hint?: string }) {
  return (
    <div className="glass rounded-[18px] p-4">
      <div className="flex items-center gap-1.5 text-xs text-muted"><Icon name={icon} size={15} />{label}</div>
      <div className="mt-1.5 text-xl font-bold tabular-nums" dir="auto">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-faint">{hint}</div>}
    </div>
  );
}

function SourceCard({ row, queryId }: { row: SourceRow; queryId: number | null }) {
  const t = useTranslations("radar.sourcesPage");
  const fmt = useFormat();
  const label = useSourceLabel();
  const qc = useQueryClient();
  const canEdit = useSession((s) => s.can("editor"));
  const toggle = useMutation({
    mutationFn: (on: boolean) => api.post(`/listening/sources/${row.key}/toggle`, { query_id: queryId, on }),
    onSuccess: (_r, on) => { qc.invalidateQueries({ queryKey: ["radar"] }); toast.success(on ? t("enabled") : t("disabled")); },
    onError,
  });
  const status = row.health.status;
  const blocked = status === "disabled" || status === "not_in_plan" || !row.available;
  return (
    <li className={cx("flex flex-col gap-2.5 rounded-2xl p-3.5 ring-1 ring-line", row.in_query && status === "ready" ? "bg-white/70" : "bg-fill")}>
      <div className="flex items-start gap-3">
        <SourceBadge source={row.key} size={34} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-sm font-semibold">{label(row.key)}</span>
            {row.beta && <Badge tone="ink">{t("beta")}</Badge>}
            <StatusPill status={status} />
          </div>
          <p className="mt-1 text-xs leading-relaxed text-muted">{t(`covers.${row.key}`)}</p>
        </div>
        {queryId && canEdit && row.available && (
          <Switch checked={row.in_query} disabled={blocked || toggle.isPending} label={<span className="sr-only">{t("use")}</span>}
            onChange={(v) => toggle.mutate(v)} />
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-2">
        <span className="flex items-center gap-1"><Icon name="payments" size={13} /><CostLine row={row} /></span>
        {row.quota && (
          <span className="flex items-center gap-1" dir="auto"><Icon name="schedule" size={13} />
            {t(row.quota.per === "day" ? "quotaDay" : "quotaMonth", { used: fmt.number(row.quota.used), limit: fmt.number(row.quota.limit) })}
          </span>
        )}
        {row.usage && <span className="flex items-center gap-1"><Icon name="bar_chart" size={13} />{t("usage", { units: fmt.number(row.usage.units), usd: `$${fmt.number(row.usage.price, 2)}` })}</span>}
      </div>
      {status !== "ready" && row.health.message && <p className="bidi text-xs leading-relaxed text-text-2">{row.health.message}</p>}
      {row.health.note && <p className="text-xs leading-relaxed text-faint">{row.health.note}</p>}
      {row.terms_note && <p className="flex gap-1 text-[11px] leading-relaxed text-warn"><Icon name="warning" size={12} className="mt-0.5 shrink-0" />{t(`terms.${row.key}`)}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <FixButton row={row} queryId={queryId} />
        {row.in_query && status === "ready" && <span className="text-xs text-ok">{t("listening")}</span>}
      </div>
    </li>
  );
}
