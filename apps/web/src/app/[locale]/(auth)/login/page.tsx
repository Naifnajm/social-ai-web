"use client";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { type FormEvent, Suspense, useState } from "react";
import { Button, Field, Input } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { type Me, useSession } from "@/lib/session";

type LoginAnswer = { me: Me } | { two_factor_required: true; challenge: string };

function LoginForm() {
  const t = useTranslations("auth");
  const t2 = useTranslations("account.login2fa");
  const router = useRouter();
  const next = useSearchParams().get("next") || "/";
  const setMe = useSession((s) => s.setMe);
  const refreshWorkspace = useSession((s) => s.refreshWorkspace);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [challenge, setChallenge] = useState("");
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(false);

  const signedIn = async (me: Me) => {
    setMe(me);
    const target = next.startsWith("/") && !next.startsWith("//") ? next : "/";
    if (me.user.must_change_password) {
      router.replace(`/change-password?next=${encodeURIComponent(target)}`);
      return;
    }
    await refreshWorkspace();
    router.replace(target);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (challenge) {
        const data = await api.post<{ me: Me }>("/auth/login/2fa", { challenge, code });
        await signedIn(data.me);
        return;
      }
      const data = await api.post<LoginAnswer>("/auth/login", { email, password });
      if ("two_factor_required" in data) setChallenge(data.challenge);
      else await signedIn(data.me);
    } catch (err) {
      if (err instanceof ApiError && err.code === "challenge_expired") { setChallenge(""); setCode(""); }
      setError(err instanceof ApiError ? err.message : t("error"));
    } finally {
      setBusy(false);
    }
  };

  if (challenge) {
    return (
      <form onSubmit={submit} className="flex flex-col gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight">{t2("title")}</h1>
          <p className="mt-1 text-sm text-muted">{recovery ? t2("recoveryText") : t2("text")}</p>
        </div>
        <Field label={recovery ? t2("recovery") : t2("code")}>
          {recovery
            ? <Input key="recovery" autoFocus required dir="ltr" autoComplete="off" spellCheck={false} value={code} onChange={(e) => setCode(e.target.value)} />
            : <Input key="code" autoFocus required dir="ltr" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,7}" maxLength={7} className="text-center text-lg tracking-[.4em]" value={code} onChange={(e) => setCode(e.target.value)} />}
        </Field>
        {error && <p className="rounded-xl bg-bad-bg px-3 py-2 text-sm text-bad">{error}</p>}
        <Button type="submit" variant="primary" size="lg" loading={busy}>{t2("verify")}</Button>
        <div className="flex items-center justify-between text-sm">
          <button type="button" className="text-muted hover:text-text" onClick={() => { setChallenge(""); setCode(""); setError(""); }}>{t2("back")}</button>
          <button type="button" className="font-semibold" onClick={() => { setRecovery(!recovery); setCode(""); }}>{recovery ? t2("useApp") : t2("useRecovery")}</button>
        </div>
      </form>
    );
  }

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
