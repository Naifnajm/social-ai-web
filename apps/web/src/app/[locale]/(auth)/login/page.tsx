"use client";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { type FormEvent, Suspense, useEffect, useState } from "react";
import { TwoStepForm, type TwoStep, isTwoStep } from "@/components/auth/two-step-form";
import { Button, Field, Input } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { isCancel, passkeysSupported, signInWithPasskey } from "@/lib/passkeys";
import { type Me, useSession } from "@/lib/session";

function LoginForm() {
  const t = useTranslations("auth");
  const router = useRouter();
  const next = useSearchParams().get("next") || "/";
  const setMe = useSession((s) => s.setMe);
  const refreshWorkspace = useSession((s) => s.refreshWorkspace);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState<TwoStep | null>(null);
  const [passkeys, setPasskeys] = useState(false);
  const [passkeyBusy, setPasskeyBusy] = useState(false);
  useEffect(() => { setPasskeys(passkeysSupported()); }, []); // eslint-disable-line react-hooks/set-state-in-effect

  const finish = async (me: Me) => {
    setMe(me);
    await refreshWorkspace();
    router.replace(next.startsWith("/") ? next : "/");
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await api.post<{ me: Me } | TwoStep>("/auth/login", { email, password });
      if (isTwoStep(data)) setStep(data);
      else await finish(data.me);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error"));
    } finally {
      setBusy(false);
    }
  };

  const withPasskey = async () => {
    setPasskeyBusy(true);
    setError("");
    try {
      await finish((await signInWithPasskey()).me);
    } catch (err) {
      if (!isCancel(err)) setError(err instanceof ApiError ? err.message : t("passkeyFailed"));
    } finally {
      setPasskeyBusy(false);
    }
  };

  if (step) return <TwoStepForm challenge={step.challenge} onDone={finish} onBack={() => { setStep(null); setPassword(""); }} />;

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-bold tracking-tight">{t("loginTitle")}</h1>
        <p className="mt-1 text-sm text-muted">{t("loginSubtitle")}</p>
      </div>
      <Field label={t("emailOrUsername")}>
        <Input type="text" inputMode="email" autoComplete="username" autoCapitalize="none" spellCheck={false} dir="ltr" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </Field>
      <Field label={t("password")}>
        <Input type="password" autoComplete="current-password" dir="ltr" required value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      {error && <p className="rounded-xl bg-bad-bg px-3 py-2 text-sm text-bad">{error}</p>}
      <Button type="submit" variant="primary" size="lg" loading={busy}>{t("login")}</Button>
      {passkeys && (
        <>
          <div className="flex items-center gap-3 text-xs text-faint"><span className="h-px flex-1 bg-line" />{t("or")}<span className="h-px flex-1 bg-line" /></div>
          <Button type="button" size="lg" loading={passkeyBusy} onClick={withPasskey}>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden><circle cx="9" cy="8" r="4" /><path d="M2.5 20c.6-3.4 3.2-5.5 6.5-5.5 1.2 0 2.3.3 3.2.8" /><circle cx="17.5" cy="14.5" r="2.5" /><path d="M17.5 17v4.5m0-1.5h1.8m-1.8-1.6h1.4" /></svg>
            {t("withPasskey")}
          </Button>
        </>
      )}
      <div className="flex items-center justify-between text-sm">
        <Link href="/forgot-password" className="text-muted hover:text-text">{t("forgot")}</Link>
        <Link href="/signup" className="font-semibold">{t("createAccount")}</Link>
      </div>
    </form>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
