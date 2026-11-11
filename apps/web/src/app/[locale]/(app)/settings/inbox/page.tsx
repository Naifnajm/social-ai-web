"use client";
/** Settings › Inbox & assistant: per-account assistant modes, webhooks, WhatsApp numbers, knowledge base,
 * canned replies and comment-to-DM triggers. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import { Badge, Button, Card, EmptyState, Field, IconButton, Input, Modal, SectionTitle, Segmented, Select, Switch, Textarea, cx, toast } from "@/components/ui";
import { api } from "@/lib/api";
import { copyText, showError } from "../../inbox/_components/bits";
import type { BotMode, BotSettings, Canned, HistoryResult, InboxAccount, InboxSettings, Knowledge, Trigger } from "../../inbox/_lib/types";

const ACCOUNTS_KEY = ["inbox", "accounts"];

export default function InboxSettingsPage() {
  return (
    <div className="flex flex-col gap-4">
      <AccountsSection />
      <GeneralSection />
      <KnowledgeSection />
      <CannedSection />
      <TriggersSection />
    </div>
  );
}

// ====================================================================== accounts
function AccountsSection() {
  const t = useTranslations("inbox");
  const accounts = useQuery({ queryKey: ACCOUNTS_KEY, queryFn: () => api.get<InboxAccount[]>("/inbox/accounts") });
  const [waOpen, setWaOpen] = useState(false);
  return (
    <Card>
      <SectionTitle icon="smart_toy" actions={<Button size="sm" icon="add" className="whitespace-nowrap" onClick={() => setWaOpen(true)}>{t("settings.addWhatsapp")}</Button>}>
        {t("settings.accountsTitle")}
      </SectionTitle>
      <p className="-mt-1 mb-3 text-sm text-muted">{t("settings.accountsHelp")}</p>
      {!accounts.isLoading && !accounts.data?.length && <EmptyState icon="forum" title={t("settings.noAccounts")} text={t("noAccountsText")} />}
      <ul className="flex flex-col gap-2">
        {accounts.data?.map((a) => <AccountRow key={a.id} account={a} />)}
      </ul>
      <WhatsAppModal open={waOpen} onClose={() => setWaOpen(false)} />
    </Card>
  );
}

function AccountRow({ account }: { account: InboxAccount }) {
  const t = useTranslations("inbox");
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [bot, setBot] = useState<BotSettings>(account.bot);
  const [busy, setBusy] = useState<string | null>(null);
  const isMeta = account.platform === "facebook" || account.platform === "instagram";

  const save = async (values: Record<string, unknown>, key = "save") => {
    setBusy(key);
    try {
      const out = await api.patch<InboxAccount>(`/inbox/accounts/${account.id}`, values);
      qc.setQueryData<InboxAccount[]>(ACCOUNTS_KEY, (list) => list?.map((a) => (a.id === out.id ? out : a)));
      qc.invalidateQueries({ queryKey: ["inbox", "meta"] });
      if (key === "save") toast.success(t("settings.saved"));
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };
  const importHistory = async () => {
    setBusy("history");
    try {
      const out = await api.post<HistoryResult>(`/inbox/accounts/${account.id}/import-history`, { days: 90 });
      qc.invalidateQueries({ queryKey: ACCOUNTS_KEY });
      qc.invalidateQueries({ queryKey: ["inbox"] });
      qc.invalidateQueries({ queryKey: ["external-posts"] });
      toast.success(t("settings.historyDone", { messages: out.messages, comments: out.comments, posts: out.posts, scheduled: out.scheduled }));
      if (out.errors.length) toast.error(out.errors.join("; "));
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };
  const call = async (key: string, run: () => Promise<unknown>, done?: string) => {
    setBusy(key);
    try {
      await run();
      qc.invalidateQueries({ queryKey: ACCOUNTS_KEY });
      if (done) toast.success(done);
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  const modeOptions = (["off", "suggest", "auto"] as BotMode[]).map((m) => ({ value: m, label: t(`settings.modes.${m}`) }));
  const stateTone = account.state === "connected" ? "ok" : account.state === "draft" ? "neutral" : "bad";

  return (
    <li className="rounded-2xl border border-line bg-white/50">
      <div className="flex items-center gap-3 p-3">
        <PlatformBadge platform={account.platform} size={34} />
        <button className="min-w-0 flex-1 text-start" onClick={() => setOpen((o) => !o)}>
          <div className="bidi truncate text-sm font-semibold">{account.name}</div>
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
            <Badge tone={stateTone}>{t(`settings.states.${account.state}`)}</Badge>
            <span>{t("settings.dmShort")}: {t(`settings.modes.${account.bot.mode}`)}</span>
            {isMeta && <span>· {t("settings.commentsShort")}: {t(`settings.modes.${account.bot.comment_mode}`)}</span>}
          </div>
        </button>
        <Switch checked={account.inbox_enabled} onChange={(v) => save({ inbox_enabled: v }, "enabled")} label={<span className="hidden text-xs text-muted sm:inline">{t("settings.inboxOn")}</span>} />
        <IconButton icon={open ? "expand_less" : "expand_more"} label={t("settings.details")} onClick={() => setOpen((o) => !o)} />
      </div>
      {open && (
        <div className="grid grid-cols-1 gap-4 border-t border-line p-4 md:grid-cols-2 [&>*]:min-w-0">
          <Field label={t("settings.dmMode")} hint={t("settings.modeHelp")}>
            <Segmented size="sm" value={bot.mode} onChange={(mode) => setBot({ ...bot, mode })} options={modeOptions} />
          </Field>
          {isMeta && (
            <Field label={t("settings.commentMode")}>
              <Segmented size="sm" value={bot.comment_mode} onChange={(comment_mode) => setBot({ ...bot, comment_mode })} options={modeOptions} />
            </Field>
          )}
          <Field label={t("settings.confidence", { value: bot.confidence })} hint={t("settings.confidenceHelp")}>
            <input type="range" min={0} max={100} step={5} value={bot.confidence} onChange={(e) => setBot({ ...bot, confidence: Number(e.target.value) })}
              className="w-full accent-black" />
          </Field>
          <Field label={t("settings.when")}>
            <div className="flex flex-wrap items-center gap-2">
              <Select className="!w-auto flex-1" value={bot.when} onChange={(e) => setBot({ ...bot, when: e.target.value as BotSettings["when"] })}>
                {(["always", "office_hours", "outside_hours"] as const).map((w) => <option key={w} value={w}>{t(`settings.whenOptions.${w}`)}</option>)}
              </Select>
              {bot.when !== "always" && (
                <span className="flex items-center gap-1 text-xs text-muted" dir="ltr">
                  <Input type="number" min={0} max={24} step={0.5} className="!h-9 !w-16" value={bot.hour_from} onChange={(e) => setBot({ ...bot, hour_from: Number(e.target.value) })} />
                  –
                  <Input type="number" min={0} max={24} step={0.5} className="!h-9 !w-16" value={bot.hour_to} onChange={(e) => setBot({ ...bot, hour_to: Number(e.target.value) })} />
                </span>
              )}
            </div>
          </Field>
          {isMeta && (
            <div className="flex flex-col gap-2 md:col-span-2">
              <Switch checked={bot.hide_offensive} onChange={(v) => setBot({ ...bot, hide_offensive: v })} label={t("settings.hideOffensive")} />
              <Switch checked={bot.private_reply} onChange={(v) => setBot({ ...bot, private_reply: v })} label={t("settings.privateReply")} />
            </div>
          )}
          <Field label={t("settings.instructions")} hint={t("settings.instructionsHelp")} className="md:col-span-2">
            <Textarea rows={2} value={bot.instructions} onChange={(e) => setBot({ ...bot, instructions: e.target.value })} />
          </Field>

          {account.webhook_url && (
            <div className="md:col-span-2">
              <div className="mb-1.5 text-[13px] font-medium text-text-2">{t(`settings.webhook.${account.webhook_kind}`)}</div>
              <CopyRow value={account.webhook_url} />
              {account.platform === "telegram" && (
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
                  <Badge tone={account.telegram_webhook_active ? "ok" : "neutral"}>
                    {account.telegram_webhook_active ? t("settings.telegramInstant") : t("settings.telegramPolling")}
                  </Badge>
                  {account.telegram_webhook_active ? (
                    <Button size="sm" variant="ghost" loading={busy === "tgoff"} onClick={() => call("tgoff", () => api.delete(`/inbox/accounts/${account.id}/telegram-webhook`))}>{t("settings.telegramRemove")}</Button>
                  ) : (
                    <Button size="sm" loading={busy === "tgon"} onClick={() => call("tgon", () => api.post(`/inbox/accounts/${account.id}/telegram-webhook`), t("settings.telegramSet"))}>{t("settings.telegramEnable")}</Button>
                  )}
                  <Button size="sm" variant="ghost" icon="refresh" loading={busy === "rotate"} onClick={() => call("rotate", () => api.post(`/inbox/accounts/${account.id}/rotate-secret`))}>{t("settings.rotateSecret")}</Button>
                </div>
              )}
            </div>
          )}
          {isMeta && (
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted md:col-span-2">
              <Badge tone={account.webhook_ok ? "ok" : account.webhook_ok === false ? "bad" : "neutral"}>
                {account.webhook_ok ? t("settings.webhookOk") : account.webhook_ok === false ? t("settings.webhookMissing") : t("settings.webhookUnknown")}
              </Badge>
              {account.webhook_ok === false && account.webhook_error && <span className="bidi text-bad">{account.webhook_error}</span>}
              <Button size="sm" variant="ghost" icon="verified" loading={busy === "whcheck"} onClick={() => call("whcheck", () => api.post(`/inbox/accounts/${account.id}/webhook/check`), t("settings.webhookChecked"))}>{t("settings.webhookCheck")}</Button>
              <Button size="sm" variant="ghost" icon="link" loading={busy === "whsub"} onClick={() => call("whsub", () => api.post(`/inbox/accounts/${account.id}/webhook/subscribe`), t("settings.webhookSubscribed"))}>{t("settings.webhookSubscribe")}</Button>
              <Button size="sm" variant="ghost" icon="history" loading={busy === "history"} onClick={importHistory}>{t("settings.importHistory")}</Button>
            </div>
          )}
          {account.sync_error && <p className="bidi text-xs text-bad md:col-span-2"><Icon name="error" size={13} /> {account.sync_error}</p>}
          <div className="flex flex-wrap items-center justify-end gap-2 md:col-span-2">
            {account.platform === "whatsapp" && (
              <Button size="sm" variant="ghost" icon="verified" loading={busy === "check"} onClick={() => call("check", () => api.post(`/inbox/whatsapp-accounts/${account.id}/check`), t("settings.checked"))}>{t("settings.check")}</Button>
            )}
            {account.platform !== "whatsapp" && (
              <Button size="sm" variant="ghost" icon="refresh" loading={busy === "sync"} onClick={() => call("sync", () => api.post(`/inbox/accounts/${account.id}/sync`), t("settings.synced"))}>{t("sync")}</Button>
            )}
            <Button size="sm" variant="primary" loading={busy === "save"} onClick={() => save({ bot })}>{t("settings.save")}</Button>
          </div>
        </div>
      )}
    </li>
  );
}

function CopyRow({ value, secret = false }: { value: string; secret?: boolean }) {
  const t = useTranslations("inbox");
  return (
    <div className="flex items-center gap-2">
      <code dir="ltr" className={cx("min-w-0 flex-1 truncate rounded-xl bg-fill px-3 py-2 text-xs", secret && "tracking-wider")}>{value}</code>
      <IconButton icon="content_copy" label={t("settings.copy")} onClick={() => copyText(value, t("settings.copied"))} />
    </div>
  );
}

function WhatsAppModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useTranslations("inbox");
  const qc = useQueryClient();
  const empty = { name: "WhatsApp", provider: "cloud" as "cloud" | "twilio", phone_number_id: "", access_token: "", whatsapp_number: "", twilio_account_sid: "", twilio_auth_token: "" };
  const [form, setForm] = useState(empty);
  const create = useMutation({
    mutationFn: () => api.post<InboxAccount>("/inbox/whatsapp-accounts", form),
    onSuccess: (account) => {
      qc.invalidateQueries({ queryKey: ["inbox"] });
      if (account.state === "connected") toast.success(t("settings.waConnected"));
      else toast.error(t("settings.waNotVerified"));
      setForm(empty);
      onClose();
    },
    onError: showError,
  });
  const set = (key: keyof typeof empty) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  return (
    <Modal open={open} onClose={onClose} title={t("settings.addWhatsapp")}
      footer={<><Button onClick={onClose}>{t("settings.cancel")}</Button><Button variant="primary" loading={create.isPending} onClick={() => create.mutate()}>{t("settings.connect")}</Button></>}>
      <div className="flex flex-col gap-4">
        <Segmented value={form.provider} onChange={(provider) => setForm({ ...form, provider })}
          options={[{ value: "cloud", label: "WhatsApp Cloud API" }, { value: "twilio", label: "Twilio" }]} />
        <p className="text-xs text-muted">{form.provider === "cloud" ? t("settings.waCloudHelp") : t("settings.waTwilioHelp")}</p>
        <Field label={t("settings.name")}><Input value={form.name} onChange={set("name")} /></Field>
        {form.provider === "cloud" ? (
          <>
            <Field label={t("settings.phoneNumberId")}><Input dir="ltr" value={form.phone_number_id} onChange={set("phone_number_id")} /></Field>
            <Field label={t("settings.accessToken")}><Input dir="ltr" type="password" autoComplete="off" value={form.access_token} onChange={set("access_token")} /></Field>
            <Field label={t("settings.waNumberOptional")}><Input dir="ltr" placeholder="+9665…" value={form.whatsapp_number} onChange={set("whatsapp_number")} /></Field>
          </>
        ) : (
          <>
            <Field label="Account SID"><Input dir="ltr" value={form.twilio_account_sid} onChange={set("twilio_account_sid")} /></Field>
            <Field label="Auth token"><Input dir="ltr" type="password" autoComplete="off" value={form.twilio_auth_token} onChange={set("twilio_auth_token")} /></Field>
            <Field label={t("settings.waNumber")}><Input dir="ltr" placeholder="+14155238886" value={form.whatsapp_number} onChange={set("whatsapp_number")} /></Field>
          </>
        )}
      </div>
    </Modal>
  );
}

// ====================================================================== general
function GeneralSection() {
  const t = useTranslations("inbox");
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["inbox", "settings"], queryFn: () => api.get<InboxSettings>("/inbox/settings") });
  if (!settings.data) return null;
  return <GeneralForm key={settings.dataUpdatedAt} initial={settings.data} onSaved={(s) => qc.setQueryData(["inbox", "settings"], s)} t={t} />;
}

function GeneralForm({ initial, onSaved, t }: { initial: InboxSettings; onSaved: (s: InboxSettings) => void; t: ReturnType<typeof useTranslations> }) {
  const [form, setForm] = useState({ ...initial, meta_app_id: initial.meta_app_id || "", meta_app_secret: "" });
  const [busy, setBusy] = useState(false);
  const save = async (extra?: Record<string, unknown>) => {
    setBusy(true);
    try {
      const body: Record<string, unknown> = {
        handover_message: form.handover_message, private_ack: form.private_ack, human_agent_tag: form.human_agent_tag,
        create_contacts: form.create_contacts, company_info: form.company_info, ...extra,
      };
      if (!form.platform_meta_app || form.meta_app_id) body.meta_app_id = form.meta_app_id;
      if (form.meta_app_secret) body.meta_app_secret = form.meta_app_secret;
      onSaved(await api.put<InboxSettings>("/inbox/settings", body));
      toast.success(t("settings.saved"));
    } catch (err) {
      showError(err);
    } finally {
      setBusy(false);
    }
  };
  const rotate = async () => {
    try {
      onSaved(await api.post<InboxSettings>("/inbox/settings/rotate-verify-token"));
    } catch (err) {
      showError(err);
    }
  };
  return (
    <Card>
      <SectionTitle icon="settings">{t("settings.generalTitle")}</SectionTitle>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 [&>*]:min-w-0">
        <Field label={t("settings.handoverMessage")} hint={t("settings.handoverHelp")}>
          <Textarea rows={2} value={form.handover_message} onChange={(e) => setForm({ ...form, handover_message: e.target.value })} />
        </Field>
        <Field label={t("settings.privateAck")} hint={t("settings.privateAckHelp")}>
          <Textarea rows={2} value={form.private_ack} onChange={(e) => setForm({ ...form, private_ack: e.target.value })} />
        </Field>
        <Field label={t("settings.companyInfo")} hint={t("settings.companyInfoHelp")} className="md:col-span-2">
          <Textarea rows={3} value={form.company_info} onChange={(e) => setForm({ ...form, company_info: e.target.value })} />
        </Field>
        <div className="flex flex-col gap-2 md:col-span-2">
          <Switch checked={form.human_agent_tag} onChange={(v) => setForm({ ...form, human_agent_tag: v })} label={t("settings.humanAgent")} />
          <p className="-mt-1 ps-12 text-xs text-muted">{t("settings.humanAgentHelp")}</p>
          <Switch checked={form.create_contacts} onChange={(v) => setForm({ ...form, create_contacts: v })} label={t("settings.createContacts")} />
        </div>
      </div>

      <div className="mt-5 rounded-2xl border border-line bg-white/50 p-4">
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><Icon name="link" size={16} />{t("settings.metaTitle")}</div>
        <p className="mb-3 text-xs text-muted">{form.platform_meta_app ? t("settings.metaManaged") : t("settings.metaOwnApp")}</p>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 [&>*]:min-w-0">
          <Field label={t("settings.callbackUrl")} className="md:col-span-2"><CopyRow value={form.meta_webhook_url} /></Field>
          <Field label={t("settings.metaAppId")}>
            <Input dir="ltr" value={form.meta_app_id} onChange={(e) => setForm({ ...form, meta_app_id: e.target.value })} />
          </Field>
          <Field label={t("settings.metaAppSecret")} hint={form.has_meta_app_secret ? t("settings.secretSaved") : undefined}>
            <Input dir="ltr" type="password" autoComplete="off" placeholder={form.has_meta_app_secret ? "••••••••" : ""} value={form.meta_app_secret}
              onChange={(e) => setForm({ ...form, meta_app_secret: e.target.value })} />
          </Field>
          {form.meta_verify_token && (
            <Field label={t("settings.verifyToken")} className="md:col-span-2">
              <div className="flex items-center gap-1">
                <div className="min-w-0 flex-1"><CopyRow value={form.meta_verify_token} secret /></div>
                <IconButton icon="refresh" label={t("settings.rotateSecret")} onClick={rotate} />
              </div>
            </Field>
          )}
        </div>
      </div>
      <div className="mt-4 flex justify-end"><Button variant="primary" loading={busy} onClick={() => save()}>{t("settings.save")}</Button></div>
    </Card>
  );
}

// ====================================================================== knowledge
function KnowledgeSection() {
  const t = useTranslations("inbox");
  const [editing, setEditing] = useState<Partial<Knowledge> | null>(null);
  const crud = useCrud<Knowledge>("/inbox/knowledge", ["inbox", "knowledge"]);
  return (
    <Card>
      <SectionTitle icon="menu_book" actions={<Button size="sm" icon="add" onClick={() => setEditing({ title: "", content: "", active: true, sequence: 10 })}>{t("settings.add")}</Button>}>
        {t("settings.knowledgeTitle")}
      </SectionTitle>
      <p className="-mt-1 mb-3 text-sm text-muted">{t("settings.knowledgeHelp")}</p>
      {!crud.list.data?.length && !crud.list.isLoading && <p className="rounded-xl bg-fill px-3 py-4 text-center text-sm text-muted">{t("settings.knowledgeEmpty")}</p>}
      <ul className="divide-y divide-line">
        {crud.list.data?.map((k) => (
          <li key={k.id} className="flex items-start gap-3 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="bidi text-sm font-semibold">{k.title} {!k.active && <Badge>{t("settings.inactive")}</Badge>}</div>
              <div className="bidi line-clamp-2 text-xs text-muted">{k.content}</div>
            </div>
            <IconButton icon="edit_square" label={t("edit")} onClick={() => setEditing(k)} />
            <IconButton icon="delete" label={t("remove")} onClick={() => crud.remove.mutate(k.id)} />
          </li>
        ))}
      </ul>
      <Modal open={!!editing} onClose={() => setEditing(null)} title={t("settings.knowledgeTitle")}
        footer={<><Button onClick={() => setEditing(null)}>{t("settings.cancel")}</Button><Button variant="primary" loading={crud.save.isPending}
          onClick={() => editing && crud.save.mutate(editing, { onSuccess: () => setEditing(null) })}>{t("settings.save")}</Button></>}>
        {editing && (
          <div className="flex flex-col gap-4">
            <Field label={t("settings.knowledgeTitleField")}><Input value={editing.title} placeholder={t("settings.knowledgeTitlePh")} onChange={(e) => setEditing({ ...editing, title: e.target.value })} /></Field>
            <Field label={t("settings.knowledgeContent")}><Textarea rows={6} value={editing.content} onChange={(e) => setEditing({ ...editing, content: e.target.value })} /></Field>
            <Switch checked={editing.active ?? true} onChange={(v) => setEditing({ ...editing, active: v })} label={t("settings.active")} />
          </div>
        )}
      </Modal>
    </Card>
  );
}

// ====================================================================== canned replies
function CannedSection() {
  const t = useTranslations("inbox");
  const [editing, setEditing] = useState<Partial<Canned> | null>(null);
  const crud = useCrud<Canned>("/inbox/canned-replies", ["inbox", "canned"]);
  return (
    <Card>
      <SectionTitle icon="bolt" actions={<Button size="sm" icon="add" onClick={() => setEditing({ name: "", body: "", shortcut: "", active: true, sequence: 10 })}>{t("settings.add")}</Button>}>
        {t("cannedReplies")}
      </SectionTitle>
      <p className="-mt-1 mb-3 text-sm text-muted">{t("settings.cannedHelp")}</p>
      {!crud.list.data?.length && !crud.list.isLoading && <p className="rounded-xl bg-fill px-3 py-4 text-center text-sm text-muted">{t("noCanned")}</p>}
      <ul className="divide-y divide-line">
        {crud.list.data?.map((c) => (
          <li key={c.id} className="flex items-start gap-3 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-sm font-semibold"><span className="bidi">{c.name}</span>
                {c.shortcut && <span className="rounded-md bg-fill-2 px-1.5 text-[11px] font-medium text-muted" dir="ltr">/{c.shortcut}</span>}</div>
              <div className="bidi line-clamp-2 text-xs text-muted">{c.body}</div>
            </div>
            <IconButton icon="edit_square" label={t("edit")} onClick={() => setEditing(c)} />
            <IconButton icon="delete" label={t("remove")} onClick={() => crud.remove.mutate(c.id)} />
          </li>
        ))}
      </ul>
      <Modal open={!!editing} onClose={() => setEditing(null)} title={t("cannedReplies")}
        footer={<><Button onClick={() => setEditing(null)}>{t("settings.cancel")}</Button><Button variant="primary" loading={crud.save.isPending}
          onClick={() => editing && crud.save.mutate({ ...editing, shortcut: editing.shortcut || null }, { onSuccess: () => setEditing(null) })}>{t("settings.save")}</Button></>}>
        {editing && (
          <div className="flex flex-col gap-4">
            <Field label={t("settings.name")}><Input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></Field>
            <Field label={t("settings.shortcut")} hint={t("settings.shortcutHelp")}><Input dir="ltr" value={editing.shortcut || ""} placeholder="hours" onChange={(e) => setEditing({ ...editing, shortcut: e.target.value })} /></Field>
            <Field label={t("settings.body")} hint={t("settings.nameVar")}><Textarea rows={4} value={editing.body} onChange={(e) => setEditing({ ...editing, body: e.target.value })} /></Field>
          </div>
        )}
      </Modal>
    </Card>
  );
}

// ====================================================================== triggers
function TriggersSection() {
  const t = useTranslations("inbox");
  const [editing, setEditing] = useState<Partial<Trigger> | null>(null);
  const crud = useCrud<Trigger>("/inbox/triggers", ["inbox", "triggers"]);
  const accounts = useQuery({ queryKey: ACCOUNTS_KEY, queryFn: () => api.get<InboxAccount[]>("/inbox/accounts") });
  const metaAccounts = (accounts.data || []).filter((a) => a.platform === "facebook" || a.platform === "instagram");
  return (
    <Card>
      <SectionTitle icon="campaign" actions={<Button size="sm" icon="add" onClick={() => setEditing({ name: "", keywords: "", public_reply: "", dm_text: "", account_ids: [], active: true, sequence: 10 })}>{t("settings.add")}</Button>}>
        {t("settings.triggersTitle")}
      </SectionTitle>
      <p className="-mt-1 mb-3 text-sm text-muted">{t("settings.triggersHelp")}</p>
      {!crud.list.data?.length && !crud.list.isLoading && <p className="rounded-xl bg-fill px-3 py-4 text-center text-sm text-muted">{t("settings.triggersEmpty")}</p>}
      <ul className="divide-y divide-line">
        {crud.list.data?.map((tr) => (
          <li key={tr.id} className="flex items-start gap-3 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 text-sm font-semibold"><span className="bidi">{tr.name}</span>
                {!tr.active && <Badge>{t("settings.inactive")}</Badge>}
                <Badge tone="ink">{t("settings.used", { count: tr.hit_count })}</Badge></div>
              <div className="bidi truncate text-xs text-muted">{tr.keywords}</div>
            </div>
            <IconButton icon="edit_square" label={t("edit")} onClick={() => setEditing(tr)} />
            <IconButton icon="delete" label={t("remove")} onClick={() => crud.remove.mutate(tr.id)} />
          </li>
        ))}
      </ul>
      <Modal open={!!editing} onClose={() => setEditing(null)} title={t("settings.triggersTitle")}
        footer={<><Button onClick={() => setEditing(null)}>{t("settings.cancel")}</Button><Button variant="primary" loading={crud.save.isPending}
          onClick={() => editing && crud.save.mutate(editing, { onSuccess: () => setEditing(null) })}>{t("settings.save")}</Button></>}>
        {editing && (
          <div className="flex flex-col gap-4">
            <Field label={t("settings.name")}><Input value={editing.name} placeholder={t("settings.triggerNamePh")} onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></Field>
            <Field label={t("settings.keywords")} hint={t("settings.keywordsHelp")}><Input value={editing.keywords} placeholder="price, سعر, السعر" onChange={(e) => setEditing({ ...editing, keywords: e.target.value })} /></Field>
            <Field label={t("settings.publicReply")} hint={t("settings.nameVar")}><Textarea rows={2} value={editing.public_reply || ""} onChange={(e) => setEditing({ ...editing, public_reply: e.target.value })} /></Field>
            <Field label={t("settings.dmText")} hint={t("settings.nameVar")}><Textarea rows={3} value={editing.dm_text || ""} onChange={(e) => setEditing({ ...editing, dm_text: e.target.value })} /></Field>
            <Field label={t("settings.triggerAccounts")} hint={t("settings.triggerAccountsHelp")}>
              <div className="flex flex-wrap gap-1.5">
                {metaAccounts.map((a) => {
                  const on = (editing.account_ids || []).includes(a.id);
                  return (
                    <button key={a.id} type="button" onClick={() => setEditing({ ...editing, account_ids: on ? editing.account_ids!.filter((x) => x !== a.id) : [...(editing.account_ids || []), a.id] })}
                      className={cx("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs", on ? "border-ink bg-ink text-white" : "border-line text-text-2")}>
                      <PlatformBadge platform={a.platform} size={16} /><span className="bidi">{a.name}</span>
                    </button>
                  );
                })}
              </div>
            </Field>
            <Switch checked={editing.active ?? true} onChange={(v) => setEditing({ ...editing, active: v })} label={t("settings.active")} />
          </div>
        )}
      </Modal>
    </Card>
  );
}

// ====================================================================== helpers
function useCrud<T extends { id: number }>(path: string, key: string[]) {
  const qc = useQueryClient();
  const t = useTranslations("inbox");
  const list = useQuery({ queryKey: key, queryFn: () => api.get<T[]>(path) });
  const save = useMutation({
    mutationFn: (item: Partial<T>) => {
      const { id, ...body } = item as Partial<T> & { id?: number };
      return id ? api.put<T>(`${path}/${id}`, body) : api.post<T>(path, body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: ["inbox", "meta"] });
      toast.success(t("settings.saved"));
    },
    onError: showError,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`${path}/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: ["inbox", "meta"] });
    },
    onError: showError,
  });
  return { list, save, remove };
}
