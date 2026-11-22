"use client";
/** Platform admin › Users: every account on the platform with search, filters, sorting and CSV export. Each row
 *  opens the user's page (all their workspaces, keys, activity and every action). */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { type AdminUser, UserBadges } from "@/components/account/admin-user";
import { Icon } from "@/components/icon";
import { Button, Card, EmptyState, Field, Input, Select, Spinner, toast } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { formatDate } from "@/lib/billing";
import { downloadBlob } from "@/lib/download";

type Page = { items: AdminUser[]; total: number; page: number; page_size: number };

const PLANS = ["trial", "free", "starter", "pro", "business", "enterprise"];
const SORTS = ["-created", "created", "name", "email", "-last_login", "last_login"];
const EMPTY = { q: "", status: "", superadmin: "", verified: "", two_factor: "", plan: "", created_from: "", created_to: "", login_from: "", login_to: "", sort: "-created" };

export default function AdminUsersPage() {
  const t = useTranslations("adminUsers");
  const ta = useTranslations("admin");
  const tp = useTranslations("shell.plan");
  const locale = useLocale();
  const router = useRouter();
  const [filters, setFilters] = useState(EMPTY);
  const [more, setMore] = useState(false);
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const set = (key: keyof typeof EMPTY, value: string) => { setFilters({ ...filters, [key]: value }); setPage(1); };
  const users = useQuery({ queryKey: ["admin-users", filters, page], queryFn: () => api.get<Page>("/admin/users", { ...filters, page }), placeholderData: keepPreviousData });
  const data = users.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const active = Object.entries(filters).some(([k, v]) => k !== "sort" && v);
  const csv = async () => {
    setExporting(true);
    try {
      downloadBlob(await api.get<Blob>("/admin/users/export.csv", filters), `users-${new Date().toISOString().slice(0, 10)}.csv`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : String(err));
    } finally {
      setExporting(false);
    }
  };
  const select = (key: keyof typeof EMPTY, label: string, options: [string, string][]) => (
    <Field label={label} className="min-w-[140px]">
      <Select value={filters[key]} onChange={(e) => set(key, e.target.value)}>
        {options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </Select>
    </Field>
  );

  return (
    <Card>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label={t("searchLabel")} className="min-w-[220px] flex-1">
          <Input placeholder={t("search")} value={filters.q} onChange={(e) => set("q", e.target.value)} />
        </Field>
        {select("status", t("filters.status"), [["", t("filters.all")], ["active", t("filters.active")], ["disabled", t("filters.disabled")], ["deleted", t("filters.deleted")], ["must_change", t("filters.must_change")]])}
        {select("superadmin", t("filters.role"), [["", t("filters.anyRole")], ["true", t("filters.superadmins")], ["false", t("filters.regular")]])}
        {select("plan", t("filters.plan"), [["", t("filters.anyPlan")], ...PLANS.map((p) => [p, tp(p)] as [string, string])])}
        {select("sort", t("filters.sort"), SORTS.map((s) => [s, t(`sorts.${s.replace("-", "desc_")}`)] as [string, string]))}
        <Button icon="filter_list" variant="ghost" onClick={() => setMore(!more)}>{t("filters.more")}</Button>
        <Button icon="download" loading={exporting} onClick={csv}>{t("csv")}</Button>
      </div>
      {more && (
        <div className="mb-4 flex flex-wrap items-end gap-3 rounded-2xl bg-fill-2 p-3">
          {select("verified", t("filters.verified"), [["", t("filters.anyVerified")], ["true", t("filters.verifiedYes")], ["false", t("filters.verifiedNo")]])}
          {select("two_factor", t("filters.twoFactor"), [["", t("filters.anyVerified")], ["true", t("filters.on")], ["false", t("filters.off")]])}
          <Field label={`${t("filters.created")} · ${t("filters.from")}`}><Input type="date" value={filters.created_from} onChange={(e) => set("created_from", e.target.value)} /></Field>
          <Field label={t("filters.to")}><Input type="date" value={filters.created_to} onChange={(e) => set("created_to", e.target.value)} /></Field>
          <Field label={`${t("filters.lastLogin")} · ${t("filters.from")}`}><Input type="date" value={filters.login_from} onChange={(e) => set("login_from", e.target.value)} /></Field>
          <Field label={t("filters.to")}><Input type="date" value={filters.login_to} onChange={(e) => set("login_to", e.target.value)} /></Field>
        </div>
      )}
      <div className="mb-3 flex items-center gap-3 text-sm text-muted">
        {data && <span>{t("total", { n: data.total })}</span>}
        {active && <button className="font-medium text-text-2 hover:text-text" onClick={() => { setFilters(EMPTY); setPage(1); }}>{t("filters.clear")}</button>}
      </div>
      {users.isLoading ? <div className="flex justify-center py-12"><Spinner /></div>
        : !data?.items.length ? <EmptyState icon="group" title={t("empty")} />
          : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-sm">
                <thead className="text-xs text-muted">
                  <tr className="border-b border-line">
                    <th className="py-2 text-start font-medium">{t("cols.user")}</th>
                    <th className="py-2 text-start font-medium">{t("cols.workspaces")}</th>
                    <th className="py-2 text-start font-medium">{t("cols.created")}</th>
                    <th className="py-2 text-start font-medium">{t("cols.lastLogin")}</th>
                    <th className="py-2 text-start font-medium">{t("cols.state")}</th>
                    <th className="py-2" />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((u) => (
                    <tr key={u.id} className="cursor-pointer border-b border-line/60 align-top hover:bg-fill-2/60" onClick={() => router.push(`/admin/users/${u.id}`)}>
                      <td className="py-3 pe-3">
                        <div className="font-semibold">{u.name}</div>
                        <div className="text-xs text-muted" dir="ltr">{u.email}{u.username ? ` · @${u.username}` : ""}</div>
                      </td>
                      <td className="py-3 pe-3 text-text-2">
                        {u.workspaces.join(locale === "ar" ? "، " : ", ") || "—"}
                        {!!u.plans.length && <div className="text-xs text-muted">{u.plans.map((p) => (tp.has(p) ? tp(p) : p)).join(" · ")}</div>}
                      </td>
                      <td className="py-3 pe-3 text-text-2">{formatDate(u.created_at, locale)}</td>
                      <td className="py-3 pe-3 text-text-2">{u.last_login_at ? formatDate(u.last_login_at, locale) : t("never")}</td>
                      <td className="py-3 pe-3"><UserBadges user={u} /></td>
                      <td className="py-3 text-end">
                        <Link href={`/admin/users/${u.id}`} onClick={(e) => e.stopPropagation()} className="inline-flex items-center gap-1 text-sm font-medium text-text-2 hover:text-text">
                          {t("open")} <Icon name="chevron_right" size={16} className="rtl:rotate-180" />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      {pages > 1 && (
        <div className="mt-4 flex items-center justify-between text-sm">
          <Button size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>{ta("prev")}</Button>
          <span className="text-muted">{t("pageOf", { page, pages })}</span>
          <Button size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>{ta("next")}</Button>
        </div>
      )}
    </Card>
  );
}
