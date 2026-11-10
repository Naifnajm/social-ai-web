"use client";
/**
 * The template canvas: the live preview image with the photo window and the text zone drawn on top.
 * Drag a box to move it, drag a corner to resize it (values in % of the canvas).
 */
import { useTranslations } from "next-intl";
import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/icon";
import { Spinner, cx } from "@/components/ui";

export type Box = { x: number; y: number; w: number; h: number };
type Kind = "photo" | "text";
type Mode = "move" | "nw" | "se";
const MIN = 3;
const round = (v: number) => Math.round(v * 100) / 100;
const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

export function FrameStage({ ratio, src, loading, photo, text, onChange, readOnly, emptyLabel }: {
  ratio: number; // width / height
  src: string | null;
  loading?: boolean;
  photo: Box;
  text: Box | null;
  onChange: (kind: Kind, box: Box) => void;
  readOnly?: boolean;
  emptyLabel?: string;
}) {
  const t = useTranslations("templates");
  const [drag, setDrag] = useState<{ kind: Kind; mode: Mode; x: number; y: number; rect: DOMRect; orig: Box } | null>(null);
  const [live, setLive] = useState<Partial<Record<Kind, Box>>>({});
  const liveRef = useRef<Partial<Record<Kind, Box>>>({});

  useEffect(() => {
    if (!drag) return;
    const move = (ev: PointerEvent) => {
      const dx = ((ev.clientX - drag.x) / drag.rect.width) * 100;
      const dy = ((ev.clientY - drag.y) / drag.rect.height) * 100;
      const o = drag.orig;
      let b: Box;
      if (drag.mode === "move") {
        b = { x: clamp(o.x + dx, 0, 100 - o.w), y: clamp(o.y + dy, 0, 100 - o.h), w: o.w, h: o.h };
      } else if (drag.mode === "se") {
        b = { x: o.x, y: o.y, w: clamp(o.w + dx, MIN, 100 - o.x), h: clamp(o.h + dy, MIN, 100 - o.y) };
      } else {
        const x = clamp(o.x + dx, 0, o.x + o.w - MIN);
        const y = clamp(o.y + dy, 0, o.y + o.h - MIN);
        b = { x, y, w: o.x + o.w - x, h: o.y + o.h - y };
      }
      liveRef.current = { ...liveRef.current, [drag.kind]: b };
      setLive(liveRef.current);
    };
    const up = () => {
      const b = liveRef.current[drag.kind];
      if (b) onChange(drag.kind, { x: round(b.x), y: round(b.y), w: round(b.w), h: round(b.h) });
      liveRef.current = { ...liveRef.current, [drag.kind]: undefined };
      setLive(liveRef.current);
      setDrag(null);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
    };
  }, [drag, onChange]);

  const start = (ev: ReactPointerEvent, kind: Kind, mode: Mode) => {
    const host = (ev.currentTarget as HTMLElement).closest("[data-frame-stage]");
    if (readOnly || ev.button !== 0 || !host) return;
    ev.preventDefault();
    ev.stopPropagation();
    const orig = live[kind] ?? (kind === "photo" ? photo : text!);
    setDrag({ kind, mode, x: ev.clientX, y: ev.clientY, rect: host.getBoundingClientRect(), orig });
  };

  const boxes: { kind: Kind; box: Box }[] = [{ kind: "photo", box: live.photo ?? photo }];
  if (text) boxes.push({ kind: "text", box: live.text ?? text });

  return (
    <div dir="ltr" data-frame-stage
      className={cx("relative w-full touch-none select-none overflow-hidden rounded-2xl bg-fill-2 shadow-[0_18px_40px_-18px_rgba(0,0,0,.45)]", drag && "cursor-grabbing")}
      style={{ aspectRatio: String(ratio) }}>
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt="" draggable={false} className="absolute inset-0 h-full w-full object-cover" />
      ) : (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-muted">
          <Icon name="photo_frame" size={34} />
          <span className="text-sm">{emptyLabel}</span>
        </div>
      )}
      {loading && <span className="glass absolute end-2 top-2 rounded-full p-1.5"><Spinner size={16} /></span>}
      {boxes.map(({ kind, box }) => (
        <div key={kind}
          onPointerDown={(ev) => start(ev, kind, "move")}
          className={cx("group absolute rounded-md border-2 border-dashed transition-colors",
            readOnly ? "pointer-events-none" : "cursor-grab",
            kind === "photo" ? "border-white/90 bg-white/5 shadow-[0_0_0_1px_rgba(0,0,0,.35)]" : "border-amber-300 bg-amber-300/10 shadow-[0_0_0_1px_rgba(0,0,0,.35)]")}
          style={{ left: `${box.x}%`, top: `${box.y}%`, width: `${box.w}%`, height: `${box.h}%` }}>
          <span className={cx("pointer-events-none absolute start-1.5 top-1.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold opacity-0 shadow transition-opacity group-hover:opacity-100",
            drag?.kind === kind && "opacity-100",
            kind === "photo" ? "bg-white text-ink" : "bg-amber-300 text-ink")}>
            <Icon name={kind === "photo" ? "image" : "text_fields"} size={12} />
            {kind === "photo" ? t("editor.photoBox") : t("editor.textBox")}
          </span>
          {!readOnly && (["nw", "se"] as const).map((corner) => (
            <span key={corner} title={t("editor.resize")}
              onPointerDown={(ev) => start(ev, kind, corner)}
              className={cx("absolute h-4 w-4 rounded-full border-2 border-ink bg-white shadow",
                corner === "nw" ? "-left-2 -top-2 cursor-nwse-resize" : "-bottom-2 -right-2 cursor-nwse-resize")} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Legend under the stage (the box labels only show on hover). */
export function StageLegend({ text }: { text: boolean }) {
  const t = useTranslations("templates");
  return (
    <div className="flex items-center justify-center gap-4 text-xs text-muted">
      <span className="inline-flex items-center gap-1.5"><span className="h-3 w-4 rounded-sm border-2 border-dashed border-text-2" />{t("editor.photoBox")}</span>
      {text && <span className="inline-flex items-center gap-1.5"><span className="h-3 w-4 rounded-sm border-2 border-dashed border-amber-400" />{t("editor.textBox")}</span>}
    </div>
  );
}
