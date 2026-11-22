"use client";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { type FormEvent, Suspense, useState } from "react";
import { PasswordStrength } from "@/components/account/password-strength";
import { Button, Field, Input, toast } from "@/components/ui";
import { useRouter } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { type Me, useSession } from "@/lib/session";

function ResetForm() {
  const t = useTranslations("auth");
  const ta = useTranslations("account");
  const token = useSearchParams().get("token") || "";
  const router = useRouter();
  const setMe = useSession((s) => s.setMe);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await api.post<{ me?: Me; two_factor_required?: boolean }>("/auth/password/reset", { token, password });
      if (data.me) {
        setMe(data.me);
        router.replace("/");
      } else {
        // two-step sign-in is on: the e-mail link alone does not sign in
        toast.success(ta("resetDone"));
        router.replace("/login");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <h1 className="text-xl font-bold tracking-tight">{t("resetTitle")}</h1>
      <Field label={t("newPassword")}>
        <Input type="password" dir="ltr" required minLength={8} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      <PasswordStrength value={password} />
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
