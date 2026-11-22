"use client";
/** Account center › Security: password, two-step sign-in (authenticator app + recovery codes), sessions and recent
 *  sign-ins, and the latest changes to the account. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { EventLabel, device } from "@/components/account/event-label";
import { PasswordStrength } from "@/components/account/password-strength";
import { QrCode } from "@/components/account/qr-code";
import { Badge, Button, Card, Field, Input, Modal, SectionTitle, Spinner, toast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatDate } from "@/lib/billing";
import { downloadBlob } from "@/lib/download";
import { type Me, useSession } from "@/lib/session";

type Security = {
  email: string; email_verified: boolean; totp_enabled: boolean; recovery_codes_left: number;
  password_changed_at: string | null; last_login_at: string | null; created_at: string; must_change_password: boolean;
  sign_ins: { at: string; ip: string | null; user_agent: string | null; how: string | null }[];
  events: { type: string; at: string; by_admin: boolean }[];
};

const onError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : String(err));

export default function AccountSecurityPage() {
  const t = useTranslations("account.security");
  const locale = useLocale();
  const client = useQueryClient();
  const me = useSession((s) => s.me);
  const security = useQuery({ queryKey: ["account-security"], queryFn: () => api.get<Security>("/account/security") });
  const refresh = () => client.invalidateQueries({ queryKey: ["account-security"] });
  const data = security.data;
  if (!data || !me) return <div className="flex justify-center py-12"><Spinner /></div>;
  const when = (value: string | null) => (value ? formatDate(value, locale) : t("never"));

  const signOutAll = async () => {
    if (!window.confirm(t("signOutConfirm"))) return;
    await api.post("/auth/logout-everywhere").catch(onError);
    window.location.href = `/${locale}/login`;
  };

  return (
    <div className="flex flex-col gap-4">
      <PasswordCard changedAt={data.password_changed_at} onDone={refresh} />
      <TwoFactorCard data={data} onDone={refresh} />
      <Card>
        <SectionTitle icon="history" actions={<Button size="sm" variant="danger" onClick={signOutAll}>{t("signOutAll")}</Button>}>{t("sessions")}</SectionTitle>
        <p className="mb-3 text-sm text-muted">{t("signOutAllText")}</p>
        <p className="mb-3 text-sm">{t("lastLogin")}: <b>{when(data.last_login_at)}</b></p>
        <h3 className="mb-2 text-sm font-semibold">{t("signIns")}</h3>
        {!data.sign_ins.length ? <p className="text-sm text-muted">{t("noSignIns")}</p> : (
          <ul className="divide-y divide-line/60 text-sm">
            {data.sign_ins.map((s, i) => (
              <li key={i} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2">
                <span className="min-w-36 font-medium">{formatDate(s.at, locale)}</span>
                <span className="text-text-2">{device(s.user_agent)}</span>
                <span className="text-muted" dir="ltr">{s.ip || ""}</span>
                {s.how === "password+2fa" && <Badge tone="ok">{t("with2fa")}</Badge>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {!!data.events.length && (
        <Card>
          <SectionTitle icon="verified_user">{t("events")}</SectionTitle>
          <ul className="divide-y divide-line/60 text-sm">
            {data.events.map((e, i) => (
              <li key={i} className="flex flex-wrap items-center gap-x-4 py-2">
                <span className="min-w-36 text-text-2">{formatDate(e.at, locale)}</span>
                <span className="font-medium"><EventLabel type={e.type} /></span>
                {e.by_admin && <Badge tone="warn">{t("byAdmin")}</Badge>}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function PasswordCard({ changedAt, onDone }: { changedAt: string | null; onDone: () => void }) {
  const t = useTranslations("account.security");
  const locale = useLocale();
  const { me, setMe } = useSession();
  const [form, setForm] = useState({ current: "", password: "", repeat: "" });
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (form.password !== form.repeat) return toast.error(t("mismatch"));
    setBusy(true);
    try {
      const data = await api.post<{ me: Me }>("/auth/password", { current_password: form.current, new_password: form.password });
      setMe(data.me);
      setForm({ current: "", password: "", repeat: "" });
      toast.success(t("changed"));
      onDone();
    } catch (err) {
      onError(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <SectionTitle icon="lock">{t("password")}</SectionTitle>
      <p className="mb-3 text-sm text-muted">{changedAt ? t("lastChanged", { date: formatDate(changedAt, locale) }) : t("neverChanged")}</p>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label={t("current")}><Input type="password" dir="ltr" autoComplete="current-password" value={form.current} onChange={(e) => setForm({ ...form, current: e.target.value })} /></Field>
        <Field label={t("new")}><Input type="password" dir="ltr" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
        <Field label={t("repeat")}><Input type="password" dir="ltr" autoComplete="new-password" value={form.repeat} onChange={(e) => setForm({ ...form, repeat: e.target.value })} /></Field>
      </div>
      <div className="mt-3"><PasswordStrength value={form.password} email={me?.user.email} /></div>
      <div className="mt-4 flex justify-end">
        <Button variant="primary" loading={busy} disabled={!form.current || form.password.length < 8} onClick={submit}>{t("change")}</Button>
      </div>
    </Card>
  );
}

function RecoveryCodes({ codes, onClose }: { codes: string[]; onClose: () => void }) {
  const t = useTranslations("account.security");
  const text = codes.join("\n");
  const download = () => {
    downloadBlob(new Blob([text + "\n"], { type: "text/plain" }), "stravica-recovery-codes.txt");
  };
  return (
    <Modal open onClose={onClose} title={t("codesTitle")} size="sm"
      footer={<>
        <Button icon="download" onClick={download}>{t("download")}</Button>
        <Button icon="content_copy" onClick={() => navigator.clipboard.writeText(text).then(() => toast.success(t("copied")))}>{t("copyAll")}</Button>
        <Button variant="primary" onClick={onClose}>{t("done")}</Button>
      </>}>
      <p className="mb-3 text-sm text-text-2">{t("codesText")}</p>
      <ol className="grid grid-cols-2 gap-2 rounded-2xl bg-fill-2 p-4 font-mono text-sm" dir="ltr">
        {codes.map((code) => <li key={code}>{code}</li>)}
      </ol>
    </Modal>
  );
}

function TwoFactorCard({ data, onDone }: { data: Security; onDone: () => void }) {
  const t = useTranslations("account.security");
  const { setMe } = useSession();
  const [step, setStep] = useState<"" | "password" | "scan" | "disable" | "codes">("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const close = () => { setStep(""); setPassword(""); setCode(""); setSetup(null); };
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try { await action(); } catch (err) { onError(err); } finally { setBusy(false); }
  };
  const after = async () => { setMe(await api.get<Me>("/auth/me")); onDone(); };

  return (
    <Card>
      <SectionTitle icon="shield" actions={data.totp_enabled
        ? <><Button size="sm" onClick={() => setStep("codes")}>{t("newCodes")}</Button><Button size="sm" variant="danger" onClick={() => setStep("disable")}>{t("disable")}</Button></>
        : <Button size="sm" variant="primary" onClick={() => setStep("password")}>{t("enable")}</Button>}>
        {t("twoFactor")} <Badge tone={data.totp_enabled ? "ok" : "neutral"} className="ms-2">{data.totp_enabled ? t("twoFactorOn") : t("twoFactorOff")}</Badge>
      </SectionTitle>
      <p className="text-sm text-muted">{t("twoFactorText")}</p>
      {data.totp_enabled && <p className="mt-2 text-sm">{t("codesLeft", { n: data.recovery_codes_left })}</p>}

      <Modal open={step === "password"} onClose={close} title={t("setupTitle")} size="sm"
        footer={<Button variant="primary" loading={busy} disabled={!password} onClick={() => run(async () => {
          setSetup(await api.post<{ secret: string; uri: string }>("/account/2fa/setup", { password }));
          setStep("scan");
        })}>{t("continue")}</Button>}>
        <Field label={t("confirmPassword")}><Input type="password" dir="ltr" autoFocus autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
      </Modal>

      <Modal open={step === "scan" && !!setup} onClose={close} title={t("setupTitle")} size="md"
        footer={<Button variant="primary" loading={busy} disabled={code.replace(/\s/g, "").length !== 6} onClick={() => run(async () => {
          const result = await api.post<{ recovery_codes: string[] }>("/account/2fa/enable", { code });
          close();
          setCodes(result.recovery_codes);
          toast.success(t("enabled"));
          await after();
        })}>{t("confirm")}</Button>}>
        {setup && (
          <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start">
            <div className="shrink-0 rounded-2xl bg-white p-2 shadow-sm"><QrCode value={setup.uri} label={t("scan")} /></div>
            <div className="flex min-w-0 flex-1 flex-col gap-3">
              <p className="text-sm text-text-2">{t("scan")}</p>
              <Field label={t("key")}>
                <div className="flex gap-2">
                  <code className="min-w-0 flex-1 break-all rounded-xl bg-fill-2 px-3 py-2 text-xs" dir="ltr">{setup.secret.replace(/(.{4})/g, "$1 ").trim()}</code>
                  <Button size="sm" icon="content_copy" onClick={() => navigator.clipboard.writeText(setup.secret).then(() => toast.success(t("copied")))} />
                </div>
              </Field>
              <Field label={t("enterCode")}>
                <Input autoFocus inputMode="numeric" autoComplete="one-time-code" maxLength={7} dir="ltr" className="text-center text-lg tracking-[.4em]" value={code} onChange={(e) => setCode(e.target.value)} />
              </Field>
            </div>
          </div>
        )}
      </Modal>

      <Modal open={step === "disable" || step === "codes"} onClose={close} title={step === "disable" ? t("disableTitle") : t("newCodes")} size="sm"
        footer={<Button variant={step === "disable" ? "danger" : "primary"} loading={busy} disabled={!password || code.length < 6} onClick={() => run(async () => {
          if (step === "disable") {
            await api.post("/account/2fa/disable", { password, code });
            toast.success(t("disabled"));
          } else {
            const result = await api.post<{ recovery_codes: string[] }>("/account/2fa/recovery-codes", { password, code });
            setCodes(result.recovery_codes);
          }
          close();
          await after();
        })}>{step === "disable" ? t("disable") : t("continue")}</Button>}>
        <div className="flex flex-col gap-3">
          <Field label={t("confirmPassword")}><Input type="password" dir="ltr" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          <Field label={t("codeOrRecovery")}><Input dir="ltr" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} /></Field>
        </div>
      </Modal>
      {codes && <RecoveryCodes codes={codes} onClose={() => setCodes(null)} />}
    </Card>
  );
}
