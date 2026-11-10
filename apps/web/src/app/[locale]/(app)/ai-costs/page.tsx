"use client";
/** AI costs: spending of the workspace's AI providers by day, provider, model and task type, budgets and the
 * detailed log of every AI call (admins). */
import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { Icon } from "@/components/icon";
import { WalletChip } from "@/components/model-picker";
import { Button, Card, EmptyState, PageHeader, SectionTitle, Segmented, Select, Spinner, cx } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { CAPABILITY_ICONS, type Capability, type Wallet, count, money } from "@/lib/ai";
import { useSession } from "@/lib/session";

type CostRow = { key: string; label: string; cost: number; calls: number };
type Summary = {
  date_from: string; date_to: string; total_cost: number; total_calls: number; month_cost: number;
  by_provider: CostRow[]; by_model: CostRow[]; by_capability: CostRow[]; by_day: { day: string; cost: number; calls: number }[];
  by_month: CostRow[]; budgets: { provider_id: number; provider: string; spent_month: number; monthly_budget?: number | null; wallet: Wallet }[];
};
type Usage = {
  id: number; created_at: string; provider?: string | null; model_name?: string | null; capability: Capability;
  tokens_in: number; tokens_out: number; units: number; cost: number; purpose?: string | null; user_name?: string | null;
};

const PAGE = 25;

function isoDaysAgo(days: number) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

function Stat({ icon, label, value, hint }: { icon: string; label: string; value: string; hint?: string }) {
  return (
    <Card className="!p-4">
      <div className="flex items-center gap-2 text-[13px] text-muted"><Icon name={icon} size={16} /> {label}</div>
      <div className="mt-1.5 text-2xl font-bold tracking-tight tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </Card>
  );
}

function DailyChart({ days, locale }: { days: Summary["by_day"]; locale: string }) {
  const t = useTranslations("ai.costs");
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...days.map((d) => d.cost), 0);
  const fmtDay = (iso: string, long = false) => new Date(`${iso}T12:00:00`).toLocaleDateString(locale === "ar" ? "ar-SA-u-nu-latn" : "en-GB",
    long ? { weekday: "short", day: "numeric", month: "short" } : { day: "numeric", month: "short" });
  const ticks = [0, Math.floor((days.length - 1) / 2), days.length - 1];
  const active = hover !== null ? days[hover] : null;
  return (
    <div>
      <div className="mb-2 flex h-9 items-end justify-between gap-2 text-xs text-muted">
        {active ? (
          <span className="glass-strong rounded-xl px-3 py-1.5 text-text">
            <b>{fmtDay(active.day, true)}</b> · <span dir="ltr">{money(active.cost, true)}</span> · {t("calls", { count: active.calls })}
          </span>
        ) : <span>{t("hoverHint")}</span>}
        <span dir="ltr">{t("max")} {money(max, true)}</span>
      </div>
      <div className="relative h-44 border-b border-line" onMouseLeave={() => setHover(null)}>
        <div className="pointer-events-none absolute inset-x-0 top-1/2 border-t border-dashed border-line" />
        <div className="absolute inset-0 flex items-end gap-[2px]" dir="ltr">
          {days.map((d, i) => (
            <button key={d.day} type="button" aria-label={`${d.day}: ${money(d.cost, true)}`} onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)}
              onClick={() => setHover(i)} className="group flex h-full min-w-0 flex-1 items-end">
              <span className={cx("w-full rounded-t-[4px] transition-colors", d.cost ? (hover === i ? "bg-ink" : "bg-ink/75 group-hover:bg-ink") : "bg-track")}
                style={{ height: d.cost && max ? `${Math.max((d.cost / max) * 100, 2)}%` : "2px" }} />
            </button>
          ))}
        </div>
      </div>
      <div className="mt-1.5 flex justify-between text-[11px] text-muted" dir="ltr">
        {ticks.map((i) => days[i] && <span key={i}>{fmtDay(days[i].day)}</span>)}
      </div>
    </div>
  );
}

function Breakdown({ rows, icon, labelOf }: { rows: CostRow[]; icon?: (row: CostRow) => string; labelOf?: (row: CostRow) => string }) {
  const t = useTranslations("ai.costs");
  const total = rows.reduce((s, r) => s + r.cost, 0) || 1;
  if (!rows.length) return <p className="py-4 text-center text-sm text-muted">{t("nothing")}</p>;
  return (
    <ul className="flex flex-col gap-3">
      {rows.slice(0, 8).map((r) => (
        <li key={r.key}>
          <div className="mb-1 flex items-center gap-2 text-[13px]">
            {icon && <Icon name={icon(r)} size={15} className="text-muted" />}
            <span className="min-w-0 flex-1 truncate font-medium" dir="auto">{labelOf ? labelOf(r) : r.label}</span>
            <span className="text-xs text-muted">{t("calls", { count: r.calls })}</span>
            <span className="w-20 text-end font-semibold tabular-nums" dir="ltr">{money(r.cost, true)}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-track">
            <div className="h-full rounded-full bg-ink" style={{ width: `${Math.max((r.cost / total) * 100, r.cost ? 2 : 0)}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function AiCostsPage() {
  const t = useTranslations("ai.costs");
  const tc = useTranslations("ai.providers.caps");
  const locale = useLocale();
  const isAdmin = useSession((s) => s.can("admin"));
  const [range, setRange] = useState<7 | 30 | 90>(30);
  const [capability, setCapability] = useState("");
  const [page, setPage] = useState(0);
  const dateFrom = isoDaysAgo(range - 1);
  const summary = useQuery({
    queryKey: ["ai", "usage-summary", range],
    queryFn: () => api.get<Summary>("/ai/usage/summary", { date_from: dateFrom }),
    enabled: isAdmin,
  });
  const usage = useQuery({
    queryKey: ["ai", "usage", range, capability, page],
    queryFn: () => api.get<{ items: Usage[]; total: number }>("/ai/usage", { date_from: dateFrom, capability, limit: PAGE, offset: page * PAGE }),
    enabled: isAdmin,
    placeholderData: (prev) => prev,
  });

  if (!isAdmin) return <div className="pt-2"><Card><EmptyState icon="lock" title={t("adminOnly")} /></Card></div>;
  const s = summary.data;
  const capLabel = (r: CostRow) => (tc.has(r.key) ? tc(r.key) : r.key);
  const fmtTime = (iso: string) => new Date(iso).toLocaleString(locale === "ar" ? "ar-SA-u-nu-latn" : "en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

  return (
    <div className="pt-2">
      <PageHeader icon="payments" title={t("title")} subtitle={t("subtitle")} />
      <Segmented className="-mt-2 mb-4" value={range} onChange={(v) => { setRange(v); setPage(0); }}
        options={([7, 30, 90] as const).map((d) => ({ value: d, label: t("days", { count: d }) }))} />
      {summary.isLoading || !s ? <div className="py-16 text-center"><Spinner /></div> : (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat icon="calendar_today" label={t("thisMonth")} value={money(s.month_cost)} />
            <Stat icon="payments" label={t("period")} value={money(s.total_cost)} hint={t("days", { count: range })} />
            <Stat icon="bolt" label={t("callsLabel")} value={count(s.total_calls)} />
            <Stat icon="percent" label={t("average")} value={money(s.total_calls ? s.total_cost / s.total_calls : 0, true)} />
          </div>

          <Card>
            <SectionTitle icon="bar_chart">{t("perDay")}</SectionTitle>
            {s.total_calls ? <DailyChart days={s.by_day} locale={locale} /> : (
              <EmptyState icon="payments" title={t("emptyTitle")} text={t("emptyText")}
                action={<Link href="/settings/ai"><Button icon="smart_toy">{t("providersLink")}</Button></Link>} />
            )}
          </Card>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card><SectionTitle icon="smart_toy">{t("byProvider")}</SectionTitle><Breakdown rows={s.by_provider} /></Card>
            <Card><SectionTitle icon="account_tree">{t("byModel")}</SectionTitle><Breakdown rows={s.by_model} /></Card>
            <Card><SectionTitle icon="apps">{t("byType")}</SectionTitle>
              <Breakdown rows={s.by_capability} labelOf={capLabel} icon={(r) => CAPABILITY_ICONS[r.key as Capability] ?? "auto_awesome"} />
            </Card>
          </div>

          {!!s.budgets.length && (
            <Card>
              <SectionTitle icon="account_balance" actions={<Link href="/settings/ai" className="text-[13px] font-medium text-text-2 hover:text-text">{t("manage")}</Link>}>{t("budgets")}</SectionTitle>
              <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {s.budgets.map((b) => {
                  const pct = b.monthly_budget ? Math.min((b.spent_month / b.monthly_budget) * 100, 100) : 0;
                  return (
                    <li key={b.provider_id} className="rounded-2xl bg-white/55 p-3 ring-1 ring-line">
                      <div className="flex items-center gap-2">
                        <span className="min-w-0 flex-1 truncate text-sm font-semibold">{b.provider}</span>
                        <span className="text-sm font-semibold tabular-nums" dir="ltr">{money(b.spent_month)}</span>
                      </div>
                      {b.monthly_budget ? (
                        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-track">
                          <div className={cx("h-full rounded-full", pct >= 100 ? "bg-bad" : pct >= 85 ? "bg-warn" : "bg-ink")} style={{ width: `${pct}%` }} />
                        </div>
                      ) : null}
                      <div className="mt-2"><WalletChip wallet={b.wallet} /></div>
                    </li>
                  );
                })}
              </ul>
            </Card>
          )}

          <Card>
            <SectionTitle icon="history" actions={
              <Select value={capability} onChange={(e) => { setCapability(e.target.value); setPage(0); }} className="!h-8 !w-auto text-[13px]">
                <option value="">{t("allTypes")}</option>
                {(["text", "image", "video", "audio", "stt"] as Capability[]).map((c) => <option key={c} value={c}>{tc(c)}</option>)}
              </Select>
            }>{t("log")}</SectionTitle>
            <div className="-mx-5 overflow-x-auto px-5">
              <table className="w-full min-w-[640px] text-[13px]">
                <thead className="text-xs text-muted">
                  <tr className="border-b border-line">
                    <th className="py-2 text-start font-medium">{t("when")}</th>
                    <th className="py-2 text-start font-medium">{t("what")}</th>
                    <th className="py-2 text-start font-medium">{t("model")}</th>
                    <th className="py-2 text-start font-medium">{t("who")}</th>
                    <th className="py-2 text-end font-medium">{t("cost")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {usage.data?.items.map((u) => (
                    <tr key={u.id}>
                      <td className="whitespace-nowrap py-2.5 text-muted">{fmtTime(u.created_at)}</td>
                      <td className="max-w-[260px] py-2.5">
                        <div className="flex items-center gap-1.5">
                          <Icon name={CAPABILITY_ICONS[u.capability] ?? "auto_awesome"} size={15} className="shrink-0 text-muted" />
                          <span className="bidi truncate">{u.purpose || tc(u.capability)}</span>
                        </div>
                      </td>
                      <td className="py-2.5">
                        <div className="truncate"><bdi>{u.model_name || "—"}</bdi></div>
                        <div className="text-[11px] text-muted">
                          {u.provider}{u.tokens_in || u.tokens_out ? <span dir="ltr"> · {count(u.tokens_in)} / {count(u.tokens_out)} tok</span> : null}
                        </div>
                      </td>
                      <td className="py-2.5 text-muted">{u.user_name || "—"}</td>
                      <td className="py-2.5 text-end font-semibold tabular-nums" dir="ltr">{money(u.cost, true)}</td>
                    </tr>
                  ))}
                  {!usage.data?.items.length && <tr><td colSpan={5} className="py-8 text-center text-muted">{t("nothing")}</td></tr>}
                </tbody>
              </table>
            </div>
            {(usage.data?.total ?? 0) > PAGE && (
              <div className="mt-3 flex items-center justify-end gap-2 text-xs text-muted">
                <span>{t("pageOf", { from: page * PAGE + 1, to: Math.min((page + 1) * PAGE, usage.data!.total), total: usage.data!.total })}</span>
                <Button size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>{t("prev")}</Button>
                <Button size="sm" disabled={(page + 1) * PAGE >= (usage.data?.total ?? 0)} onClick={() => setPage(page + 1)}>{t("next")}</Button>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
