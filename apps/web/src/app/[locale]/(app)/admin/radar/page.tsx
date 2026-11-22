"use client";
/** Platform admin › Radar sources: the platform's keys for each source (write-only), the price per unit, on/off for
 *  every workspace, what each source cost this month and which workspaces used it. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon } from "@/components/icon";
import { onError, useFormat } from "@/components/planning/ui";
import { SourceBadge, useSourceLabel } from "@/components/radar/shared";
import { Badge, Button, Card, Field, IconButton, Input, SectionTitle, Spinner, Switch, toast } from "@/components/ui";
import { api } from "@/lib/api";

type AdminSource = {
  key: string; label: string; access: string; beta: boolean; available: boolean; enabled: boolean; feature: string;
  unit: string | null; default_price: number; unit_price: number | null; workspace_price: number | null;
  keys: Record<string, boolean>; required_keys: string[]; permission: string | null; permission_doc: string | null;
  quota: string | null; terms_note: string | null; docs: string | null;
  usage: { units: number; cost: number; price: number; calls: number } | null;
};
type AdminOut = {
  sources: AdminSource[]; markup_percent: number; youtube_units_per_run: number; youtube_units_today: number; youtube_daily_units: number;
  workspaces: { id: number; name: string; cost: number; price: number; by_source: Record<string, { cost: number; units: number }> }[];
  month_cost: number; month_price: number;
};

const KEY_LABELS: Record<string, string> = {
  "listening.x_bearer_token": "X API bearer token",
  "listening.youtube_api_key": "YouTube Data API key",
  "listening.brave_api_key": "Brave Search API key",
  "listening.reddit_client_id": "Reddit client id",
  "listening.reddit_client_secret": "Reddit client secret",
  "listening.tiktok_provider_key": "ScrapeCreators API key",
  "listening.gnews_api_key": "GNews API key",
  "listening.newsapi_key": "NewsAPI key",
};

export default function AdminRadarPage() {
  const { data } = useQuery({ queryKey: ["admin-radar"], queryFn: () => api.get<AdminOut>("/listening/admin/sources") });
  if (!data) return <div className="flex justify-center py-16"><Spinner size={26} /></div>;
  return <RadarForm initial={data} />;
}

function RadarForm({ initial }: { initial: AdminOut }) {
  const t = useTranslations("admin.radar");
  const ta = useTranslations("admin");
  const fmt = useFormat();
  const label = useSourceLabel();
  const qc = useQueryClient();
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [prices, setPrices] = useState<Record<string, string>>(() =>
    Object.fromEntries(initial.sources.filter((s) => s.unit && s.unit_price !== s.default_price).map((s) => [s.key, String(s.unit_price)])));
  const [enabled, setEnabled] = useState<Record<string, boolean>>(() => Object.fromEntries(initial.sources.map((s) => [s.key, s.enabled])));
  const [units, setUnits] = useState(String(initial.youtube_units_per_run));
  const save = useMutation({
    mutationFn: () => api.put<AdminOut>("/listening/admin/sources", {
      secrets,
      prices: Object.fromEntries(initial.sources.filter((s) => s.unit).map((s) => [s.key, prices[s.key] ? Number(prices[s.key]) : null])),
      enabled, youtube_units_per_run: Number(units) || null,
    }),
    onSuccess: (out) => { qc.setQueryData(["admin-radar"], out); setSecrets({}); toast.success(t("saved")); },
    onError,
  });
  const allKeys = Array.from(new Set(initial.sources.flatMap((s) => Object.keys(s.keys))));
  const configured = (key: string) => initial.sources.some((s) => s.keys[key]) && secrets[key] !== "";

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Tile icon="payments" label={t("monthCost")} value={`$${fmt.number(initial.month_cost, 2)}`} />
        <Tile icon="wallet" label={t("monthBilled")} value={`$${fmt.number(initial.month_price, 2)}`} hint={t("markup", { n: initial.markup_percent })} />
        <Tile icon="schedule" label={t("youtubeToday")} value={`${fmt.number(initial.youtube_units_today)} / ${fmt.number(initial.youtube_daily_units)}`} />
      </div>

      <Card>
        <SectionTitle icon="key">{t("keys")}</SectionTitle>
        <p className="-mt-1 mb-3 text-sm text-muted">{t("keysHint")}</p>
        <ul className="flex flex-col divide-y divide-line">
          {allKeys.map((key) => (
            <li key={key} className="flex flex-wrap items-center gap-3 py-3">
              <Icon name="key" size={18} className="text-text-2" />
              <span className="w-48 text-sm font-semibold" dir="ltr">{KEY_LABELS[key] ?? key}</span>
              <Badge tone={configured(key) ? "ok" : "neutral"}>{configured(key) ? t("configured") : t("notConfigured")}</Badge>
              <Input className="min-w-[200px] flex-1" type="password" dir="ltr" autoComplete="off" aria-label={KEY_LABELS[key] ?? key}
                placeholder={configured(key) ? "••••••••  " + t("replace") : "…"} value={secrets[key] ?? ""}
                onChange={(e) => setSecrets({ ...secrets, [key]: e.target.value })} />
              {initial.sources.some((s) => s.keys[key]) && <IconButton icon="delete" label={t("clear")} onClick={() => setSecrets({ ...secrets, [key]: "" })} />}
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <SectionTitle icon="graphic_eq">{t("sources")}</SectionTitle>
        <ul className="flex flex-col divide-y divide-line">
          {initial.sources.map((s) => (
            <li key={s.key} className="flex flex-col gap-2 py-3.5 sm:flex-row sm:items-start">
              <div className="flex min-w-0 flex-1 gap-3">
                <SourceBadge source={s.key} size={30} />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5 text-sm font-semibold">
                    {label(s.key)}
                    {s.beta && <Badge tone="ink">{t("beta")}</Badge>}
                    {!s.available && <Badge>{t("unavailable")}</Badge>}
                    {s.feature !== "listening" && <Badge>{t("plan", { feature: s.feature })}</Badge>}
                  </div>
                  <p className="mt-0.5 text-xs text-muted">{t(`todo.${s.key}`)}</p>
                  {s.permission && s.permission_doc && (
                    <a href={s.permission_doc} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs font-semibold underline">
                      <Icon name="verified_user" size={12} /><span dir="ltr">{s.permission}</span>
                    </a>
                  )}
                  {s.quota && <p className="mt-1 text-[11px] text-faint" dir="ltr">{s.quota}</p>}
                  {s.terms_note && <p className="mt-1 text-[11px] text-warn">{t(`terms.${s.key}`)}</p>}
                  {s.usage && <p className="mt-1 text-xs text-text-2">{t("usage", { units: fmt.number(s.usage.units), cost: `$${fmt.number(s.usage.cost, 2)}`, billed: `$${fmt.number(s.usage.price, 2)}` })}</p>}
                </div>
              </div>
              <div className="flex items-center gap-3 ps-11 sm:ps-0">
                {s.unit && (
                  <Field label={<span className="text-xs">{t("price", { unit: t(`units.${s.unit}`) })}</span>}>
                    <div className="relative w-32" dir="ltr">
                      <span className="pointer-events-none absolute inset-y-0 start-3 flex items-center text-sm text-muted">$</span>
                      <Input type="number" min={0} step={0.0001} dir="ltr" className="ps-7" placeholder={String(s.default_price)}
                        value={prices[s.key] ?? ""} onChange={(e) => setPrices({ ...prices, [s.key]: e.target.value })} />
                    </div>
                  </Field>
                )}
                {s.available && <Switch checked={enabled[s.key]} onChange={(v) => setEnabled({ ...enabled, [s.key]: v })} label={<span className="text-xs">{enabled[s.key] ? t("on") : t("off")}</span>} />}
              </div>
            </li>
          ))}
        </ul>
        <div className="mt-4 max-w-xs">
          <Field label={t("youtubeUnits")} hint={t("youtubeUnitsHint")}>
            <Input type="number" min={1} max={10000} dir="ltr" value={units} onChange={(e) => setUnits(e.target.value)} />
          </Field>
        </div>
      </Card>

      <Card>
        <SectionTitle icon="group">{t("byWorkspace")}</SectionTitle>
        {!initial.workspaces.length ? <p className="text-sm text-muted">{t("noUsage")}</p> : (
          <table className="w-full text-sm">
            <thead><tr className="text-start text-xs text-muted"><th className="py-2 text-start font-medium">{t("workspace")}</th><th className="text-start font-medium">{t("bySource")}</th><th className="text-end font-medium">{t("cost")}</th><th className="text-end font-medium">{t("billed")}</th></tr></thead>
            <tbody className="divide-y divide-line">
              {initial.workspaces.map((w) => (
                <tr key={w.id}>
                  <td className="py-2 font-medium">{w.name}</td>
                  <td className="text-xs text-text-2">{Object.entries(w.by_source).map(([k, v]) => `${label(k)} ${fmt.number(v.units)}`).join(" · ")}</td>
                  <td className="text-end tabular-nums" dir="ltr">${fmt.number(w.cost, 2)}</td>
                  <td className="text-end tabular-nums" dir="ltr">${fmt.number(w.price, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <div className="flex justify-end">
        <Button variant="primary" icon="save" loading={save.isPending} onClick={() => save.mutate()}>{ta("save")}</Button>
      </div>
    </div>
  );
}

function Tile({ icon, label, value, hint }: { icon: string; label: string; value: string; hint?: string }) {
  return (
    <div className="glass rounded-[18px] p-4">
      <div className="flex items-center gap-1.5 text-xs text-muted"><Icon name={icon} size={15} />{label}</div>
      <div className="mt-1.5 text-xl font-bold tabular-nums" dir="ltr">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-faint">{hint}</div>}
    </div>
  );
}
