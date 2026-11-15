"use client";
/** Home page: a small radar card (open events and net sentiment of the last 7 days) once the radar is set up. */
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Icon } from "@/components/icon";
import { Card, cx } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { signed } from "./charts";
import { useRadarStatus, useScope } from "./shared";
import type { EventShort, Overview } from "./types";

export function RadarHomeCard() {
  const t = useTranslations("radar.home");
  const status = useRadarStatus();
  const { queryId } = useScope();
  const ready = !!status.data?.enabled && !!queryId;
  const events = useQuery({
    queryKey: ["radar", "events", "home"],
    queryFn: () => api.get<EventShort[]>("/listening/events", { state: "open", limit: 50 }),
    enabled: ready,
  });
  const overview = useQuery({
    queryKey: ["radar", "overview", queryId, 7],
    queryFn: () => api.get<Overview>("/listening/overview", { query_id: queryId, days: 7 }),
    enabled: ready,
  });
  if (!ready || !events.data || !overview.data) return null;
  const open = events.data.length;
  const urgent = events.data.some((e) => e.severity === "urgent");
  const net = overview.data.kpis.net_sentiment.value;
  const first = events.data[0];
  return (
    <Link href={first && urgent ? `/radar/events/${first.id}` : "/radar"} className="mb-5 block">
      <Card className="flex flex-wrap items-center gap-4 transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-lift)]">
        <span className={cx("flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl", urgent ? "bg-[var(--bad-solid)] text-white" : "bg-fill-2 text-text-2")}>
          <Icon name="graphic_eq" size={22} duo />
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-semibold">{t("title")}</div>
          <p className="bidi truncate text-sm text-muted">{first ? first.title : t("calm")}</p>
        </div>
        <div className="flex items-center gap-5 text-center">
          <div>
            <div className={cx("text-xl font-bold tabular-nums", urgent && "text-bad")}>{open}</div>
            <div className="text-[11px] text-muted">{t("openEvents")}</div>
          </div>
          <div>
            <div className={cx("text-xl font-bold tabular-nums bidi", net > 0 ? "text-ok" : net < 0 ? "text-bad" : "")}>{signed(net)}</div>
            <div className="text-[11px] text-muted">{t("net")}</div>
          </div>
          <Icon name="east" size={18} className="text-faint rtl:-scale-x-100" />
        </div>
      </Card>
    </Link>
  );
}
