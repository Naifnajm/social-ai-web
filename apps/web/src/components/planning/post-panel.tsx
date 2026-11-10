"use client";
/** The post panel of the Planner: date & time, campaign / pillar, evergreen reposting, open in the Studio. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Icon } from "@/components/icon";
import { Button, Field, Input, Modal, Select, Spinner, Switch, toast } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Evergreen, PlannerData, PlannerPost } from "./types";
import { PlatformStack, StateBadge, onError, useFormat } from "./ui";

export function PostPanel({ postId, data, onClose }: { postId: number; data: PlannerData; onClose: () => void }) {
  const t = useTranslations("planner");
  const qc = useQueryClient();
  const fmt = useFormat();
  const canEdit = useSession((s) => s.can("editor"));
  const { data: post, isLoading } = useQuery({
    queryKey: ["planner-post", postId],
    queryFn: () => api.get<PlannerPost>(`/planner/posts/${postId}`),
  });
  const [day, setDay] = useState("");
  const [time, setTime] = useState("");

  useEffect(() => {
    if (post) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- form follows the loaded post
      setDay(post.day || "");
      setTime(post.time || "");
    }
  }, [post]);

  const refresh = (item?: PlannerPost) => {
    if (item) qc.setQueryData(["planner-post", postId], item);
    qc.invalidateQueries({ queryKey: ["planner"] });
    qc.invalidateQueries({ queryKey: ["campaign"] });
  };

  const isDraft = post && ["draft", "failed"].includes(post.state);
  const save = useMutation({
    mutationFn: () => {
      if (isDraft && time) return api.post<PlannerPost>(`/planner/posts/${postId}/schedule`, { day, time });
      return api.post<PlannerPost>(`/planner/posts/${postId}/move`, { day, time: time || undefined });
    },
    onSuccess: (item) => {
      refresh(item);
      toast.success(item.state === "scheduled" ? t("panel.scheduled") : item.state === "to_approve" ? t("panel.sentForApproval") : t("moved"));
    },
    onError,
  });
  const unplan = useMutation({
    mutationFn: () => api.post<PlannerPost>(`/planner/posts/${postId}/unplan`),
    onSuccess: (item) => { refresh(item); onClose(); },
    onError,
  });
  const plan = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.patch<PlannerPost>(`/planner/posts/${postId}`, body),
    onSuccess: (item) => refresh(item),
    onError,
  });

  const published = post && ["posted", "partial"].includes(post.state);
  const bestFor = data.best_slots.slice(0, 3);

  return (
    <Modal open onClose={onClose} size="md" title={t("panel.title")}
      footer={post && (
        <>
          {canEdit && isDraft && post.day && (
            <Button variant="ghost" icon="event_upcoming" loading={unplan.isPending} onClick={() => unplan.mutate()}>{t("panel.unplan")}</Button>
          )}
          <Link href={`/studio?post=${postId}`} className="ms-auto"><Button icon="edit_square">{t("panel.openStudio")}</Button></Link>
        </>
      )}>
      {isLoading || !post ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : (
        <div className="flex flex-col gap-5">
          <div className="flex gap-3">
            {post.media ? (
              post.media.kind === "image" ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={post.media.url} alt="" className="h-20 w-20 shrink-0 rounded-2xl object-cover" />
              ) : (
                <span className="flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl bg-ink text-white"><Icon name="movie" size={26} /></span>
              )
            ) : (
              <span className="flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl bg-fill-2 text-muted"><Icon name="text_fields" size={24} /></span>
            )}
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <StateBadge state={post.state} />
                <PlatformStack platforms={post.platforms} />
                {post.evergreen && <span className="inline-flex items-center gap-1 text-[11px] font-medium text-text-2"><Icon name="recycle" size={13} />{t("panel.evergreen")}</span>}
              </div>
              <div className="mt-1 truncate font-semibold bidi">{post.name || t("untitled")}</div>
              <p className="mt-0.5 line-clamp-3 text-[13px] text-muted bidi">{post.preview}</p>
              {post.published_at && <p className="mt-1 text-[12px] text-text-2">{t("panel.publishedOn", { date: fmt.dateTime(post.published_at) })}</p>}
            </div>
          </div>

          {post.movable && canEdit && (
            <div className="rounded-2xl bg-fill p-3.5">
              <div className="mb-2 text-[13px] font-semibold">{t("panel.when")}</div>
              <div className="grid grid-cols-2 gap-2">
                <Field label={t("panel.day")}><Input type="date" dir="ltr" value={day} min={data.today} onChange={(e) => setDay(e.target.value)} /></Field>
                <Field label={t("panel.time")} hint={isDraft ? t("panel.timeHint") : undefined}>
                  <Input type="time" dir="ltr" value={time} onChange={(e) => setTime(e.target.value)} />
                </Field>
              </div>
              {bestFor.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <span className="text-[11.5px] text-muted">★ {t("panel.bestSlots")}</span>
                  {bestFor.map((slot) => (
                    <button key={slot.at} type="button" onClick={() => { setDay(slot.local.slice(0, 10)); setTime(slot.time); }}
                      className="rounded-full bg-white px-2.5 py-1 text-[11.5px] font-medium shadow-[var(--shadow)] hover:bg-ink hover:text-white">
                      {fmt.date(slot.local.slice(0, 10), { weekday: "short", day: "numeric" })} · <span dir="ltr">{slot.time}</span>
                    </button>
                  ))}
                </div>
              )}
              <div className="mt-3 flex justify-end">
                <Button variant="primary" size="sm" icon={isDraft && time ? "schedule" : "calendar_today"} disabled={!day} loading={save.isPending} onClick={() => save.mutate()}>
                  {isDraft ? (time ? t("panel.schedule") : t("panel.planDay")) : t("panel.reschedule")}
                </Button>
              </div>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("panel.campaign")}>
              <Select value={post.campaign?.id ?? ""} disabled={!canEdit || plan.isPending}
                onChange={(e) => plan.mutate(e.target.value ? { campaign_id: Number(e.target.value) } : { clear_campaign: true })}>
                <option value="">{t("panel.none")}</option>
                {data.campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            </Field>
            <Field label={t("panel.pillar")}>
              <Select value={post.pillar?.id ?? ""} disabled={!canEdit || plan.isPending}
                onChange={(e) => plan.mutate(e.target.value ? { pillar_id: Number(e.target.value) } : { clear_pillar: true })}>
                <option value="">{t("panel.none")}</option>
                {data.pillars.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </Select>
            </Field>
          </div>

          {published && !post.recycled && <EvergreenBox postId={postId} canEdit={canEdit} onChange={() => refresh()} />}
        </div>
      )}
    </Modal>
  );
}

function EvergreenBox({ postId, canEdit, onChange }: { postId: number; canEdit: boolean; onChange: () => void }) {
  const t = useTranslations("planner");
  const fmt = useFormat();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["evergreen", postId], queryFn: () => api.get<Evergreen>(`/evergreen/${postId}`) });
  const [form, setForm] = useState({ evergreen: false, interval_days: 30, until: "", rewrite: false });
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- form follows the loaded settings
    if (data) setForm({ evergreen: data.evergreen, interval_days: data.interval_days, until: data.until || "", rewrite: data.rewrite });
  }, [data]);
  const save = useMutation({
    mutationFn: (body: typeof form) => api.put<Evergreen>(`/evergreen/${postId}`, { ...body, until: body.until || null }),
    onSuccess: (row) => { qc.setQueryData(["evergreen", postId], row); onChange(); toast.success(t("panel.saved")); },
    onError,
  });
  const repost = useMutation({
    mutationFn: () => api.post<{ copy_id: number; state: string }>(`/evergreen/${postId}/repost`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["evergreen", postId] }); onChange(); toast.success(t("panel.reposted")); },
    onError,
  });
  if (!data) return null;
  return (
    <div className="rounded-2xl border border-line p-3.5">
      <div className="flex items-center gap-2">
        <Icon name="recycle" size={18} />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold">{t("panel.evergreenTitle")}</div>
          <div className="text-[11.5px] text-muted">{t("panel.evergreenHint")}</div>
        </div>
        <Switch checked={form.evergreen} disabled={!canEdit} onChange={(v) => { const next = { ...form, evergreen: v }; setForm(next); save.mutate(next); }} />
      </div>
      {form.evergreen && (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Field label={t("panel.every")}>
            <Select value={form.interval_days} disabled={!canEdit} onChange={(e) => setForm({ ...form, interval_days: Number(e.target.value) })}>
              {[7, 14, 30, 60, 90].map((d) => <option key={d} value={d}>{t("panel.days", { count: d })}</option>)}
            </Select>
          </Field>
          <Field label={t("panel.until")}><Input type="date" dir="ltr" value={form.until} disabled={!canEdit} onChange={(e) => setForm({ ...form, until: e.target.value })} /></Field>
          <div className="sm:col-span-2"><Switch checked={form.rewrite} disabled={!canEdit} onChange={(v) => setForm({ ...form, rewrite: v })} label={t("panel.rewrite")} /></div>
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted sm:col-span-2">
            {data.next_recycle_at && <span>{t("panel.nextRepost", { date: fmt.date(data.next_recycle_at) })}</span>}
            {data.recycle_count > 0 && <span>· {t("panel.repostCount", { count: data.recycle_count })}</span>}
            {data.waiting_copy && <span>· {t("panel.waiting")}</span>}
            {canEdit && (
              <span className="ms-auto flex gap-2">
                <Button size="sm" variant="ghost" icon="autorenew" disabled={data.waiting_copy} loading={repost.isPending} onClick={() => repost.mutate()}>{t("panel.repostNow")}</Button>
                <Button size="sm" variant="primary" loading={save.isPending} onClick={() => save.mutate(form)}>{t("panel.save")}</Button>
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
