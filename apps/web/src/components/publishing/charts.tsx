"use client";
/** Lightweight SVG charts in neutral greys (one series each, hover tooltip, recessive axes). */
import { useState } from "react";
import { cx } from "@/components/ui";

type Point = { label: string; value: number };

function Tooltip({ percent, children }: { percent: number; children: React.ReactNode }) {
  const left = Math.min(Math.max(percent, 14), 86);
  return (
    <div className="glass-strong pointer-events-none absolute -top-2 z-10 -translate-x-1/2 rounded-xl px-2.5 py-1.5 text-xs whitespace-nowrap" style={{ left: `${left}%` }}>
      {children}
    </div>
  );
}

/** Area/line chart for a time series. */
export function AreaChart({ points, height = 160, format = String, emptyLabel }: { points: Point[]; height?: number; format?: (n: number) => string; emptyLabel?: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 600;
  const max = Math.max(1, ...points.map((p) => p.value));
  const step = points.length > 1 ? width / (points.length - 1) : 0;
  const x = (i: number) => i * step;
  const y = (v: number) => 4 + (height - 8) * (1 - v / max);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const area = points.length ? `${line} L${x(points.length - 1)},${height} L0,${height} Z` : "";
  const empty = !points.some((p) => p.value);
  const pct = (i: number) => (points.length > 1 ? (i / (points.length - 1)) * 100 : 50);
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
          {!empty && <path d={area} fill="currentColor" fillOpacity={0.07} />}
          {!empty && <path d={line} fill="none" stroke="var(--ink)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />}
          {hover !== null && !empty && <line x1={x(hover)} x2={x(hover)} y1={0} y2={height} stroke="currentColor" strokeOpacity={0.25} vectorEffect="non-scaling-stroke" />}
        </svg>
        {hover !== null && points[hover] && !empty && (
          <span className="pointer-events-none absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ink ring-2 ring-white"
            style={{ left: `${pct(hover)}%`, top: y(points[hover].value) }} />
        )}
        {empty && emptyLabel && <div className="absolute inset-0 flex items-center justify-center text-sm text-muted">{emptyLabel}</div>}
      </div>
      <div className="relative mt-1.5 h-4 text-[11px] text-muted">
        {ticks.map((i) => points[i] && (
          <span key={i} className="absolute whitespace-nowrap" style={{ left: `${pct(i)}%`, transform: `translateX(${i === 0 ? 0 : i === points.length - 1 ? -100 : -50}%)` }}>
            {points[i].label}
          </span>
        ))}
      </div>
      {hover !== null && points[hover] && !empty && (
        <Tooltip percent={pct(hover)}>
          <span className="text-muted">{points[hover].label}</span> · <b>{format(points[hover].value)}</b>
        </Tooltip>
      )}
    </div>
  );
}

/** Vertical bars (posts per day). */
export function BarChart({ points, height = 120, format = String }: { points: Point[]; height?: number; format?: (n: number) => string }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...points.map((p) => p.value));
  return (
    <div className="relative" dir="ltr">
      <div className="flex items-end gap-[2px]" style={{ height }} onMouseLeave={() => setHover(null)}>
        {points.map((p, i) => (
          <div key={i} className="flex h-full flex-1 items-end" onMouseEnter={() => setHover(i)}>
            <div className={cx("w-full rounded-t-[4px] transition", hover === i ? "bg-ink" : "bg-ink/25")}
              style={{ height: p.value ? `${Math.max(4, (p.value / max) * 100)}%` : 2, opacity: p.value ? 1 : 0.35 }} />
          </div>
        ))}
      </div>
      {hover !== null && points[hover] && (
        <div className="glass-strong pointer-events-none absolute -top-2 rounded-xl px-2.5 py-1.5 text-xs whitespace-nowrap"
          style={{ left: `${Math.min(80, Math.max(0, (hover / points.length) * 100 - 6))}%` }}>
          <span className="text-muted">{points[hover].label}</span> · <b>{format(points[hover].value)}</b>
        </div>
      )}
    </div>
  );
}

/** 7×24 heatmap of the best posting times (darker = better). */
export function Heatmap({ grid, days, cellLabel }: { grid: { score: number; count: number }[][]; days: string[]; cellLabel: (d: number, h: number, score: number, count: number) => string }) {
  const [hover, setHover] = useState<{ d: number; h: number } | null>(null);
  const max = Math.max(0.0001, ...grid.flat().map((c) => c.score));
  return (
    <div className="relative">
      <div className="overflow-x-auto pb-1">
        <div className="min-w-[560px]" dir="ltr">
          {grid.map((row, d) => (
            <div key={d} className="flex items-center gap-[2px] py-[1px]">
              <span className="w-16 shrink-0 truncate pe-2 text-end text-[11px] text-muted">{days[d]}</span>
              {row.map((cell, h) => (
                <span key={h} onMouseEnter={() => setHover({ d, h })} onMouseLeave={() => setHover(null)}
                  className={cx("h-5 flex-1 rounded-[4px]", hover?.d === d && hover?.h === h && "ring-2 ring-ink")}
                  style={{ background: cell.score ? `rgba(10,10,10,${0.06 + 0.84 * (cell.score / max)})` : "var(--fill-2)" }} />
              ))}
            </div>
          ))}
          <div className="flex gap-[2px] ps-16 pt-1">
            {Array.from({ length: 24 }, (_, h) => (
              <span key={h} className="flex-1 text-center text-[10px] text-faint">{h % 3 === 0 ? h : ""}</span>
            ))}
          </div>
        </div>
      </div>
      <div className="mt-1 min-h-5 text-xs text-muted">
        {hover ? cellLabel(hover.d, hover.h, grid[hover.d][hover.h].score, grid[hover.d][hover.h].count) : " "}
      </div>
    </div>
  );
}

/** Horizontal bar rows (content insights). */
export function BarRows({ rows, format }: { rows: { label: string; value: number; hint?: string }[]; format: (n: number) => string }) {
  const max = Math.max(0.0001, ...rows.map((r) => r.value));
  return (
    <ul className="flex flex-col gap-2.5">
      {rows.map((r) => (
        <li key={r.label} className="text-sm">
          <div className="mb-1 flex items-baseline gap-2">
            <span className="flex-1 truncate">{r.label}</span>
            {r.hint && <span className="text-xs text-muted">{r.hint}</span>}
            <b className="tabular-nums">{format(r.value)}</b>
          </div>
          <div className="h-2 rounded-full bg-fill-2">
            <div className="h-2 rounded-full bg-ink/70" style={{ width: `${Math.max(3, (r.value / max) * 100)}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
