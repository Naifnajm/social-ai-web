"use client";
/** Radar overview: events that need attention, the four numbers, daily volume, sentiment, words and sources. */
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { BarRows } from "@/components/publishing/charts";
import { useFormat } from "@/components/planning/ui";
import { SentimentBar, VolumeChart, WordCloud, signed } from "@/components/radar/charts";
import { EventCard, Kpi, useScope, useSourceLabel } from "@/components/radar/shared";
import type { EventShort, EventState, Overview } from "@/components/radar/types";
import { Button, Card, SectionTitle, Segmented, Spinner } from "@/components/ui";
import { useRouter } from "@/i18n/navigation";
import { api } from "@/lib/api";

export default function RadarOverviewPage() {
  const t = useTranslations("radar");
  const fmt = useFormat();
  const router = useRouter();
  const sourceLabel = useSourceLabel();
  const { queryId, days } = useScope();
  const overview = useQuery({
    queryKey: ["radar", "overview", queryId, days],
    queryFn: () => api.get<Overview>("/listening/overview", { query_id: queryId, days }),
    enabled: !!queryId,
  });
  const d = overview.data;
  if (!d) return <div className="flex justify-center py-24"><Spinner size={28} /></div>;
  const labels = { positive: t("sentiments.positive"), neutral: t("sentiments.neutral"), negative: t("sentiments.negative") };
  const k = d.kpis;
  return (
    <div className="flex flex-col gap-5">
      <EventsStrip queryId={queryId!} />

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Kpi icon="forum" label={t("kpi.mentions")} value={fmt.number(k.mentions.value)} change={k.mentions.delta} />
        <Kpi icon="visibility" label={t("kpi.reach")} value={fmt.compact(k.reach.value)} change={k.reach.delta} />
        <Kpi icon="mood" label={t("kpi.netSentiment")} value={signed(k.net_sentiment.value)} change={k.net_sentiment.change} unit="points" />
        <Kpi icon="percent" label={t("kpi.shareOfVoice")} value={k.share_of_voice.value == null ? "—" : `${k.share_of_voice.value}%`}
          change={k.share_of_voice.change} unit="points" hint={k.share_of_voice.value == null ? t("kpi.addCompetitors") : undefined} />
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Card>
          <SectionTitle icon="show_chart" actions={<span className="inline-flex items-center gap-1.5 text-xs text-muted"><span className="inline-block h-2.5 w-2.5 rounded-full bg-[var(--bad-solid)]" />{t("overview.spikeLegend")}</span>}>
            {t("overview.volume")}
          </SectionTitle>
          <VolumeChart points={d.series.map((s) => ({ label: fmt.date(s.date, { day: "numeric", month: "short" }), value: s.count, marked: !!s.event }))}
            format={(n) => t("overview.mentionsCount", { n })} markLabel={t("overview.unusual")} />
        </Card>
        <Card>
          <SectionTitle icon="mood" actions={<span className="text-xs text-muted">{t("overview.mentionsCount", { n: fmt.number(k.mentions.value) })}</span>}>{t("overview.sentiment")}</SectionTitle>
          <SentimentBar split={d.sentiment} labels={labels} />
          <p className="mt-4 text-xs leading-relaxed text-muted">{t("overview.netExplain")}</p>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Card>
          <SectionTitle icon="text_fields" actions={<span className="text-xs text-muted">{t("overview.wordsHint")}</span>}>{t("overview.words")}</SectionTitle>
          {!d.words.length ? <p className="text-sm text-muted">{t("notEnough")}</p> : (
            <WordCloud words={d.words} onPick={(w) => router.push(`/radar/mentions?q=${encodeURIComponent(w)}`)}
              title={(w) => t("wordTip", { word: w.word, n: w.count, pos: w.positive, neg: w.negative })} />
          )}
        </Card>
        <Card>
          <SectionTitle icon="share">{t("overview.sources")}</SectionTitle>
          {!d.sources.length ? <p className="text-sm text-muted">{t("notEnough")}</p> : (
            <BarRows rows={d.sources.map((s) => ({ label: sourceLabel(s.source), value: s.count }))} format={fmt.number} />
          )}
        </Card>
      </div>
    </div>
  );
}

function EventsStrip({ queryId }: { queryId: number }) {
  const t = useTranslations("radar");
  const [state, setState] = useState<EventState>("open");
  const [all, setAll] = useState(false);
  const events = useQuery({
    queryKey: ["radar", "events", queryId, state],
    queryFn: () => api.get<EventShort[]>("/listening/events", { query_id: queryId, state, limit: 30 }),
  });
  const rows = events.data ?? [];
  const shown = all ? rows : rows.slice(0, 3);
  return (
    <section>
      <SectionTitle icon="bolt" actions={
        <Segmented size="sm" value={state} onChange={(v) => { setState(v); setAll(false); }}
          options={(["open", "acted", "dismissed"] as const).map((s) => ({ value: s, label: t(`events.states.${s}`) }))} />
      }>{t("events.title")}</SectionTitle>
      {events.isLoading ? <div className="flex justify-center py-6"><Spinner /></div> : !rows.length ? (
        <p className="glass rounded-[18px] px-4 py-3.5 text-sm text-muted">{t(`events.empty.${state}`)}</p>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {shown.map((e) => <EventCard key={e.id} event={e} />)}
          </div>
          {rows.length > 3 && (
            <div className="mt-2 flex justify-center">
              <Button size="sm" variant="ghost" icon={all ? "expand_less" : "expand_more"} onClick={() => setAll(!all)}>
                {all ? t("events.fewer") : t("events.all", { n: rows.length })}
              </Button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
