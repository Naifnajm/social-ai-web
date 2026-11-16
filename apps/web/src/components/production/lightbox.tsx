"use client";
/** Full-screen viewer of a block's results: every version of every run, download, "use this version", compare. */
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Icon } from "@/components/icon";
import { Button, cx } from "@/components/ui";
import { credits as creditsText } from "@/lib/ai";
import { KIND_META, usd } from "./meta";
import { useCanvasStore } from "./store";
import type { BlockNode, OutputItem } from "./types";

type Item = OutputItem & { index: number };

/** What one result cost, in AI credits when the board pays with them. */
export function useOutputCost() {
  const t = useTranslations("production");
  const perUsd = useCanvasStore((s) => s.creditsPerUsd);
  return useCallback((cost: number, node: BlockNode) => {
    if (!(cost > 0)) return null;
    return perUsd && node.estimate?.credits != null ? t("creditsAmount", { amount: creditsText(cost * perUsd) }) : usd(cost);
  }, [perUsd, t]);
}

function itemsOf(node: BlockNode): Item[] {
  const list: OutputItem[] = node.outputs.length ? node.outputs : node.output
    ? [{ id: -1, run: node.run_no, cost: node.cost, media: node.output, selected: true, aspect: node.aspect }]
    : node.output_text ? [{ id: -1, run: node.run_no, cost: node.cost, text: node.output_text, selected: true }] : [];
  return list.map((o, index) => ({ ...o, index }));
}

function View({ item, compact }: { item: Item; compact?: boolean }) {
  const media = item.media;
  if (media?.kind === "image") {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={media.url} alt="" className="max-h-full max-w-full rounded-xl object-contain shadow-2xl" draggable={false} />;
  }
  if (media?.kind === "video") {
    return <video key={media.url} src={media.url} controls autoPlay={!compact} playsInline loop className="max-h-full max-w-full rounded-xl bg-black shadow-2xl" />;
  }
  if (media?.kind === "audio") {
    return (
      <div className="flex w-full max-w-md flex-col items-center gap-4 rounded-3xl bg-white/10 p-8 text-white">
        <Icon name="graphic_eq" size={48} />
        <audio key={media.url} src={media.url} controls autoPlay={!compact} className="w-full" />
      </div>
    );
  }
  return (
    <div className="bidi max-h-full w-full max-w-2xl overflow-auto whitespace-pre-wrap rounded-2xl bg-white p-6 text-[15px] leading-relaxed text-text shadow-2xl" dir="auto">
      {item.text}
    </div>
  );
}

export function Lightbox({ nodeId, outputId, onClose }: { nodeId: number; outputId?: number | null; onClose: () => void }) {
  const t = useTranslations("production.lightbox");
  const tp = useTranslations("production");
  const node = useCanvasStore((s) => s.blocks.get(nodeId));
  const actions = useCanvasStore((s) => s.actions);
  const readOnly = useCanvasStore((s) => s.readOnly);
  const costOf = useOutputCost();
  const items = useMemo(() => (node ? itemsOf(node) : []), [node]);
  const [current, setCurrent] = useState(() => {
    const start = items.findIndex((o) => (outputId ? o.id === outputId : o.selected));
    return Math.max(0, start);
  });
  const [compare, setCompare] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const item = items[Math.min(current, items.length - 1)];
  const rtl = typeof document !== "undefined" && document.documentElement.dir === "rtl";

  const go = useCallback((step: number) => setCurrent((c) => (items.length ? (c + step + items.length) % items.length : 0)), [items.length]);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); }
      else if (e.key === "ArrowRight") { e.preventDefault(); go(rtl ? -1 : 1); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); go(rtl ? 1 : -1); }
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      previous?.focus?.();
    };
  }, [go, onClose, rtl]);

  if (!node || !item || typeof document === "undefined") return null;
  const meta = KIND_META[node.kind] || KIND_META.text;
  const other = compare != null ? items[compare] : null;
  const cost = costOf(item.cost, node);
  const choose = async (target: Item) => {
    if (!actions || target.id < 0) return;
    setBusy(true);
    try {
      await actions.selectOutput(node.id, target.id);
    } catch {
      /* toast shown */
    } finally {
      setBusy(false);
    }
  };
  const download = item.media ? item.media.url : item.text ? `data:text/plain;charset=utf-8,${encodeURIComponent(item.text)}` : null;

  return createPortal(
    <div role="dialog" aria-modal aria-label={t("title", { name: node.name })} className="fixed inset-0 z-[70] flex flex-col bg-[#0b0b0d]/95 text-white backdrop-blur-md">
      <header className="flex items-center gap-3 px-4 py-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl text-white" style={{ background: meta.color }}>
          <Icon name={meta.icon} size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="bidi truncate text-[15px] font-semibold" dir="auto">{node.name}</div>
          <div className="flex flex-wrap items-center gap-x-2 text-xs text-white/60">
            <span>{t("position", { n: item.index + 1, total: items.length })}</span>
            <span>· {tp("inspector.runNo", { n: item.run })}</span>
            {item.model && <span className="font-mono" dir="ltr">· {item.model}</span>}
            {cost && <span className="tabular-nums">· {cost}</span>}
            {item.selected && <span className="rounded-full bg-white/15 px-2 py-px text-[11px] font-medium text-white">{t("inUse")}</span>}
          </div>
        </div>
        {items.length > 1 && (
          <button type="button" onClick={() => setCompare(compare == null ? (current + 1) % items.length : null)} aria-pressed={compare != null}
            className={cx("hidden h-9 items-center gap-1.5 rounded-full px-3 text-[13px] font-medium transition-colors duration-150 sm:inline-flex", compare != null ? "bg-white text-ink" : "bg-white/10 hover:bg-white/20")}>
            <Icon name="swap_horiz" size={16} />{t("compare")}
          </button>
        )}
        {download && (
          <a href={download} download={item.media?.filename || `${node.name}.txt`} target="_blank" rel="noreferrer"
            className="inline-flex h-9 items-center gap-1.5 rounded-full bg-white/10 px-3 text-[13px] font-medium hover:bg-white/20" aria-label={t("download")}>
            <Icon name="download" size={16} /><span className="hidden sm:inline">{t("download")}</span>
          </a>
        )}
        {!readOnly && !item.selected && item.id > 0 && (
          <Button size="md" icon="check" loading={busy} onClick={() => choose(item)} className="!bg-white !text-ink hover:!bg-white/90">{t("use")}</Button>
        )}
        <button ref={closeRef} type="button" aria-label={tp("close")} title={tp("close")} onClick={onClose}
          className="inline-flex h-9 w-9 items-center justify-center rounded-full text-white transition-colors duration-150 hover:bg-white/15">
          <Icon name="close" size={18} />
        </button>
      </header>

      <div className="relative flex min-h-0 flex-1 items-center justify-center gap-4 px-4 pb-2 sm:px-16">
        {other ? (
          <div className="grid h-full w-full grid-cols-2 gap-4">
            {[item, other].map((side, i) => (
              <figure key={`${i}-${side.id}`} className="flex min-h-0 flex-col items-center gap-2">
                <div className="flex min-h-0 w-full flex-1 items-center justify-center"><View item={side} compact /></div>
                <figcaption className="flex items-center gap-2 text-xs text-white/70">
                  {t("position", { n: side.index + 1, total: items.length })}
                  {side.selected ? <span className="rounded-full bg-white/15 px-2 py-px text-white">{t("inUse")}</span> : !readOnly && side.id > 0 && (
                    <button type="button" onClick={() => choose(side)} className="rounded-full bg-white/10 px-2.5 py-1 font-medium text-white hover:bg-white/20">{t("use")}</button>
                  )}
                </figcaption>
              </figure>
            ))}
          </div>
        ) : <View item={item} />}
        {items.length > 1 && (
          <>
            <button type="button" onClick={() => go(-1)} aria-label={t("previous")}
              className="absolute start-3 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 hover:bg-white/20">
              <Icon name="arrow_back" size={20} className="rtl:rotate-180" />
            </button>
            <button type="button" onClick={() => go(1)} aria-label={t("next")}
              className="absolute end-3 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 hover:bg-white/20">
              <Icon name="arrow_forward" size={20} className="rtl:rotate-180" />
            </button>
          </>
        )}
      </div>

      {items.length > 1 && (
        <div className="flex justify-center gap-1.5 overflow-x-auto px-4 pb-4 pt-2" role="listbox" aria-label={t("versions")}>
          {items.map((o, i) => (
            <button key={`${o.id}-${i}`} type="button" role="option" aria-selected={i === current || i === compare}
              onClick={() => (compare != null && i !== current ? setCompare(i) : setCurrent(i))}
              className={cx("relative h-14 w-14 shrink-0 overflow-hidden rounded-xl border-2 bg-white/10 text-[11px] transition-colors duration-150",
                i === current ? "border-white" : i === compare ? "border-[#5b8def]" : "border-transparent hover:border-white/40")}
              title={t("position", { n: i + 1, total: items.length })}>
              {o.media?.kind === "image" ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={o.media.url} alt="" loading="lazy" className="h-full w-full object-cover" />
              ) : (
                <span className="flex h-full w-full items-center justify-center"><Icon name={o.media?.kind === "video" ? "movie" : o.media?.kind === "audio" ? "graphic_eq" : "text_fields"} size={18} /></span>
              )}
              {o.selected && <span className="absolute bottom-0.5 end-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-white text-ink"><Icon name="check" size={11} /></span>}
            </button>
          ))}
        </div>
      )}
    </div>,
    document.body,
  );
}
