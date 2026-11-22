"use client";
/** Account center › Your data: download everything as JSON (GDPR) and delete the account. */
import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { Icon } from "@/components/icon";
import { Button, Card, Field, Input, SectionTitle, toast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { downloadJson } from "@/lib/download";
import { useSession } from "@/lib/session";

type Blocker = { workspace_id: number; workspace_name: string; other_members: number; action: "transfer" | "delete" };

export default function AccountDataPage() {
  const t = useTranslations("account.data");
  const locale = useLocale();
  const me = useSession((s) => s.me);
  const check = useQuery({ queryKey: ["account-delete-check"], queryFn: () => api.get<{ workspaces: Blocker[]; is_superadmin: boolean }>("/account/delete-check") });
  const [form, setForm] = useState({ password: "", confirm_email: "", code: "" });
  const [busy, setBusy] = useState("");
  if (!me) return null;
  const blockers = check.data?.workspaces ?? [];
  const blocked = blockers.some((b) => b.action === "transfer");
  const exportData = async () => {
    setBusy("export");
    try {
      downloadJson(await api.get("/account/export"), `account-${me.user.id}.json`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };
  const remove = async () => {
    setBusy("delete");
    try {
      await api.post("/account/delete", { ...form, code: form.code || null, delete_workspaces: blockers.filter((b) => b.action === "delete").map((b) => b.workspace_id) });
      toast.success(t("deleted"));
      window.location.href = `/${locale}/welcome`;
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : String(err));
      setBusy("");
    }
  };
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <SectionTitle icon="download">{t("exportTitle")}</SectionTitle>
        <p className="mb-4 text-sm text-muted">{t("exportText")}</p>
        <Button icon="download" loading={busy === "export"} onClick={exportData}>{t("export")}</Button>
      </Card>
      <Card className="ring-1 ring-bad/30">
        <SectionTitle icon="warning">{t("deleteTitle")}</SectionTitle>
        <p className="mb-4 text-sm text-text-2">{t("deleteText")}</p>
        {!!blockers.length && (
          <div className="mb-4 rounded-2xl bg-warn-bg p-3 text-sm">
            <div className="mb-1 font-semibold">{t("blockers")}</div>
            <ul className="flex flex-col gap-1">
              {blockers.map((b) => (
                <li key={b.workspace_id} className="flex gap-2"><Icon name={b.action === "transfer" ? "swap_horiz" : "delete"} size={16} className="mt-0.5 shrink-0" />
                  {b.action === "transfer" ? t("transfer", { name: b.workspace_name }) : t("deleteWs", { name: b.workspace_name })}</li>
              ))}
            </ul>
          </div>
        )}
        {check.data?.is_superadmin && <p className="mb-4 text-sm text-warn">{t("superadmin")}</p>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("password")}><Input type="password" dir="ltr" autoComplete="current-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
          <Field label={t("typeEmail", { email: me.user.email })}><Input dir="ltr" autoComplete="off" value={form.confirm_email} onChange={(e) => setForm({ ...form, confirm_email: e.target.value })} /></Field>
          {me.user.totp_enabled && <Field label={t("code")}><Input dir="ltr" inputMode="numeric" autoComplete="one-time-code" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} /></Field>}
        </div>
        <div className="mt-4 flex justify-end">
          <Button variant="danger" icon="delete" loading={busy === "delete"}
            disabled={blocked || !form.password || form.confirm_email.trim().toLowerCase() !== me.user.email.toLowerCase()} onClick={remove}>{t("delete")}</Button>
        </div>
      </Card>
    </div>
  );
}
