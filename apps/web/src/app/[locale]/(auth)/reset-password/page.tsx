"use client";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { type FormEvent, Suspense, useState } from "react";
import { TwoStepForm, type TwoStep, isTwoStep } from "@/components/auth/two-step-form";
import { Button, Field, Input } from "@/components/ui";
import { useRouter } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { type Me, useSession } from "@/lib/session";

function ResetForm() {
  const t = useTranslations("auth");
  const token = useSearchParams().get("token") || "";
  const router = useRouter();
  const setMe = useSession((s) => s.setMe);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState<TwoStep | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await api.post<{ me: Me } | TwoStep>("/auth/password/reset", { token, password });
      if (isTwoStep(data)) { setStep(data); return; } // the new password is saved; the phone still decides
      setMe(data.me);
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error"));
    } finally {
      setBusy(false);
    }
  };

  if (step) return <TwoStepForm challenge={step.challenge} onDone={(me) => { setMe(me); router.replace("/"); }} onBack={() => router.replace("/login")} />;

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <h1 className="text-xl font-bold tracking-tight">{t("resetTitle")}</h1>
      <Field label={t("newPassword")} hint={t("passwordHint")}>
        <Input type="password" dir="ltr" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      {error && <p className="rounded-xl bg-bad-bg px-3 py-2 text-sm text-bad">{error}</p>}
      <Button type="submit" variant="primary" size="lg" loading={busy}>{t("savePassword")}</Button>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense>
      <ResetForm />
    </Suspense>
  );
}
