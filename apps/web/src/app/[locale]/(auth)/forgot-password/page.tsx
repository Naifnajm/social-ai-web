"use client";
import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";
import { Button, Field, Input } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";

export default function ForgotPasswordPage() {
  const t = useTranslations("auth");
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    await api.post("/auth/password/forgot", { email }).catch(() => undefined);
    setBusy(false);
    setSent(true);
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-bold tracking-tight">{t("forgotTitle")}</h1>
        <p className="mt-1 text-sm text-muted">{t("forgotSubtitle")}</p>
      </div>
      {sent ? (
        <p className="rounded-xl bg-ok-bg px-3 py-2 text-sm text-ok">{t("forgotSent")}</p>
      ) : (
        <>
          <Field label={t("email")}>
            <Input type="email" dir="ltr" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Button type="submit" variant="primary" size="lg" loading={busy}>{t("sendLink")}</Button>
        </>
      )}
      <Link href="/login" className="text-center text-sm text-muted hover:text-text">{t("backToLogin")}</Link>
    </form>
  );
}
