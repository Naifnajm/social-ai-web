"use client";
import { useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { type FormEvent, Suspense, useState } from "react";
import { Button, Field, Input } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { type Me, useSession } from "@/lib/session";

function SignupForm() {
  const t = useTranslations("auth");
  const locale = useLocale();
  const router = useRouter();
  const params = useSearchParams();
  const invitation = params.get("invitation");
  const setMe = useSession((s) => s.setMe);
  const refreshWorkspace = useSession((s) => s.refreshWorkspace);
  const [form, setForm] = useState({ name: "", email: params.get("email") || "", password: "", workspace_name: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await api.post<{ me: Me }>("/auth/signup", {
        ...form, workspace_name: form.workspace_name || form.name, locale, invitation_token: invitation,
      });
      setMe(data.me);
      await refreshWorkspace();
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-bold tracking-tight">{t("signupTitle")}</h1>
        <p className="mt-1 text-sm text-muted">{t("signupSubtitle")}</p>
      </div>
      <Field label={t("name")}>
        <Input autoComplete="name" required value={form.name} onChange={set("name")} />
      </Field>
      {!invitation && (
        <Field label={t("company")} hint={t("companyHint")}>
          <Input required value={form.workspace_name} onChange={set("workspace_name")} />
        </Field>
      )}
      <Field label={t("email")}>
        <Input type="email" autoComplete="email" dir="ltr" required value={form.email} onChange={set("email")} />
      </Field>
      <Field label={t("password")} hint={t("passwordHint")}>
        <Input type="password" autoComplete="new-password" dir="ltr" required minLength={8} value={form.password} onChange={set("password")} />
      </Field>
      {error && <p className="rounded-xl bg-bad-bg px-3 py-2 text-sm text-bad">{error}</p>}
      <Button type="submit" variant="primary" size="lg" loading={busy}>{t("signup")}</Button>
      <p className="text-center text-sm text-muted">
        {t("haveAccount")} <Link href="/login" className="font-semibold text-text">{t("login")}</Link>
      </p>
    </form>
  );
}

export default function SignupPage() {
  return (
    <Suspense>
      <SignupForm />
    </Suspense>
  );
}
