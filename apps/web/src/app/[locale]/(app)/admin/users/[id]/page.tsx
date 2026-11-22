"use client";
/** Platform admin › Users › one user: everything that belongs to the account and every action on it, in tabs.
 *  Each action asks for confirmation and is recorded in the account's activity with the administrator's name. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { type ReactNode, Suspense, useState } from "react";
import { type AdminUser, UserBadges } from "@/components/account/admin-user";
import { EventLabel, device } from "@/components/account/event-label";
import { Icon } from "@/components/icon";
import { Avatar, Badge, Button, Card, EmptyState, Field, Input, Modal, SectionTitle, Select, Spinner, Switch, cx, toast } from "@/components/ui";
import { Link, usePathname, useRouter } from "@/i18n/navigation";
import { LOCALE_NAMES, routing } from "@/i18n/routing";
import { ApiError, api } from "@/lib/api";
import { formatDate } from "@/lib/billing";
import { downloadJson } from "@/lib/download";
import { useSession } from "@/lib/session";

type Blocker = { workspace_id: number; workspace_name: string; other_members: number; action: "transfer" | "delete" };
type Detail = {
  user: AdminUser; locale: string; timezone: string; avatar_url: string | null; password_changed_at: string | null;
  has_password: boolean; recovery_codes_left: number;
  workspaces: { workspace_id: number; name: string; role: string; plan: string; status: string; members: number; owners: number; sole_owner: boolean; joined_at: string; ai_spent_month: number }[];
  api_keys: { id: number; name: string; prefix: string; workspace: string; scopes: string[]; created_at: string; expires_at: string; last_used_at: string | null; revoked_at: string | null }[];
  apps: { id: number; name: string; workspace: string; scopes: string[]; created_at: string; last_used_at: string | null; revoked_at: string | null }[];
  events: { id: number; type: string; summary: string | null; ip: string | null; user_agent: string | null; at: string; actor: string | null; impersonator: string | null }[];
  ai_month: { calls: number; charged_usd: number }; storage_bytes: number; files: number;
  support_tickets: { total: number; open: number }; delete_blockers: Blocker[]; can_impersonate: boolean; last_superadmin: boolean;
};
type Confirm = { title: string; text: ReactNode; label: string; danger?: boolean; action: () => Promise<void> } | null;

const TABS = [
  { key: "overview", icon: "person" }, { key: "workspaces", icon: "business_center" }, { key: "security", icon: "shield" },
  { key: "apps", icon: "apps" }, { key: "activity", icon: "history" }, { key: "danger", icon: "warning" },
] as const;
type Tab = (typeof TABS)[number]["key"];
const ROLES = ["viewer", "editor", "approver", "admin", "owner"];
const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

function bytes(n: number, locale: string) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(n)} ${units[i]}`;
}

function UserPage() {
  const t = useTranslations("adminUsers");
  const locale = useLocale();
  const { id } = useParams<{ id: string }>();
  const tab = (useSearchParams().get("tab") as Tab) || "overview";
  const router = useRouter();
  const pathname = usePathname();
  const client = useQueryClient();
  const meId = useSession((s) => s.me?.user.id);
  const detail = useQuery({ queryKey: ["admin-user", id], queryFn: () => api.get<Detail>(`/admin/users/${id}`) });
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [busy, setBusy] = useState(false);
  const reload = () => { client.invalidateQueries({ queryKey: ["admin-user", id] }); client.invalidateQueries({ queryKey: ["admin-users"] }); };
  const run = async (action: () => Promise<void>, done?: string) => {
    setBusy(true);
    try {
      await action();
      if (done) toast.success(done);
      reload();
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  };
  const ask = (c: NonNullable<Confirm>) => setConfirm(c);

  if (detail.isError) return <Card><EmptyState icon="person" title={errorText(detail.error)} action={<Link href="/admin/users"><Button>{t("back")}</Button></Link>} /></Card>;
  const data = detail.data;
  if (!data) return <div className="flex justify-center py-16"><Spinner /></div>;
  const u = data.user;
  const self = u.id === meId;
  const ctx = { data, t, locale, ask, run, busy, self, id };

  return (
    <div className="flex flex-col gap-4">
      <Link href="/admin/users" className="inline-flex items-center gap-1 text-sm text-text-2 hover:text-text">
        <Icon name="arrow_back" size={16} className="rtl:rotate-180" /> {t("back")}
      </Link>
      <Card>
        <div className="flex flex-wrap items-center gap-4">
          <Avatar name={u.name} src={data.avatar_url} size={56} />
          <div className="min-w-0 flex-1">
            <h2 className="text-xl font-bold tracking-tight">{u.name}</h2>
            <div className="text-sm text-muted" dir="ltr">{u.email}{u.username ? ` · @${u.username}` : ""} · #{u.id}</div>
            <div className="mt-2"><UserBadges user={u} /></div>
          </div>
          {data.can_impersonate && !self && (
            <Button icon="visibility" onClick={() => router.push(`${pathname}?tab=danger`)}>{t("danger.impersonate")}</Button>
          )}
        </div>
      </Card>
      <nav className="flex gap-1 overflow-x-auto">
        {TABS.map((item) => (
          <Link key={item.key} href={`/admin/users/${id}?tab=${item.key}`} replace
            className={cx("flex h-10 shrink-0 items-center gap-2 rounded-xl px-3 text-sm font-medium transition",
              tab === item.key ? "glass text-text" : "text-text-2 hover:bg-fill-2", item.key === "danger" && tab !== item.key && "text-bad")}>
            <Icon name={item.icon} size={16} /> {t(`tabs.${item.key}`)}
          </Link>
        ))}
      </nav>
      {tab === "overview" && <Overview {...ctx} />}
      {tab === "workspaces" && <Workspaces {...ctx} />}
      {tab === "security" && <Security {...ctx} />}
      {tab === "apps" && <Apps {...ctx} />}
      {tab === "activity" && <Activity {...ctx} />}
      {tab === "danger" && <Danger {...ctx} />}
      <Modal open={!!confirm} onClose={() => setConfirm(null)} title={confirm?.title} size="sm"
        footer={<><Button variant="ghost" onClick={() => setConfirm(null)}>{t("cancel")}</Button>
          <Button variant={confirm?.danger ? "danger" : "primary"} loading={busy} onClick={() => confirm && confirm.action()}>{confirm?.label}</Button></>}>
        <div className="text-sm text-text-2">{confirm?.text}</div>
      </Modal>
    </div>
  );
}

type Ctx = {
  data: Detail; t: ReturnType<typeof useTranslations<"adminUsers">>; locale: string; ask: (c: NonNullable<Confirm>) => void;
  run: (action: () => Promise<void>, done?: string) => Promise<void>; busy: boolean; self: boolean; id: string;
};

function Fact({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-2xl bg-fill-2 p-3">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 font-semibold">{value}</div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </div>
  );
}

function Overview({ data, t, locale, run, busy, id }: Ctx) {
  const u = data.user;
  const [form, setForm] = useState({ name: u.name, email: u.email, locale: data.locale, timezone: data.timezone, email_verified: u.email_verified });
  const deleted = !!u.deleted_at;
  const save = () => run(async () => { await api.patch(`/admin/users/${id}`, form); }, t("overview.saved"));
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <Card>
        <SectionTitle icon="person">{t("overview.profile")}</SectionTitle>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("overview.name")}><Input disabled={deleted} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label={t("overview.email")} hint={t("overview.emailNote")}><Input disabled={deleted} type="email" dir="ltr" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label={t("overview.locale")}>
            <Select disabled={deleted} value={form.locale} onChange={(e) => setForm({ ...form, locale: e.target.value })}>
              {routing.locales.map((code) => <option key={code} value={code}>{LOCALE_NAMES[code]}</option>)}
            </Select>
          </Field>
          <Field label={t("overview.timezone")}><Input disabled={deleted} dir="ltr" value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} /></Field>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Switch disabled={deleted || form.email !== u.email} checked={form.email_verified} onChange={(v) => setForm({ ...form, email_verified: v })} label={t("overview.emailVerified")} />
          {!u.email_verified && !deleted && <Button size="sm" variant="ghost" onClick={() => run(async () => { await api.post(`/admin/users/${id}/send-verification`); }, t("overview.verificationSent"))}>{t("overview.sendVerification")}</Button>}
          <Button className="ms-auto" variant="primary" loading={busy} disabled={deleted} onClick={save}>{t("overview.save")}</Button>
        </div>
      </Card>
      <Card>
        <SectionTitle icon="bar_chart">{t("overview.facts")}</SectionTitle>
        <div className="grid grid-cols-2 gap-3">
          <Fact label={t("overview.created")} value={formatDate(u.created_at, locale)} />
          <Fact label={t("overview.lastLogin")} value={u.last_login_at ? formatDate(u.last_login_at, locale) : t("never")} />
          <Fact label={t("overview.workspacesCount")} value={data.workspaces.length} sub={data.workspaces.map((w) => w.name).join(" · ")} />
          <Fact label={t("overview.aiMonth")} value={`$${data.ai_month.charged_usd.toFixed(2)}`} sub={t("overview.aiCalls", { n: data.ai_month.calls })} />
          <Fact label={t("overview.storage")} value={bytes(data.storage_bytes, locale)} sub={t("overview.files", { n: data.files })} />
          <Fact label={t("overview.tickets")} value={data.support_tickets.total} sub={t("overview.ticketsOpen", { open: data.support_tickets.open, total: data.support_tickets.total })} />
        </div>
      </Card>
    </div>
  );
}

function Workspaces({ data, t, run, ask, id, busy }: Ctx) {
  const tr = useTranslations("settings.roles");
  const tp = useTranslations("shell.plan");
  const [transfer, setTransfer] = useState<Detail["workspaces"][number] | null>(null);
  const [q, setQ] = useState("");
  const [role, setRole] = useState("editor");
  const deleted = !!data.user.deleted_at;
  const search = useQuery({
    queryKey: ["admin-ws-search", q], enabled: q.trim().length > 1,
    queryFn: () => api.get<{ items: { id: number; name: string; owner_email: string | null }[] }>("/admin/workspaces", { q, page_size: 8 }),
  });
  const mine = new Set(data.workspaces.map((w) => w.workspace_id));
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <SectionTitle icon="business_center">{t("tabs.workspaces")}</SectionTitle>
        {!data.workspaces.length ? <p className="text-sm text-muted">{t("workspaces.empty")}</p> : (
          <ul className="divide-y divide-line/60">
            {data.workspaces.map((w) => (
              <li key={w.workspace_id} className="flex flex-wrap items-center gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 font-semibold">
                    <Link href={`/admin/workspaces/${w.workspace_id}`} className="hover:underline">{w.name}</Link>
                    {w.sole_owner && <Badge tone="warn">{t("workspaces.soleOwner")}</Badge>}
                    {w.status !== "active" && <Badge tone="bad">{w.status}</Badge>}
                  </div>
                  <div className="text-xs text-muted">{tp.has(w.plan) ? tp(w.plan) : w.plan} · {t("workspaces.members", { n: w.members })} · {t("workspaces.aiSpent", { value: w.ai_spent_month.toFixed(2) })}</div>
                </div>
                <Select className="w-36" disabled={deleted || busy} value={w.role}
                  onChange={(e) => run(async () => { await api.patch(`/admin/users/${id}/memberships/${w.workspace_id}`, { role: e.target.value }); }, t("workspaces.changeRole"))}>
                  {ROLES.map((r) => <option key={r} value={r}>{tr(r)}</option>)}
                </Select>
                {w.role === "owner" && <Button size="sm" icon="swap_horiz" onClick={() => setTransfer(w)}>{t("workspaces.transfer")}</Button>}
                <Button size="sm" variant="ghost" icon="remove" onClick={() => ask({
                  title: t("workspaces.remove"), danger: true, label: t("workspaces.remove"),
                  text: t("workspaces.removeConfirm", { user: data.user.name, workspace: w.name }),
                  action: () => run(async () => { await api.delete(`/admin/users/${id}/memberships/${w.workspace_id}`); }, t("workspaces.removed")),
                })}>{t("workspaces.remove")}</Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {!deleted && (
        <Card>
          <SectionTitle icon="add">{t("workspaces.add")}</SectionTitle>
          <div className="flex flex-wrap items-end gap-3">
            <Field label={t("workspaces.find")} className="min-w-[240px] flex-1"><Input value={q} placeholder={t("workspaces.findHint")} onChange={(e) => setQ(e.target.value)} /></Field>
            <Field label={t("workspaces.role")}>
              <Select value={role} onChange={(e) => setRole(e.target.value)}>{ROLES.map((r) => <option key={r} value={r}>{tr(r)}</option>)}</Select>
            </Field>
          </div>
          {!!search.data?.items.length && (
            <ul className="mt-3 divide-y divide-line/60 rounded-2xl bg-fill-2 px-3">
              {search.data.items.map((w) => (
                <li key={w.id} className="flex items-center gap-3 py-2 text-sm">
                  <span className="flex-1"><b>{w.name}</b> <span className="text-muted" dir="ltr">{w.owner_email}</span></span>
                  <Button size="sm" disabled={mine.has(w.id) || busy}
                    onClick={() => run(async () => { await api.post(`/admin/users/${id}/memberships`, { workspace_id: w.id, role }); setQ(""); }, t("workspaces.added"))}>
                    {mine.has(w.id) ? t("workspaces.already") : t("workspaces.addButton")}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
      {transfer && <TransferDialog ctx={{ data, t, run, id }} workspace={transfer} onClose={() => setTransfer(null)} />}
    </div>
  );
}

function TransferDialog({ ctx, workspace, onClose }: { ctx: Pick<Ctx, "data" | "t" | "run" | "id">; workspace: Detail["workspaces"][number]; onClose: () => void }) {
  const { t, run, id, data } = ctx;
  const tr = useTranslations("settings.roles");
  const members = useQuery({ queryKey: ["admin-ws-members", id, workspace.workspace_id], queryFn: () => api.get<{ user_id: number; name: string; email: string; role: string }[]>(`/admin/users/${id}/workspace-members/${workspace.workspace_id}`) });
  const [to, setTo] = useState<number | null>(null);
  return (
    <Modal open onClose={onClose} title={t("workspaces.transferTitle", { workspace: workspace.name })} size="sm"
      footer={<><Button variant="ghost" onClick={onClose}>{t("cancel")}</Button>
        <Button variant="primary" disabled={!to} onClick={() => run(async () => { await api.post(`/admin/users/${id}/memberships/${workspace.workspace_id}/transfer`, { to_user_id: to }); onClose(); }, t("workspaces.transferred"))}>{t("confirm")}</Button></>}>
      <p className="mb-3 text-sm text-text-2">{t("workspaces.transferText", { user: data.user.name })}</p>
      {!members.data ? <Spinner /> : !members.data.length ? <p className="text-sm text-warn">{t("workspaces.noMembers")}</p> : (
        <div className="flex flex-col gap-1">
          {members.data.map((m) => (
            <label key={m.user_id} className={cx("flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2 text-sm", to === m.user_id ? "bg-accent-soft" : "hover:bg-fill-2")}>
              <input type="radio" name="owner" checked={to === m.user_id} onChange={() => setTo(m.user_id)} />
              <span className="flex-1"><b>{m.name}</b> <span className="text-muted" dir="ltr">{m.email}</span></span>
              <span className="text-xs text-muted">{tr(m.role)}</span>
            </label>
          ))}
        </div>
      )}
    </Modal>
  );
}

function Security({ data, t, locale, ask, run, self, id }: Ctx) {
  const u = data.user;
  const [temporary, setTemporary] = useState<string | null>(null);
  const deleted = !!u.deleted_at;
  const signIns = data.events.filter((e) => e.type === "login").slice(0, 8);
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <SectionTitle icon="lock">{t("security.password")}</SectionTitle>
        <p className="mb-4 text-sm text-muted">{t("security.passwordChanged")}: {data.password_changed_at ? formatDate(data.password_changed_at, locale) : t("never")}</p>
        <div className="flex flex-col gap-4">
          <div>
            <Button icon="mail" disabled={deleted || !u.is_active} onClick={() => ask({
              title: t("security.resetEmail"), label: t("security.send"), text: t("security.resetEmailText"),
              action: () => run(async () => { await api.post(`/admin/users/${id}/password-reset-email`); }, t("security.resetSent")),
            })}>{t("security.resetEmail")}</Button>
            <p className="mt-1 text-xs text-muted">{t("security.resetEmailText")}</p>
          </div>
          <div>
            <Button icon="key" disabled={deleted || self} onClick={() => ask({
              title: t("security.temporary"), label: t("security.temporary"), danger: true, text: t("security.temporaryConfirm", { email: u.email }),
              action: () => run(async () => { setTemporary((await api.post<{ password: string }>(`/admin/users/${id}/temporary-password`)).password); }),
            })}>{t("security.temporary")}</Button>
            <p className="mt-1 text-xs text-muted">{t("security.temporaryText")}</p>
          </div>
        </div>
      </Card>
      <Card>
        <SectionTitle icon="shield">{t("security.twoFactor")}</SectionTitle>
        <p className="mb-4 text-sm">{u.totp_enabled ? t("security.twoFactorOn", { n: data.recovery_codes_left }) : t("security.twoFactorOff")}</p>
        {u.totp_enabled && <Button icon="refresh" variant="danger" onClick={() => ask({
          title: t("security.reset2fa"), label: t("security.reset2fa"), danger: true, text: t("security.reset2faConfirm", { email: u.email }),
          action: () => run(async () => { await api.post(`/admin/users/${id}/reset-2fa`); }, t("security.reset2faDone")),
        })}>{t("security.reset2fa")}</Button>}
      </Card>
      <Card>
        <SectionTitle icon="history" actions={!deleted && <Button size="sm" variant="danger" onClick={() => ask({
          title: t("security.signOut"), label: t("security.signOut"), danger: true, text: t("security.signOutConfirm", { email: u.email }),
          action: () => run(async () => { await api.post(`/admin/users/${id}/sign-out`); }, t("security.signedOut")),
        })}>{t("security.signOut")}</Button>}>{t("security.sessions")}</SectionTitle>
        <p className="mb-3 text-xs text-muted">{t("security.signOutText")}</p>
        <h3 className="mb-1 text-sm font-semibold">{t("security.signIns")}</h3>
        {!signIns.length ? <p className="text-sm text-muted">{t("activity.empty")}</p> : (
          <ul className="divide-y divide-line/60 text-sm">
            {signIns.map((e) => (
              <li key={e.id} className="flex flex-wrap gap-x-3 py-1.5">
                <span className="min-w-32">{formatDate(e.at, locale)}</span><span className="text-text-2">{device(e.user_agent)}</span><span className="text-muted" dir="ltr">{e.ip}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card>
        <SectionTitle icon="verified_user">{t("security.access")}</SectionTitle>
        {self && <p className="mb-3 text-sm text-muted">{t("security.self")}</p>}
        {data.last_superadmin && <p className="mb-3 rounded-xl bg-warn-bg px-3 py-2 text-sm">{t("security.lastAdmin")}</p>}
        <div className="flex flex-wrap gap-2">
          <Button disabled={deleted || self || (u.is_active && data.last_superadmin)} variant={u.is_active ? "danger" : "primary"} onClick={() => ask({
            title: u.is_active ? t("security.disable") : t("security.enable"), danger: u.is_active, label: u.is_active ? t("security.disable") : t("security.enable"),
            text: u.is_active ? t("security.disableConfirm", { email: u.email }) : t("security.enableConfirm", { email: u.email }),
            action: () => run(async () => { await api.post(`/admin/users/${id}/active`, { value: !u.is_active }); }, t("done")),
          })}>{u.is_active ? t("security.disable") : t("security.enable")}</Button>
          <Button disabled={deleted || self || data.last_superadmin} onClick={() => ask({
            title: u.is_superadmin ? t("security.revokeAdmin") : t("security.makeAdmin"), danger: !u.is_superadmin,
            label: u.is_superadmin ? t("security.revokeAdmin") : t("security.makeAdmin"),
            text: u.is_superadmin ? t("security.revokeAdminConfirm", { email: u.email }) : t("security.makeAdminConfirm", { email: u.email }),
            action: () => run(async () => { await api.post(`/admin/users/${id}/superadmin`, { value: !u.is_superadmin }); }, t("done")),
          })}>{u.is_superadmin ? t("security.revokeAdmin") : t("security.makeAdmin")}</Button>
        </div>
      </Card>
      <Modal open={!!temporary} onClose={() => setTemporary(null)} title={t("security.temporaryTitle")} size="sm"
        footer={<><Button icon="content_copy" onClick={() => temporary && navigator.clipboard.writeText(temporary).then(() => toast.success(t("security.copied")))}>{t("security.copy")}</Button>
          <Button variant="primary" onClick={() => setTemporary(null)}>{t("security.close")}</Button></>}>
        <p className="mb-3 text-sm text-text-2">{t("security.temporaryShown")}</p>
        <code className="block rounded-2xl bg-fill-2 p-4 text-center font-mono text-lg tracking-wide" dir="ltr">{temporary}</code>
      </Modal>
    </div>
  );
}

function Apps({ data, t, locale, ask, run, id }: Ctx) {
  const activeKeys = data.api_keys.filter((k) => !k.revoked_at).length;
  const activeApps = data.apps.filter((a) => !a.revoked_at).length;
  const row = (name: string, sub: string, revoked: string | null, extra: ReactNode) => (
    <li className="flex flex-wrap items-center gap-3 py-2.5 text-sm">
      <div className="min-w-0 flex-1"><div className="font-semibold">{name}</div><div className="text-xs text-muted">{sub}</div></div>
      <div className="text-xs text-muted">{extra}</div>
      {revoked ? <Badge tone="bad">{t("apps.revoked")}</Badge> : <Badge tone="ok">{t("apps.active")}</Badge>}
    </li>
  );
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <SectionTitle icon="key" actions={(activeKeys + activeApps > 0) && <Button size="sm" variant="danger" onClick={() => ask({
          title: t("apps.revokeAll"), label: t("apps.revokeAll"), danger: true, text: t("apps.revokeConfirm", { email: data.user.email }),
          action: () => run(async () => {
            const r = await api.post<{ api_keys: number; apps: number }>(`/admin/users/${id}/revoke-access`);
            toast.success(t("apps.revokedAll", { keys: r.api_keys, apps: r.apps }));
          }),
        })}>{t("apps.revokeAll")}</Button>}>{t("apps.keys")}</SectionTitle>
        {!data.api_keys.length ? <p className="text-sm text-muted">{t("apps.none")}</p> : (
          <ul className="divide-y divide-line/60">
            {data.api_keys.map((k) => <div key={k.id}>{row(k.name, `${k.workspace} · ${k.scopes.join(", ")} · ${k.prefix}…`, k.revoked_at,
              <>{t("apps.expires", { date: formatDate(k.expires_at, locale) })}{k.last_used_at ? ` · ${t("apps.lastUsed", { date: formatDate(k.last_used_at, locale) })}` : ""}</>)}</div>)}
          </ul>
        )}
      </Card>
      <Card>
        <SectionTitle icon="smart_toy">{t("apps.apps")}</SectionTitle>
        {!data.apps.length ? <p className="text-sm text-muted">{t("apps.none")}</p> : (
          <ul className="divide-y divide-line/60">
            {data.apps.map((a) => <div key={a.id}>{row(a.name, `${a.workspace} · ${a.scopes.join(", ")}`, a.revoked_at,
              a.last_used_at ? t("apps.lastUsed", { date: formatDate(a.last_used_at, locale) }) : formatDate(a.created_at, locale))}</div>)}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Activity({ data, t, locale }: Ctx) {
  return (
    <Card>
      <SectionTitle icon="history">{t("activity.title")}</SectionTitle>
      {!data.events.length ? <p className="text-sm text-muted">{t("activity.empty")}</p> : (
        <ul className="divide-y divide-line/60 text-sm">
          {data.events.map((e) => (
            <li key={e.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-2">
              <span className="min-w-36 text-text-2">{formatDate(e.at, locale)}</span>
              <span className="font-medium"><EventLabel type={e.type} /></span>
              {e.summary && <span className="text-text-2" dir="auto">{e.summary}</span>}
              {e.impersonator ? <Badge tone="warn">{t("activity.asAdmin", { who: e.impersonator })}</Badge> : e.actor && <Badge tone="ink">{t("activity.by", { who: e.actor })}</Badge>}
              <span className="ms-auto text-xs text-muted" dir="ltr">{[device(e.user_agent), e.ip].filter((v) => v && v !== "—").join(" · ")}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Danger({ data, t, locale, ask, run, self, id }: Ctx) {
  const u = data.user;
  const [confirmEmail, setConfirmEmail] = useState("");
  const blockers = data.delete_blockers;
  const transfer = blockers.some((b) => b.action === "transfer");
  const impersonate = () => ask({
    title: t("danger.impersonate"), label: t("danger.impersonateStart"), text: t("danger.impersonateConfirm", { email: u.email }),
    action: () => run(async () => {
      await api.post(`/admin/users/${id}/impersonate`);
      window.location.href = `/${locale}`;
    }),
  });
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <SectionTitle icon="visibility">{t("danger.impersonate")}</SectionTitle>
        <p className="mb-4 text-sm text-text-2">{t("danger.impersonateText", { name: u.name })}</p>
        {data.can_impersonate && !self ? <Button variant="primary" icon="visibility" onClick={impersonate}>{t("danger.impersonate")}</Button>
          : <p className="text-sm text-muted">{t("danger.noImpersonate")}</p>}
      </Card>
      <Card>
        <SectionTitle icon="download">{t("danger.export")}</SectionTitle>
        <p className="mb-4 text-sm text-text-2">{t("danger.exportText")}</p>
        <Button icon="download" onClick={() => run(async () => { downloadJson(await api.get(`/admin/users/${id}/export`), `user-${u.id}.json`); })}>{t("danger.export")}</Button>
      </Card>
      {!u.deleted_at && (
        <Card className="ring-1 ring-bad/30">
          <SectionTitle icon="delete">{t("danger.delete")}</SectionTitle>
          <p className="mb-4 text-sm text-text-2">{t("danger.deleteText")}</p>
          {self ? <p className="text-sm text-muted">{t("danger.isSelf")}</p> : (
            <>
              {!!blockers.length && (
                <div className="mb-4 rounded-2xl bg-warn-bg p-3 text-sm">
                  <div className="mb-1 font-semibold">{t("danger.blockers")}</div>
                  <ul className="flex flex-col gap-1">
                    {blockers.map((b) => <li key={b.workspace_id}>{b.action === "transfer" ? t("danger.transfer", { name: b.workspace_name, n: b.other_members }) : t("danger.deleteWs", { name: b.workspace_name })}</li>)}
                  </ul>
                </div>
              )}
              <Field label={t("danger.typeEmail", { email: u.email })} className="max-w-md"><Input dir="ltr" autoComplete="off" value={confirmEmail} onChange={(e) => setConfirmEmail(e.target.value)} /></Field>
              <Button className="mt-4" variant="danger" icon="delete" disabled={transfer || data.last_superadmin || confirmEmail.trim().toLowerCase() !== u.email.toLowerCase()}
                onClick={() => ask({
                  title: t("danger.delete"), label: t("danger.deleteConfirm"), danger: true, text: t("danger.deleteText"),
                  action: () => run(async () => {
                    await api.post(`/admin/users/${id}/delete`, { confirm_email: confirmEmail, delete_workspaces: blockers.filter((b) => b.action === "delete").map((b) => b.workspace_id) });
                    setConfirmEmail("");
                  }, t("danger.deleted")),
                })}>{t("danger.delete")}</Button>
            </>
          )}
        </Card>
      )}
    </div>
  );
}

export default function AdminUserPage() {
  return (
    <Suspense>
      <UserPage />
    </Suspense>
  );
}
