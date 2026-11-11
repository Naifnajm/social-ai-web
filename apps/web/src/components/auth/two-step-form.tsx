"use client";
/** Second sign-in step: the 6-digit code from the authenticator app, or a recovery code. */
import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";
import { Button, Field, Input } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Me } from "@/lib/session";

export type TwoStep = { two_step: true; challenge: string; methods: string[] };
export const isTwoStep = (value: unknown): value is TwoStep => !!value && (value as TwoStep).two_step === true;

export function TwoStepForm({ challenge, onDone, onBack }: { challenge: string; onDone: (me: Me) => void; onBack: () => void }) {
  const t = useTranslations("auth");
  const [recovery, setRecovery] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await api.post<{ me: Me }>("/auth/login/two-step", { challenge, code });
      onDone(data.me);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error"));
      if (err instanceof ApiError && err.code === "two_step_expired") setTimeout(onBack, 1500);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <div>
        <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-[linear-gradient(135deg,#ff5c9d,#b3124f)] text-white shadow-[0_10px_24px_-10px_rgba(224,36,111,.75)]">
          <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden><rect x="6" y="2.5" width="12" height="19" rx="3" /><path d="M10.5 18.5h3" /><path d="m9.5 10.5 2 2 3.5-4" /></svg>
        </span>
        <h1 className="text-xl font-bold tracking-tight">{t("twoStepTitle")}</h1>
        <p className="mt-1 text-sm text-muted">{recovery ? t("recoveryText") : t("twoStepText")}</p>
      </div>
      <Field label={recovery ? t("recoveryCode") : t("code")}>
        {recovery ? (
          <Input key="recovery" dir="ltr" autoFocus autoComplete="off" autoCapitalize="none" spellCheck={false} placeholder="abcde-fghjk" required value={code} onChange={(e) => setCode(e.target.value)} />
        ) : (
          <Input key="totp" dir="ltr" autoFocus inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]*" maxLength={7} placeholder="123 456" required
            className="text-center font-mono text-2xl tracking-[.35em]" value={code} onChange={(e) => setCode(e.target.value.replace(/[^0-9]/g, "").slice(0, 6))} />
        )}
      </Field>
      {error && <p className="rounded-xl bg-bad-bg px-3 py-2 text-sm text-bad">{error}</p>}
      <Button type="submit" variant="primary" size="lg" loading={busy} disabled={!recovery && code.length !== 6}>{t("verify")}</Button>
      <div className="flex items-center justify-between text-sm">
        <button type="button" className="text-muted hover:text-text" onClick={() => { setRecovery(!recovery); setCode(""); setError(""); }}>
          {recovery ? t("useApp") : t("useRecovery")}
        </button>
        <button type="button" className="font-semibold" onClick={onBack}>{t("back")}</button>
      </div>
    </form>
  );
}
