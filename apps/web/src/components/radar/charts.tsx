"use client";
/**
 * Radar charts: small SVG/HTML components in the app's colours. Time axes run left to right in every language
 * (wrapped in dir="ltr"), like the performance page.
 *
 *   <VolumeChart points={[{ label, value, marked }]} />      daily mentions with red markers on unusual days
 *   <SentimentBar split={{ positive, neutral, negative }} />  one 100% bar + legend
 *   <WordCloud words={[{ word, count, sentiment }]} />        size = count, colour = sentiment
 *   <ShareColumns weeks brands colors />                      weekly share of voice, 100% stacked
 *   <PassionMatrix rows />                                    x = net sentiment, y = passion, bubble = mentions
 *   <TopicBubbles topics />  <HourlyBars values usual />  <HeatGrid grid days />
 */
import { type ReactNode, useState } from "react";
import { cx } from "@/components/ui";
import type { Sentiment, Word } from "./types";

export const SENTIMENT_COLOR: Record<Sentiment, string> = {
  positive: "var(--ok)",
  neutral: "var(--faint)",
  negative: "var(--bad-solid)",
};

/** Brand colours in the competitor charts: your brand first (ink), then the competitors. */
export const BRAND_COLORS = ["var(--ink)", "var(--accent)", "#2563eb", "#059669", "#ca8a04", "#7c3aed"];

/** A signed number (+24, −9) kept left-to-right inside Arabic text. */
export const signed = (value: number, suffix = "") =>
  `⁦${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value)}${suffix}⁩`;

/** Net sentiment (−100..100) as a colour from red to green. */
export const netColor = (net: number) => (net >= 20 ? "var(--ok)" : net <= -20 ? "var(--bad-solid)" : "var(--faint)");

function Tip({ left, children }: { left: number; children: ReactNode }) {
  return (
    <div className="glass-strong pointer-events-none absolute -top-2 z-10 -translate-x-1/2 -translate-y-full rounded-xl px-2.5 py-1.5 text-xs whitespace-nowrap"
      style={{ left: `${Math.min(Math.max(left, 12), 88)}%` }}>
      {children}
    </div>
  );
}

export function Legend({ items }: { items: { color: string; label: ReactNode }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
      {items.map((item, i) => (
        <span key={i} className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: item.color }} />
          {item.label}
        </span>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------------------------------- daily volume
export function VolumeChart({ points, height = 170, format = String, markLabel }: {
  points: { label: string; value: number; marked?: boolean }[];
  height?: number;
  format?: (n: number) => string;
  markLabel?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 600;
  const max = Math.max(1, ...points.map((p) => p.value));
  const step = points.length > 1 ? width / (points.length - 1) : 0;
  const x = (i: number) => i * step;
  const y = (v: number) => 6 + (height - 12) * (1 - v / max);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const area = points.length ? `${line} L${x(points.length - 1)},${height} L0,${height} Z` : "";
  const at = (i: number) => (points.length > 1 ? (i / (points.length - 1)) * 100 : 50);
  const ticks = points.length > 2 ? [0, Math.floor((points.length - 1) / 2), points.length - 1] : points.map((_, i) => i);
  return (
    <div className="relative" dir="ltr">
      <div className="relative" style={{ height }}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const box = e.currentTarget.getBoundingClientRect();
          const rel = (e.clientX - box.left) / box.width;
          setHover(Math.max(0, Math.min(points.length - 1, Math.round(rel * (points.length - 1)))));
        }}>
        <svg viewBox={`0 0 ${width} ${height}`} className="absolute inset-0 h-full w-full" preserveAspectRatio="none" aria-hidden>
          {[0.5, 1].map((f) => (
            <line key={f} x1={0} x2={width} y1={y(max * f)} y2={y(max * f)} stroke="currentColor" strokeOpacity={0.08} vectorEffect="non-scaling-stroke" />
          ))}
          <line x1={0} x2={width} y1={height - 0.5} y2={height - 0.5} stroke="currentColor" strokeOpacity={0.15} vectorEffect="non-scaling-stroke" />
          <path d={area} fill="currentColor" fillOpacity={0.07} />
          <path d={line} fill="none" stroke="var(--ink)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={0} y2={height} stroke="currentColor" strokeOpacity={0.25} vectorEffect="non-scaling-stroke" />}
        </svg>
        {points.map((p, i) => p.marked && (
          <span key={i} className="pointer-events-none absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[var(--bad-solid)] ring-2 ring-white"
            style={{ left: `${at(i)}%`, top: y(p.value) }} />
        ))}
        {hover !== null && points[hover] && !points[hover].marked && (
          <span className="pointer-events-none absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ink ring-2 ring-white"
            style={{ left: `${at(hover)}%`, top: y(points[hover].value) }} />
        )}
      </div>
      <div className="relative mt-1.5 h-4 text-[11px] text-muted">
        {ticks.map((i) => points[i] && (
          <span key={i} className="absolute whitespace-nowrap" style={{ left: `${at(i)}%`, transform: `translateX(${i === 0 ? 0 : i === points.length - 1 ? -100 : -50}%)` }}>
            {points[i].label}
          </span>
        ))}
      </div>
      {hover !== null && points[hover] && (
        <Tip left={at(hover)}>
          <span className="text-muted">{points[hover].label}</span> · <b>{format(points[hover].value)}</b>
          {points[hover].marked && markLabel && <span className="ms-1.5 font-semibold text-bad">{markLabel}</span>}
        </Tip>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------- sentiment split
export function SentimentBar({ split, labels, height = 14 }: { split: Record<Sentiment, number>; labels: Record<Sentiment, string>; height?: number }) {
  const order: Sentiment[] = ["positive", "neutral", "negative"];
  return (
    <div>
      <div className="flex w-full gap-0.5 overflow-hidden rounded-full bg-track" style={{ height }} dir="ltr" role="img"
        aria-label={order.map((s) => `${labels[s]} ${split[s]}%`).join(", ")}>
        {order.map((s) => split[s] > 0 && (
          <div key={s} className="h-full" style={{ width: `${split[s]}%`, background: SENTIMENT_COLOR[s] }} title={`${labels[s]} ${split[s]}%`} />
        ))}
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2">
        {order.map((s) => (
          <div key={s}>
            <div className="flex items-center gap-1.5 text-xs text-muted">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: SENTIMENT_COLOR[s] }} />{labels[s]}
            </div>
            <div className="mt-0.5 text-lg font-bold tabular-nums bidi">{`⁦${split[s]}%⁩`}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// -------------------------------------------------------------------------------------------- word cloud
/** Biggest words in the middle, smaller ones around them. */
function centred<T>(items: T[]): T[] {
  const out: T[] = [];
  items.forEach((item, i) => (i % 2 ? out.push(item) : out.unshift(item)));
  return out;
}

export function WordCloud({ words, min = 13, max = 34, onPick, title }: {
  words: Word[];
  min?: number;
  max?: number;
  onPick?: (word: string) => void;
  title?: (w: Word) => string;
}) {
  const top = Math.max(1, ...words.map((w) => w.count));
  const low = Math.min(top, ...words.map((w) => w.count));
  const size = (n: number) => (top === low ? (min + max) / 2 : min + ((n - low) / (top - low)) * (max - min));
  const sorted = centred([...words].sort((a, b) => b.count - a.count));
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-3.5 gap-y-1.5 py-2 leading-tight">
      {sorted.map((w) => {
        const style = { fontSize: size(w.count), color: SENTIMENT_COLOR[w.sentiment] === "var(--faint)" ? "var(--text-2)" : SENTIMENT_COLOR[w.sentiment] };
        const label = title ? title(w) : `${w.word}: ${w.count}`;
        return onPick ? (
          <button key={w.word} type="button" onClick={() => onPick(w.word)} title={label}
            className="bidi rounded-lg px-1 font-semibold transition hover:bg-fill-2" style={style}>{w.word}</button>
        ) : (
          <span key={w.word} title={label} className="bidi px-1 font-semibold" style={style}>{w.word}</span>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------------------------ share of voice
export function ShareColumns({ weeks, brands, colors = BRAND_COLORS, height = 180, weekLabel }: {
  weeks: { week_start: string; shares: number[]; counts: number[] }[];
  brands: string[];
  colors?: string[];
  height?: number;
  weekLabel: (iso: string) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  return (
    <div className="relative" dir="ltr">
      <div className="flex items-end gap-1.5" style={{ height }} onMouseLeave={() => setHover(null)}>
        {weeks.map((w, i) => {
          const sum = w.shares.reduce((a, b) => a + b, 0);
          return (
            <div key={w.week_start} className={cx("flex h-full flex-1 flex-col-reverse overflow-hidden rounded-[6px] transition", hover !== null && hover !== i && "opacity-60")}
              onMouseEnter={() => setHover(i)}>
              {sum === 0 ? <div className="h-full bg-fill-2" /> : w.shares.map((share, b) => share > 0 && (
                <div key={b} style={{ height: `${(share / sum) * 100}%`, background: colors[b % colors.length] }} />
              ))}
            </div>
          );
        })}
      </div>
      <div className="mt-1.5 flex gap-1.5 text-[11px] text-muted">
        {weeks.map((w, i) => (
          <span key={w.week_start} className="flex-1 truncate text-center">{i % Math.ceil(weeks.length / 6) === 0 ? weekLabel(w.week_start) : ""}</span>
        ))}
      </div>
      {hover !== null && weeks[hover] && (
        <Tip left={((hover + 0.5) / weeks.length) * 100}>
          <div className="mb-1 text-muted">{weekLabel(weeks[hover].week_start)}</div>
          {brands.map((b, i) => (
            <div key={b} className="flex items-center gap-1.5" dir="auto">
              <span className="inline-block h-2 w-2 rounded-full" style={{ background: colors[i % colors.length] }} />
              <span className="bidi">{b}</span><b className="ms-auto ps-3 tabular-nums">{weeks[hover].shares[i]}%</b>
            </div>
          ))}
        </Tip>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------------------- passion matrix
export function PassionMatrix({ rows, colors = BRAND_COLORS, labels }: {
  rows: { brand: string; net_sentiment: number; passion: number; mentions: number }[];
  colors?: string[];
  labels: { x: string; lovedStrongly: string; hatedStrongly: string; mildlyLiked: string; mildlyDisliked: string; tip: (r: { brand: string; net_sentiment: number; passion: number; mentions: number }) => string };
}) {
  const w = 420, h = 280, m = { l: 34, r: 14, t: 14, b: 38 };
  const iw = w - m.l - m.r, ih = h - m.t - m.b;
  const pad = 30; // room for the largest bubble inside the frame
  const x = (v: number) => m.l + pad + ((v + 100) / 200) * (iw - 2 * pad);
  const y = (v: number) => m.t + pad + (1 - v / 100) * (ih - 2 * pad);
  const top = Math.max(1, ...rows.map((r) => r.mentions));
  const radius = (n: number) => 6 + Math.sqrt(n / top) * 22;
  return (
    <div dir="ltr">
      <svg viewBox={`0 0 ${w} ${h}`} className="h-auto w-full" role="img" aria-label={rows.map(labels.tip).join("; ")}>
        <rect x={x(0)} y={m.t} width={m.l + iw - x(0)} height={y(50) - m.t} fill="var(--ok-bg)" />
        <rect x={m.l} y={m.t} width={x(0) - m.l} height={y(50) - m.t} fill="var(--bad-bg)" />
        <rect x={m.l} y={m.t} width={iw} height={ih} fill="none" stroke="var(--line-strong)" />
        <line x1={x(0)} x2={x(0)} y1={m.t} y2={m.t + ih} stroke="var(--line-strong)" />
        <line x1={m.l} x2={m.l + iw} y1={y(50)} y2={y(50)} stroke="var(--line-strong)" strokeDasharray="3 3" />
        <text x={m.l + iw - 6} y={m.t + 14} textAnchor="end" fontSize={11} fill="var(--muted)">{labels.lovedStrongly}</text>
        <text x={m.l + 6} y={m.t + 14} fontSize={11} fill="var(--muted)">{labels.hatedStrongly}</text>
        <text x={m.l + iw - 6} y={m.t + ih - 7} textAnchor="end" fontSize={11} fill="var(--muted)">{labels.mildlyLiked}</text>
        <text x={m.l + 6} y={m.t + ih - 7} fontSize={11} fill="var(--muted)">{labels.mildlyDisliked}</text>
        {[-100, -50, 0, 50, 100].map((t) => (
          <text key={t} x={x(t)} y={h - 22} textAnchor="middle" fontSize={10.5} fill="var(--muted)">{t > 0 ? `+${t}` : t < 0 ? `−${-t}` : "0"}</text>
        ))}
        {[0, 50, 100].map((t) => <text key={t} x={m.l - 6} y={y(t) + 4} textAnchor="end" fontSize={10.5} fill="var(--muted)">{t}</text>)}
        <text x={m.l + iw / 2} y={h - 4} textAnchor="middle" fontSize={11} fill="var(--text-2)">{labels.x}</text>
        {rows.map((r, i) => {
          const rr = radius(r.mentions);
          const cx_ = x(Math.max(-100, Math.min(100, r.net_sentiment)));
          const cy = y(Math.max(0, Math.min(100, r.passion)));
          return (
            <g key={r.brand}>
              <circle cx={cx_} cy={cy} r={rr} fill={colors[i % colors.length]} fillOpacity={0.85} stroke="white" strokeWidth={2}>
                <title>{labels.tip(r)}</title>
              </circle>
              <text x={Math.max(m.l + 34, Math.min(m.l + iw - 34, cx_))} y={Math.max(11, cy - rr - 5)} textAnchor="middle" fontSize={11.5} fontWeight={600} fill="var(--text)" style={{ pointerEvents: "none" }}>{r.brand}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ------------------------------------------------------------------------------------------ topic bubbles
export function TopicBubbles({ topics, tip }: { topics: { topic: string; count: number; net_sentiment: number }[]; tip: (t: { topic: string; count: number; net_sentiment: number }) => string }) {
  const top = Math.max(1, ...topics.map((t) => t.count));
  return (
    <div className="flex flex-wrap items-center justify-center gap-2.5 py-2">
      {centred([...topics].sort((a, b) => b.count - a.count)).map((t) => {
        const d = 56 + Math.sqrt(t.count / top) * 64;
        return (
          <div key={t.topic} title={tip(t)}
            className="flex shrink-0 flex-col items-center justify-center rounded-full p-2 text-center"
            style={{ width: d, height: d, background: `color-mix(in srgb, ${netColor(t.net_sentiment)} 16%, transparent)`, boxShadow: `inset 0 0 0 1.5px ${netColor(t.net_sentiment)}` }}>
            <span className="bidi line-clamp-2 text-[12px] font-semibold leading-tight">{t.topic}</span>
            <span className="mt-0.5 text-[11px] text-muted tabular-nums">{t.count}</span>
          </div>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------------------- hourly bars vs usual
export function HourlyBars({ values, usual, labels, height = 150, tip, color = "var(--bad-solid)" }: {
  values: number[];
  usual?: number | null;
  labels: string[];
  height?: number;
  tip: (i: number) => string;
  color?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, usual ?? 0, ...values) * 1.1;
  return (
    <div className="relative" dir="ltr">
      <div className="relative flex items-end gap-[3px]" style={{ height }} onMouseLeave={() => setHover(null)}>
        {values.map((v, i) => (
          <div key={i} className="flex h-full flex-1 items-end" onMouseEnter={() => setHover(i)}>
            <div className={cx("w-full rounded-t-[4px] transition", hover !== null && hover !== i && "opacity-60")}
              style={{ height: v ? `${Math.max(3, (v / max) * 100)}%` : 2, background: v ? color : "var(--fill-2)" }} />
          </div>
        ))}
        {usual != null && usual > 0 && (
          <div className="pointer-events-none absolute inset-x-0 border-t-2 border-dashed border-ink-2" style={{ bottom: `${(usual / max) * 100}%` }} />
        )}
      </div>
      <div className="mt-1.5 flex gap-[3px] text-[10.5px] text-muted">
        {labels.map((l, i) => <span key={i} className="flex-1 text-center">{i % 3 === 0 ? l : ""}</span>)}
      </div>
      {hover !== null && <Tip left={((hover + 0.5) / values.length) * 100}>{tip(hover)}</Tip>}
    </div>
  );
}

// ---------------------------------------------------------------------------------------- when (heatmap)
export function HeatGrid({ grid, days, cellTip }: { grid: number[][]; days: string[]; cellTip: (d: number, slot: number, n: number) => string }) {
  const [hover, setHover] = useState<{ d: number; s: number } | null>(null);
  const max = Math.max(1, ...grid.flat());
  return (
    <div>
      <div className="overflow-x-auto pb-1">
        <div className="min-w-[420px]" dir="ltr">
          {grid.map((row, d) => (
            <div key={d} className="flex items-center gap-[3px] py-[1.5px]">
              <span className="w-16 shrink-0 truncate pe-2 text-end text-[11px] text-muted">{days[d]}</span>
              {row.map((n, s) => (
                <span key={s} onMouseEnter={() => setHover({ d, s })} onMouseLeave={() => setHover(null)}
                  className={cx("h-6 flex-1 rounded-[5px]", hover?.d === d && hover?.s === s && "ring-2 ring-ink")}
                  style={{ background: n ? `rgba(10,10,10,${0.08 + 0.82 * (n / max)})` : "var(--fill-2)" }} />
              ))}
            </div>
          ))}
          <div className="flex gap-[3px] ps-16 pt-1">
            {Array.from({ length: 12 }, (_, s) => (
              <span key={s} className="flex-1 text-center text-[10px] text-faint">{s % 2 === 0 ? String(s * 2).padStart(2, "0") : ""}</span>
            ))}
          </div>
        </div>
      </div>
      <div className="mt-1 min-h-5 text-xs text-muted">{hover ? cellTip(hover.d, hover.s, grid[hover.d][hover.s]) : " "}</div>
    </div>
  );
}
