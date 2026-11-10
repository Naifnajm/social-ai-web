"use client";
/**
 * Canva-like design editor of the Design block: background (linked AI image or brand gradient) and text / shape /
 * logo layers. Rendering happens in the browser canvas, so Arabic text is shaped correctly; the PNG and the layers
 * are saved on the block.
 */
import { useTranslations } from "next-intl";
import { type PointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/icon";
import { Button, Field, IconButton, Modal, Segmented, Switch, Textarea, cx } from "@/components/ui";
import { FORMATS, aspectBox } from "./meta";
import type { BrandDesign } from "./types";

const SIZES: Record<string, [number, number]> = { "1:1": [1080, 1080], "4:5": [1080, 1350], "9:16": [1080, 1920], "16:9": [1920, 1080] };
const FONT = "'SF Arabic', 'Noto Sans Arabic', 'Inter', 'Segoe UI', Tahoma, sans-serif";
const RTL = /[֐-ࣿ]/;

type Layer = {
  id: number;
  type: "text" | "rect" | "logo";
  x: number;
  y: number;
  w: number;
  h?: number;
  text?: string;
  size?: number;
  color?: string;
  bold?: boolean;
  align?: CanvasTextAlign;
  box?: boolean;
  opacity?: number;
  radius?: number;
};

export type DesignState = { aspect: string; overlay: number; bgMode: "image" | "gradient" | "solid"; color1: string; color2: string; layers: Layer[] };

let uid = Date.now();
const nextId = () => ++uid;

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  r = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function drawText(ctx: CanvasRenderingContext2D, layer: Layer, family: string): [number, number, number, number] {
  const size = layer.size || 48;
  const rtl = RTL.test(layer.text || "");
  ctx.save();
  ctx.font = `${layer.bold ? 800 : 500} ${size}px ${family}`;
  ctx.direction = rtl ? "rtl" : "ltr";
  ctx.textBaseline = "top";
  const lines: string[] = [];
  for (const paragraph of (layer.text || "").split("\n")) {
    let line = "";
    for (const word of paragraph.split(" ")) {
      const test = line ? `${line} ${word}` : word;
      if (ctx.measureText(test).width > layer.w && line) {
        lines.push(line);
        line = word;
      } else line = test;
    }
    lines.push(line);
  }
  const lh = size * 1.25;
  const height = lines.length * lh;
  if (layer.box) {
    ctx.save();
    ctx.globalAlpha = 0.55;
    ctx.fillStyle = "#000";
    roundRect(ctx, layer.x - size * 0.4, layer.y - size * 0.3, layer.w + size * 0.8, height + size * 0.5, size * 0.3);
    ctx.fill();
    ctx.restore();
  }
  ctx.fillStyle = layer.color || "#fff";
  ctx.shadowColor = "rgba(0,0,0,0.25)";
  ctx.shadowBlur = size * 0.15;
  const align = layer.align || "left";
  ctx.textAlign = align;
  const anchor = align === "center" ? layer.x + layer.w / 2 : align === "right" ? layer.x + layer.w : layer.x;
  lines.forEach((text, i) => ctx.fillText(text, anchor, layer.y + i * lh));
  ctx.restore();
  return [layer.x, layer.y, layer.w, height];
}

type Layout = "bottom" | "center" | "banner";

function makeLayout(kind: Layout, base: DesignState, headline: string, hasLogo: boolean): DesignState {
  const [lw, lh] = SIZES[base.aspect] || SIZES["1:1"];
  const text = headline.split("\n")[0];
  const rtl = RTL.test(text);
  const pad = Math.round(lw * 0.07);
  const layers: Layer[] = [];
  if (kind === "bottom") {
    layers.push({ id: nextId(), type: "rect", x: 0, y: lh * 0.62, w: lw, h: lh * 0.38, color: "#000000", opacity: 0.45, radius: 0 });
    layers.push({ id: nextId(), type: "text", text, x: pad, y: lh * 0.68, w: lw - pad * 2, size: Math.round(lw * 0.075), color: "#ffffff", bold: true, align: rtl ? "right" : "left" });
  } else if (kind === "center") {
    layers.push({ id: nextId(), type: "text", text, x: pad, y: lh * 0.4, w: lw - pad * 2, size: Math.round(lw * 0.085), color: "#ffffff", bold: true, align: "center" });
  } else {
    layers.push({ id: nextId(), type: "rect", x: pad, y: pad, w: lw - pad * 2, h: lh * 0.2, color: base.color1, opacity: 0.92, radius: 28 });
    layers.push({ id: nextId(), type: "text", text, x: pad * 1.5, y: pad * 1.45, w: lw - pad * 3, size: Math.round(lw * 0.06), color: "#ffffff", bold: true, align: rtl ? "right" : "left" });
  }
  if (hasLogo) {
    const logoW = Math.round(lw * 0.16);
    layers.push({ id: nextId(), type: "logo", x: rtl ? pad : lw - pad - logoW, y: lh - pad - logoW * 0.5, w: logoW });
  }
  return { ...base, layers };
}

export function DesignEditor({ initial, aspect, imageUrl, headline, brand, onSave, onClose }: {
  initial?: Partial<DesignState> | null;
  aspect: string;
  imageUrl?: string | null;
  headline?: string | null;
  brand: BrandDesign;
  onSave: (png: string, design: DesignState) => Promise<void>;
  onClose: () => void;
}) {
  const t = useTranslations("production");
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const images = useRef<{ bg?: HTMLImageElement; logo?: HTMLImageElement }>({});
  const bounds = useRef<Record<number, [number, number, number, number]>>({});
  const drag = useRef<{ id: number; sx: number; sy: number; lx: number; ly: number } | null>(null);
  const [loaded, setLoaded] = useState(0);
  const [saving, setSaving] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [state, setState] = useState<DesignState>(() => {
    const base: DesignState = {
      aspect: initial?.aspect || aspect || "1:1",
      overlay: initial?.overlay ?? 35,
      bgMode: initial?.bgMode || (imageUrl ? "image" : "gradient"),
      color1: initial?.color1 || brand.color,
      color2: initial?.color2 || brand.color2,
      layers: initial?.layers || [],
    };
    // first open: start from a ready layout
    return base.layers.length ? base : makeLayout("bottom", base, headline || t("design.headline"), !!brand.logo_url);
  });
  const [w, h] = SIZES[state.aspect] || SIZES["1:1"];
  const family = brand.font && brand.font !== "system-ui" ? `${brand.font}, ${FONT}` : FONT;
  const layer = state.layers.find((l) => l.id === selected) || null;

  // load the background and the logo once
  useEffect(() => {
    const load = (key: "bg" | "logo", url?: string | null) => {
      if (!url) return;
      const img = new Image();
      img.onload = () => {
        images.current[key] = img;
        setLoaded((n) => n + 1);
      };
      img.src = url;
    };
    load("bg", imageUrl);
    load("logo", brand.logo_url);
  }, [imageUrl, brand.logo_url]);

  const layout = (kind: Layout, base: DesignState) => makeLayout(kind, base, headline || t("design.headline"), !!brand.logo_url);

  const render = useCallback((ctx: CanvasRenderingContext2D, withSelection: boolean) => {
    ctx.clearRect(0, 0, w, h);
    const bg = images.current.bg;
    if (state.bgMode === "image" && bg) {
      const scale = Math.max(w / bg.width, h / bg.height);
      ctx.drawImage(bg, (w - bg.width * scale) / 2, (h - bg.height * scale) / 2, bg.width * scale, bg.height * scale);
      if (state.overlay) {
        ctx.fillStyle = `rgba(0,0,0,${state.overlay / 100})`;
        ctx.fillRect(0, 0, w, h);
      }
    } else {
      const g = ctx.createLinearGradient(0, 0, w, h);
      g.addColorStop(0, state.color1);
      g.addColorStop(1, state.bgMode === "solid" ? state.color1 : state.color2);
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
    }
    const box: Record<number, [number, number, number, number]> = {};
    for (const l of state.layers) {
      if (l.type === "rect") {
        ctx.save();
        ctx.globalAlpha = l.opacity ?? 1;
        ctx.fillStyle = l.color || "#000";
        roundRect(ctx, l.x, l.y, l.w, l.h || 100, l.radius || 0);
        ctx.fill();
        ctx.restore();
        box[l.id] = [l.x, l.y, l.w, l.h || 100];
      } else if (l.type === "logo" && images.current.logo) {
        const img = images.current.logo;
        const lh = (img.height / img.width) * l.w;
        ctx.drawImage(img, l.x, l.y, l.w, lh);
        box[l.id] = [l.x, l.y, l.w, lh];
      } else if (l.type === "text") {
        box[l.id] = drawText(ctx, l, family);
      }
    }
    if (withSelection && selected && box[selected]) {
      const [x, y, bw, bh] = box[selected];
      ctx.save();
      ctx.strokeStyle = "#0a0a0a";
      ctx.lineWidth = Math.max(3, w / 300);
      ctx.setLineDash([w / 80, w / 120]);
      ctx.strokeRect(x - 6, y - 6, bw + 12, bh + 12);
      ctx.restore();
    }
    return box;
  }, [state, selected, w, h, family]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (ctx) bounds.current = render(ctx, true);
  }, [render, w, h, loaded]);

  const patchLayer = (values: Partial<Layer>) => setState((s) => ({ ...s, layers: s.layers.map((l) => (l.id === selected ? { ...l, ...values } : l)) }));
  const addLayer = (l: Layer) => {
    setState((s) => ({ ...s, layers: [...s.layers, l] }));
    setSelected(l.id);
  };
  const move = (dir: number) => setState((s) => {
    const layers = [...s.layers];
    const i = layers.findIndex((l) => l.id === selected);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= layers.length) return s;
    [layers[i], layers[j]] = [layers[j], layers[i]];
    return { ...s, layers };
  });
  const setAspect = (next: string) => setState((s) => {
    const [ow, oh] = SIZES[s.aspect] || SIZES["1:1"];
    const [nw, nh] = SIZES[next];
    return {
      ...s, aspect: next,
      layers: s.layers.map((l) => ({ ...l, x: (l.x * nw) / ow, y: (l.y * nh) / oh, w: (l.w * nw) / ow, h: l.h ? (l.h * nh) / oh : l.h, size: l.size ? (l.size * nw) / ow : l.size })),
    };
  });

  const point = (e: PointerEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    return [((e.clientX - rect.left) / rect.width) * w, ((e.clientY - rect.top) / rect.height) * h];
  };
  const onDown = (e: PointerEvent<HTMLCanvasElement>) => {
    const [px, py] = point(e);
    const hit = [...state.layers].reverse().find((l) => {
      const b = bounds.current[l.id];
      return b && px >= b[0] && px <= b[0] + b[2] && py >= b[1] && py <= b[1] + b[3];
    });
    setSelected(hit ? hit.id : null);
    if (hit) {
      drag.current = { id: hit.id, sx: px, sy: py, lx: hit.x, ly: hit.y };
      e.currentTarget.setPointerCapture(e.pointerId);
    }
  };
  const onMove = (e: PointerEvent<HTMLCanvasElement>) => {
    const d = drag.current;
    if (!d) return;
    const [px, py] = point(e);
    setState((s) => ({ ...s, layers: s.layers.map((l) => (l.id === d.id ? { ...l, x: d.lx + px - d.sx, y: d.ly + py - d.sy } : l)) }));
  };

  const save = async () => {
    setSaving(true);
    try {
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      render(ctx, false);
      await onSave(canvas.toDataURL("image/png"), state);
      onClose();
    } catch {
      /* toast already shown */
    } finally {
      setSaving(false);
    }
  };

  const colorInput = (value: string, onChange: (v: string) => void, label: string) => (
    <label className="flex items-center gap-2 text-xs text-muted">
      <input type="color" value={value} onChange={(e) => onChange(e.target.value)} className="h-8 w-10 cursor-pointer rounded-lg border border-line bg-transparent" aria-label={label} />
      {label}
    </label>
  );
  const ratio = useMemo(() => `${w} / ${h}`, [w, h]);

  return (
    <Modal open onClose={onClose} size="xl" title={t("design.title")}
      footer={<>
        <Button variant="ghost" onClick={onClose}>{t("cancel")}</Button>
        <Button variant="primary" icon="save" loading={saving} onClick={save}>{t("design.save")}</Button>
      </>}>
      <div className="flex flex-col gap-4 lg:flex-row">
        <div className="flex min-w-0 flex-1 items-center justify-center rounded-2xl bg-[#e9e9ec] p-3">
          <canvas ref={canvasRef} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={() => (drag.current = null)}
            className="max-h-[62vh] max-w-full cursor-move touch-none rounded-lg shadow-[0_12px_32px_-12px_rgba(0,0,0,.35)]"
            style={{ aspectRatio: ratio, width: state.aspect === "16:9" ? "100%" : undefined, height: state.aspect === "16:9" ? undefined : "62vh" }} />
        </div>
        <div className="flex w-full shrink-0 flex-col gap-4 lg:w-72">
          <Field label={t("inspector.format")}>
            <div className="grid grid-cols-4 gap-1.5">
              {FORMATS.map((f) => (
                <button key={f} type="button" onClick={() => setAspect(f)}
                  className={cx("flex flex-col items-center gap-1 rounded-xl border px-1 pb-1.5 pt-2 text-[11px]", f === state.aspect ? "border-ink font-semibold" : "border-line text-muted")}>
                  <span className={cx("rounded-sm", f === state.aspect ? "bg-ink" : "bg-black/20")} style={aspectBox(f, 22)} />
                  <span dir="ltr">{f}</span>
                </button>
              ))}
            </div>
          </Field>
          <Field label={t("design.layout")}>
            <div className="flex flex-wrap gap-1.5">
              {(["bottom", "center", "banner"] as const).map((k) => (
                <Button key={k} size="sm" onClick={() => { setSelected(null); setState((s) => layout(k, s)); }}>{t(`design.layouts.${k}`)}</Button>
              ))}
            </div>
          </Field>
          <Field label={t("design.background")}>
            <Segmented size="sm" value={state.bgMode} onChange={(bgMode) => setState((s) => ({ ...s, bgMode }))}
              options={[...(imageUrl ? [{ value: "image" as const, label: t("design.bg.image") }] : []),
                { value: "gradient" as const, label: t("design.bg.gradient") }, { value: "solid" as const, label: t("design.bg.solid") }]} />
          </Field>
          {state.bgMode === "image" ? (
            <Field label={t("design.overlay", { value: state.overlay })}>
              <input type="range" min={0} max={80} value={state.overlay} onChange={(e) => setState((s) => ({ ...s, overlay: Number(e.target.value) }))} className="accent-black" />
            </Field>
          ) : (
            <div className="flex gap-3">
              {colorInput(state.color1, (color1) => setState((s) => ({ ...s, color1 })), t("design.color1"))}
              {state.bgMode === "gradient" && colorInput(state.color2, (color2) => setState((s) => ({ ...s, color2 })), t("design.color2"))}
            </div>
          )}
          <div className="flex flex-wrap gap-1.5">
            <Button size="sm" icon="title" onClick={() => addLayer({ id: nextId(), type: "text", text: t("design.newText"), x: w * 0.1, y: h * 0.1, w: w * 0.8, size: Math.round(w * 0.05), color: "#ffffff", align: "center", box: true })}>{t("design.addText")}</Button>
            <Button size="sm" icon="square" onClick={() => addLayer({ id: nextId(), type: "rect", x: w * 0.1, y: h * 0.1, w: w * 0.4, h: h * 0.12, color: state.color1, opacity: 0.9, radius: 24 })}>{t("design.addShape")}</Button>
            {brand.logo_url && <Button size="sm" icon="branding" onClick={() => addLayer({ id: nextId(), type: "logo", x: w * 0.05, y: w * 0.05, w: w * 0.18 })}>{t("design.addLogo")}</Button>}
          </div>

          {layer && (
            <div className="flex flex-col gap-3 rounded-2xl bg-fill p-3">
              <div className="flex items-center gap-1">
                <span className="flex-1 text-[13px] font-semibold">{t(`design.layer.${layer.type}`)}</span>
                <IconButton icon="flip_to_front" label={t("design.forward")} onClick={() => move(1)} />
                <IconButton icon="flip_to_back" label={t("design.backward")} onClick={() => move(-1)} />
                <IconButton icon="delete" label={t("delete")} onClick={() => { setState((s) => ({ ...s, layers: s.layers.filter((l) => l.id !== selected) })); setSelected(null); }} />
              </div>
              {layer.type === "text" && (
                <>
                  <Textarea rows={3} dir="auto" value={layer.text} onChange={(e) => patchLayer({ text: e.target.value })} />
                  <Field label={t("design.size", { value: Math.round(layer.size || 0) })}>
                    <input type="range" min={16} max={Math.round(w * 0.16)} value={layer.size} onChange={(e) => patchLayer({ size: Number(e.target.value) })} className="accent-black" />
                  </Field>
                  <div className="flex flex-wrap items-center gap-2">
                    {colorInput(layer.color || "#ffffff", (color) => patchLayer({ color }), t("design.textColor"))}
                    <Segmented size="sm" value={layer.align || "left"} onChange={(align) => patchLayer({ align })}
                      options={[{ value: "left", label: <Icon name="format_align_left" size={14} /> }, { value: "center", label: <Icon name="format_align_center" size={14} /> }, { value: "right", label: <Icon name="format_align_right" size={14} /> }]} />
                  </div>
                  <div className="flex gap-4">
                    <Switch checked={!!layer.bold} onChange={(bold) => patchLayer({ bold })} label={t("design.bold")} />
                    <Switch checked={!!layer.box} onChange={(box) => patchLayer({ box })} label={t("design.box")} />
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {[brand.color, brand.color2, brand.text_color, "#ffffff", "#0a0a0a"].map((c, i) => (
                      <button key={`${c}-${i}`} type="button" onClick={() => patchLayer({ color: c })} className="h-6 w-6 rounded-full border border-line" style={{ background: c }} aria-label={c} />
                    ))}
                  </div>
                </>
              )}
              {layer.type === "rect" && (
                <>
                  {colorInput(layer.color || "#000000", (color) => patchLayer({ color }), t("design.fill"))}
                  <Field label={t("design.opacity", { value: Math.round((layer.opacity ?? 1) * 100) })}>
                    <input type="range" min={0} max={100} value={Math.round((layer.opacity ?? 1) * 100)} onChange={(e) => patchLayer({ opacity: Number(e.target.value) / 100 })} className="accent-black" />
                  </Field>
                  <Field label={t("design.radius")}>
                    <input type="range" min={0} max={120} value={layer.radius || 0} onChange={(e) => patchLayer({ radius: Number(e.target.value) })} className="accent-black" />
                  </Field>
                </>
              )}
              {layer.type === "logo" && (
                <Field label={t("design.size", { value: Math.round(layer.w) })}>
                  <input type="range" min={60} max={Math.round(w * 0.5)} value={layer.w} onChange={(e) => patchLayer({ w: Number(e.target.value) })} className="accent-black" />
                </Field>
              )}
            </div>
          )}
          {!layer && <p className="text-xs text-muted">{t("design.tip")}</p>}
        </div>
      </div>
    </Modal>
  );
}
