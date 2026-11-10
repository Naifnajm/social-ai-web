"use client";
/** Add / edit an AI provider: key (never shown back), base URL, default models, voice, budget, default switch,
 * and (when editing) the model price list. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon } from "@/components/icon";
import { Button, Field, Input, Modal, Segmented, Switch, toast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Capability } from "@/lib/ai";
import { ModelsTable } from "./models-table";
import { type CatalogEntry, MODEL_FIELDS, type Provider, type TestResult } from "./types";

type Form = {
  name: string; api_key: string; base_url: string; text_model: string; image_model: string; video_model: string;
  audio_model: string; voice: string; max_tokens: string; monthly_budget: string; is_default: boolean;
};

function initialForm(entry: CatalogEntry, provider?: Provider | null): Form {
  if (provider) {
    return {
      name: provider.name, api_key: "", base_url: provider.base_url ?? "", text_model: provider.text_model ?? "",
      image_model: provider.image_model ?? "", video_model: provider.video_model ?? "", audio_model: provider.audio_model ?? "",
      voice: provider.voice ?? "", max_tokens: String(provider.max_tokens ?? ""), monthly_budget: provider.monthly_budget ? String(provider.monthly_budget) : "",
      is_default: provider.is_default,
    };
  }
  const d = entry.default_models;
  return {
    name: entry.label.split(" (")[0], api_key: "", base_url: entry.needs_base_url ? "" : "", text_model: d.text ?? "",
    image_model: d.image ?? "", video_model: d.video ?? "", audio_model: d.audio ?? "", voice: entry.voice ?? "",
    max_tokens: String(entry.max_tokens), monthly_budget: "", is_default: false,
  };
}

export function ProviderDialog({ entry, provider, open, onClose }: { entry: CatalogEntry; provider?: Provider | null; open: boolean; onClose: () => void }) {
  const t = useTranslations("ai.providers");
  const qc = useQueryClient();
  const [form, setForm] = useState<Form>(() => initialForm(entry, provider));
  const [tab, setTab] = useState<"settings" | "models">("settings");
  const [advanced, setAdvanced] = useState(entry.needs_base_url);
  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));
  const editing = !!provider;
  const canText = entry.capabilities.includes("text");

  const save = useMutation({
    mutationFn: async () => {
      const body: Record<string, unknown> = {
        name: form.name.trim() || undefined, base_url: form.base_url.trim() || null,
        text_model: form.text_model.trim() || null, image_model: form.image_model.trim() || null,
        video_model: form.video_model.trim() || null, audio_model: form.audio_model.trim() || null,
        voice: form.voice.trim() || null, max_tokens: Number(form.max_tokens) || undefined,
        monthly_budget: form.monthly_budget === "" ? null : Number(form.monthly_budget),
      };
      if (canText) body.is_default = form.is_default;
      if (form.api_key.trim()) body.api_key = form.api_key.trim();
      if (editing) return api.patch<Provider>(`/ai/providers/${provider!.id}`, body);
      const created = await api.post<Provider>("/ai/providers", { ...body, provider_type: entry.type });
      if (created.has_key || entry.no_key) {
        const test = await api.post<TestResult>(`/ai/providers/${created.id}/test`).catch(() => null);
        if (test) (test.ok ? toast.success : toast.error)(test.message);
      }
      return created;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ai"] });
      if (editing) toast.success(t("saved"));
      onClose();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
  const clearKey = useMutation({
    mutationFn: () => api.patch<Provider>(`/ai/providers/${provider!.id}`, { api_key: "" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["ai"] }); toast.success(t("keyRemoved")); },
  });

  const footer = tab === "settings" ? (
    <>
      <Button onClick={onClose}>{t("cancel")}</Button>
      <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()} disabled={!entry.no_key && !editing && !form.api_key.trim()}>
        {editing ? t("save") : t("addAndTest")}
      </Button>
    </>
  ) : <Button onClick={onClose}>{t("close")}</Button>;

  return (
    <Modal open={open} onClose={onClose} size="lg" footer={footer}
      title={<span className="flex items-center gap-2">{editing ? provider!.name : t("addTitle", { name: entry.label })}</span>}>
      {editing && (
        <Segmented className="mb-4" value={tab} onChange={setTab}
          options={[{ value: "settings", label: t("tabSettings"), icon: "settings" }, { value: "models", label: t("tabModels"), icon: "payments" }]} />
      )}
      {tab === "models" && editing ? (
        <ModelsTable providerId={provider!.id} capabilities={entry.capabilities} />
      ) : (
        <div className="flex flex-col gap-4">
          {!entry.no_key && (
            <Field label={t("apiKey")} hint={editing && provider!.has_key ? t("keySavedHint") : t("keyHint")}>
              <div className="flex gap-2">
                <Input type="password" dir="ltr" autoComplete="off" value={form.api_key} onChange={(e) => set({ api_key: e.target.value })}
                  placeholder={editing && provider!.has_key ? "••••••••••••" : "sk-…"} className="flex-1" />
                {entry.key_url && (
                  <a href={entry.key_url} target="_blank" rel="noopener noreferrer"
                    className="glass inline-flex h-10 shrink-0 items-center gap-1.5 rounded-full px-4 text-sm font-medium hover:bg-white/80">
                    <Icon name="key" size={15} /> {t("getKey")}
                  </a>
                )}
              </div>
            </Field>
          )}
          {editing && provider!.has_key && (
            <Button size="sm" variant="ghost" icon="delete" className="-mt-2 self-start text-bad" loading={clearKey.isPending} onClick={() => clearKey.mutate()}>{t("removeKey")}</Button>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("name")}><Input value={form.name} onChange={(e) => set({ name: e.target.value })} /></Field>
            <Field label={t("monthlyBudget")} hint={t("budgetHint")}>
              <Input type="number" min={0} step="1" dir="ltr" placeholder="—" value={form.monthly_budget} onChange={(e) => set({ monthly_budget: e.target.value })} />
            </Field>
            {(Object.keys(MODEL_FIELDS) as Capability[]).filter((c) => entry.capabilities.includes(c)).map((c) => (
              <Field key={c} label={t(`defaultModel.${c}`)}>
                <Input dir="ltr" list={c === "text" && editing ? `models-${provider!.id}` : undefined} value={form[MODEL_FIELDS[c]!]}
                  onChange={(e) => set({ [MODEL_FIELDS[c]!]: e.target.value } as Partial<Form>)} />
              </Field>
            ))}
            {entry.capabilities.includes("audio") && (
              <Field label={t("voice")} hint={t("voiceHint")}><Input dir="ltr" value={form.voice} onChange={(e) => set({ voice: e.target.value })} /></Field>
            )}
          </div>
          {editing && !!provider!.available_models.length && (
            <datalist id={`models-${provider!.id}`}>{provider!.available_models.map((m) => <option key={m} value={m} />)}</datalist>
          )}
          {canText && <Switch checked={form.is_default} onChange={(v) => set({ is_default: v })} label={t("defaultSwitch")} />}

          <button type="button" onClick={() => setAdvanced((v) => !v)} className="flex items-center gap-1 self-start text-[13px] font-medium text-text-2">
            <Icon name={advanced ? "expand_less" : "expand_more"} size={16} /> {t("advanced")}
          </button>
          {advanced && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t("baseUrl")} hint={entry.needs_base_url ? t("baseUrlRequired") : t("baseUrlHint", { url: entry.base_url })} className="sm:col-span-2">
                <Input dir="ltr" value={form.base_url} placeholder={entry.base_url || "https://…/v1"} onChange={(e) => set({ base_url: e.target.value })} />
              </Field>
              {canText && (
                <Field label={t("maxTokens")} hint={t("maxTokensHint")}>
                  <Input type="number" dir="ltr" value={form.max_tokens} onChange={(e) => set({ max_tokens: e.target.value })} />
                </Field>
              )}
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
