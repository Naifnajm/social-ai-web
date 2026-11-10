"use client";
/** Editable price list of one provider (prices feed estimates, budgets and the AI costs page). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon } from "@/components/icon";
import { Button, IconButton, Input, Select, Spinner, Switch, cx, toast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { CAPABILITY_ICONS, type Capability } from "@/lib/ai";
import { type AiModel, UNITS } from "./types";

const onError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : String(err));

export function ModelsTable({ providerId, capabilities }: { providerId: number; capabilities: Capability[] }) {
  const t = useTranslations("ai.providers");
  const qc = useQueryClient();
  const key = ["ai", "models", providerId];
  const models = useQuery({ queryKey: key, queryFn: () => api.get<AiModel[]>(`/ai/providers/${providerId}/models`) });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: ["ai", "picker"] });
  };
  const update = useMutation({
    mutationFn: ({ id, ...body }: Partial<AiModel> & { id: number }) => api.patch(`/ai/models/${id}`, body),
    onSuccess: refresh, onError,
  });
  const remove = useMutation({ mutationFn: (id: number) => api.delete(`/ai/models/${id}`), onSuccess: refresh, onError });
  const loadCatalog = useMutation({
    mutationFn: () => api.post(`/ai/providers/${providerId}/models/load-catalog`),
    onSuccess: () => { refresh(); toast.success(t("catalogLoaded")); }, onError,
  });
  const [draft, setDraft] = useState({ name: "", capability: capabilities[0] ?? "text", unit: "tokens", price_in: "", price_out: "", price: "" });
  const create = useMutation({
    mutationFn: () => api.post(`/ai/providers/${providerId}/models`, {
      name: draft.name, capability: draft.capability, unit: draft.unit, price_in: Number(draft.price_in) || 0,
      price_out: Number(draft.price_out) || 0, price: Number(draft.price) || 0,
    }),
    onSuccess: () => { refresh(); setDraft({ ...draft, name: "", price_in: "", price_out: "", price: "" }); }, onError,
  });

  if (models.isLoading) return <div className="py-6 text-center"><Spinner /></div>;

  const priceInput = (m: AiModel, field: "price_in" | "price_out" | "price") => (
    <Input key={`${m.id}-${field}-${m[field]}`} type="number" min={0} step="0.001" dir="ltr" defaultValue={m[field]}
      className="!h-8 !w-20 !px-2 text-[13px] tabular-nums" aria-label={t(`fields.${field}`)}
      onBlur={(e) => { const v = Number(e.target.value) || 0; if (v !== m[field]) update.mutate({ id: m.id, [field]: v }); }} />
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="flex-1 text-xs text-muted">{t("pricesHint")}</p>
        <Button size="sm" icon="download" loading={loadCatalog.isPending} onClick={() => loadCatalog.mutate()}>{t("loadCatalog")}</Button>
      </div>
      <div className="overflow-x-auto rounded-2xl ring-1 ring-line">
        <table className="w-full min-w-[620px] text-[13px]">
          <thead className="bg-fill text-start text-xs text-muted">
            <tr>
              <th className="px-3 py-2 text-start font-medium">{t("fields.model")}</th>
              <th className="px-2 py-2 text-start font-medium">{t("fields.unit")}</th>
              <th className="px-2 py-2 text-start font-medium">{t("fields.prices")}</th>
              <th className="px-2 py-2 text-start font-medium">{t("fields.active")}</th>
              <th className="w-10" />
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {models.data?.map((m) => (
              <tr key={m.id} className={cx(!m.active && "opacity-50")}>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <Icon name={CAPABILITY_ICONS[m.capability]} size={15} className="text-muted" />
                    <div className="min-w-0">
                      <div className="truncate font-medium">{m.label}</div>
                      <div className="truncate text-[11px] text-muted" dir="ltr">{m.name}</div>
                    </div>
                  </div>
                </td>
                <td className="px-2 py-2 text-xs text-text-2">{t(`units.${m.unit}`)}</td>
                <td className="px-2 py-2">
                  {m.unit === "free" ? <span className="text-xs text-muted">{t("units.free")}</span> : m.unit === "tokens" ? (
                    <div dir="ltr" className="flex w-fit items-center gap-1 whitespace-nowrap text-[11px] text-muted">{priceInput(m, "price_in")}<span>/</span>{priceInput(m, "price_out")}<span>$ / 1M</span></div>
                  ) : (
                    <div dir="ltr" className="flex w-fit items-center gap-1 text-[11px] text-muted">{priceInput(m, "price")}<span>$</span></div>
                  )}
                </td>
                <td className="px-2 py-2"><Switch checked={m.active} onChange={(v) => update.mutate({ id: m.id, active: v })} /></td>
                <td className="px-1 py-2"><IconButton icon="delete" label={t("deleteModel")} onClick={() => remove.mutate(m.id)} /></td>
              </tr>
            ))}
            {!models.data?.length && (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-muted">{t("noModels")}</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-end gap-2 rounded-2xl bg-fill p-3">
        <Input dir="ltr" placeholder={t("fields.modelId")} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} className="!h-9 min-w-40 flex-1" />
        <Select value={draft.capability} onChange={(e) => setDraft({ ...draft, capability: e.target.value as Capability })} className="!h-9 !w-auto">
          {capabilities.map((c) => <option key={c} value={c}>{t(`caps.${c}`)}</option>)}
        </Select>
        <Select value={draft.unit} onChange={(e) => setDraft({ ...draft, unit: e.target.value })} className="!h-9 !w-auto">
          {UNITS.map((u) => <option key={u} value={u}>{t(`units.${u}`)}</option>)}
        </Select>
        {draft.unit === "tokens" ? (
          <>
            <Input type="number" dir="ltr" placeholder={t("fields.price_in")} value={draft.price_in} onChange={(e) => setDraft({ ...draft, price_in: e.target.value })} className="!h-9 !w-24" />
            <Input type="number" dir="ltr" placeholder={t("fields.price_out")} value={draft.price_out} onChange={(e) => setDraft({ ...draft, price_out: e.target.value })} className="!h-9 !w-24" />
          </>
        ) : draft.unit !== "free" && (
          <Input type="number" dir="ltr" placeholder={t("fields.price")} value={draft.price} onChange={(e) => setDraft({ ...draft, price: e.target.value })} className="!h-9 !w-24" />
        )}
        <Button size="sm" icon="add" disabled={!draft.name.trim()} loading={create.isPending} onClick={() => create.mutate()}>{t("addModel")}</Button>
      </div>
    </div>
  );
}
