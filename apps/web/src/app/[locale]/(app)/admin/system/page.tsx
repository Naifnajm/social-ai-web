"use client";
import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { Badge, Card, SectionTitle, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/billing";

type Check = { key: string; ok: boolean; detail: string };
type LogError = { id: number; service: string; operation: string; status_code: number | null; error: string | null; created_at: string };
type SystemOut = {
  checks: Check[]; queues: Record<string, number>; workers: number; failed_jobs: number; errors_24h: number;
  posts_today: number; failed_posts_today: number; recent_errors: LogError[];
};

/** Is everything running: database, Redis, the background worker and its queues, and recent failures. */
export default function AdminSystemPage() {
  const t = useTranslations("admin");
  const locale = useLocale();
  const { data, isLoading } = useQuery({ queryKey: ["admin-system"], queryFn: () => api.get<SystemOut>("/admin/system"), refetchInterval: 30000 });
  if (isLoading || !data) return <div className="flex justify-center py-16"><Spinner /></div>;
  const numbers: [string, number, boolean][] = [
    [t("system.postsToday"), data.posts_today, true], [t("system.failedPosts"), data.failed_posts_today, data.failed_posts_today === 0],
    [t("system.errors24h"), data.errors_24h, data.errors_24h === 0], [t("system.failedJobs"), data.failed_jobs, data.failed_jobs === 0],
  ];
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card>
        <SectionTitle icon="check_circle">{t("system.services")}</SectionTitle>
        <ul className="mt-3 flex flex-col gap-2.5 text-sm">
          {data.checks.map((c) => (
            <li key={c.key} className="flex items-center justify-between gap-3">
              <span>{t(`system.checks.${c.key}`)}</span>
              <Badge tone={c.ok ? "ok" : "bad"}>{c.ok ? t("system.ok") : t("system.down")}</Badge>
            </li>
          ))}
          {Object.entries(data.queues).map(([name, count]) => (
            <li key={name} className="flex items-center justify-between gap-3 text-text-2">
              <span>{t("system.queue", { name })}</span><span dir="ltr">{count}</span>
            </li>
          ))}
        </ul>
      </Card>
      <div className="grid grid-cols-2 gap-4 lg:col-span-2">
        {numbers.map(([label, value, good]) => (
          <Card key={label} className="!p-4">
            <div className="text-[13px] text-text-2">{label}</div>
            <div className={`mt-2 text-2xl font-bold tracking-tight ${good ? "" : "text-bad"}`} dir="ltr">{value}</div>
          </Card>
        ))}
      </div>
      <Card className="lg:col-span-3">
        <SectionTitle icon="error">{t("system.recentErrors")}</SectionTitle>
        {data.recent_errors.length === 0 ? <p className="mt-3 text-sm text-ok">{t("noErrors")}</p>
          : (
            <ul className="mt-3 flex flex-col divide-y divide-line/60 text-sm">
              {data.recent_errors.map((e) => (
                <li key={e.id} className="py-2.5">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                    <Badge tone="bad">{e.status_code ?? "—"}</Badge><span dir="ltr">{e.service} · {e.operation}</span><span>{formatDate(e.created_at, locale)}</span>
                  </div>
                  <p className="mt-1 break-words text-text-2" dir="ltr">{e.error}</p>
                </li>
              ))}
            </ul>
          )}
      </Card>
    </div>
  );
}
