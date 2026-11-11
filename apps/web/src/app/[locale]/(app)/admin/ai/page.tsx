"use client";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Badge, Card, EmptyState, SectionTitle, Spinner } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";

type Row = { key: string; label: string; cost: number; calls: number; limit: number | null };
type Overview = { month_total: number; keys: Record<string, boolean>; by_provider: Row[]; by_workspace: Row[] };
const money = (v: number) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const KEY_LABELS: Record<string, string> = { openai: "OpenAI", anthropic: "Anthropic", gemini: "Google Gemini", elevenlabs: "ElevenLabs" };

/** What the platform's own AI keys cost this month: per provider and per workspace, against each plan's credit. */
export default function AdminAiPage() {
  const t = useTranslations("admin");
  const { data, isLoading } = useQuery({ queryKey: ["admin-ai"], queryFn: () => api.get<Overview>("/admin/ai") });
  if (isLoading || !data) return <div className="flex justify-center py-16"><Spinner /></div>;
  const anyKey = Object.values(data.keys).some(Boolean);
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-1">
        <SectionTitle icon="key">{t("ai.keys")}</SectionTitle>
        <ul className="mt-3 flex flex-col gap-2 text-sm">
          {Object.entries(data.keys).map(([name, ok]) => (
            <li key={name} className="flex items-center justify-between">
              <span dir="ltr">{KEY_LABELS[name] ?? name}</span>
              <Badge tone={ok ? "ok" : "neutral"}>{ok ? t("ai.keySet") : t("ai.keyMissing")}</Badge>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-xs leading-relaxed text-muted">{anyKey ? t("ai.keysHintOn") : t("ai.keysHintOff")}</p>
        <Link href="/admin/settings" className="mt-3 inline-block text-sm font-semibold underline">{t("ai.manageKeys")}</Link>
      </Card>
      <Card className="lg:col-span-2">
        <SectionTitle icon="bar_chart">{t("ai.spendTitle")}</SectionTitle>
        <div className="mt-2 text-3xl font-bold tracking-tight" dir="ltr">{money(data.month_total)}</div>
        <p className="text-xs text-muted">{t("ai.spendHint")}</p>
        {data.by_provider.length === 0 ? <EmptyState icon="auto_awesome" title={t("ai.noSpend")} />
          : (
            <ul className="mt-4 flex flex-col gap-3 text-sm">
              {data.by_provider.map((p) => (
                <li key={p.key}>
                  <div className="flex justify-between"><b dir="ltr">{p.label}</b><span dir="ltr">{money(p.cost)} · {p.calls}</span></div>
                  <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-track"><div className="h-full rounded-full bg-ink" style={{ width: `${Math.max(2, (p.cost / (data.month_total || 1)) * 100)}%` }} /></div>
                </li>
              ))}
            </ul>
          )}
      </Card>
      <Card className="lg:col-span-3">
        <SectionTitle icon="business_center">{t("ai.byWorkspace")}</SectionTitle>
        {data.by_workspace.length === 0 ? <p className="mt-3 text-sm text-muted">{t("ai.noSpend")}</p>
          : (
            <ul className="mt-3 flex flex-col divide-y divide-line/60 text-sm">
              {data.by_workspace.map((w) => (
                <li key={w.key} className="flex items-center gap-4 py-2.5">
                  <Link href={`/admin/workspaces/${w.key}`} className="min-w-0 flex-1 truncate font-semibold">{w.label}</Link>
                  <span className="text-muted">{t("ai.calls", { n: w.calls })}</span>
                  <span dir="ltr" className="w-40 text-end">{money(w.cost)}{w.limit != null ? ` / ${money(w.limit)}` : ""}</span>
                </li>
              ))}
            </ul>
          )}
      </Card>
    </div>
  );
}
