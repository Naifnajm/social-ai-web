"use client";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { Badge, Button, Card, EmptyState, Input, Spinner, toast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatDate } from "@/lib/billing";
import { useSession } from "@/lib/session";

type AdminUser = {
  id: number; name: string; email: string; username: string | null; is_active: boolean; is_superadmin: boolean;
  last_login_at: string | null; created_at: string; workspaces: string[];
};
type Page = { items: AdminUser[]; total: number; page: number; page_size: number };

/** Every account on the platform: search, disable or enable, and grant platform administrator rights. */
export default function AdminUsersPage() {
  const t = useTranslations("admin");
  const locale = useLocale();
  const me = useSession((s) => s.me);
  const client = useQueryClient();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const users = useQuery({ queryKey: ["admin-users", q, page], queryFn: () => api.get<Page>("/admin/users", { q, page }), placeholderData: keepPreviousData });
  const change = useMutation({
    mutationFn: (v: { id: number; what: "active" | "superadmin"; value: boolean }) => api.post<AdminUser>(`/admin/users/${v.id}/${v.what}`, { value: v.value }),
    onSuccess: () => { client.invalidateQueries({ queryKey: ["admin-users"] }); toast.success(t("done")); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : String(e)),
  });
  const data = users.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  return (
    <Card>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Input className="max-w-sm" placeholder={t("users.search")} value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        {data && <span className="text-sm text-muted">{t("users.total", { n: data.total })}</span>}
      </div>
      {users.isLoading ? <div className="flex justify-center py-12"><Spinner /></div>
        : !data?.items.length ? <EmptyState icon="group" title={t("users.empty")} />
          : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead className="text-start text-xs text-muted">
                  <tr className="border-b border-line">
                    <th className="py-2 text-start font-medium">{t("users.user")}</th>
                    <th className="py-2 text-start font-medium">{t("users.workspaces")}</th>
                    <th className="py-2 text-start font-medium">{t("lastLogin")}</th>
                    <th className="py-2 text-start font-medium">{t("users.state")}</th>
                    <th className="py-2" />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((u) => (
                    <tr key={u.id} className="border-b border-line/60 align-top">
                      <td className="py-3">
                        <div className="font-semibold">{u.name}</div>
                        <div className="text-xs text-muted" dir="ltr">{u.email}{u.username ? ` · @${u.username}` : ""}</div>
                      </td>
                      <td className="py-3 text-text-2">{u.workspaces.join("، ") || "—"}</td>
                      <td className="py-3 text-text-2">{u.last_login_at ? formatDate(u.last_login_at, locale) : t("never")}</td>
                      <td className="py-3">
                        <div className="flex flex-wrap gap-1.5">
                          <Badge tone={u.is_active ? "ok" : "bad"}>{u.is_active ? t("users.active") : t("users.disabled")}</Badge>
                          {u.is_superadmin && <Badge tone="ink">{t("users.admin")}</Badge>}
                        </div>
                      </td>
                      <td className="py-3">
                        {u.id !== me?.user.id && (
                          <div className="flex flex-wrap justify-end gap-2">
                            <Button size="sm" loading={change.isPending} onClick={() => change.mutate({ id: u.id, what: "active", value: !u.is_active })}>
                              {u.is_active ? t("users.disable") : t("users.enable")}
                            </Button>
                            <Button size="sm" loading={change.isPending} onClick={() => change.mutate({ id: u.id, what: "superadmin", value: !u.is_superadmin })}>
                              {u.is_superadmin ? t("users.revokeAdmin") : t("users.makeAdmin")}
                            </Button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      {pages > 1 && (
        <div className="mt-4 flex items-center justify-between text-sm">
          <Button size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t("prev")}</Button>
          <span className="text-muted">{t("pageOf", { page, pages })}</span>
          <Button size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>{t("next")}</Button>
        </div>
      )}
    </Card>
  );
}
