"use client";
/** Profile › Security: two-step sign-in with an authenticator app, recovery codes and passkeys. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Badge, Button, Card, Field, Input, Modal, SectionTitle, toast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { addPasskey, deviceName, isCancel, passkeysSupported } from "@/lib/passkeys";

type Security = {
  two_step: boolean; two_step_since: string | null; recovery_codes_left: number;
  passkeys: { id: number; name: string; created_at: string; last_used_at: string | null }[];
};
const onError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : String(err));

export function SecuritySettings() {
  const t = useTranslations("settings.security");
  const locale = useLocale();
  const client = useQueryClient();
  const security = useQuery({ queryKey: ["security"], queryFn: () => api.get<Security>("/auth/security") });
  const [setupOpen, setSetupOpen] = useState(false);
  const [manage, setManage] = useState<"off" | "recovery" | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [supported, setSupported] = useState(true);
  useEffect(() => { setSupported(passkeysSupported()); }, []); // eslint-disable-line react-hooks/set-state-in-effect
  const date = (value: string) => new Intl.DateTimeFormat(locale === "ar" ? "ar-SA-u-nu-latn-ca-gregory" : locale, { dateStyle: "medium" }).format(new Date(value));
  const refresh = (data?: Security) => (data ? client.setQueryData(["security"], data) : client.invalidateQueries({ queryKey: ["security"] }));

  const add = useMutation({
    mutationFn: () => addPasskey(deviceName()),
    onSuccess: (data) => { refresh(data as Security); toast.success(t("passkeyAdded")); },
    onError: (err) => { if (!isCancel(err)) onError(err); },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete<Security>(`/auth/passkeys/${id}`),
    onSuccess: (data) => refresh(data), onError,
  });
  const data = security.data;

  return (
    <>
      <Card>
        <SectionTitle icon="lock">{t("title")}</SectionTitle>
        <p className="-mt-2 mb-5 text-sm text-muted">{t("subtitle")}</p>

        <div className="flex flex-wrap items-start gap-4 rounded-2xl border border-line p-4">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-fill-2 text-text-2">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden><rect x="6" y="2.5" width="12" height="19" rx="3" /><path d="M10.5 18.5h3" /><path d="m9.5 10.5 2 2 3.5-4" /></svg>
          </span>
          <div className="min-w-[220px] flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-semibold">{t("appTitle")}</h3>
              {data?.two_step ? <Badge tone="ok">{t("on")}</Badge> : <Badge>{t("off")}</Badge>}
            </div>
            <p className="mt-1 text-sm text-muted">{t("appText")}</p>
            {data?.two_step && (
              <p className="mt-2 text-xs text-muted">
                {data.two_step_since && t("onSince", { date: date(data.two_step_since) })} · {t("codesLeft", { n: data.recovery_codes_left })}
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {data?.two_step ? (
              <>
                <Button size="sm" onClick={() => setManage("recovery")}>{t("newCodes")}</Button>
                <Button size="sm" variant="ghost" onClick={() => setManage("off")}>{t("turnOff")}</Button>
              </>
            ) : (
              <Button size="sm" variant="primary" onClick={() => setSetupOpen(true)}>{t("turnOn")}</Button>
            )}
          </div>
        </div>

        <div className="mt-3 rounded-2xl border border-line p-4">
          <div className="flex flex-wrap items-start gap-4">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-fill-2 text-text-2">
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden><circle cx="9" cy="8" r="4" /><path d="M2.5 20c.6-3.4 3.2-5.5 6.5-5.5 1.2 0 2.3.3 3.2.8" /><circle cx="17.5" cy="14.5" r="2.5" /><path d="M17.5 17v4.5m0-1.5h1.8m-1.8-1.6h1.4" /></svg>
            </span>
            <div className="min-w-[220px] flex-1">
              <h3 className="font-semibold">{t("passkeysTitle")}</h3>
              <p className="mt-1 text-sm text-muted">{supported ? t("passkeysText") : t("passkeysUnsupported")}</p>
            </div>
            <Button size="sm" variant="primary" disabled={!supported} loading={add.isPending} onClick={() => add.mutate()}>{t("addPasskey")}</Button>
          </div>
          {!!data?.passkeys.length && (
            <ul className="mt-4 flex flex-col divide-y divide-line border-t border-line">
              {data.passkeys.map((p) => (
                <li key={p.id} className="flex flex-wrap items-center gap-3 py-3 text-sm">
                  <span className="font-semibold">{p.name}</span>
                  <span className="text-xs text-muted">{t("added", { date: date(p.created_at) })}{p.last_used_at ? ` · ${t("lastUsed", { date: date(p.last_used_at) })}` : ""}</span>
                  <Button size="sm" variant="ghost" className="ms-auto" onClick={() => remove.mutate(p.id)}>{t("remove")}</Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>

      {setupOpen && <SetupDialog onClose={() => setSetupOpen(false)} onEnabled={(list) => { setSetupOpen(false); setCodes(list); refresh(); }} />}
      {manage && <ManageDialog mode={manage} onClose={() => setManage(null)} onCodes={(list) => { setManage(null); setCodes(list); refresh(); }} onOff={(sec) => { setManage(null); refresh(sec); toast.success(t("turnedOff")); }} />}
      {codes && <RecoveryCodes codes={codes} onClose={() => setCodes(null)} />}
    </>
  );
}

function SetupDialog({ onClose, onEnabled }: { onClose: () => void; onEnabled: (codes: string[]) => void }) {
  const t = useTranslations("settings.security");
  const setup = useQuery({ queryKey: ["two-step-setup"], queryFn: () => api.post<{ secret: string; uri: string; qr_svg: string }>("/auth/two-step/setup"), gcTime: 0, staleTime: Infinity, retry: false });
  const [code, setCode] = useState("");
  const enable = useMutation({
    mutationFn: () => api.post<{ recovery_codes: string[] }>("/auth/two-step/enable", { code }),
    onSuccess: (data) => onEnabled(data.recovery_codes), onError,
  });
  const secret = setup.data?.secret.replace(/(.{4})/g, "$1 ").trim();
  return (
    <Modal open onClose={onClose} title={t("setupTitle")}
      footer={<><Button onClick={onClose}>{t("cancel")}</Button><Button variant="primary" loading={enable.isPending} disabled={code.length !== 6} onClick={() => enable.mutate()}>{t("confirm")}</Button></>}>
      <div className="flex flex-col gap-4">
        <ol className="flex list-decimal flex-col gap-1 ps-5 text-sm text-text-2">
          <li>{t("step1")}</li>
          <li>{t("step2")}</li>
          <li>{t("step3")}</li>
        </ol>
        <div className="flex flex-wrap items-center gap-5 rounded-2xl bg-fill p-4">
          <div className="h-[168px] w-[168px] shrink-0 overflow-hidden rounded-xl bg-white p-1 [&>svg]:h-full [&>svg]:w-full" dangerouslySetInnerHTML={{ __html: setup.data?.qr_svg ?? "" }} />
          <div className="min-w-0 flex-1 text-sm">
            <div className="text-xs text-muted">{t("manualKey")}</div>
            <div className="mt-1 break-all font-mono text-[13px] font-semibold" dir="ltr">{secret ?? "…"}</div>
            <Button size="sm" className="mt-2" disabled={!secret} onClick={() => navigator.clipboard.writeText(setup.data?.secret ?? "").then(() => toast.success(t("copied")))}>{t("copy")}</Button>
          </div>
        </div>
        <Field label={t("codeLabel")}>
          <Input dir="ltr" inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="123456" className="text-center font-mono text-xl tracking-[.3em]"
            value={code} onChange={(e) => setCode(e.target.value.replace(/[^0-9]/g, "").slice(0, 6))} />
        </Field>
      </div>
    </Modal>
  );
}

function ManageDialog({ mode, onClose, onCodes, onOff }: {
  mode: "off" | "recovery"; onClose: () => void; onCodes: (codes: string[]) => void; onOff: (security: Security) => void;
}) {
  const t = useTranslations("settings.security");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const run = useMutation({
    mutationFn: () => mode === "off"
      ? api.post<Security>("/auth/two-step/disable", { password, code }).then(onOff)
      : api.post<{ recovery_codes: string[] }>("/auth/two-step/recovery", { code }).then((d) => onCodes(d.recovery_codes)),
    onError,
  });
  return (
    <Modal open onClose={onClose} size="sm" title={mode === "off" ? t("offTitle") : t("newCodesTitle")}
      footer={<><Button onClick={onClose}>{t("cancel")}</Button><Button variant={mode === "off" ? "danger" : "primary"} loading={run.isPending} disabled={!code || (mode === "off" && !password)} onClick={() => run.mutate()}>{mode === "off" ? t("turnOff") : t("newCodes")}</Button></>}>
      <div className="flex flex-col gap-4">
        <p className="text-sm text-muted">{mode === "off" ? t("offText") : t("newCodesText")}</p>
        {mode === "off" && <Field label={t("password")}><Input type="password" dir="ltr" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>}
        <Field label={mode === "off" ? t("codeOrRecovery") : t("codeLabel")}><Input dir="ltr" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

function RecoveryCodes({ codes, onClose }: { codes: string[]; onClose: () => void }) {
  const t = useTranslations("settings.security");
  const text = codes.join("\n");
  const download = () => {
    const url = URL.createObjectURL(new Blob([`Stravica Social: recovery codes\n\n${text}\n`], { type: "text/plain" }));
    const link = Object.assign(document.createElement("a"), { href: url, download: "stravica-social-recovery-codes.txt" });
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <Modal open onClose={onClose} title={t("codesTitle")}
      footer={<><Button onClick={download}>{t("download")}</Button><Button onClick={() => navigator.clipboard.writeText(text).then(() => toast.success(t("copied")))}>{t("copy")}</Button><Button variant="primary" onClick={onClose}>{t("saved")}</Button></>}>
      <p className="mb-4 text-sm text-muted">{t("codesText")}</p>
      <div className="grid grid-cols-2 gap-2 rounded-2xl bg-fill p-4 font-mono text-[15px] font-semibold" dir="ltr">
        {codes.map((c) => <span key={c}>{c}</span>)}
      </div>
    </Modal>
  );
}
