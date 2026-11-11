"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { type ReactNode, useState } from "react";
import { type AdminRow, StatusBadge } from "@/components/billing/admin-ui";
import { Icon } from "@/components/icon";
import { Avatar, Badge, Button, Card, Field, Input, Modal, SectionTitle, Select, Spinner, Textarea, toast } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { RESOURCES, type Resource, formatDate, formatMoney } from "@/lib/billing";

type Detail = {
  workspace: AdminRow; locale: string; timezone: string; currency: string; note: string | null;
  limit_overrides: Partial<Record<Resource, number | null>> | null;
  usage: Record<Resource, { used: number; limit: number | null }>; features: string[];
  members: { user_id: number; name: string; email: string; role: string; last_login_at: string | null; is_active: boolean }[];
  events: { id: number; provider: string; type: string; summary: string | null; created_at: string }[];
  recent_errors: { id: number; service: string; operation: string; status_code: number | null; error: string | null; created_at: string }[];
  provider_customer_id: string | null; provider_subscription_id: string | null;
};

const PLANS = ["trial", "free", "starter", "pro", "business", "enterprise"];
const SUB_STATUSES = ["trialing", "active", "past_due", "canceled"];

function Info({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2 text-sm">
      <span className="text-muted">{label}</span>
      <span className="min-w-0 truncate text-end font-medium">{children}</span>
    </div>
  );
}

export default function AdminWorkspacePage() {
  const t = useTranslations("admin");
  const tb = useTranslations("billing");
  const ts = useTranslations("settings");
  const locale = useLocale();
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const key = ["admin-workspace", id];
  const { data } = useQuery({ queryKey: key, queryFn: () => api.get<Detail>(`/admin/workspaces/${id}`) });
  const [dialog, setDialog] = useState<null | "suspend" | "extend" | "plan">(null);
  const [reason, setReason] = useState("");
  const [days, setDays] = useState(14);
  const [planForm, setPlanForm] = useState<{ plan: string; status: string; interval: string; period_end: string; note: string; overrides: Record<string, string> }>(
    { plan: "pro", status: "active", interval: "month", period_end: "", note: "", overrides: {} });

  const action = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => api.post(`/admin/workspaces/${id}/${path}`, body ?? {}),
    onSuccess: () => {
      toast.success(t("done"));
      setDialog(null);
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: ["admin-workspaces"] });
      qc.invalidateQueries({ queryKey: ["admin-stats"] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });

  if (!data) return <div className="flex justify-center py-16"><Spinner size={26} /></div>;
  const w = data.workspace;
  const num = (v: number, d = 0) => v.toLocaleString(locale === "ar" ? "ar-SA-u-nu-latn" : "en-US", { maximumFractionDigits: d });
  const fmt = (r: Resource, v: number) => (r === "ai_credits" ? formatMoney(v, "USD", "en") : r === "storage_gb" ? `${num(v, 2)} GB` : num(v));

  const openPlan = () => {
    setPlanForm({
      plan: w.plan, status: w.subscription_status, interval: w.interval, note: data.note || "",
      period_end: w.current_period_end ? w.current_period_end.slice(0, 10) : "",
      overrides: Object.fromEntries(Object.entries(data.limit_overrides || {}).map(([k, v]) => [k, v == null ? "" : String(v)])),
    });
    setDialog("plan");
  };
  const savePlan = () => {
    const overrides = Object.fromEntries(Object.entries(planForm.overrides).filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)]));
    action.mutate({ path: "plan", body: {
      plan: planForm.plan, status: planForm.status, interval: planForm.interval, note: planForm.note,
      period_end: planForm.period_end ? new Date(planForm.period_end + "T23:59:59Z").toISOString() : null,
      limit_overrides: overrides,
    } });
  };

  return (
    <div className="flex flex-col gap-4">
      <Link href="/admin" className="inline-flex w-fit items-center gap-1 text-sm text-text-2 hover:text-text">
        <Icon name="arrow_back" size={16} className="rtl:rotate-180" /> {t("back")}
      </Link>
      <Card>
        <div className="flex flex-wrap items-start gap-4">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-ink text-lg font-bold text-white">{w.name.slice(0, 1).toUpperCase()}</span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-xl font-bold tracking-tight">{w.name}</h2>
              <Badge tone="ink">{tb(`plans.${w.plan}`)}</Badge>
              <StatusBadge row={w} />
            </div>
            <p className="mt-1 text-xs text-muted" dir="ltr">#{w.id} · {w.slug} · {w.owner_email}</p>
            <p className="mt-2 inline-flex items-center gap-1.5 text-xs text-muted"><Icon name="visibility" size={14} /> {t("support")}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" icon="event_add" onClick={() => setDialog("extend")}>{t("actions.extend")}</Button>
            <Button size="sm" icon="verified" onClick={openPlan}>{t("actions.plan")}</Button>
            {w.status === "active"
              ? <Button size="sm" variant="danger" icon="block" onClick={() => setDialog("suspend")}>{t("actions.suspend")}</Button>
              : <Button size="sm" variant="primary" icon="check_circle" loading={action.isPending} onClick={() => action.mutate({ path: "reactivate" })}>{t("actions.reactivate")}</Button>}
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1.4fr]">
        <Card>
          <SectionTitle icon="info">{tb("title")}</SectionTitle>
          <div className="divide-y divide-line">
            {w.trial_ends_at && w.subscription_status === "trialing" && <Info label={t("info.trialEnds")}>{formatDate(w.trial_ends_at, locale)}</Info>}
            {w.current_period_end && <Info label={t("info.periodEnd")}>{formatDate(w.current_period_end, locale)}</Info>}
            <Info label={t("info.provider")}>{w.provider}</Info>
            {data.provider_customer_id && <Info label={t("info.customer")}><span dir="ltr">{data.provider_customer_id}</span></Info>}
            {data.provider_subscription_id && <Info label={t("info.subscription")}><span dir="ltr">{data.provider_subscription_id}</span></Info>}
            <Info label={t("info.locale")}>{data.locale} · {data.currency}</Info>
            <Info label={t("info.timezone")}><span dir="ltr">{data.timezone}</span></Info>
            {data.note && <Info label={t("info.note")}><span className="bidi">{data.note}</span></Info>}
          </div>
        </Card>
        <Card>
          <SectionTitle icon="bar_chart">{t("usage")}</SectionTitle>
          <ul className="flex flex-col gap-3">
            {RESOURCES.map((r) => {
              const u = data.usage[r];
              const ratio = u.limit ? Math.min(1, u.used / u.limit) : 0;
              return (
                <li key={r} className="text-sm">
                  <div className="flex justify-between gap-2">
                    <span>{tb(`resources.${r}`)}</span>
                    <span className="text-text-2" dir="ltr">{fmt(r, u.used)} / {u.limit == null ? "∞" : fmt(r, u.limit)}</span>
                  </div>
                  <div className="mt-1 h-1.5 rounded-full bg-track">
                    <div className={ratio >= 1 ? "h-full rounded-full bg-[var(--bad-solid)]" : "h-full rounded-full bg-ink"} style={{ width: `${ratio * 100}%` }} />
                  </div>
                </li>
              );
            })}
          </ul>
        </Card>
      </div>

      <Card>
        <SectionTitle icon="group">{t("members")} · {data.members.length}</SectionTitle>
        <ul className="divide-y divide-line">
          {data.members.map((m) => (
            <li key={m.user_id} className="flex flex-wrap items-center gap-3 py-2.5">
              <Avatar name={m.name} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold">{m.name} {!m.is_active && <Badge tone="bad">{t("inactive")}</Badge>}</div>
                <div className="truncate text-xs text-muted" dir="ltr">{m.email}</div>
              </div>
              <Badge>{ts(`roles.${m.role}`)}</Badge>
              <span className="w-full text-xs text-muted sm:w-auto">{t("lastLogin")}: {m.last_login_at ? formatDate(m.last_login_at, locale) : t("never")}</span>
            </li>
          ))}
        </ul>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <SectionTitle icon="history">{t("events")}</SectionTitle>
          {!data.events.length ? <p className="text-sm text-muted">{t("noEvents")}</p> : (
            <ul className="divide-y divide-line">
              {data.events.map((e) => (
                <li key={e.id} className="flex items-center gap-3 py-2 text-sm">
                  <Badge tone={e.provider === "admin" ? "ink" : "neutral"}>{e.provider}</Badge>
                  <span className="min-w-0 flex-1 truncate" dir="ltr">{e.type}{e.summary && e.summary !== e.type ? ` — ${e.summary}` : ""}</span>
                  <span className="shrink-0 text-xs text-muted">{formatDate(e.created_at, locale)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <SectionTitle icon="error">{t("errors")}</SectionTitle>
          {!data.recent_errors.length ? <p className="flex items-center gap-2 text-sm text-ok"><Icon name="check_circle" size={16} /> {t("noErrors")}</p> : (
            <ul className="divide-y divide-line">
              {data.recent_errors.map((e) => (
                <li key={e.id} className="py-2 text-sm">
                  <div className="flex items-center gap-2">
                    <Badge tone="bad">{e.status_code ?? "—"}</Badge>
                    <span className="min-w-0 flex-1 truncate font-medium" dir="ltr">{e.service} · {e.operation}</span>
                    <span className="shrink-0 text-xs text-muted">{formatDate(e.created_at, locale)}</span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs text-muted" dir="ltr">{e.error}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Modal open={dialog === "suspend"} onClose={() => setDialog(null)} title={t("actions.suspend")} size="sm"
        footer={<>
          <Button variant="ghost" onClick={() => setDialog(null)}>{t("cancel")}</Button>
          <Button variant="danger" loading={action.isPending} onClick={() => action.mutate({ path: "suspend", body: { reason } })}>{t("actions.suspend")}</Button>
        </>}>
        <p className="mb-4 text-sm text-text-2">{t("suspendConfirm", { name: w.name })}</p>
        <Field label={t("reason")}><Input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </Modal>

      <Modal open={dialog === "extend"} onClose={() => setDialog(null)} title={t("actions.extend")} size="sm"
        footer={<>
          <Button variant="ghost" onClick={() => setDialog(null)}>{t("cancel")}</Button>
          <Button variant="primary" loading={action.isPending} onClick={() => action.mutate({ path: "extend-trial", body: { days } })}>{t("save")}</Button>
        </>}>
        <Field label={t("days")}><Input type="number" min={1} max={365} dir="ltr" value={days} onChange={(e) => setDays(Number(e.target.value))} /></Field>
      </Modal>

      <Modal open={dialog === "plan"} onClose={() => setDialog(null)} title={t("actions.plan")}
        footer={<>
          <Button variant="ghost" onClick={() => setDialog(null)}>{t("cancel")}</Button>
          <Button variant="primary" loading={action.isPending} onClick={savePlan}>{t("save")}</Button>
        </>}>
        {w.provider === "stripe" && <p className="mb-4 rounded-xl bg-warn-bg px-3 py-2 text-xs text-warn">{t("planForm.stripeWarning")}</p>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("planForm.plan")}>
            <Select value={planForm.plan} onChange={(e) => setPlanForm({ ...planForm, plan: e.target.value })}>
              {PLANS.map((p) => <option key={p} value={p}>{tb(`plans.${p}`)}</option>)}
            </Select>
          </Field>
          <Field label={t("planForm.status")}>
            <Select value={planForm.status} disabled={planForm.plan === "trial"} onChange={(e) => setPlanForm({ ...planForm, status: e.target.value })}>
              {SUB_STATUSES.map((st) => <option key={st} value={st}>{t(`statuses.${st}`)}</option>)}
            </Select>
          </Field>
          <Field label={t("planForm.interval")}>
            <Select value={planForm.interval} onChange={(e) => setPlanForm({ ...planForm, interval: e.target.value })}>
              <option value="month">{tb("monthly")}</option>
              <option value="year">{tb("yearly")}</option>
            </Select>
          </Field>
          <Field label={t("planForm.periodEnd")}>
            <Input type="date" dir="ltr" value={planForm.period_end} onChange={(e) => setPlanForm({ ...planForm, period_end: e.target.value })} />
          </Field>
        </div>
        <p className="mb-2 mt-5 text-[13px] font-medium text-text-2">{t("planForm.overrides")}</p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {RESOURCES.map((r) => (
            <Field key={r} label={<span className="text-xs">{tb(`resources.${r}`)}</span>}>
              <Input type="number" min={0} dir="ltr" value={planForm.overrides[r] ?? ""}
                onChange={(e) => setPlanForm({ ...planForm, overrides: { ...planForm.overrides, [r]: e.target.value } })} />
            </Field>
          ))}
        </div>
        <Field label={t("planForm.note")} className="mt-4">
          <Textarea rows={2} value={planForm.note} onChange={(e) => setPlanForm({ ...planForm, note: e.target.value })} />
        </Field>
      </Modal>
    </div>
  );
}
