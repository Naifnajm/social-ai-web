"use client";
/** Mention stream: every mention with its source, classification and reach. Answer in the inbox, mute, mark as
 *  reviewed or correct a wrong classification. */
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useState } from "react";
import { Chip, useFormat } from "@/components/planning/ui";
import { MentionCard, useRadarQueries, useScope, useSourceLabel } from "@/components/radar/shared";
import { type MentionPage, SOURCES } from "@/components/radar/types";
import { Button, Card, EmptyState, Input, Select, Spinner } from "@/components/ui";
import { api } from "@/lib/api";

type Preset = "all" | "negative" | "purchase" | "influencers" | "unanswered";
const PRESETS: Preset[] = ["all", "negative", "purchase", "influencers", "unanswered"];
const PAGE = 30;

export default function RadarMentionsPage() {
  return <Suspense><Mentions /></Suspense>;
}

function Mentions() {
  const t = useTranslations("radar");
  const fmt = useFormat();
  const sourceLabel = useSourceLabel();
  const params = useSearchParams();
  const { queryId, days } = useScope();
  const queries = useRadarQueries();
  const competitors = queries.data?.find((q) => q.id === queryId)?.competitors ?? [];
  const [preset, setPreset] = useState<Preset>("all");
  const [source, setSource] = useState("");
  const [brand, setBrand] = useState("own");
  const [status, setStatus] = useState("");
  const [text, setText] = useState(() => params.get("q") ?? "");
  const [q, setQ] = useState(() => params.get("q") ?? "");

  const filters = {
    query_id: queryId, days, source, brand, status, q,
    sentiment: preset === "negative" ? "negative" : undefined,
    intent: preset === "purchase" ? "purchase" : undefined,
    influencers: preset === "influencers" ? true : undefined,
    unanswered: preset === "unanswered" ? true : undefined,
  };
  const list = useInfiniteQuery({
    queryKey: ["radar", "mentions", filters],
    queryFn: ({ pageParam }) => api.get<MentionPage>("/listening/mentions", { ...filters, offset: pageParam, limit: PAGE }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => (pages.length * PAGE < last.total ? pages.length * PAGE : undefined),
    enabled: !!queryId,
  });
  // counts of the chips: always for your own brand, whatever the other filters
  const counts = useQuery({
    queryKey: ["radar", "mentions", "counts", queryId, days],
    queryFn: () => api.get<MentionPage>("/listening/mentions", { query_id: queryId, days, limit: 1 }),
    enabled: !!queryId,
    select: (r) => r.counts,
  });
  const items = list.data?.pages.flatMap((p) => p.items) ?? [];
  const total = list.data?.pages[0]?.total ?? 0;
  const filtered = preset !== "all" || source || brand !== "own" || status || q;
  const reset = () => { setPreset("all"); setSource(""); setBrand("own"); setStatus(""); setText(""); setQ(""); };

  return (
    <div className="flex flex-col gap-4">
      <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0">
        {PRESETS.map((p) => (
          <Chip key={p} active={preset === p} onClick={() => setPreset(p)}>
            {t(`mentions.presets.${p}`)}
            {counts.data && <span className="tabular-nums opacity-60">{fmt.number(counts.data[p])}</span>}
          </Chip>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <form className="flex min-w-[220px] flex-1 gap-2" onSubmit={(e) => { e.preventDefault(); setQ(text.trim()); }}>
          <Input type="search" value={text} placeholder={t("mentions.searchPlaceholder")} onChange={(e) => { setText(e.target.value); if (!e.target.value) setQ(""); }} />
          <Button type="submit" icon="search">{t("mentions.search")}</Button>
        </form>
        <Select className="!w-44" aria-label={t("mentions.source")} value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">{t("mentions.allSources")}</option>
          {SOURCES.map((s) => <option key={s} value={s}>{sourceLabel(s)}</option>)}
        </Select>
        {competitors.length > 0 && (
          <Select className="!w-44" aria-label={t("mentions.brand")} value={brand} onChange={(e) => setBrand(e.target.value)}>
            <option value="own">{t("mentions.ownBrand")}</option>
            <option value="all">{t("mentions.allBrands")}</option>
            {competitors.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
          </Select>
        )}
        <Select className="!w-40" aria-label={t("mentions.status")} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">{t("mentions.statuses.any")}</option>
          {(["new", "reviewed", "converted", "muted"] as const).map((s) => <option key={s} value={s}>{t(`mentions.statuses.${s}`)}</option>)}
        </Select>
      </div>

      <Card padded={false} className="px-5">
        {list.isLoading ? <div className="flex justify-center py-16"><Spinner /></div> : !items.length ? (
          <EmptyState icon="search" title={t("mentions.emptyTitle")} text={filtered ? t("mentions.emptyFiltered") : t("mentions.emptyText")}
            action={filtered && <Button icon="close" onClick={reset}>{t("mentions.clearFilters")}</Button>} />
        ) : (
          <>
            <div className="border-b border-line py-3 text-xs text-muted">{t("mentions.showing", { shown: fmt.number(items.length), total: fmt.number(total) })}</div>
            <div className="divide-y divide-line">
              {items.map((m) => <MentionCard key={m.id} mention={m} />)}
            </div>
            {list.hasNextPage && (
              <div className="flex justify-center border-t border-line py-4">
                <Button icon="expand_more" loading={list.isFetchingNextPage} onClick={() => list.fetchNextPage()}>{t("mentions.more")}</Button>
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
