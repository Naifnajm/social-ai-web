"use client";
/** Shown on every page while a platform administrator views the app as someone (support): who, until when, End. */
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Icon } from "../icon";
import { Button, toast } from "../ui";

export function ImpersonationBanner() {
  const t = useTranslations("account.impersonation");
  const locale = useLocale();
  const me = useSession((s) => s.me);
  const [busy, setBusy] = useState(false);
  if (!me?.impersonator) return null;
  const until = me.impersonator.expires_at
    ? new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(new Date(me.impersonator.expires_at))
    : null;
  const end = async () => {
    setBusy(true);
    const userId = me.user.id;
    const result = await api.post<{ restored: boolean }>("/auth/impersonation/end").catch(() => ({ restored: false }));
    toast.success(t("ended"));
    // a full reload: every cached query belonged to the person
    window.location.href = result.restored ? `/${locale}/admin/users/${userId}` : `/${locale}/login`;
  };
  return (
    <div role="status" className="sticky top-0 z-40 m-3 mb-0 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl bg-[#2b1a00] px-4 py-2.5 text-sm text-[#ffd79a] shadow-lg lg:ms-0">
      <Icon name="visibility" size={18} />
      <span className="font-semibold">{t("banner", { name: me.user.name, email: me.user.email })}</span>
      {until && <span className="opacity-80">{t("until", { time: until })}</span>}
      <span className="hidden text-xs opacity-70 xl:inline">{t("limits")}</span>
      <Button size="sm" className="ms-auto !bg-[#ffd79a] !text-[#2b1a00]" loading={busy} onClick={end}>{t("end")}</Button>
    </div>
  );
}
