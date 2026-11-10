"use client";
/** Reports: performance reports e-mailed every week or month (HTML / PDF), with a live preview. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import type { Account, ReportSchedule } from "@/components/planning/types";
import { onError, useFormat, useWeekdays } from "@/components/planning/ui";
import { Badge, Button, Card, EmptyState, Field, IconButton, Input, Modal, PageHeader, Segmented, Select, Spinner, Switch, Textarea, cx, toast } from "@/components/ui";
import { api } from "@/lib/api";

type Meta = { pdf_available: boolean; timezone: string };
type Form = Omit<ReportSchedule, "id" | "last_sent_at" | "next_send_at" | "last_error" | "send_count" | "recipients"> & { recipients: string };

const empty = (locale: string): Form => ({
  name: "", recipients: "", frequency: "weekly", weekday: 6, month_day: 1, hour: 9, period: "last_7", account_ids: [],
  language: locale === "en" ? "en" : "ar", include_ai: true, active: true,
});

export default function ReportsPage() {
  const t = useTranslations("reports");
  const qc = useQueryClient();
  const fmt = useFormat();
  const weekdays = useWeekdays("long");
  const meta = useQuery({ queryKey: ["reports-meta"], queryFn: () => api.get<Meta>("/reports/meta") });
  const { data, isLoading } = useQuery({ queryKey: ["report-schedules"], queryFn: () => api.get<ReportSchedule[]>("/reports/schedules") });
  const [editing, setEditing] = useState<ReportSchedule | "new" | null>(null);
  const [preview, setPreview] = useState<{ id?: number; title: string } | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["report-schedules"] });
  const closePreview = useCallback(() => setPreview(null), []);

  const send = useMutation({
    mutationFn: (id: number) => api.post<{ recipients: number; format: string }>(`/reports/schedules/${id}/send`),
    onSuccess: (r) => { refresh(); toast.success(t("sent", { count: r.recipients, format: r.format.toUpperCase() })); },
    onError,
  });
  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) => api.patch(`/reports/schedules/${id}`, { active }),
    onSuccess: refresh,
    onError,
  });
  const pdf = async (s: ReportSchedule) => {
    try {
      const blob = await api.get<Blob>(`/reports/schedules/${s.id}/pdf`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${s.name}.pdf`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      onError(err);
    }
  };

  const when = (s: ReportSchedule) =>
    s.frequency === "weekly"
      ? t("everyWeek", { day: weekdays[s.weekday], hour: `${String(s.hour).padStart(2, "0")}:00` })
      : t("everyMonth", { day: s.month_day, hour: `${String(s.hour).padStart(2, "0")}:00` });

  return (
    <div className="pt-2">
      <PageHeader icon="description" title={t("title")} subtitle={t("subtitle")}
        actions={<>
          <Button icon="visibility" onClick={() => setPreview({ title: t("previewNow") })}>{t("previewNow")}</Button>
          <Button variant="primary" icon="add" onClick={() => setEditing("new")}>{t("new")}</Button>
        </>} />

      {meta.data && !meta.data.pdf_available && (
        <div className="mb-4 flex items-center gap-2 rounded-2xl bg-fill px-4 py-2.5 text-[12.5px] text-text-2">
          <Icon name="info" size={16} /> {t("noPdf")}
        </div>
      )}

      {isLoading ? <div className="flex justify-center py-16"><Spinner /></div> : !data?.length ? (
        <Card><EmptyState icon="description" title={t("emptyTitle")} text={t("emptyText")}
          action={<Button variant="primary" icon="add" onClick={() => setEditing("new")}>{t("new")}</Button>} /></Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {data.map((s) => (
            <Card key={s.id} className={cx("flex flex-col", !s.active && "opacity-70")}>
              <div className="flex items-start gap-3">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-ink text-white"><Icon name="mail" size={20} duo /></span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-[15px] font-semibold bidi">{s.name}</span>
                    <Badge>{s.language === "ar" ? "العربية" : "English"}</Badge>
                    {s.include_ai && <Badge tone="ink"><Icon name="auto_awesome" size={11} />AI</Badge>}
                  </div>
                  <div className="text-[12.5px] text-muted">{when(s)} · {t(`periods.${s.period}`)}</div>
                </div>
                <Switch checked={s.active} onChange={(active) => toggle.mutate({ id: s.id, active })} />
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {s.recipients.map((r) => <span key={r} dir="ltr" className="rounded-full bg-fill-2 px-2.5 py-0.5 text-[11.5px] text-text-2">{r}</span>)}
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-2 text-[12px]">
                <div className="rounded-xl bg-fill px-3 py-2"><dt className="text-muted">{t("next")}</dt><dd className="font-semibold">{s.next_send_at ? fmt.dateTime(s.next_send_at) : "—"}</dd></div>
                <div className="rounded-xl bg-fill px-3 py-2"><dt className="text-muted">{t("last")}</dt><dd className="font-semibold">{s.last_sent_at ? fmt.dateTime(s.last_sent_at) : t("never")}{s.send_count > 0 && <span className="font-normal text-muted"> · {t("times", { count: s.send_count })}</span>}</dd></div>
              </dl>
              {s.last_error && <p className="mt-2 flex items-start gap-1.5 rounded-xl bg-bad-bg px-3 py-2 text-[12px] text-bad"><Icon name="error" size={14} className="mt-0.5 shrink-0" />{s.last_error}</p>}
              <div className="mt-auto flex flex-wrap items-center gap-1 border-t border-line pt-3">
                <Button size="sm" variant="ghost" icon="visibility" onClick={() => setPreview({ id: s.id, title: s.name })}>{t("preview")}</Button>
                <Button size="sm" variant="ghost" icon="send" loading={send.isPending && send.variables === s.id} onClick={() => send.mutate(s.id)}>{t("sendNow")}</Button>
                {meta.data?.pdf_available && <Button size="sm" variant="ghost" icon="download" onClick={() => pdf(s)}>PDF</Button>}
                <IconButton icon="edit_square" label={t("edit")} className="ms-auto" onClick={() => setEditing(s)} />
              </div>
            </Card>
          ))}
        </div>
      )}

      {editing && <ScheduleModal key={editing === "new" ? "new" : editing.id} schedule={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={refresh} />}
      {preview && <PreviewModal scheduleId={preview.id} title={preview.title} onClose={closePreview} />}
    </div>
  );
}

function ScheduleModal({ schedule, onClose, onSaved }: { schedule: ReportSchedule | null; onClose: () => void; onSaved: () => void }) {
  const t = useTranslations("reports");
  const weekdays = useWeekdays("long");
  const locale = useLocale();
  const accounts = useQuery({ queryKey: ["planner-accounts"], queryFn: () => api.get<Account[]>("/planner/accounts") });
  const [form, setForm] = useState<Form>(() => schedule ? { ...schedule, recipients: schedule.recipients.join(", ") } : { ...empty(locale), name: t("defaultName") });
  const recipients = form.recipients.split(/[\s,;]+/).map((r) => r.trim()).filter(Boolean);
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: form.name, recipients, frequency: form.frequency, weekday: form.weekday, month_day: form.month_day, hour: form.hour,
        period: form.period, account_ids: form.account_ids, language: form.language, include_ai: form.include_ai, active: form.active,
      };
      return schedule ? api.patch(`/reports/schedules/${schedule.id}`, body) : api.post("/reports/schedules", body);
    },
    onSuccess: () => { onSaved(); toast.success(t("saved")); onClose(); },
    onError,
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/reports/schedules/${schedule?.id}`),
    onSuccess: () => { onSaved(); onClose(); },
    onError,
  });
  const toggleAccount = (id: number) =>
    setForm({ ...form, account_ids: form.account_ids.includes(id) ? form.account_ids.filter((x) => x !== id) : [...form.account_ids, id] });

  return (
    <Modal open onClose={onClose} size="lg" title={schedule ? t("edit") : t("new")}
      footer={<>
        {schedule && <Button variant="danger" icon="delete" loading={remove.isPending} onClick={() => window.confirm(t("confirmDelete")) && remove.mutate()}>{t("delete")}</Button>}
        <Button className="ms-auto" onClick={onClose}>{t("cancel")}</Button>
        <Button variant="primary" disabled={!form.name.trim() || !recipients.length} loading={save.isPending} onClick={() => save.mutate()}>{t("save")}</Button>
      </>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("name")} className="sm:col-span-2"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label={t("recipients")} hint={t("recipientsHint")} className="sm:col-span-2">
          <Textarea rows={2} dir="ltr" value={form.recipients} placeholder="owner@company.com, team@company.com" onChange={(e) => setForm({ ...form, recipients: e.target.value })} />
        </Field>
        <Field label={t("frequency")}>
          <Segmented value={form.frequency} onChange={(frequency) => setForm({ ...form, frequency })} options={[
            { value: "weekly", label: t("weekly") }, { value: "monthly", label: t("monthly") },
          ]} />
        </Field>
        {form.frequency === "weekly" ? (
          <Field label={t("weekday")}>
            <Select value={form.weekday} onChange={(e) => setForm({ ...form, weekday: Number(e.target.value) })}>
              {weekdays.map((d, i) => <option key={i} value={i}>{d}</option>)}
            </Select>
          </Field>
        ) : (
          <Field label={t("monthDay")}>
            <Select value={form.month_day} onChange={(e) => setForm({ ...form, month_day: Number(e.target.value) })}>
              {Array.from({ length: 28 }, (_, i) => <option key={i + 1} value={i + 1}>{i + 1}</option>)}
            </Select>
          </Field>
        )}
        <Field label={t("hour")}>
          <Select value={form.hour} dir="ltr" onChange={(e) => setForm({ ...form, hour: Number(e.target.value) })}>
            {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{`${String(h).padStart(2, "0")}:00`}</option>)}
          </Select>
        </Field>
        <Field label={t("period")}>
          <Select value={form.period} onChange={(e) => setForm({ ...form, period: e.target.value as Form["period"] })}>
            {(["last_7", "last_30", "prev_month"] as const).map((p) => <option key={p} value={p}>{t(`periods.${p}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("language")}>
          <Segmented value={form.language} onChange={(language) => setForm({ ...form, language })} options={[
            { value: "ar", label: "العربية" }, { value: "en", label: "English" },
          ]} />
        </Field>
        <Field label={t("networks")} hint={t("networksHint")} className="sm:col-span-2">
          <div className="flex flex-wrap gap-1.5">
            {accounts.data?.map((a) => (
              <button key={a.id} type="button" onClick={() => toggleAccount(a.id)}
                className={cx("inline-flex items-center gap-1.5 rounded-full border py-1 ps-1 pe-2.5 text-[12px] font-medium transition",
                  form.account_ids.includes(a.id) ? "border-ink bg-ink text-white" : "border-line bg-white/70")}>
                <PlatformBadge platform={a.platform} size={20} /> <span className="bidi">{a.name}</span>
              </button>
            ))}
          </div>
        </Field>
        <div className="flex flex-col gap-3 rounded-2xl bg-fill p-3.5 sm:col-span-2">
          <Switch checked={form.include_ai} onChange={(include_ai) => setForm({ ...form, include_ai })} label={t("includeAi")} />
          <Switch checked={form.active} onChange={(active) => setForm({ ...form, active })} label={t("active")} />
        </div>
      </div>
    </Modal>
  );
}

function PreviewModal({ scheduleId, title, onClose }: { scheduleId?: number; title: string; onClose: () => void }) {
  const t = useTranslations("reports");
  const locale = useLocale();
  const [language, setLanguage] = useState<"ar" | "en">(locale === "en" ? "en" : "ar");
  const [period, setPeriod] = useState<"last_7" | "last_30" | "prev_month">("last_30");
  const [html, setHtml] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const path = scheduleId ? `/reports/schedules/${scheduleId}/preview` : "/reports/preview";
    api.get<Blob>(path, scheduleId ? undefined : { language, period })
      .then((blob) => blob.text())
      .then((text) => { if (!cancelled) setHtml(text); })
      .catch((err) => { onError(err); onClose(); });
    return () => { cancelled = true; };
  }, [scheduleId, language, period, onClose]);
  return (
    <Modal open onClose={onClose} size="xl" title={title}>
      {!scheduleId && (
        <div className="mb-3 flex flex-wrap gap-2">
          <Segmented size="sm" value={period} onChange={(p) => { setHtml(null); setPeriod(p); }} options={(["last_7", "last_30", "prev_month"] as const).map((p) => ({ value: p, label: t(`periods.${p}`) }))} />
          <Segmented size="sm" value={language} onChange={(l) => { setHtml(null); setLanguage(l); }} options={[{ value: "ar", label: "العربية" }, { value: "en", label: "English" }]} />
        </div>
      )}
      <div className="overflow-hidden rounded-2xl border border-line bg-[#e9e9ec]">
        {html === null ? <div className="flex h-[60vh] items-center justify-center"><Spinner /></div> : (
          <iframe title={title} srcDoc={html} sandbox="" className="h-[70vh] w-full bg-white" />
        )}
      </div>
    </Modal>
  );
}
