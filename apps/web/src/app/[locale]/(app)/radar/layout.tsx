"use client";
/** Radar (social listening): header, tabs, setup and period switchers, and the states before there is data
 *  (not in the plan, nothing set up yet, first collection running). */
import { useTranslations } from "next-intl";
import { type ReactNode, useState } from "react";
import { Icon } from "@/components/icon";
import { useFormat } from "@/components/planning/ui";
import { SearchDialog } from "@/components/radar/search";
import { useCollectNow, useRadarQueries, useRadarScope, useRadarStatus, useScope } from "@/components/radar/shared";
import { Button, Card, EmptyState, PageHeader, Segmented, Select, Spinner, cx } from "@/components/ui";
import { Link, usePathname } from "@/i18n/navigation";
import { useSession } from "@/lib/session";

const TABS = [
  { href: "/radar", key: "overview", icon: "bar_chart" },
  { href: "/radar/voice", key: "voice", icon: "forum" },
  { href: "/radar/mentions", key: "mentions", icon: "view_list" },
  { href: "/radar/competitors", key: "competitors", icon: "flag" },
  { href: "/radar/sources", key: "sources", icon: "apps" },
  { href: "/radar/setup", key: "setup", icon: "settings" },
];

export default function RadarLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("radar");
  const fmt = useFormat();
  const pathname = usePathname();
  const can = useSession((s) => s.can);
  const status = useRadarStatus();
  const enabled = !!status.data?.enabled;
  const queries = useRadarQueries(enabled);
  const { query, days } = useScope();
  const setQuery = useRadarScope((s) => s.setQuery);
  const setDays = useRadarScope((s) => s.setDays);
  const collect = useCollectNow();
  const [searching, setSearching] = useState(false);

  const isSetup = pathname === "/radar/setup";
  const isEvent = pathname.startsWith("/radar/events");
  const isSources = pathname === "/radar/sources";
  const list = status.data?.queries ?? [];
  const full = queries.data?.find((q) => q.id === query?.id);

  let body: ReactNode = children;
  if (status.isLoading) body = <div className="flex justify-center py-24"><Spinner size={28} /></div>;
  else if (status.isError) body = <Card><EmptyState icon="error" title={t("loadFailed")} action={<Button icon="refresh" onClick={() => status.refetch()}>{t("retry")}</Button>} /></Card>;
  else if (!enabled) body = <UpgradeCard />;
  else if (!list.length && !isSetup && !isSources) body = <NoSetupCard />;
  else if (!isSetup && !isEvent && !isSources && full && full.mentions === 0) {
    body = (
      <Card>
        <EmptyState icon="schedule" title={t("waiting.title")}
          text={full.last_collected_at ? t("waiting.nothingYet", { date: fmt.dateTime(full.last_collected_at) }) : t("waiting.text")}
          action={can("editor") && (
            <div className="flex flex-wrap justify-center gap-2">
              <Button variant="primary" icon="refresh" loading={collect.isPending} onClick={() => collect.mutate(full.id)}>{t("collect.now")}</Button>
              <Link href="/radar/setup"><Button icon="settings">{t("waiting.editSetup")}</Button></Link>
            </div>
          )} />
        {full.last_error && <p className="bidi mx-auto -mt-6 mb-4 max-w-lg text-center text-xs text-bad">{t("waiting.error", { error: full.last_error })}</p>}
      </Card>
    );
  }

  const showBar = enabled && (list.length > 0 || isSources);
  return (
    <div className="pt-2">
      <PageHeader icon="graphic_eq" title={t("title")}
        subtitle={query ? (full?.last_collected_at ? t("subtitleWhen", { name: query.name, date: fmt.dateTime(full.last_collected_at) }) : t("subtitleName", { name: query.name })) : t("subtitle")}
        actions={showBar && can("editor") && (
          <>
            <Button icon="search" onClick={() => setSearching(true)}>{t("search.button")}</Button>
            {query && <Button icon="refresh" loading={collect.isPending} onClick={() => collect.mutate(query.id)}>{t("collect.now")}</Button>}
          </>
        )} />
      {showBar && (
        <div className="mb-5 flex flex-col gap-3">
          <nav className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
            <div className="inline-flex w-max rounded-full bg-track p-0.5">
              {TABS.map((tab) => {
                const active = pathname === tab.href;
                return (
                  <Link key={tab.href} href={tab.href} aria-current={active ? "page" : undefined}
                    className={cx("inline-flex h-8 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium transition",
                      active ? "bg-white text-text shadow-[0_1px_3px_rgba(0,0,0,.12)]" : "text-text-2 hover:text-text")}>
                    <Icon name={tab.icon} size={14} />{t(`tabs.${tab.key}`)}
                  </Link>
                );
              })}
            </div>
          </nav>
          {!isSetup && !isEvent && !isSources && list.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              {list.length > 1 && (
                <Select className="!w-56" aria-label={t("setupSwitch")} value={query?.id ?? ""} onChange={(e) => setQuery(Number(e.target.value))}>
                  {list.map((q) => <option key={q.id} value={q.id}>{q.active ? q.name : t("paused", { name: q.name })}</option>)}
                </Select>
              )}
              <Segmented value={days} onChange={setDays} options={[7, 30, 90].map((n) => ({ value: n, label: t("lastDays", { n }) }))} />
            </div>
          )}
        </div>
      )}
      {body}
      {searching && <SearchDialog onClose={() => setSearching(false)} />}
    </div>
  );
}

function UpgradeCard() {
  const t = useTranslations("radar.upgrade");
  const owner = useSession((s) => s.can("owner"));
  return (
    <Card>
      <EmptyState icon="lock" title={t("title")} text={owner ? t("text") : t("askOwner")}
        action={owner && <Link href="/settings/billing"><Button variant="primary" icon="rocket_launch">{t("button")}</Button></Link>} />
      <ul className="mx-auto mb-6 grid max-w-2xl grid-cols-1 gap-3 sm:grid-cols-3">
        {(["listen", "alert", "act"] as const).map((k) => (
          <li key={k} className="rounded-2xl bg-fill p-3 text-sm">
            <div className="font-semibold">{t(`points.${k}.title`)}</div>
            <p className="mt-0.5 text-xs leading-relaxed text-muted">{t(`points.${k}.text`)}</p>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function NoSetupCard() {
  const t = useTranslations("radar.noSetup");
  const canEdit = useSession((s) => s.can("editor"));
  return (
    <Card>
      <EmptyState icon="graphic_eq" title={t("title")} text={canEdit ? t("text") : t("askEditor")}
        action={canEdit && <Link href="/radar/setup"><Button variant="primary" icon="add">{t("button")}</Button></Link>} />
    </Card>
  );
}
