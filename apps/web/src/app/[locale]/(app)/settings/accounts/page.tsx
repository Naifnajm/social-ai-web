"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useEffect, useState } from "react";
import { Icon } from "@/components/icon";
import { ConnectDialog } from "@/components/publishing/connect-dialog";
import type { Account } from "@/components/publishing/types";
import { AccountAvatar, errorText, stateTone, useFormat } from "@/components/publishing/util";
import { Badge, Button, Card, EmptyState, Field, IconButton, Input, Modal, SectionTitle, Select, Spinner, Switch, toast } from "@/components/ui";
import { usePathname, useRouter } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

function AccountsSettings() {
  const t = useTranslations("publishing.accounts");
  const qc = useQueryClient();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const fmt = useFormat();
  const isAdmin = useSession((s) => s.can("admin"));
  const [connectOpen, setConnectOpen] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const [confirm, setConfirm] = useState<Account | null>(null);
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<Account[]>("/accounts") });
  const approvals = useQuery({ queryKey: ["approval-settings"], queryFn: () => api.get<{ required: boolean }>("/approvals/settings") });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["accounts"] });
    qc.invalidateQueries({ queryKey: ["studio"] });
  };

  // back from the network's consent page
  useEffect(() => {
    const connected = params.get("connected");
    const error = params.get("error");
    if (!connected && !error) return;
    if (connected) toast.success(t("connectedCount", { count: Number(connected) }));
    if (error) toast.error(error);
    router.replace(pathname);
  }, [params, router, pathname, t]);

  const test = useMutation({
    mutationFn: (id: number) => api.post<{ ok: boolean; message?: string }>(`/accounts/${id}/test`),
    onSuccess: (res) => { refresh(); if (res.ok) toast.success(res.message || t("ok")); else toast.error(res.message || t("failed")); },
    onError: (err) => toast.error(errorText(err)),
  });
  const sync = useMutation({
    mutationFn: (id: number) => api.post<{ posts: number; accounts: number }>(`/accounts/${id}/sync`),
    onSuccess: (res) => { refresh(); toast.success(t("synced", { posts: res.posts })); },
    onError: (err) => toast.error(errorText(err)),
  });
  const disconnect = useMutation({
    mutationFn: (id: number) => api.delete(`/accounts/${id}`),
    onSuccess: () => { setConfirm(null); refresh(); toast.success(t("disconnected")); },
    onError: (err) => toast.error(errorText(err)),
  });
  const setApprovals = useMutation({
    mutationFn: (required: boolean) => api.put("/approvals/settings", { required }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["approval-settings"] }); qc.invalidateQueries({ queryKey: ["studio"] }); toast.success(t("saved")); },
    onError: (err) => toast.error(errorText(err)),
  });

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <SectionTitle icon="link" actions={isAdmin && <Button variant="primary" size="sm" icon="add" onClick={() => setConnectOpen(true)}>{t("connect")}</Button>}>
          {t("title")}
        </SectionTitle>
        {accounts.isLoading ? (
          <div className="flex justify-center py-10"><Spinner /></div>
        ) : !accounts.data?.length ? (
          <EmptyState icon="link" title={t("emptyTitle")} text={t("emptyText")}
            action={isAdmin && <Button variant="primary" icon="add" onClick={() => setConnectOpen(true)}>{t("connect")}</Button>} />
        ) : (
          <ul className="divide-y divide-line">
            {accounts.data.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-3 py-3">
                <AccountAvatar name={a.name} src={a.avatar_url} platform={a.platform} size={40} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="bidi truncate text-sm font-semibold">{a.name}</span>
                    <Badge tone={stateTone(a.state)}>{t(`state.${a.state}`)}</Badge>
                    {a.inbox_only && <Badge tone="neutral"><Icon name="inbox" size={12} />{t("inboxOnly")}</Badge>}
                    {a.oauth_app === "workspace" && <Badge>{t("ownApp")}</Badge>}
                  </div>
                  <div className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-muted">
                    <span>{a.platform_label}</span>
                    {a.username && <span dir="ltr">@{a.username.replace(/^@/, "")}</span>}
                    {!a.inbox_only && <span>{t("followers", { count: fmt.compact(a.followers) })}</span>}
                    {a.token_expires_at && !a.can_refresh && <span>{t("expires", { date: fmt.date(a.token_expires_at) })}</span>}
                  </div>
                  {a.last_error && a.state !== "connected" && <div className="bidi mt-1 text-xs text-bad">{a.last_error}</div>}
                </div>
                {!a.inbox_only && (
                  <div className="flex items-center gap-0.5">
                    {isAdmin && (a.state === "expired" || a.state === "error") && (
                      <Button size="sm" icon="refresh" onClick={() => setConnectOpen(true)}>{t("reconnect")}</Button>
                    )}
                    <IconButton icon="sync_alt" label={t("sync")} disabled={sync.isPending} onClick={() => sync.mutate(a.id)} />
                    {isAdmin && <IconButton icon="verified" label={t("test")} disabled={test.isPending} onClick={() => test.mutate(a.id)} />}
                    {isAdmin && <IconButton icon="edit_square" label={t("edit")} onClick={() => setEditing(a)} />}
                    {isAdmin && <IconButton icon="link_off" label={t("disconnect")} onClick={() => setConfirm(a)} />}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <SectionTitle icon="verified_user">{t("approvalsTitle")}</SectionTitle>
        <div className="flex flex-wrap items-center gap-4">
          <p className="min-w-0 flex-1 text-sm text-muted">{t("approvalsText")}</p>
          <Switch checked={!!approvals.data?.required} disabled={!isAdmin || setApprovals.isPending} onChange={(v) => setApprovals.mutate(v)} label={t("approvalsSwitch")} />
        </div>
      </Card>

      <ConnectDialog open={connectOpen} onClose={() => setConnectOpen(false)} />
      {editing && <EditAccount account={editing} onClose={() => { setEditing(null); refresh(); }} />}
      <Modal open={!!confirm} onClose={() => setConfirm(null)} size="sm" title={t("disconnectTitle")}
        footer={<><Button onClick={() => setConfirm(null)}>{t("cancel")}</Button><Button variant="danger" loading={disconnect.isPending} onClick={() => confirm && disconnect.mutate(confirm.id)}>{t("disconnect")}</Button></>}>
        <p className="text-sm text-muted">{t("disconnectText", { name: confirm?.name ?? "" })}</p>
      </Modal>
    </div>
  );
}

function EditAccount({ account, onClose }: { account: Account; onClose: () => void }) {
  const t = useTranslations("publishing.accounts");
  const c = useTranslations("publishing.connect");
  const [form, setForm] = useState({ name: account.name, access_token: "", privacy_level: account.privacy_level || "SELF_ONLY", board_id: account.board_id || "" });
  const save = useMutation({
    mutationFn: () => api.patch(`/accounts/${account.id}`, {
      name: form.name, ...(form.access_token ? { access_token: form.access_token } : {}),
      ...(account.platform === "tiktok" ? { privacy_level: form.privacy_level } : {}),
      ...(account.platform === "pinterest" && form.board_id ? { board_id: form.board_id } : {}),
    }),
    onSuccess: () => { toast.success(t("saved")); onClose(); },
    onError: (err) => toast.error(errorText(err)),
  });
  return (
    <Modal open onClose={onClose} title={t("edit")}
      footer={<><Button onClick={onClose}>{t("cancel")}</Button><Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>{t("save")}</Button></>}>
      <div className="flex flex-col gap-4">
        <Field label={c("displayName")}><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label={c("accessToken")} hint={t("newTokenHint")}>
          <Input dir="ltr" type="password" autoComplete="off" value={form.access_token} onChange={(e) => setForm({ ...form, access_token: e.target.value })} />
        </Field>
        {account.platform === "tiktok" && (
          <Field label={c("privacy")} hint={c("privacyHint")}>
            <Select value={form.privacy_level} onChange={(e) => setForm({ ...form, privacy_level: e.target.value })}>
              {["SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "PUBLIC_TO_EVERYONE"].map((p) => <option key={p} value={p}>{c(`privacyLevels.${p}`)}</option>)}
            </Select>
          </Field>
        )}
        {account.platform === "pinterest" && (account.boards?.length ?? 0) > 0 && (
          <Field label={c("board")} hint={c("boardHint")}>
            <Select value={form.board_id} onChange={(e) => setForm({ ...form, board_id: e.target.value })}>
              {(account.boards ?? []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </Select>
          </Field>
        )}
      </div>
    </Modal>
  );
}

export default function AccountsSettingsPage() {
  return (
    <Suspense>
      <AccountsSettings />
    </Suspense>
  );
}
