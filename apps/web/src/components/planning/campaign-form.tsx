"use client";
/** Create / edit a campaign (modal). */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button, Field, Input, Modal, Select, Switch, Textarea, toast } from "@/components/ui";
import { api } from "@/lib/api";
import type { Campaign } from "./types";
import { ColorPicker, SWATCHES, onError } from "./ui";

type Form = {
  name: string; tagline: string; goal: string; date_start: string; date_end: string; color: string;
  budget: string; target_posts: string; auto_state: boolean; state: string;
};

const fromCampaign = (c?: Campaign | null): Form => ({
  name: c?.name ?? "", tagline: c?.tagline ?? "", goal: c?.goal ?? "", date_start: c?.date_start ?? "",
  date_end: c?.date_end ?? "", color: c?.color ?? SWATCHES[2], budget: c?.budget != null ? String(c.budget) : "",
  target_posts: c?.target_posts != null ? String(c.target_posts) : "", auto_state: c?.auto_state ?? true,
  state: c?.state ?? "planned",
});

export function CampaignForm({ campaign, open, onClose, onSaved }: {
  campaign?: Campaign | null; open: boolean; onClose: () => void; onSaved?: (c: Campaign) => void;
}) {
  const t = useTranslations("campaigns");
  const states = useTranslations("planning.states");
  const qc = useQueryClient();
  const [form, setForm] = useState<Form>(() => fromCampaign(campaign));
  const set = (key: keyof Form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {
        name: form.name, tagline: form.tagline || null, goal: form.goal || null, color: form.color,
        date_start: form.date_start || null, date_end: form.date_end || null,
        budget: form.budget ? Number(form.budget) : null, target_posts: form.target_posts ? Number(form.target_posts) : null,
        auto_state: form.auto_state,
      };
      if (!form.auto_state) body.state = form.state;
      return campaign ? api.patch<Campaign>(`/campaigns/${campaign.id}`, body) : api.post<Campaign>("/campaigns", body);
    },
    onSuccess: (saved) => {
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      qc.invalidateQueries({ queryKey: ["campaign", saved.id] });
      toast.success(campaign ? t("saved") : t("created"));
      onSaved?.(saved);
      onClose();
    },
    onError,
  });

  return (
    <Modal open={open} onClose={onClose} title={campaign ? t("edit") : t("new")} size="lg"
      footer={<>
        <Button onClick={onClose}>{t("cancel")}</Button>
        <Button variant="primary" disabled={!form.name.trim()} loading={save.isPending} onClick={() => save.mutate()}>{campaign ? t("save") : t("create")}</Button>
      </>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("fields.name")} className="sm:col-span-2"><Input value={form.name} onChange={set("name")} placeholder={t("fields.namePlaceholder")} autoFocus /></Field>
        <Field label={t("fields.tagline")} className="sm:col-span-2"><Input value={form.tagline} onChange={set("tagline")} placeholder={t("fields.taglinePlaceholder")} /></Field>
        <Field label={t("fields.goal")} className="sm:col-span-2"><Textarea rows={3} value={form.goal} onChange={set("goal")} placeholder={t("fields.goalPlaceholder")} /></Field>
        <Field label={t("fields.start")}><Input type="date" dir="ltr" value={form.date_start} onChange={set("date_start")} /></Field>
        <Field label={t("fields.end")}><Input type="date" dir="ltr" value={form.date_end} min={form.date_start || undefined} onChange={set("date_end")} /></Field>
        <Field label={t("fields.budget")}><Input type="number" min={0} dir="ltr" value={form.budget} onChange={set("budget")} /></Field>
        <Field label={t("fields.targetPosts")} hint={t("fields.targetPostsHint")}><Input type="number" min={0} dir="ltr" value={form.target_posts} onChange={set("target_posts")} /></Field>
        <Field label={t("fields.color")} className="sm:col-span-2"><ColorPicker value={form.color} onChange={(color) => setForm({ ...form, color })} /></Field>
        <div className="flex flex-col gap-3 rounded-2xl bg-fill p-3.5 sm:col-span-2">
          <Switch checked={form.auto_state} onChange={(auto_state) => setForm({ ...form, auto_state })} label={t("fields.autoState")} />
          {!form.auto_state && (
            <Field label={t("fields.state")}>
              <Select value={form.state} onChange={set("state")}>
                {["planned", "running", "finished"].map((s) => <option key={s} value={s}>{states(s)}</option>)}
              </Select>
            </Field>
          )}
        </div>
      </div>
    </Modal>
  );
}
