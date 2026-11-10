"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useEffect } from "react";
import { Icon } from "@/components/icon";
import { Card, EmptyState, PageHeader, cx } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";

type Notification = { id: number; kind: string; title: string; body?: string | null; link?: string | null; read_at?: string | null; created_at: string };

export default function NotificationsPage() {
  const t = useTranslations("notifications");
  const format = useFormatter();
  const qc = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ["notifications"], queryFn: () => api.get<Notification[]>("/notifications") });
  useEffect(() => {
    if (data.some((n) => !n.read_at)) {
      api.post("/notifications/read").then(() => qc.invalidateQueries({ queryKey: ["notifications-count"] }));
    }
  }, [data, qc]);
  return (
    <div className="pt-2">
      <PageHeader icon="mail" title={t("title")} />
      <Card padded={false}>
        {!data.length && <EmptyState icon="mail" title={t("empty")} />}
        <ul className="divide-y divide-line">
          {data.map((n) => {
            const row = (
              <div className={cx("flex items-start gap-3 px-5 py-4", !n.read_at && "bg-white/50")}>
                <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-fill-2"><Icon name={n.kind.startsWith("inbox") ? "forum" : n.kind.startsWith("post") ? "send" : "info"} size={18} duo /></span>
                <div className="min-w-0 flex-1">
                  <div className="bidi text-sm font-semibold">{n.title}</div>
                  {n.body && <div className="bidi mt-0.5 text-sm text-muted">{n.body}</div>}
                </div>
                <time className="shrink-0 text-xs text-muted">{format.relativeTime(new Date(n.created_at))}</time>
              </div>
            );
            return <li key={n.id}>{n.link ? <Link href={n.link}>{row}</Link> : row}</li>;
          })}
        </ul>
      </Card>
    </div>
  );
}
