"use client";
/** Settings › AI providers › "Who does each job": which provider writes (the default text provider), makes images,
 * video, voice & sound and speech to text, and the fast (cheap) text model used for bulk work. Every job is a
 * drop-down of the providers added here, each shown with the model it uses. `null` everywhere means "automatic". */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { Icon } from "@/components/icon";
import { Card, SectionTitle, Select, Spinner, toast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { CAPABILITY_ICONS } from "@/lib/ai";
import { MODEL_FIELDS, type Provider } from "./types";

type Brief = { id: number; name: string; type: string; managed: boolean };
type MediaCap = "image" | "video" | "audio" | "stt";
type CapDefaults = { chosen_id: number | null; effective: Brief | null; options: Brief[]; recommended: string[] };
type FastModel = { id: number; label: string; provider: string; price_label?: string | null };
type Defaults = {
  text: Brief | null;
  capabilities: Record<MediaCap, CapDefaults>;
  fast: { chosen_id: number | null; effective: { id: number; label: string; price_label?: string | null } | null; options: FastModel[] };
};
type DefaultsIn = Record<MediaCap, number | null> & { fast_model_id: number | null };

const JOBS: MediaCap[] = ["image", "video", "audio", "stt"];

function Row({ icon, title, children, now }: { icon: string; title: string; children: ReactNode; now?: ReactNode }) {
  return (
    <li className="flex flex-col gap-2 rounded-2xl bg-white/55 p-3.5 ring-1 ring-line sm:flex-row sm:items-center sm:gap-4">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-fill-2 text-text-2">
          <Icon name={icon} size={18} />
        </span>
        <div className="min-w-0">
          <div className="text-sm font-semibold">{title}</div>
          {now && <div className="truncate text-xs text-muted">{now}</div>}
        </div>
      </div>
      <div className="w-full sm:w-72">{children}</div>
    </li>
  );
}

export function JobDefaultsCard() {
  const t = useTranslations("ai.providers.jobs");
  const qc = useQueryClient();
  const defaults = useQuery({ queryKey: ["ai", "defaults"], queryFn: () => api.get<Defaults>("/ai/defaults") });

  const save = useMutation({
    mutationFn: (body: DefaultsIn) => api.put<Defaults>("/ai/defaults", body),
    onSuccess: (data) => {
      qc.setQueryData(["ai", "defaults"], data);
      qc.invalidateQueries({ queryKey: ["ai", "status"] });
      toast.success(t("saved"));
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });

  const providers = useQuery({ queryKey: ["ai", "providers"], queryFn: () => api.get<Provider[]>("/ai/providers") });
  const makeDefault = useMutation({
    mutationFn: (id: number) => api.post<Provider>(`/ai/providers/${id}/default`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ai"] });
      toast.success(t("saved"));
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
  const byId = new Map((providers.data ?? []).map((p) => [p.id, p]));
  const textProviders = (providers.data ?? []).filter((p) => p.capabilities.includes("text"));
  // "OpenAI · gpt-image-1": the provider and the model it uses for that job
  const withModel = (id: number, name: string, cap: "text" | MediaCap) => {
    const field = MODEL_FIELDS[cap];
    const model = field ? byId.get(id)?.[field] : null;
    return model ? `${name} · ${model}` : name;
  };

  const d = defaults.data;
  const change = (patch: Partial<DefaultsIn>) => {
    if (!d) return;
    // PUT replaces every choice, so send the current ones along with the change
    const body = { fast_model_id: d.fast.chosen_id, ...Object.fromEntries(JOBS.map((c) => [c, d.capabilities[c].chosen_id])) } as DefaultsIn;
    save.mutate({ ...body, ...patch });
  };
  const toId = (value: string) => (value ? Number(value) : null);

  return (
    <Card>
      <SectionTitle icon="account_tree" actions={(save.isPending || makeDefault.isPending) && <Spinner size={16} />}>{t("title")}</SectionTitle>
      <p className="-mt-1 mb-4 text-sm text-muted">{t("hint")}</p>
      {defaults.isLoading || !d ? (
        <div className="py-6 text-center"><Spinner /></div>
      ) : (
        <ul className="flex flex-col gap-2.5">
          <Row icon={CAPABILITY_ICONS.text} title={t("names.text")}
            now={d.text ? t("inUse", { name: withModel(d.text.id, d.text.name, "text") }) : t("nobody")}>
            <Select aria-label={t("names.text")} value={d.text?.id ?? ""} disabled={makeDefault.isPending || !textProviders.length}
              onChange={(e) => e.target.value && makeDefault.mutate(Number(e.target.value))}>
              {!d.text && <option value="">{textProviders.length ? t("choose") : t("noOptions")}</option>}
              {textProviders.map((p) => <option key={p.id} value={p.id}>{withModel(p.id, p.name, "text")}</option>)}
            </Select>
          </Row>
          {JOBS.map((cap) => {
            const c = d.capabilities[cap];
            const recommended = c.options.find((o) => c.recommended.includes(o.type)) ?? c.options[0];
            return (
              <Row key={cap} icon={CAPABILITY_ICONS[cap]} title={t(`names.${cap}`)}
                now={c.effective ? t("inUse", { name: withModel(c.effective.id, c.effective.name, cap) }) : t("nobody")}>
                <Select aria-label={t(`names.${cap}`)} value={c.chosen_id ?? ""} disabled={save.isPending || !c.options.length}
                  onChange={(e) => change({ [cap]: toId(e.target.value) })}>
                  <option value="">{recommended ? t("autoRecommended", { name: withModel(recommended.id, recommended.name, cap) }) : t("noOptions")}</option>
                  {c.options.map((o) => <option key={o.id} value={o.id}>{withModel(o.id, o.name, cap)}</option>)}
                </Select>
              </Row>
            );
          })}
          <Row icon="bolt" title={t("names.fast")}
            now={d.fast.effective ? t("inUse", { name: d.fast.effective.label }) : t("nobody")}>
            <Select aria-label={t("names.fast")} value={d.fast.chosen_id ?? ""} disabled={save.isPending || !d.fast.options.length}
              onChange={(e) => change({ fast_model_id: toId(e.target.value) })}>
              <option value="">{d.fast.options.length ? t("auto") : t("noOptions")}</option>
              {d.fast.options.map((m) => (
                <option key={m.id} value={m.id}>{m.price_label ? `${m.label} · ${m.provider} · ${m.price_label}` : `${m.label} · ${m.provider}`}</option>
              ))}
            </Select>
          </Row>
        </ul>
      )}
    </Card>
  );
}
