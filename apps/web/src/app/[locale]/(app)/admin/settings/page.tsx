"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon } from "@/components/icon";
import { Badge, Button, Card, Field, IconButton, Input, SectionTitle, Select, Spinner, Textarea, toast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

type Pack = { usd: number | string; credits: number | string };
type Values = Record<string, string | number | boolean | Record<string, string> | Pack[] | null>;
type SettingsOut = { values: Values; schema: Record<string, string>; stripe_configured: boolean; stripe_webhook_configured: boolean; webhook_url: string };

const AI_KEYS = [
  { key: "ai.openai_api_key", label: "OpenAI" },
  { key: "ai.anthropic_api_key", label: "Anthropic" },
  { key: "ai.gemini_api_key", label: "Google Gemini" },
  { key: "ai.elevenlabs_api_key", label: "ElevenLabs" },
];
const PRICE_KEYS = ["starter_month", "starter_year", "pro_month", "pro_year", "business_month", "business_year"];
// shown as placeholders: the API's defaults (billing/credits.py) when a setting is empty
const DEFAULT_MARKUP = 10;
const DEFAULT_CREDITS_PER_USD = 100;
const DEFAULT_PACKS: Pack[] = [{ usd: 10, credits: 1000 }, { usd: 25, credits: 2600 }, { usd: 50, credits: 5400 }, { usd: 100, credits: 11000 }];

/** A setting of schema type "float"/"int" as text for an input ("" = not set, the default applies). */
const numText = (value: Values[string]) => (value == null || value === "" ? "" : String(value));
/** Schema type "list" of credit packs: rows with both numbers filled, as numbers (empty = the default packs). */
const cleanPacks = (rows: { usd: string; credits: string }[]) =>
  rows.filter((r) => Number(r.usd) > 0 && Number(r.credits) > 0).map((r) => ({ usd: Number(r.usd), credits: Math.round(Number(r.credits)) }));

function SettingsForm({ initial }: { initial: SettingsOut }) {
  const t = useTranslations("admin.settings");
  const ta = useTranslations("admin");
  const tb = useTranslations("billing");
  const qc = useQueryClient();
  const v = initial.values;
  const [form, setForm] = useState({
    provider: String(v["ai.default_provider"] ?? ""),
    textModel: String(v["ai.default_text_model"] ?? ""),
    imageModel: String(v["ai.default_image_model"] ?? ""),
    trialDays: v["billing.trial_days"] == null ? "" : String(v["billing.trial_days"]),
    graceDays: v["billing.grace_days"] == null ? "" : String(v["billing.grace_days"]),
    prices: { ...((v["billing.stripe_prices"] as Record<string, string>) || {}) },
    announcement: String(v["platform.announcement"] ?? ""),
    markup: numText(v["billing.ai_markup_percent"]),
    creditsPerUsd: numText(v["billing.credits_per_usd"]),
    packs: (Array.isArray(v["billing.credit_packs"]) && v["billing.credit_packs"].length ? (v["billing.credit_packs"] as Pack[]) : DEFAULT_PACKS)
      .map((p) => ({ usd: String(p.usd ?? ""), credits: String(p.credits ?? "") })),
  });
  const setPack = (index: number, patch: Partial<{ usd: string; credits: string }>) =>
    setForm((f) => ({ ...f, packs: f.packs.map((p, i) => (i === index ? { ...p, ...patch } : p)) }));
  const perUsd = Number(form.creditsPerUsd) || DEFAULT_CREDITS_PER_USD;
  const [secrets, setSecrets] = useState<Record<string, string>>({});

  const save = useMutation({
    mutationFn: () => api.put<SettingsOut>("/admin/settings", { values: {
      "ai.default_provider": form.provider, "ai.default_text_model": form.textModel, "ai.default_image_model": form.imageModel,
      "billing.trial_days": form.trialDays, "billing.grace_days": form.graceDays, "billing.stripe_prices": form.prices,
      "platform.announcement": form.announcement,
      "billing.ai_markup_percent": form.markup, "billing.credits_per_usd": form.creditsPerUsd,
      "billing.credit_packs": cleanPacks(form.packs).length ? cleanPacks(form.packs) : null,
      ...secrets,
    } }),
    onSuccess: (data) => {
      qc.setQueryData(["admin-settings"], data);
      setSecrets({});
      toast.success(t("saved"));
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <SectionTitle icon="auto_awesome">{t("ai")}</SectionTitle>
        <p className="-mt-1 mb-4 text-sm text-muted">{t("aiHint")}</p>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label={t("defaultProvider")}>
            <Select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })}>
              <option value="">—</option>
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="gemini">Google Gemini</option>
            </Select>
          </Field>
          <Field label={t("textModel")}><Input dir="ltr" value={form.textModel} onChange={(e) => setForm({ ...form, textModel: e.target.value })} /></Field>
          <Field label={t("imageModel")}><Input dir="ltr" value={form.imageModel} onChange={(e) => setForm({ ...form, imageModel: e.target.value })} /></Field>
        </div>
        <ul className="mt-5 flex flex-col divide-y divide-line">
          {AI_KEYS.map(({ key, label }) => {
            const configured = initial.values[key] === true && secrets[key] !== "";
            return (
              <li key={key} className="flex flex-wrap items-center gap-3 py-3">
                <Icon name="key" size={18} className="text-text-2" />
                <span className="w-32 text-sm font-semibold" dir="ltr">{label}</span>
                <Badge tone={configured ? "ok" : "neutral"}>{configured ? t("configured") : t("notConfigured")}</Badge>
                <Input className="min-w-[200px] flex-1" type="password" dir="ltr" autoComplete="off" placeholder={configured ? "••••••••  " + t("replace") : "sk-…"}
                  value={secrets[key] ?? ""} onChange={(e) => setSecrets({ ...secrets, [key]: e.target.value })} />
                {initial.values[key] === true && <IconButton icon="delete" label={t("clear")} onClick={() => setSecrets({ ...secrets, [key]: "" })} />}
              </li>
            );
          })}
        </ul>
      </Card>

      <Card>
        <SectionTitle icon="payments">{t("billing")}</SectionTitle>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("trialDays")}><Input type="number" min={1} dir="ltr" placeholder="14" value={form.trialDays} onChange={(e) => setForm({ ...form, trialDays: e.target.value })} /></Field>
          <Field label={t("graceDays")}><Input type="number" min={0} dir="ltr" placeholder="7" value={form.graceDays} onChange={(e) => setForm({ ...form, graceDays: e.target.value })} /></Field>
        </div>
        <div className="mt-5 rounded-2xl bg-fill p-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-semibold">{t("stripe")}</span>
            <Badge tone={initial.stripe_configured ? "ok" : "warn"} className="cursor-help"><span title="SAI_STRIPE_SECRET_KEY">{t("stripeKey")}</span>: {initial.stripe_configured ? t("configured") : t("notConfigured")}</Badge>
            <Badge tone={initial.stripe_webhook_configured ? "ok" : "warn"}><span title="SAI_STRIPE_WEBHOOK_SECRET">{t("webhookSecret")}</span>: {initial.stripe_webhook_configured ? t("configured") : t("notConfigured")}</Badge>
          </div>
          <Field label={t("webhookUrl")} className="mt-3"><Input readOnly dir="ltr" value={initial.webhook_url} onFocus={(e) => e.target.select()} /></Field>
          <p className="mb-2 mt-4 text-[13px] font-medium text-text-2">{t("prices")}</p>
          <div className="grid gap-3 sm:grid-cols-2">
            {PRICE_KEYS.map((k) => {
              const [plan, interval] = k.split("_");
              return (
                <Field key={k} label={<span className="text-xs">{tb(`plans.${plan}`)} · {interval === "year" ? tb("yearly") : tb("monthly")}</span>}>
                  <Input dir="ltr" placeholder="price_…" value={form.prices[k] ?? ""} onChange={(e) => setForm({ ...form, prices: { ...form.prices, [k]: e.target.value } })} />
                </Field>
              );
            })}
          </div>
        </div>
      </Card>

      <Card>
        <SectionTitle icon="toll">{t("credits.title")}</SectionTitle>
        <p className="-mt-1 mb-4 text-sm text-muted">{t("credits.hint")}</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("credits.markup")} hint={t("credits.markupHint")}>
            <div className="relative" dir="ltr">
              <Input type="number" min={0} max={500} step={0.5} dir="ltr" className="pe-9" placeholder={String(DEFAULT_MARKUP)}
                value={form.markup} onChange={(e) => setForm({ ...form, markup: e.target.value })} />
              <span className="pointer-events-none absolute inset-y-0 end-3 flex items-center text-sm font-semibold text-muted">%</span>
            </div>
          </Field>
          <Field label={t("credits.perUsd")} hint={t("credits.perUsdHint", { n: perUsd })}>
            <Input type="number" min={1} step={1} dir="ltr" placeholder={String(DEFAULT_CREDITS_PER_USD)}
              value={form.creditsPerUsd} onChange={(e) => setForm({ ...form, creditsPerUsd: e.target.value })} />
          </Field>
        </div>
        <div className="mt-5">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-[13px] font-medium text-text-2">{t("credits.packs")}</span>
            {!form.packs.length && <span className="text-xs text-muted">{t("credits.packsDefault")}</span>}
          </div>
          <ul className="flex flex-col gap-2">
            {form.packs.map((pack, i) => {
              const usd = Number(pack.usd), amount = Number(pack.credits);
              const bonus = usd > 0 && amount > 0 ? Math.round((100 * (amount - usd * perUsd)) / (usd * perUsd)) : 0;
              return (
                <li key={i} className="flex flex-wrap items-center gap-2">
                  <div className="relative w-32" dir="ltr">
                    <span className="pointer-events-none absolute inset-y-0 start-3 flex items-center text-sm text-muted">$</span>
                    <Input type="number" min={0} step={1} dir="ltr" className="ps-7" aria-label={t("credits.price")} placeholder="10"
                      value={pack.usd} onChange={(e) => setPack(i, { usd: e.target.value })} />
                  </div>
                  <Icon name="east" size={16} className="text-muted rtl:rotate-180" />
                  <div className="relative w-40" dir="ltr">
                    <Input type="number" min={0} step={1} dir="ltr" className="pe-16" aria-label={t("credits.amount")} placeholder="1000"
                      value={pack.credits} onChange={(e) => setPack(i, { credits: e.target.value })} />
                    <span className="pointer-events-none absolute inset-y-0 end-3 flex items-center text-xs text-muted">{t("credits.unit")}</span>
                  </div>
                  {/* fixed-width slot: the delete button stays in the same column with or without a bonus */}
                  <span className="flex w-28 shrink-0">{bonus > 0 && <Badge tone="ok">{t("credits.bonus", { n: bonus })}</Badge>}</span>
                  <IconButton icon="delete" label={t("credits.remove")} onClick={() => setForm((f) => ({ ...f, packs: f.packs.filter((_, j) => j !== i) }))} />
                </li>
              );
            })}
          </ul>
          <Button size="sm" variant="ghost" icon="add" className="mt-2" onClick={() => setForm((f) => ({ ...f, packs: [...f.packs, { usd: "", credits: "" }] }))}>
            {t("credits.addPack")}
          </Button>
        </div>
      </Card>

      <Card>
        <SectionTitle icon="campaign">{t("general")}</SectionTitle>
        <Field label={t("announcement")}><Textarea rows={2} value={form.announcement} onChange={(e) => setForm({ ...form, announcement: e.target.value })} /></Field>
      </Card>

      <div className="flex justify-end">
        <Button variant="primary" icon="save" loading={save.isPending} onClick={() => save.mutate()}>{ta("save")}</Button>
      </div>
    </div>
  );
}

export default function PlatformSettingsPage() {
  const { data } = useQuery({ queryKey: ["admin-settings"], queryFn: () => api.get<SettingsOut>("/admin/settings") });
  if (!data) return <div className="flex justify-center py-16"><Spinner size={26} /></div>;
  return <SettingsForm initial={data} />;
}
