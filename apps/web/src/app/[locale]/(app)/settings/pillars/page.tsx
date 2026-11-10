"use client";
/** Settings › Content pillars: the themes of your posts, their target share and the real mix of the last 30 days. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon } from "@/components/icon";
import type { Pillar } from "@/components/planning/types";
import { ColorDot, ColorPicker, SWATCHES, ShareBar, onError, pct } from "@/components/planning/ui";
import { Badge, Button, Card, EmptyState, Field, IconButton, Input, Modal, SectionTitle, Spinner, Switch, Textarea, cx, toast } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

type Form = { name: string; description: string; color: string; target_share: number; active: boolean };

export default function PillarsSettingsPage() {
  const t = useTranslations("pillars");
  const qc = useQueryClient();
  const isAdmin = useSession((s) => s.can("admin"));
  const { data, isLoading } = useQuery({ queryKey: ["pillars"], queryFn: () => api.get<Pillar[]>("/pillars") });
  const [editing, setEditing] = useState<Pillar | "new" | null>(null);
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["pillars"] }); qc.invalidateQueries({ queryKey: ["planner"] }); };

  const reorder = useMutation({
    mutationFn: (ids: number[]) => api.put<Pillar[]>("/pillars/order", { ids }),
    onSuccess: (rows) => { qc.setQueryData(["pillars"], rows); invalidate(); },
    onError,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/pillars/${id}`),
    onSuccess: () => { invalidate(); toast.success(t("deleted")); },
    onError,
  });

  const pillars = data || [];
  const totalTarget = pillars.filter((p) => p.active).reduce((s, p) => s + p.target_share, 0);
  const move = (index: number, dir: number) => {
    const ids = pillars.map((p) => p.id);
    const [id] = ids.splice(index, 1);
    ids.splice(index + dir, 0, id);
    reorder.mutate(ids);
  };

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <SectionTitle icon="flag" actions={isAdmin && <Button variant="primary" size="sm" icon="add" onClick={() => setEditing("new")}>{t("add")}</Button>}>
          {t("title")}
        </SectionTitle>
        <p className="-mt-1 mb-4 text-[13px] text-muted">{t("intro")}</p>
        {isLoading ? (
          <div className="flex justify-center py-8"><Spinner /></div>
        ) : !pillars.length ? (
          <EmptyState icon="flag" title={t("emptyTitle")} text={t("emptyText")}
            action={isAdmin && <Button variant="primary" icon="add" onClick={() => setEditing("new")}>{t("add")}</Button>} />
        ) : (
          <>
            <ul className="flex flex-col divide-y divide-line">
              {pillars.map((p, index) => (
                <li key={p.id} className={cx("flex flex-wrap items-center gap-3 py-3.5", !p.active && "opacity-55")}>
                  <ColorDot color={p.color} size={14} />
                  <div className="min-w-0 flex-1 basis-48">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold bidi">{p.name}</span>
                      {!p.active && <Badge>{t("inactive")}</Badge>}
                    </div>
                    {p.description && <p className="truncate text-[12.5px] text-muted bidi">{p.description}</p>}
                  </div>
                  <div className="w-full sm:w-64">
                    <div className="mb-1 flex justify-between text-[11.5px] text-muted">
                      <span>{t("actual", { value: pct(p.share_30) })}</span>
                      <span>{t("target", { value: pct(p.target_share) })}</span>
                    </div>
                    <ShareBar value={p.share_30} target={p.target_share} color={p.color} />
                    <div className="mt-1 text-[11px]">
                      {p.published_30 === 0 && p.planned_30 === 0 ? <span className="text-faint">{t("noPosts")}</span> : (
                        <span className={p.gap <= -5 ? "font-semibold text-text" : "text-muted"}>
                          {p.gap <= -5 ? t("postMore") : p.gap >= 10 ? t("tooMuch") : t("onTrack")} · {t("planned", { count: p.planned_30 })}
                        </span>
                      )}
                    </div>
                  </div>
                  {isAdmin && (
                    <div className="flex items-center">
                      <IconButton icon="arrow_upward" label={t("up")} disabled={index === 0 || reorder.isPending} onClick={() => move(index, -1)} />
                      <IconButton icon="arrow_downward" label={t("down")} disabled={index === pillars.length - 1 || reorder.isPending} onClick={() => move(index, 1)} />
                      <IconButton icon="edit_square" label={t("edit")} onClick={() => setEditing(p)} />
                      <IconButton icon="delete" label={t("delete")} onClick={() => window.confirm(t("confirmDelete")) && remove.mutate(p.id)} />
                    </div>
                  )}
                </li>
              ))}
            </ul>
            <div className={cx("mt-3 flex items-center gap-2 rounded-xl px-3 py-2 text-[12.5px]", totalTarget === 100 ? "bg-ok-bg text-ok" : "bg-warn-bg text-warn")}>
              <Icon name={totalTarget === 100 ? "check_circle" : "info"} size={16} />
              {totalTarget === 100 ? t("totalOk") : t("totalOff", { total: pct(totalTarget) })}
            </div>
          </>
        )}
      </Card>
      <Card className="text-[13px] text-muted">
        <SectionTitle icon="lightbulb">{t("tipsTitle")}</SectionTitle>
        <ul className="grid gap-1.5">
          <li>• {t("tip1")}</li>
          <li>• {t("tip2")}</li>
          <li>• {t("tip3")}</li>
        </ul>
      </Card>
      {editing && <PillarForm key={editing === "new" ? "new" : editing.id} pillar={editing === "new" ? null : editing} count={pillars.length}
        onClose={() => setEditing(null)} onSaved={invalidate} />}
    </div>
  );
}

function PillarForm({ pillar, count, onClose, onSaved }: { pillar: Pillar | null; count: number; onClose: () => void; onSaved: () => void }) {
  const t = useTranslations("pillars");
  const [form, setForm] = useState<Form>(() => ({
    name: pillar?.name ?? "", description: pillar?.description ?? "", color: pillar?.color ?? SWATCHES[(count + 4) % SWATCHES.length],
    target_share: pillar?.target_share ?? 25, active: pillar?.active ?? true,
  }));
  const save = useMutation({
    mutationFn: () => (pillar ? api.patch(`/pillars/${pillar.id}`, form) : api.post("/pillars", form)),
    onSuccess: () => { onSaved(); toast.success(t("saved")); onClose(); },
    onError,
  });
  return (
    <Modal open onClose={onClose} title={pillar ? t("edit") : t("add")}
      footer={<><Button onClick={onClose}>{t("cancel")}</Button><Button variant="primary" disabled={!form.name.trim()} loading={save.isPending} onClick={() => save.mutate()}>{t("save")}</Button></>}>
      <div className="flex flex-col gap-4">
        <Field label={t("name")}><Input value={form.name} autoFocus placeholder={t("namePlaceholder")} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label={t("description")} hint={t("descriptionHint")}>
          <Textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Field>
        <Field label={t("targetShare", { value: pct(form.target_share) })}>
          <input type="range" min={0} max={100} step={5} value={form.target_share} className="w-full accent-black"
            onChange={(e) => setForm({ ...form, target_share: Number(e.target.value) })} />
        </Field>
        <Field label={t("color")}><ColorPicker value={form.color} onChange={(color) => setForm({ ...form, color })} /></Field>
        <Switch checked={form.active} onChange={(active) => setForm({ ...form, active })} label={t("active")} />
      </div>
    </Modal>
  );
}
