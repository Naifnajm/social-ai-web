"use client";
/**
 * Minimal model dropdown grouped by provider (the AI feature's shared `@/components/model-picker` can replace it).
 * Groups come from `/api/ai/pickers` when the AI feature provides it, else from the board graph.
 */
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Select } from "@/components/ui";
import { api } from "@/lib/api";
import { usd } from "./meta";
import type { Estimate, PickerGroup } from "./types";

/** Accepts `{capability, groups}` (AI feature), `{[capability]: groups}` or a plain list of groups. */
function normalize(data: unknown, capability: string): PickerGroup[] | null {
  if (Array.isArray(data)) return data as PickerGroup[];
  if (data && typeof data === "object") {
    const record = data as Record<string, unknown>;
    if (Array.isArray(record.groups)) return record.groups as PickerGroup[];
    if (Array.isArray(record[capability])) return record[capability] as PickerGroup[];
  }
  return null;
}

export function ModelPicker({ capability, value, fallback, estimate, onChange, disabled }: {
  capability: string;
  value?: number | null;
  fallback: PickerGroup[];
  estimate?: Estimate | null;
  onChange: (modelId: number | null) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("production");
  const shared = useQuery({
    queryKey: ["ai", "pickers", capability],
    queryFn: () => api.get<unknown>("/ai/pickers", { capability }),
    retry: false,
    staleTime: 60_000,
  });
  const groups = normalize(shared.data, capability) || fallback;
  return (
    <div className="flex flex-col gap-1.5">
      <Select value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
        <option value="">{t("inspector.defaultModel")}</option>
        {groups.map((group) => (
          <optgroup key={group.provider_id} label={group.provider}>
            {group.models.map((m) => (
              <option key={m.id} value={m.id}>{m.label}{(m.price_label || m.price) ? ` · ${m.price_label || m.price}` : ""}</option>
            ))}
          </optgroup>
        ))}
      </Select>
      {!groups.length && <span className="text-xs text-muted">{t("inspector.noModels")}</span>}
      {estimate && (
        <span className="text-xs text-muted">
          {estimate.cost > 0 ? t("inspector.estimate", { cost: usd(estimate.cost) }) : t("inspector.free")}
          {estimate.model ? <span className="font-mono" dir="ltr"> · {estimate.model}</span> : null}
        </span>
      )}
    </div>
  );
}
