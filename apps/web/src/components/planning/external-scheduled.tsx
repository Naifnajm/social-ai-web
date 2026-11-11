"use client";
/** Posts scheduled outside this platform (Meta Business Suite / the Page's own scheduler): a read-only reminder
 * above the calendar, so nothing planned elsewhere is a surprise. Hidden when there is none. */
import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { PlatformBadge } from "@/components/icon";
import { Card } from "@/components/ui";
import { api } from "@/lib/api";

type ExternalPost = { id: number; account_name: string; platform: string; text?: string | null; scheduled_at?: string | null };

export function ExternalScheduled() {
  const t = useTranslations("planner");
  const locale = useLocale();
  const { data } = useQuery({
    queryKey: ["external-posts", "scheduled"],
    queryFn: () => api.get<ExternalPost[]>("/posts/external?kind=scheduled&limit=20"),
    refetchInterval: 5 * 60 * 1000,
  });
  if (!data?.length) return null;
  const format = new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" });
  return (
    <Card className="mb-4 p-4">
      <div className="mb-1 text-sm font-semibold">{t("externalTitle")} · {data.length}</div>
      <p className="mb-3 text-xs text-muted">{t("externalHelp")}</p>
      <ul className="flex flex-col gap-2">
        {data.map((post) => (
          <li key={post.id} className="flex items-center gap-3 text-sm">
            <PlatformBadge platform={post.platform} />
            <span className="shrink-0 text-xs text-muted">{post.scheduled_at ? format.format(new Date(post.scheduled_at)) : ""}</span>
            <span className="bidi min-w-0 flex-1 truncate">{post.text || post.account_name}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
