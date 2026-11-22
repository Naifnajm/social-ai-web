"use client";
/** After an administrator set a temporary password: the person chooses their own before anything else. */
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { type FormEvent, Suspense, useEffect, useState } from "react";
import { PasswordStrength } from "@/components/account/password-strength";
import { Button, Field, Input, Spinner } from "@/components/ui";
import { useRouter } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { type Me, useSession } from "@/lib/session";

function ChangePasswordForm() {
  const t = useTranslations("account.changePassword");
  const ts = useTranslations("account.security");
  const next = useSearchParams().get("next") || "/";
  const router = useRouter();
  const { me, load, setMe, refreshWorkspace } = useSession();
  const [form, setForm] = useState({ current: "", password: "", repeat: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!me) load().then((result) => { if (!result) router.replace("/login"); });
  }, [me, load, router]);

  if (!me) return <div className="flex justify-center py-10"><Spinner /></div>;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (form.password !== form.repeat) return setError(ts("mismatch"));
    setBusy(true);
    setError("");
    try {
      const data = await api.post<{ me: Me }>("/auth/password", { current_password: form.current, new_password: form.password });
      setMe(data.me);
      await refreshWorkspace();
      router.replace(next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-bold tracking-tight">{t("title")}</h1>
        <p className="mt-1 text-sm text-muted">{me.user.must_change_password ? t("text") : t("textVoluntary")}</p>
        <p className="mt-2 text-sm font-medium" dir="ltr">{me.user.email}</p>
      </div>
      <Field label={me.user.must_change_password ? t("temporary") : ts("current")}>
        <Input type="password" dir="ltr" required autoComplete="current-password" value={form.current} onChange={(e) => setForm({ ...form, current: e.target.value })} />
      </Field>
      <Field label={ts("new")}>
        <Input type="password" dir="ltr" required minLength={8} autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
      </Field>
      <PasswordStrength value={form.password} email={me.user.email} />
      <Field label={ts("repeat")}>
        <Input type="password" dir="ltr" required autoComplete="new-password" value={form.repeat} onChange={(e) => setForm({ ...form, repeat: e.target.value })} />
      </Field>
      {error && <p className="rounded-xl bg-bad-bg px-3 py-2 text-sm text-bad">{error}</p>}
      <Button type="submit" variant="primary" size="lg" loading={busy}>{t("save")}</Button>
    </form>
  );
}

export default function ChangePasswordPage() {
  return (
    <Suspense>
      <ChangePasswordForm />
    </Suspense>
  );
}
