"use client";
/** "Connect an account": one-click OAuth, guided one-time developer-app setup, or a manual token. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import { Button, Field, IconButton, Input, Modal, Select, Spinner, toast } from "@/components/ui";
import { api } from "@/lib/api";
import type { Account, OAuthSetup, PlatformOption } from "./types";
import { errorText } from "./util";

type View = { kind: "list" } | { kind: "setup"; platform: string } | { kind: "token"; platform: string };
const PRIVACY = ["SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "PUBLIC_TO_EVERYONE"];

export function ConnectDialog({ open, onClose, initial }: { open: boolean; onClose: () => void; initial?: View }) {
  const t = useTranslations("publishing.connect");
  const [view, setView] = useState<View>(initial || { kind: "list" });
  const close = () => {
    setView({ kind: "list" });
    onClose();
  };
  const title = view.kind === "list" ? t("title") : view.kind === "setup" ? t("setupTitle") : t("tokenTitle");
  return (
    <Modal open={open} onClose={close} size="lg" title={
      <span className="flex items-center gap-2">
        {view.kind !== "list" && <IconButton icon="arrow_back" label={t("back")} className="rtl:rotate-180" onClick={() => setView({ kind: "list" })} />}
        {title}
      </span>
    }>
      {view.kind === "list" && <PlatformList onPick={setView} />}
      {view.kind === "setup" && <SetupView platform={view.platform} onToken={() => setView({ kind: "token", platform: view.platform })} />}
      {view.kind === "token" && <TokenForm platform={view.platform} onDone={close} />}
    </Modal>
  );
}

async function startOAuth(platform: string) {
  const { url } = await api.post<{ url: string }>("/accounts/oauth/start", { platform });
  window.location.href = url;
}

function PlatformList({ onPick }: { onPick: (v: View) => void }) {
  const t = useTranslations("publishing.connect");
  const { data, isLoading } = useQuery({ queryKey: ["account-platforms"], queryFn: () => api.get<PlatformOption[]>("/accounts/platforms") });
  const [busy, setBusy] = useState<string | null>(null);
  const pick = async (option: PlatformOption) => {
    if (option.method === "token") return onPick({ kind: "token", platform: option.key });
    if (!option.configured) return onPick({ kind: "setup", platform: option.key });
    setBusy(option.key);
    try {
      await startOAuth(option.key);
    } catch (err) {
      toast.error(errorText(err));
      setBusy(null);
    }
  };
  if (isLoading) return <div className="flex justify-center py-10"><Spinner /></div>;
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {data?.map((option) => (
          <button key={option.key} onClick={() => pick(option)} disabled={!!busy}
            className="glass flex items-center gap-3 rounded-2xl p-3 text-start transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-lift)] disabled:opacity-60">
            <PlatformBadge platform={option.key} size={36} />
            <span className="min-w-0 flex-1">
              <span className="block font-semibold">{option.label}</span>
              <span className="block text-xs text-muted">
                {option.method === "token" ? t("withToken") : option.configured ? t("oneClick") : t("setupOnce")}
              </span>
            </span>
            {busy === option.key ? <Spinner size={18} /> : <Icon name="east" size={16} className="text-faint rtl:rotate-180" />}
          </button>
        ))}
      </div>
      <p className="flex gap-2 rounded-2xl bg-fill p-3 text-xs leading-relaxed text-muted">
        <Icon name="info" size={16} className="mt-0.5 shrink-0" />
        {t("explain")}
      </p>
    </div>
  );
}

function SetupView({ platform, onToken }: { platform: string; onToken: () => void }) {
  const t = useTranslations("publishing.connect");
  const qc = useQueryClient();
  const { data: setup, isLoading } = useQuery({ queryKey: ["oauth-setup", platform], queryFn: () => api.get<OAuthSetup>(`/accounts/oauth/setup/${platform}`) });
  const [keys, setKeys] = useState({ client_id: "", client_secret: "" });
  const save = useMutation({
    mutationFn: () => api.put<{ url: string }>(`/accounts/oauth/apps/${platform}`, { ...keys, connect: true }),
    onSuccess: (data) => { if (data?.url) window.location.href = data.url; },
    onError: (err) => toast.error(errorText(err)),
  });
  const forget = useMutation({
    mutationFn: () => api.delete(`/accounts/oauth/apps/${platform}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["oauth-setup", platform] }); qc.invalidateQueries({ queryKey: ["account-platforms"] }); toast.success(t("appRemoved")); },
  });
  if (isLoading || !setup) return <div className="flex justify-center py-10"><Spinner /></div>;
  const copy = () => navigator.clipboard?.writeText(setup.redirect_uri).then(() => toast.success(t("copied")));
  return (
    <div className="flex flex-col gap-4 text-sm">
      <div className="flex items-center gap-3">
        <PlatformBadge platform={setup.platform} size={36} />
        <p className="text-muted">{t("setupIntro", { brand: setup.brand })}</p>
      </div>
      <ol className="flex flex-col gap-2">
        {setup.steps.map((step, i) => (
          <li key={i} className="flex gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink text-xs font-bold text-white">{i + 1}</span>
            <span className="bidi pt-0.5">{step}</span>
          </li>
        ))}
      </ol>
      <a href={setup.portal_url} target="_blank" rel="noopener noreferrer" className="inline-flex w-fit items-center gap-1.5 font-medium underline underline-offset-4">
        <Icon name="open_in_new" size={15} /> {t("openPortal")}
      </a>
      <Field label={t("redirectUrl")}>
        <div className="flex gap-2">
          <Input readOnly dir="ltr" value={setup.redirect_uri} onFocus={(e) => e.target.select()} />
          <Button icon="content_copy" onClick={copy}>{t("copy")}</Button>
        </div>
      </Field>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label={setup.id_label}><Input dir="ltr" autoComplete="off" value={keys.client_id} placeholder={setup.client_id} onChange={(e) => setKeys({ ...keys, client_id: e.target.value })} /></Field>
        <Field label={setup.secret_label}><Input dir="ltr" type="password" autoComplete="new-password" value={keys.client_secret} onChange={(e) => setKeys({ ...keys, client_secret: e.target.value })} /></Field>
      </div>
      {setup.note && <p className="flex gap-2 rounded-2xl bg-fill p-3 text-xs text-muted"><Icon name="info" size={16} className="shrink-0" />{setup.note}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" loading={save.isPending} disabled={!keys.client_id.trim() || !keys.client_secret.trim()} onClick={() => save.mutate()}>
          {t("saveAndConnect", { brand: setup.brand })}
        </Button>
        {setup.configured && (
          <Button onClick={() => startOAuth(setup.platform).catch((err) => toast.error(errorText(err)))}>{t("connectNow")}</Button>
        )}
        <Button variant="ghost" onClick={onToken}>{t("useToken")}</Button>
        {setup.own_app && <Button variant="ghost" className="ms-auto text-bad" loading={forget.isPending} onClick={() => forget.mutate()}>{t("removeApp")}</Button>}
      </div>
    </div>
  );
}

function TokenForm({ platform, onDone }: { platform: string; onDone: () => void }) {
  const t = useTranslations("publishing.connect");
  const qc = useQueryClient();
  const [form, setForm] = useState({ external_id: "", access_token: "", name: "", privacy_level: "SELF_ONLY" });
  const options = useQuery({ queryKey: ["account-platforms"], queryFn: () => api.get<PlatformOption[]>("/accounts/platforms") });
  const help = options.data?.find((o) => o.key === platform)?.help;
  const save = useMutation({
    mutationFn: () => api.post<{ ok: boolean; account: Account; message?: string }>("/accounts", { platform, ...form }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["studio"] });
      if (res.ok) {
        toast.success(t("connected", { name: res.account.name }));
        onDone();
      } else toast.error(res.message || t("failed"));
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const idLabel = platform === "telegram" ? t("channel") : platform === "linkedin" ? t("authorUrn") : t("accountId");
  const needsId = ["telegram", "facebook", "instagram", "google_business"].includes(platform);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <PlatformBadge platform={platform} size={36} />
        {help && <p className="bidi text-sm text-muted">{help}</p>}
      </div>
      <Field label={idLabel} hint={needsId ? undefined : t("optional")}>
        <Input dir="ltr" value={form.external_id} placeholder={platform === "telegram" ? "@channel" : ""} onChange={(e) => setForm({ ...form, external_id: e.target.value })} />
      </Field>
      <Field label={platform === "telegram" ? t("botToken") : t("accessToken")}>
        <Input dir="ltr" type="password" autoComplete="off" value={form.access_token} onChange={(e) => setForm({ ...form, access_token: e.target.value })} />
      </Field>
      <Field label={t("displayName")} hint={t("optional")}>
        <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </Field>
      {platform === "tiktok" && (
        <Field label={t("privacy")} hint={t("privacyHint")}>
          <Select value={form.privacy_level} onChange={(e) => setForm({ ...form, privacy_level: e.target.value })}>
            {PRIVACY.map((p) => <option key={p} value={p}>{t(`privacyLevels.${p}`)}</option>)}
          </Select>
        </Field>
      )}
      <div className="flex justify-end">
        <Button variant="primary" icon="link" loading={save.isPending} disabled={!form.access_token.trim() || (needsId && !form.external_id.trim())} onClick={() => save.mutate()}>
          {t("connectAndTest")}
        </Button>
      </div>
    </div>
  );
}
