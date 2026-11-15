"use client";
/** Quick search: what the radar stored about any word (every setup), and optionally the news right now. */
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon } from "@/components/icon";
import { errorText, useFormat } from "@/components/planning/ui";
import { Button, Input, Modal, Spinner, Switch } from "@/components/ui";
import { api } from "@/lib/api";
import { SentimentBar } from "./charts";
import { MentionCard, SentimentPill, useScope } from "./shared";
import type { SearchResult, Sentiment } from "./types";

export function SearchDialog({ onClose }: { onClose: () => void }) {
  const t = useTranslations("radar");
  const fmt = useFormat();
  const { days } = useScope();
  const [text, setText] = useState("");
  const [live, setLive] = useState(false);
  const [asked, setAsked] = useState<{ q: string; live: boolean } | null>(null);
  const result = useQuery({
    queryKey: ["radar", "search", asked?.q, asked?.live, days],
    queryFn: () => api.get<SearchResult>("/listening/search", { q: asked!.q, live: asked!.live, days }),
    enabled: !!asked,
  });
  const submit = () => text.trim().length >= 2 && setAsked({ q: text.trim(), live });
  const r = result.data;
  const total = r ? r.sentiment.positive + r.sentiment.neutral + r.sentiment.negative : 0;
  const split = (s: Sentiment) => (total ? Math.round((r!.sentiment[s] / total) * 100) : 0);
  const labels = { positive: t("sentiments.positive"), neutral: t("sentiments.neutral"), negative: t("sentiments.negative") };
  return (
    <Modal open size="lg" onClose={onClose} title={t("search.title")}>
      <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <div className="flex gap-2">
          <Input autoFocus value={text} maxLength={80} placeholder={t("search.placeholder")} onChange={(e) => setText(e.target.value)} />
          <Button type="submit" variant="primary" icon="search" disabled={text.trim().length < 2} loading={result.isFetching}>{t("search.go")}</Button>
        </div>
        <Switch checked={live} onChange={setLive} label={<span className="text-[13px] text-text-2">{t("search.live")}</span>} />
        <p className="text-xs text-muted">{t("search.hint", { n: days })}</p>
      </form>
      {result.isError && <p className="mt-4 text-sm text-bad">{errorText(result.error)}</p>}
      {result.isFetching && !r && <div className="flex justify-center py-10"><Spinner /></div>}
      {r && (
        <div className="mt-5 flex flex-col gap-5">
          <div>
            <div className="mb-2 text-sm font-semibold">{t("search.found", { n: fmt.number(r.total), q: r.q })}</div>
            {total > 0 && <SentimentBar split={{ positive: split("positive"), neutral: split("neutral"), negative: split("negative") }} labels={labels} height={10} />}
          </div>
          {r.items.length > 0 && (
            <div className="divide-y divide-line">
              {r.items.map((m) => <MentionCard key={m.id} mention={m} compact />)}
            </div>
          )}
          {asked?.live && (
            <div>
              <div className="mb-1 flex items-center gap-1.5 text-sm font-semibold"><Icon name="description" size={16} />{t("search.news")}</div>
              {!r.news.length ? <p className="text-sm text-muted">{t("search.noNews")}</p> : (
                <ul className="divide-y divide-line">
                  {r.news.map((n, i) => (
                    <li key={n.url ?? i} className="py-3 text-sm">
                      <p className="bidi line-clamp-3 leading-relaxed">{n.text}</p>
                      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted">
                        <SentimentPill value={n.sentiment ?? null} />
                        {n.author_name && <span className="bidi">{n.author_name}</span>}
                        {n.published_at && <span>{fmt.dateTime(n.published_at)}</span>}
                        {n.url && <a href={n.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium text-text underline underline-offset-2">{t("mention.openOriginal")}<Icon name="open_in_new" size={11} /></a>}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {!r.items.length && !asked?.live && <p className="text-sm text-muted">{t("search.nothing")}</p>}
        </div>
      )}
    </Modal>
  );
}
