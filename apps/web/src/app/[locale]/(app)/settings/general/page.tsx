"use client";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button, Card, Field, Input, Select, toast } from "@/components/ui";
import { LOCALE_NAMES, routing } from "@/i18n/routing";
import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";

const TIMEZONES = ["Asia/Riyadh", "Asia/Dubai", "Asia/Kuwait", "Asia/Qatar", "Asia/Bahrain", "Africa/Cairo", "Asia/Amman", "Europe/Amsterdam", "Europe/London", "UTC"];
const CURRENCIES = ["SAR", "AED", "KWD", "QAR", "BHD", "OMR", "EGP", "JOD", "USD", "EUR"];

export default function GeneralSettingsPage() {
  const t = useTranslations("settings");
  const { workspace, refreshWorkspace } = useSession();
  // the app shell renders pages only once the workspace is loaded
  const [form, setForm] = useState(() => ({
    name: workspace?.name ?? "", locale: workspace?.locale ?? "ar",
    timezone: workspace?.timezone ?? "Asia/Riyadh", currency: workspace?.currency ?? "SAR",
  }));
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      await api.patch("/workspace", form);
      await refreshWorkspace();
      toast.success(t("saved"));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("companyName")} className="sm:col-span-2">
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label={t("language")}>
          <Select value={form.locale} onChange={(e) => setForm({ ...form, locale: e.target.value })}>
            {routing.locales.map((code) => <option key={code} value={code}>{LOCALE_NAMES[code]}</option>)}
          </Select>
        </Field>
        <Field label={t("timezone")}>
          <Select value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} dir="ltr">
            {TIMEZONES.map((tz) => <option key={tz}>{tz}</option>)}
          </Select>
        </Field>
        <Field label={t("currency")}>
          <Select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })} dir="ltr">
            {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
          </Select>
        </Field>
      </div>
      <div className="mt-5 flex justify-end">
        <Button variant="primary" loading={busy} onClick={save}>{t("save")}</Button>
      </div>
    </Card>
  );
}
