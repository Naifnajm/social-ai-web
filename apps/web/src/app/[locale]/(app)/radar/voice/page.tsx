"use client";
/** What people say: words, phrases, hashtags, rising words, the strongest quotes, topics, feelings and timing. */
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon } from "@/components/icon";
import { BarRows } from "@/components/publishing/charts";
import { useFormat, useWeekdays } from "@/components/planning/ui";
import { HeatGrid, Legend, SENTIMENT_COLOR, TopicBubbles, WordCloud, signed } from "@/components/radar/charts";
import { SourceBadge, useScope } from "@/components/radar/shared";
import type { Breakdowns, Mention, Sentiment, Voice } from "@/components/radar/types";
import { Card, SectionTitle, Segmented, Spinner, cx } from "@/components/ui";
import { useRouter } from "@/i18n/navigation";
import { api } from "@/lib/api";

export default function RadarVoicePage() {
  const t = useTranslations("radar");
  const fmt = useFormat();
  const router = useRouter();
  const weekdays = useWeekdays("long");
  const { queryId, days } = useScope();
  const [mood, setMood] = useState<"all" | Sentiment>("all");
  const voice = useQuery({
    queryKey: ["radar", "voice", queryId, days],
    queryFn: () => api.get<Voice>("/listening/voice", { query_id: queryId, days }),
    enabled: !!queryId,
  });
  const parts = useQuery({
    queryKey: ["radar", "breakdowns", queryId, days],
    queryFn: () => api.get<Breakdowns>("/listening/breakdowns", { query_id: queryId, days }),
    enabled: !!queryId,
  });
  const v = voice.data;
  const b = parts.data;
  if (!v) return <div className="flex justify-center py-24"><Spinner size={28} /></div>;
  const words = mood === "all" ? v.words : v.words.filter((w) => w.sentiment === mood);
  const maxPhrase = Math.max(1, ...v.phrases.map((p) => p.count));
  const sundayFirst = [6, 0, 1, 2, 3, 4, 5].map((i) => weekdays[i]);
  const region = safeNames(fmt.locale, "region");
  const language = safeNames(fmt.locale, "language");
  const toMentions = (word: string) => router.push(`/radar/mentions?q=${encodeURIComponent(word.replace(/^#/, ""))}`);

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <SectionTitle icon="text_fields" actions={
          <Segmented size="sm" value={mood} onChange={setMood}
            options={[{ value: "all" as const, label: t("voice.all") }, { value: "positive" as const, label: t("sentiments.positive") }, { value: "negative" as const, label: t("sentiments.negative") }]} />
        }>{t("voice.title", { n: fmt.number(v.total) })}</SectionTitle>
        {!words.length ? <p className="py-8 text-center text-sm text-muted">{t("notEnough")}</p> : (
          <WordCloud words={words} min={14} max={44} onPick={toMentions}
            title={(w) => t("wordTip", { word: w.word, n: w.count, pos: w.positive, neg: w.negative })} />
        )}
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
          <Legend items={[
            { color: SENTIMENT_COLOR.positive, label: t("voice.mostlyPositive") },
            { color: "var(--text-2)", label: t("voice.mixed") },
            { color: SENTIMENT_COLOR.negative, label: t("voice.mostlyNegative") },
          ]} />
          <span className="text-xs text-muted">{t("voice.sizeHint")}</span>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card>
          <SectionTitle icon="format_quote" actions={<span className="text-xs text-muted">{t("voice.times")}</span>}>{t("voice.phrases")}</SectionTitle>
          {!v.phrases.length ? <p className="text-sm text-muted">{t("notEnough")}</p> : (
            <ul className="flex flex-col gap-2.5">
              {v.phrases.map((p) => (
                <li key={p.phrase} className="text-sm">
                  <div className="mb-1 flex items-baseline gap-2"><span className="bidi flex-1 truncate">{p.phrase}</span><b className="tabular-nums">{fmt.number(p.count)}</b></div>
                  <div className="h-2 rounded-full bg-fill-2"><div className="h-2 rounded-full" style={{ width: `${Math.max(3, (p.count / maxPhrase) * 100)}%`, background: SENTIMENT_COLOR[p.sentiment] }} /></div>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <SectionTitle icon="tag" actions={<span className="text-xs text-muted">{t("voice.timesChange")}</span>}>{t("voice.hashtags")}</SectionTitle>
          {!v.hashtags.length ? <p className="text-sm text-muted">{t("voice.noHashtags")}</p> : (
            <ul className="flex flex-col divide-y divide-line">
              {v.hashtags.map((h) => (
                <li key={h.tag} className="flex items-center gap-2 py-2 text-sm">
                  <button type="button" onClick={() => toMentions(h.tag)} className="bidi min-w-0 flex-1 truncate text-start font-medium hover:underline" dir="auto">#{h.tag.replace(/^#/, "")}</button>
                  <span className="tabular-nums text-text-2">{fmt.number(h.count)}</span>
                  <Change value={h.change} />
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <SectionTitle icon="trending_up" actions={<span className="text-xs text-muted">{t("voice.vsLastWeek")}</span>}>{t("voice.rising")}</SectionTitle>
          {!v.rising.length ? <p className="text-sm text-muted">{t("voice.noRising")}</p> : (
            <ul className="flex flex-col divide-y divide-line">
              {v.rising.map((r) => (
                <li key={r.word} className="flex items-center gap-2 py-2 text-sm">
                  <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: SENTIMENT_COLOR[r.sentiment] }} />
                  <button type="button" onClick={() => toMentions(r.word)} className="bidi min-w-0 flex-1 truncate text-start font-medium hover:underline">{r.word}</button>
                  <span className="text-xs text-muted tabular-nums">{t("voice.fromTo", { from: r.before, to: r.count })}</span>
                  <Change value={r.change} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Quote mention={v.top_positive} kind="positive" />
        <Quote mention={v.top_negative} kind="negative" />
      </div>

      {b && (
        <>
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
            <Card>
              <SectionTitle icon="forum" actions={<span className="text-xs text-muted">{t("voice.topicsHint")}</span>}>{t("voice.topics")}</SectionTitle>
              {!b.topics.length ? <p className="text-sm text-muted">{t("notEnough")}</p> : (
                <TopicBubbles topics={b.topics} tip={(x) => t("voice.topicTip", { topic: x.topic, n: x.count, net: signed(x.net_sentiment) })} />
              )}
            </Card>
            <Card>
              <SectionTitle icon="favorite">{t("voice.emotions")}</SectionTitle>
              {!b.emotions.length ? <p className="text-sm text-muted">{t("notEnough")}</p> : (
                <BarRows rows={b.emotions.map((e) => ({ label: t.has(`emotions.${e.emotion}`) ? t(`emotions.${e.emotion}`) : e.emotion, value: e.share }))} format={(n) => `${n}%`} />
              )}
              {b.intents.length > 0 && (
                <>
                  <div className="mb-2 mt-5 text-[13px] font-semibold">{t("voice.intents")}</div>
                  <BarRows rows={b.intents.map((i) => ({ label: t(`intents.${i.intent}`), value: i.count }))} format={fmt.number} />
                </>
              )}
            </Card>
          </div>
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
            <Card>
              <SectionTitle icon="schedule">{t("voice.when")}</SectionTitle>
              <HeatGrid grid={b.heatmap} days={sundayFirst}
                cellTip={(d, s, n) => t("voice.whenTip", { day: sundayFirst[d], from: String(s * 2).padStart(2, "0"), to: String(s * 2 + 2).padStart(2, "0"), n })} />
            </Card>
            <Card>
              <SectionTitle icon="share">{t("voice.where")}</SectionTitle>
              {!b.countries.length && !b.languages.length ? <p className="text-sm text-muted">{t("notEnough")}</p> : (
                <div className="flex flex-col gap-5">
                  {b.countries.length > 0 && <BarRows rows={b.countries.map((c) => ({ label: region(c.country), value: c.share }))} format={(n) => `${n}%`} />}
                  {b.languages.length > 0 && (
                    <div>
                      <div className="mb-2 text-[13px] font-semibold">{t("voice.languages")}</div>
                      <BarRows rows={b.languages.map((l) => ({ label: language(l.lang), value: l.share }))} format={(n) => `${n}%`} />
                    </div>
                  )}
                </div>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function safeNames(locale: string, type: "region" | "language") {
  try {
    const names = new Intl.DisplayNames([locale], { type });
    return (code: string) => names.of(code) ?? code;
  } catch {
    return (code: string) => code;
  }
}

function Change({ value }: { value: number | null }) {
  const t = useTranslations("radar");
  if (value === null) return <span className="rounded-full bg-ink px-1.5 py-0.5 text-[10.5px] font-semibold text-white">{t("voice.new")}</span>;
  return (
    <span className={cx("min-w-12 text-end text-xs font-semibold tabular-nums bidi", value >= 0 ? "text-ok" : "text-bad")}>
      {signed(Math.round(value), "%")}
    </span>
  );
}

function Quote({ mention, kind }: { mention: Mention | null; kind: Sentiment }) {
  const t = useTranslations("radar");
  const fmt = useFormat();
  return (
    <Card className={cx("relative overflow-hidden", kind === "negative" ? "!bg-bad-bg" : "!bg-ok-bg")}>
      <div className={cx("mb-2 flex items-center gap-1.5 text-xs font-semibold", kind === "negative" ? "text-bad" : "text-ok")}>
        <Icon name={kind === "negative" ? "thumb_down" : "thumb_up"} size={14} />{t(kind === "negative" ? "voice.topNegative" : "voice.topPositive")}
      </div>
      {!mention ? <p className="text-sm text-muted">{t("notEnough")}</p> : (
        <>
          <p className="bidi text-[15px] font-medium leading-relaxed">«{mention.text}»</p>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
            <SourceBadge source={mention.source} platform={mention.platform} size={20} />
            <span className="bidi font-semibold text-text-2">{mention.author_handle ? `@${mention.author_handle.replace(/^@/, "")}` : mention.author_name}</span>
            {mention.author_followers > 0 && <span>{t("mention.followers", { n: fmt.compact(mention.author_followers) })}</span>}
            {mention.engagement > 0 && <span>· {t("voice.engagements", { n: fmt.compact(mention.engagement) })}</span>}
            {mention.url && <a href={mention.url} target="_blank" rel="noopener noreferrer" className="ms-auto inline-flex items-center gap-1 font-medium text-text underline underline-offset-2">{t("mention.openOriginal")}<Icon name="open_in_new" size={11} /></a>}
          </div>
        </>
      )}
    </Card>
  );
}
