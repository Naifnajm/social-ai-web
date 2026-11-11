"use client";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { type ReactNode, useState } from "react";
import { Icon } from "@/components/icon";
import { Button, Card, EmptyState, Input, SectionTitle, Select, Spinner, cx } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { type AdminRow, StatusBadge } from "@/components/billing/admin-ui";
import { formatDate, formatMoney } from "@/lib/billing";

type Page = { items: AdminRow[]; total: number; page: number; page_size: number };
type Stats = {
  workspaces_total: number; workspaces_active: number; workspaces_suspended: number; users_total: number; signups_7d: number;
  signups_30d: number; signups_by_day: { day: string; count: number }[]; paying: number; trialing: number; past_due: number;
  mrr_usd: number; arr_usd: number; by_plan: Record<string, number>;
};

const PLANS = ["trial", "free", "starter", "pro", "business", "enterprise"];
const STATUSES = ["trialing", "active", "past_due", "canceled", "suspended"];

function Tile({ icon, label, value, hint }: { icon: string; label: string; value: string; hint?: ReactNode }) {
  return (
    <Card className="!p-4">
      <div className="flex items-center gap-2 text-[13px] text-text-2"><Icon name={icon} size={16} /> {label}</div>
      <div className="mt-2 text-2xl font-bold tracking-tight" dir="ltr">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </Card>
  );
}

function SignupsChart({ data }: { data: Stats["signups_by_day"] }) {
  const locale = useLocale();
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...data.map((d) => d.count));
  const label = (d: { day: string; count: number }) => `${formatDate(d.day, locale)} · ${d.count}`;
  return (
    <div className="relative">
      <div className="flex h-36 items-end gap-[2px]" dir="ltr" onMouseLeave={() => setHover(null)}>
        {data.map((d, i) => (
          <button key={d.day} type="button" aria-label={label(d)} onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)}
            className="group flex h-full flex-1 items-end focus:outline-none">
            <span className={cx("block w-full rounded-t-[4px] transition", hover === i ? "bg-ink" : "bg-ink/70")}
              style={{ height: `${d.count ? Math.max((d.count / max) * 100, 4) : 0}%` }} />
          </button>
        ))}
      </div>
      <div className="mt-1 h-px bg-line" />
      <div className="mt-1.5 flex justify-between text-[11px] text-muted" dir="ltr">
        <bdi>{formatDate(data[0]?.day, locale)}</bdi>
        <bdi>{formatDate(data[data.length - 1]?.day, locale)}</bdi>
      </div>
      {hover != null && (
        <div className="glass-strong pointer-events-none absolute -top-2 rounded-lg px-2 py-1 text-xs font-medium"
          style={{ left: `${((hover + 0.5) / data.length) * 100}%`, transform: "translate(-50%, -100%)" }}>
          <bdi>{label(data[hover])}</bdi>
        </div>
      )}
    </div>
  );
}

export default function AdminOverviewPage() {
  const t = useTranslations("admin");
  const tb = useTranslations("billing");
  const locale = useLocale();
  const [filters, setFilters] = useState({ q: "", plan: "", status: "", page: 1 });
  const stats = useQuery({ queryKey: ["admin-stats"], queryFn: () => api.get<Stats>("/admin/stats") });
  const list = useQuery({
    queryKey: ["admin-workspaces", filters],
    queryFn: () => api.get<Page>("/admin/workspaces", { ...filters, page_size: 25 }),
    placeholderData: keepPreviousData,
  });
  const s = stats.data;
  const num = (v: number) => v.toLocaleString(locale === "ar" ? "ar-SA-u-nu-latn" : "en-US");
  const set = (patch: Partial<typeof filters>) => setFilters({ ...filters, page: 1, ...patch });

  return (
    <div className="flex flex-col gap-4">
      {s ? (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Tile icon="payments" label={t("stats.mrr")} value={formatMoney(s.mrr_usd, "USD", "en")} hint={t("stats.arr", { value: formatMoney(s.arr_usd, "USD", "en") })} />
            <Tile icon="verified" label={t("stats.paying")} value={num(s.paying)} hint={`${t("stats.pastDue")}: ${num(s.past_due)}`} />
            <Tile icon="rocket_launch" label={t("stats.trialing")} value={num(s.trialing)} hint={t("stats.users", { n: num(s.users_total) })} />
            <Tile icon="apps" label={t("stats.active")} value={num(s.workspaces_active)}
              hint={<><bdi>{t("stats.ofTotal", { total: num(s.workspaces_total) })}</bdi> · <bdi>{t("stats.suspended", { n: num(s.workspaces_suspended) })}</bdi></>} />
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
            <Card>
              <SectionTitle icon="trending_up" actions={<span className="text-xs text-muted">{t("stats.last7", { n: num(s.signups_7d) })}</span>}>
                {t("stats.signupsChart")} · {num(s.signups_30d)}
              </SectionTitle>
              <SignupsChart data={s.signups_by_day} />
            </Card>
            <Card>
              <SectionTitle icon="view_list">{t("stats.byPlan")}</SectionTitle>
              <ul className="flex flex-col gap-2.5">
                {PLANS.map((p) => {
                  const count = s.by_plan[p] || 0;
                  return (
                    <li key={p} className="text-sm">
                      <div className="flex justify-between"><span>{tb(`plans.${p}`)}</span><span className="font-semibold" dir="ltr">{num(count)}</span></div>
                      <div className="mt-1 h-1.5 rounded-full bg-track">
                        <div className="h-full rounded-full bg-ink" style={{ width: `${s.workspaces_total ? (count / s.workspaces_total) * 100 : 0}%` }} />
                      </div>
                    </li>
                  );
                })}
              </ul>
            </Card>
          </div>
        </>
      ) : (
        <div className="flex justify-center py-10"><Spinner size={26} /></div>
      )}

      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 p-4">
          <div className="relative min-w-[220px] flex-1">
            <Icon name="search" size={16} className="absolute start-3 top-1/2 -translate-y-1/2 text-muted" />
            <Input className="ps-9" placeholder={t("search")} value={filters.q} onChange={(e) => set({ q: e.target.value })} />
          </div>
          <Select className="!w-40" value={filters.plan} onChange={(e) => set({ plan: e.target.value })}>
            <option value="">{t("allPlans")}</option>
            {PLANS.map((p) => <option key={p} value={p}>{tb(`plans.${p}`)}</option>)}
          </Select>
          <Select className="!w-40" value={filters.status} onChange={(e) => set({ status: e.target.value })}>
            <option value="">{t("allStatuses")}</option>
            {STATUSES.map((st) => <option key={st} value={st}>{t(`statuses.${st}`)}</option>)}
          </Select>
        </div>
        {!list.data ? <div className="flex justify-center py-10"><Spinner /></div> : !list.data.items.length ? (
          <EmptyState icon="search" title={t("empty")} />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead>
                  <tr className="border-y border-line text-start text-xs text-muted">
                    <th className="px-4 py-2 text-start font-medium">{t("cols.workspace")}</th>
                    <th className="px-4 py-2 text-start font-medium">{t("cols.plan")}</th>
                    <th className="px-4 py-2 text-start font-medium">{t("cols.status")}</th>
                    <th className="px-4 py-2 text-start font-medium">{t("cols.owner")}</th>
                    <th className="px-4 py-2 text-start font-medium">{t("cols.usage")}</th>
                    <th className="px-4 py-2 text-start font-medium">{t("cols.created")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {list.data.items.map((row) => (
                    <tr key={row.id} className="hover:bg-fill">
                      <td className="px-4 py-3">
                        <Link href={`/admin/workspaces/${row.id}`} className="font-semibold hover:underline">{row.name}</Link>
                        <div className="text-xs text-muted" dir="ltr">#{row.id} · {row.slug}</div>
                      </td>
                      <td className="px-4 py-3">{tb(`plans.${row.plan}`)}{row.plan !== "trial" && row.interval === "year" && <span className="text-muted"> · {tb("yearly")}</span>}</td>
                      <td className="px-4 py-3"><StatusBadge row={row} /></td>
                      <td className="px-4 py-3 text-text-2" dir="ltr">{row.owner_email}</td>
                      <td className="px-4 py-3 text-text-2" dir="ltr">{row.social_accounts} · {row.members} · {row.posts_month}</td>
                      <td className="px-4 py-3 text-text-2">{formatDate(row.created_at, locale)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center gap-2 border-t border-line px-4 py-3 text-xs text-muted">
              <span>{t("pageOf", { from: (list.data.page - 1) * list.data.page_size + 1, to: Math.min(list.data.page * list.data.page_size, list.data.total), total: list.data.total })}</span>
              <div className="ms-auto flex gap-2">
                <Button size="sm" disabled={filters.page <= 1} onClick={() => setFilters({ ...filters, page: filters.page - 1 })}>{t("prev")}</Button>
                <Button size="sm" disabled={list.data.page * list.data.page_size >= list.data.total} onClick={() => setFilters({ ...filters, page: filters.page + 1 })}>{t("next")}</Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
