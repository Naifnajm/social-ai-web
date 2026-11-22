"use client";
/**
 * Settings › Connected apps & API: the MCP server URL with steps for Claude and ChatGPT, the apps connected to this
 * workspace (disconnect), and personal API keys for developers (created once-shown, revoked).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";
import { Icon } from "@/components/icon";
import { Badge, Button, Card, EmptyState, Field, Input, Modal, SectionTitle, Segmented, Spinner, cx, toast } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";

type ScopeOption = { key: string; label: string; sensitive: boolean };
type Info = { mcp_url: string; scopes: ScopeOption[]; plan_ok: boolean; can_manage_keys: boolean; key_days: number[] };
type ConnectedApp = { id: number; client_name: string; client_host: string | null; scopes: string[]; user_name: string; mine: boolean; created_at: string; last_used_at: string | null };
type ApiKey = { id: number; name: string; prefix: string; scopes: string[]; user_name: string; created_at: string; expires_at: string; last_used_at: string | null; expired: boolean };
type Client = "claude" | "chatgpt" | "other";

export default function ConnectSettingsPage() {
  const t = useTranslations("connect.page");
  const info = useQuery({ queryKey: ["connect-info"], queryFn: () => api.get<Info>("/connect/info") });
  if (!info.data) return <div className="flex justify-center py-16"><Spinner /></div>;
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-bold tracking-tight">{t("title")}</h2>
        <p className="mt-0.5 text-sm text-muted">{t("subtitle")}</p>
      </div>
      <ConnectCard info={info.data} />
      <AppsCard />
      <KeysCard info={info.data} />
    </div>
  );
}

function CopyField({ value }: { value: string }) {
  const t = useTranslations("connect.page");
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      toast.error(t("copyFailed"));
    }
  };
  return (
    <div className="flex items-center gap-2 rounded-2xl border border-line bg-white p-1.5 ps-3.5" dir="ltr">
      <code className="min-w-0 flex-1 truncate font-mono text-[13.5px] font-semibold text-text">{value}</code>
      <Button size="sm" variant={copied ? "secondary" : "primary"} icon={copied ? "check" : "content_copy"} onClick={copy}>
        {copied ? t("copied") : t("copy")}
      </Button>
    </div>
  );
}

function ConnectCard({ info }: { info: Info }) {
  const t = useTranslations("connect.page");
  const [client, setClient] = useState<Client>("claude");
  const steps = t.raw(`steps.${client}`) as string[];
  return (
    <Card className="relative overflow-hidden">
      <div className="pointer-events-none absolute -top-24 end-[-60px] h-56 w-56 rounded-full bg-[radial-gradient(closest-side,rgba(255,61,139,.16),transparent)]" />
      <SectionTitle icon="smart_toy">{t("connectTitle")}</SectionTitle>
      <p className="max-w-2xl text-sm leading-relaxed text-text-2">{t("connectText")}</p>
      {!info.plan_ok && (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-2xl bg-accent-soft p-3.5 text-sm">
          <Icon name="lock" size={18} className="text-accent-deep" />
          <span className="flex-1 text-text-2">{t("planLocked")}</span>
          <Link href="/settings/billing" className="text-sm font-semibold text-accent-deep hover:underline">{t("upgrade")}</Link>
        </div>
      )}
      <div className="mt-5">
        <div className="mb-1.5 text-[13px] font-semibold">{t("serverUrl")}</div>
        <CopyField value={info.mcp_url} />
      </div>
      <div className="mt-5">
        <Segmented value={client} onChange={setClient} size="sm"
          options={[{ value: "claude", label: t("clients.claude") }, { value: "chatgpt", label: t("clients.chatgpt") }, { value: "other", label: t("clients.other") }]} />
        <ol className="mt-3 flex flex-col gap-2.5">
          {steps.map((step, i) => (
            <li key={i} className="flex gap-3 text-sm leading-relaxed text-text-2">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink text-[12px] font-bold text-white">{i + 1}</span>
              <span className="pt-0.5">{step}</span>
            </li>
          ))}
        </ol>
      </div>
      <div className="mt-5 flex flex-wrap gap-2">
        {info.scopes.map((s) => (
          <span key={s.key} className={cx("inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium",
            s.sensitive ? "bg-accent-soft text-accent-deep" : "bg-fill-2 text-text-2")}>
            <Icon name={SCOPE_ICON[s.key] || "check"} size={13} />{t(`scopes.${s.key}`)}
          </span>
        ))}
      </div>
      <p className="mt-2 text-xs text-muted">{t("scopesNote")}</p>
    </Card>
  );
}

const SCOPE_ICON: Record<string, string> = {
  read: "visibility",
  write: "bolt",
  publish: "send",
  inbox: "forum",
};

function useWhen() {
  const format = useFormatter();
  return (value: string) => format.dateTime(new Date(value), { dateStyle: "medium" });
}

function AppsCard() {
  const t = useTranslations("connect.page");
  const qc = useQueryClient();
  const when = useWhen();
  const format = useFormatter();
  const apps = useQuery({ queryKey: ["connect-apps"], queryFn: () => api.get<ConnectedApp[]>("/connect/apps") });
  const [confirm, setConfirm] = useState<ConnectedApp | null>(null);
  const disconnect = useMutation({
    mutationFn: (id: number) => api.delete(`/connect/apps/${id}`),
    onSuccess: () => { setConfirm(null); toast.success(t("disconnected")); qc.invalidateQueries({ queryKey: ["connect-apps"] }); },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
  return (
    <Card>
      <SectionTitle icon="apps">{t("appsTitle")}</SectionTitle>
      {apps.isLoading ? <div className="flex justify-center py-6"><Spinner /></div> : !apps.data?.length ? (
        <EmptyState icon="smart_toy" title={t("appsEmpty")} text={t("appsEmptyText")} />
      ) : (
        <ul className="divide-y divide-line">
          {apps.data.map((app) => (
            <li key={app.id} className="flex flex-wrap items-center gap-3 py-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-ink text-sm font-bold text-white">{(app.client_name[0] || "?").toUpperCase()}</span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5 text-sm font-semibold">
                  {app.client_name}
                  {app.client_host && <span className="font-mono text-[11.5px] font-normal text-muted" dir="ltr">{app.client_host}</span>}
                </div>
                <div className="mt-0.5 text-xs text-muted">
                  {t("connectedOn", { date: when(app.created_at) })}{!app.mine && ` · ${t("by", { name: app.user_name })}`} · {app.last_used_at ? t("lastUsed", { when: format.relativeTime(new Date(app.last_used_at), new Date()) }) : t("neverUsed")}
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {app.scopes.map((s) => <Badge key={s} tone={s === "publish" || s === "inbox" ? "warn" : "neutral"}>{t(`scopes.${s}`)}</Badge>)}
                </div>
              </div>
              <Button size="sm" variant="danger" icon="link_off" onClick={() => setConfirm(app)}>{t("disconnect")}</Button>
            </li>
          ))}
        </ul>
      )}
      <Modal open={!!confirm} onClose={() => setConfirm(null)} title={t("disconnect")} size="sm"
        footer={<>
          <Button variant="ghost" onClick={() => setConfirm(null)}>{t("cancel")}</Button>
          <Button variant="danger" loading={disconnect.isPending} onClick={() => confirm && disconnect.mutate(confirm.id)}>{t("disconnect")}</Button>
        </>}>
        <p className="text-sm text-text-2">{confirm && t("disconnectConfirm", { name: confirm.client_name })}</p>
      </Modal>
    </Card>
  );
}

function KeysCard({ info }: { info: Info }) {
  const t = useTranslations("connect.page");
  const qc = useQueryClient();
  const when = useWhen();
  const can = useSession((s) => s.can);
  const isAdmin = can("admin");
  const keys = useQuery({ queryKey: ["connect-keys"], queryFn: () => api.get<ApiKey[]>("/connect/keys"), enabled: isAdmin });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", scopes: ["read"], expires_days: 90 });
  const [created, setCreated] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const onError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : String(err));
  const create = useMutation({
    mutationFn: () => api.post<{ key: string }>("/connect/keys", form),
    onSuccess: (out) => {
      setOpen(false);
      setCreated(out.key);
      setForm({ name: "", scopes: ["read"], expires_days: 90 });
      qc.invalidateQueries({ queryKey: ["connect-keys"] });
    },
    onError,
  });
  const revoke = useMutation({
    mutationFn: (id: number) => api.delete(`/connect/keys/${id}`),
    onSuccess: () => { setRevoking(null); toast.success(t("revoked")); qc.invalidateQueries({ queryKey: ["connect-keys"] }); },
    onError,
  });
  const toggle = (key: string) => setForm((f) => ({ ...f, scopes: f.scopes.includes(key) ? f.scopes.filter((s) => s !== key) : [...f.scopes, key] }));

  return (
    <Card>
      <SectionTitle icon="key" actions={isAdmin && info.plan_ok && <Button size="sm" variant="primary" icon="add" onClick={() => setOpen(true)}>{t("newKey")}</Button>}>
        {t("keysTitle")}
      </SectionTitle>
      <p className="max-w-2xl text-sm leading-relaxed text-text-2">{t("keysText")}</p>
      {!isAdmin ? <p className="mt-3 text-sm text-muted">{t("adminOnly")}</p> : keys.isLoading ? <div className="flex justify-center py-6"><Spinner /></div> : !keys.data?.length ? (
        <p className="mt-4 rounded-2xl border border-dashed border-line p-4 text-center text-sm text-muted">{t("keysEmpty")}</p>
      ) : (
        <ul className="mt-3 divide-y divide-line">
          {keys.data.map((key) => (
            <li key={key.id} className="flex flex-wrap items-center gap-3 py-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-fill-2 text-text-2"><Icon name="key" size={18} /></span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-sm font-semibold">
                  {key.name}
                  <code className="rounded-md bg-fill-2 px-1.5 py-0.5 font-mono text-[11.5px] font-normal text-text-2" dir="ltr">{key.prefix}…</code>
                  {key.expired && <Badge tone="bad">{t("expired")}</Badge>}
                </div>
                <div className="mt-0.5 text-xs text-muted">
                  {key.user_name} · {t("expires", { date: when(key.expires_at) })} · {key.last_used_at ? t("lastUsedOn", { date: when(key.last_used_at) }) : t("neverUsed")}
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {key.scopes.map((s) => <Badge key={s} tone={s === "publish" || s === "inbox" ? "warn" : "neutral"}>{t(`scopes.${s}`)}</Badge>)}
                </div>
              </div>
              <Button size="sm" variant="danger" icon="delete" onClick={() => setRevoking(key)}>{t("revoke")}</Button>
            </li>
          ))}
        </ul>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title={t("newKey")}
        footer={<>
          <Button variant="ghost" onClick={() => setOpen(false)}>{t("cancel")}</Button>
          <Button variant="primary" icon="key" loading={create.isPending} disabled={!form.name.trim()} onClick={() => create.mutate()}>{t("create")}</Button>
        </>}>
        <div className="flex flex-col gap-4">
          <Field label={t("keyName")}>
            <Input value={form.name} maxLength={120} placeholder={t("keyNamePlaceholder")} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label={t("keyScopes")}>
            <div className="flex flex-col gap-2">
              {info.scopes.map((s) => (
                <label key={s.key} className="flex cursor-pointer items-start gap-2.5 rounded-xl border border-line bg-white p-3">
                  <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[#ff3d8b]" checked={s.key === "read" || form.scopes.includes(s.key)}
                    disabled={s.key === "read"} onChange={() => toggle(s.key)} />
                  <span className="text-sm">
                    <b className="font-semibold">{t(`scopes.${s.key}`)}</b>
                    <span className="block text-[13px] text-muted">{s.label}</span>
                  </span>
                </label>
              ))}
            </div>
          </Field>
          <Field label={t("keyExpiry")}>
            <Segmented value={form.expires_days} onChange={(v) => setForm({ ...form, expires_days: v })}
              options={info.key_days.map((n) => ({ value: n, label: t("days", { n }) }))} />
          </Field>
        </div>
      </Modal>

      <Modal open={!!created} onClose={() => setCreated(null)} title={t("keyCreatedTitle")}
        footer={<Button variant="primary" onClick={() => setCreated(null)}>{t("done")}</Button>}>
        <p className="mb-3 flex items-start gap-2 rounded-2xl bg-warn-bg p-3 text-[13px] text-warn">
          <Icon name="warning" size={16} className="mt-px shrink-0" />{t("keyCreatedText")}
        </p>
        {created && <CopyField value={created} />}
      </Modal>

      <Modal open={!!revoking} onClose={() => setRevoking(null)} title={t("revoke")} size="sm"
        footer={<>
          <Button variant="ghost" onClick={() => setRevoking(null)}>{t("cancel")}</Button>
          <Button variant="danger" loading={revoke.isPending} onClick={() => revoking && revoke.mutate(revoking.id)}>{t("revoke")}</Button>
        </>}>
        <p className="text-sm text-text-2">{revoking && t("revokeConfirm", { name: revoking.name })}</p>
      </Modal>
    </Card>
  );
}
