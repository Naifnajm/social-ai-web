"use client";
/** Settings › AI providers: the workspace's own keys (OpenAI, Claude, Gemini, ElevenLabs…), defaults, budgets,
 * balances and price lists. Admins only. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { AiMediaButton } from "@/components/ai-media-dialog";
import { Icon } from "@/components/icon";
import { WalletChip } from "@/components/model-picker";
import { Badge, Button, Card, EmptyState, IconButton, Modal, SectionTitle, Segmented, Spinner, cx, toast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { CAPABILITY_ICONS, type Capability, money } from "@/lib/ai";
import { useSession } from "@/lib/session";
import { ProviderDialog } from "./provider-dialog";
import type { CatalogEntry, Provider, TestResult } from "./types";

const onError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : String(err));

function ProviderMark({ label, size = 40 }: { label: string; size?: number }) {
  const letters = label.replace(/[^A-Za-z0-9 ]/g, "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  return (
    <span className="flex shrink-0 items-center justify-center rounded-[13px] bg-ink font-semibold tracking-tight text-white shadow-[0_8px_18px_-10px_rgba(0,0,0,.7)]"
      style={{ width: size, height: size, fontSize: size * 0.36 }} dir="ltr">
      {letters || "AI"}
    </span>
  );
}

function CapIcons({ caps }: { caps: Capability[] }) {
  const t = useTranslations("ai.providers");
  return (
    <span className="flex items-center gap-1">
      {caps.map((c) => (
        <span key={c} title={t(`caps.${c}`)} className="flex h-6 w-6 items-center justify-center rounded-full bg-fill-2 text-text-2">
          <Icon name={CAPABILITY_ICONS[c]} size={13} />
        </span>
      ))}
    </span>
  );
}

export default function AiProvidersPage() {
  const t = useTranslations("ai.providers");
  const qc = useQueryClient();
  const isAdmin = useSession((s) => s.can("admin"));
  const providers = useQuery({ queryKey: ["ai", "providers"], queryFn: () => api.get<Provider[]>("/ai/providers"), enabled: isAdmin });
  const catalog = useQuery({ queryKey: ["ai", "catalog"], queryFn: () => api.get<CatalogEntry[]>("/ai/catalog"), enabled: isAdmin, staleTime: 3600_000 });
  const [dialog, setDialog] = useState<{ entry: CatalogEntry; provider?: Provider | null } | null>(null);
  const [filter, setFilter] = useState<"all" | Capability>("all");
  const [toDelete, setToDelete] = useState<Provider | null>(null);
  const invalidate = () => qc.invalidateQueries({ queryKey: ["ai"] });

  const test = useMutation({
    mutationFn: (id: number) => api.post<TestResult>(`/ai/providers/${id}/test`),
    onSuccess: (r) => { (r.ok ? toast.success : toast.error)(r.warning ? `${r.message} ${r.warning}` : r.message); invalidate(); },
    onError,
  });
  const makeDefault = useMutation({ mutationFn: (id: number) => api.post(`/ai/providers/${id}/default`), onSuccess: invalidate, onError });
  const balance = useMutation({
    mutationFn: (id: number) => api.post<{ ok: boolean; message: string }>(`/ai/providers/${id}/balance`),
    onSuccess: (r) => { (r.ok ? toast.success : toast.error)(r.message); invalidate(); },
    onError,
  });
  const toggle = useMutation({ mutationFn: (p: Provider) => api.patch(`/ai/providers/${p.id}`, { active: !p.active }), onSuccess: invalidate, onError });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/ai/providers/${id}`),
    onSuccess: () => { setToDelete(null); invalidate(); }, onError,
  });

  if (!isAdmin) return <Card><EmptyState icon="lock" title={t("adminOnly")} /></Card>;
  const entryOf = (type: string) => catalog.data?.find((e) => e.type === type);
  const visibleCatalog = (catalog.data ?? []).filter((e) => filter === "all" || e.capabilities.includes(filter));

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <SectionTitle icon="smart_toy" actions={!!providers.data?.length && <AiMediaButton label={t("tryMedia")} />}>{t("yourProviders")}</SectionTitle>
        {providers.isLoading ? (
          <div className="py-8 text-center"><Spinner /></div>
        ) : !providers.data?.length ? (
          <EmptyState icon="auto_awesome" title={t("emptyTitle")} text={t("emptyText")} />
        ) : (
          <ul className="flex flex-col gap-2.5">
            {providers.data.map((p) => {
              const entry = entryOf(p.provider_type);
              return (
                <li key={p.id} className={cx("rounded-2xl bg-white/55 p-3.5 ring-1 ring-line", !p.active && "opacity-60")}>
                  <div className="flex flex-wrap items-start gap-3">
                    <ProviderMark label={p.type_label} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="truncate font-semibold">{p.name}</span>
                        {p.is_default && <Badge tone="ink">{t("default")}</Badge>}
                        <Badge tone={p.state === "ok" ? "ok" : p.state === "error" ? "bad" : "neutral"}>{t(`states.${p.state}`)}</Badge>
                        {!p.has_key && !entry?.no_key && <Badge tone="warn">{t("noKey")}</Badge>}
                        {!p.active && <Badge>{t("inactive")}</Badge>}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                        <span>{p.type_label}</span>
                        <CapIcons caps={p.capabilities} />
                        {p.text_model && <span dir="ltr" className="truncate">{p.text_model}</span>}
                      </div>
                      {p.state === "error" && p.last_error && <p className="bidi mt-1.5 line-clamp-2 text-xs text-bad">{p.last_error}</p>}
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        <WalletChip wallet={p.wallet} />
                        {p.wallet.kind !== "spent" && <span className="text-[11.5px] text-muted">{t("spentMonth", { amount: money(p.spent_month) })}</span>}
                        <span className="text-[11.5px] text-muted">· {t("modelsCount", { count: p.models_count })}</span>
                      </div>
                    </div>
                    <div className="flex w-full flex-wrap items-center gap-1 sm:w-auto">
                      <Button size="sm" icon="bolt" loading={test.isPending && test.variables === p.id} onClick={() => test.mutate(p.id)}>{t("test")}</Button>
                      {p.capabilities.includes("text") && !p.is_default && p.active && (
                        <Button size="sm" variant="ghost" icon="verified" onClick={() => makeDefault.mutate(p.id)}>{t("makeDefault")}</Button>
                      )}
                      {p.balance_supported && (
                        <Button size="sm" variant="ghost" icon="account_balance" loading={balance.isPending && balance.variables === p.id} onClick={() => balance.mutate(p.id)}>{t("balance")}</Button>
                      )}
                      <span className="ms-auto flex items-center sm:ms-0">
                        <IconButton icon="edit_square" label={t("edit")} onClick={() => entry && setDialog({ entry, provider: p })} />
                        <IconButton icon={p.active ? "visibility_off" : "visibility"} label={p.active ? t("deactivate") : t("activate")} onClick={() => toggle.mutate(p)} />
                        <IconButton icon="delete" label={t("delete")} onClick={() => setToDelete(p)} />
                      </span>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <Card>
        <SectionTitle icon="add">{t("addProvider")}</SectionTitle>
        <div className="-mt-1 mb-4 flex flex-wrap items-center gap-3">
          <p className="flex-1 text-sm text-muted">{t("addHint")}</p>
          <div className="max-w-full overflow-x-auto">
            <Segmented size="sm" value={filter} onChange={setFilter}
              options={(["all", "text", "image", "video", "audio"] as const).map((v) => ({ value: v, label: v === "all" ? t("all") : t(`caps.${v}`) }))} />
          </div>
        </div>
        {catalog.isLoading ? <div className="py-6 text-center"><Spinner /></div> : (
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
            {visibleCatalog.map((entry) => (
              <button key={entry.type} type="button" onClick={() => setDialog({ entry })}
                className="group flex items-center gap-3 rounded-2xl bg-white/55 p-3 text-start ring-1 ring-line transition hover:-translate-y-0.5 hover:bg-white/85 hover:shadow-[var(--shadow-lift)]">
                <ProviderMark label={entry.label} size={36} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold" dir="auto">{entry.label}</span>
                  <span className="mt-1 flex items-center gap-2">
                    <CapIcons caps={entry.capabilities} />
                    {entry.no_key && <span className="text-[11px] text-muted">{t("local")}</span>}
                  </span>
                </span>
                <Icon name="add" size={18} className="text-muted transition group-hover:text-text" />
              </button>
            ))}
          </div>
        )}
      </Card>

      <Card className="text-sm text-muted">
        <SectionTitle icon="info">{t("howTitle")}</SectionTitle>
        <ul className="grid list-disc gap-1.5 ps-5">
          <li>{t("how1")}</li>
          <li>{t("how2")}</li>
          <li>{t("how3")}</li>
        </ul>
      </Card>

      {dialog && <ProviderDialog key={`${dialog.entry.type}-${dialog.provider?.id ?? "new"}`} open entry={dialog.entry} provider={dialog.provider} onClose={() => setDialog(null)} />}
      <Modal open={!!toDelete} onClose={() => setToDelete(null)} title={t("deleteTitle")} size="sm"
        footer={<><Button onClick={() => setToDelete(null)}>{t("cancel")}</Button><Button variant="danger" loading={remove.isPending} onClick={() => toDelete && remove.mutate(toDelete.id)}>{t("delete")}</Button></>}>
        <p className="text-sm text-text-2">{t("deleteText", { name: toDelete?.name ?? "" })}</p>
      </Modal>
    </div>
  );
}
