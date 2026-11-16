/** Visual metadata of the Production blocks (icons, colours) and small helpers shared by the canvas. */
import type { BlockNode, Kind } from "./types";

export const NODE_W = 288;

export const TYPE_COLORS: Record<string, string> = {
  text: "#a1a1aa",
  image: "#5b8def",
  video: "#e0679f",
  audio: "#e9a23b",
  media: "#8b6fe0",
};

export const KIND_META: Record<string, { icon: string; color: string }> = {
  text: { icon: "text_fields", color: "#64748b" },
  llm: { icon: "wand_stars", color: "#7c3aed" },
  upload: { icon: "upload", color: "#0891b2" },
  image: { icon: "image", color: "#2563eb" },
  video: { icon: "movie", color: "#db2777" },
  audio: { icon: "mic", color: "#f59e0b" },
  merge: { icon: "call_merge", color: "#059669" },
  design: { icon: "brush", color: "#ea580c" },
  template: { icon: "photo_frame", color: "#c026d3" },
  reframe: { icon: "aspect_ratio", color: "#0d9488" },
  captions: { icon: "subtitles", color: "#4f46e5" },
  approval: { icon: "verified_user", color: "#16a34a" },
  post: { icon: "send", color: "#0f172a" },
};

/** Order of the bottom toolbar. */
export const TOOLBAR_KINDS = ["text", "llm", "upload", "image", "video", "audio", "merge", "design", "template", "reframe", "captions", "approval", "post"];
export const GENERATIVE = ["llm", "image", "video", "audio"];
export const CAPABILITY: Record<string, string> = { llm: "text", image: "image", video: "video", audio: "audio" };
export const FORMATS = ["9:16", "4:5", "1:1", "16:9"];

export const typeColor = (type?: string | null) => TYPE_COLORS[type || "media"] || TYPE_COLORS.media;

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const small = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 4 });
export const usd = (value: number) => (value > 0 && value < 0.01 ? small.format(value) : money.format(value));

/** Data types a block produces (an upload depends on its file). */
export function outputTypes(node: BlockNode): string[] {
  if (!node.out_type) return [];
  if (node.out_type === "media") return node.kind === "reframe" ? ["image", "video"] : node.kind === "approval" ? ["text", "image", "video", "audio"] : ["image", "video", "audio"];
  return [node.out_type];
}

/** The port of `target` a link from `source` would land on (same rule as the API), or null. */
export function pickPort(kinds: Kind[], source: BlockNode, target: BlockNode, port?: string | null) {
  const kind = kinds.find((k) => k.key === target.kind);
  if (!kind || source.id === target.id) return null;
  const types = outputTypes(source);
  return kind.ports.find((p) => (!port || p.key === port) && p.accepts.some((t) => types.includes(t))) || null;
}

export function aspectBox(aspect: string, size = 26) {
  const [w, h] = aspect.split(":").map(Number);
  return w >= h ? { width: size, height: Math.round((size * h) / w) } : { width: Math.round((size * w) / h), height: size };
}

export const isRunning = (state: string) => state === "queued" || state === "running";

/** Grid of the canvas background; blocks snap to it while dragged. */
export const GRID = 22;
/** Below this zoom the blocks are drawn as compact cards (icon, name, state, thumbnail). */
export const COMPACT_ZOOM = 0.55;
/** Runs cheaper than this start without a confirmation (the checks still run). */
export const CONFIRM_FROM_USD = 0.05;

/** A stand-in block of `kind`, to test links to/from a block that does not exist yet. */
export function sampleBlock(kinds: Kind[], kind: string): BlockNode {
  const output = kinds.find((k) => k.key === kind)?.output ?? null;
  return { id: -1, kind, out_type: output } as BlockNode;
}

/** Kinds that can be linked to a dragged link: from a block's output (`source`) or into a block's port (`target`). */
export function compatibleKinds(kinds: Kind[], from: BlockNode, handleType: "source" | "target", port?: string | null): string[] {
  return TOOLBAR_KINDS.filter((kind) => {
    const sample = sampleBlock(kinds, kind);
    return handleType === "source" ? !!pickPort(kinds, from, sample) : !!pickPort(kinds, sample, from, port);
  });
}

/** Simple left → right layout: one column per depth in the graph, blocks keep their vertical order. */
export function tidyLayout(
  nodes: { id: number; x: number; y: number; height: number }[],
  edges: { source: number; target: number }[],
  gapX = 96, gapY = 44,
): Record<number, [number, number]> {
  if (!nodes.length) return {};
  const ids = new Set(nodes.map((n) => n.id));
  const ups = new Map<number, number[]>();
  for (const e of edges) if (ids.has(e.source) && ids.has(e.target)) ups.set(e.target, [...(ups.get(e.target) || []), e.source]);
  const depth = new Map<number, number>();
  const visit = (id: number, trail: Set<number>): number => {
    if (depth.has(id)) return depth.get(id)!;
    if (trail.has(id)) return 0;
    trail.add(id);
    const d = Math.max(-1, ...(ups.get(id) || []).map((up) => visit(up, trail))) + 1;
    trail.delete(id);
    depth.set(id, d);
    return d;
  };
  nodes.forEach((n) => visit(n.id, new Set()));
  const left = Math.min(...nodes.map((n) => n.x));
  const top = Math.min(...nodes.map((n) => n.y));
  const columns = new Map<number, typeof nodes>();
  for (const n of nodes) columns.set(depth.get(n.id)!, [...(columns.get(depth.get(n.id)!) || []), n]);
  const snap = (v: number) => Math.round(v / GRID) * GRID;
  const out: Record<number, [number, number]> = {};
  for (const [d, column] of columns) {
    let y = top;
    for (const n of [...column].sort((a, b) => a.y - b.y || a.x - b.x)) {
      out[n.id] = [snap(left + d * (NODE_W + gapX)), snap(y)];
      y += n.height + gapY;
    }
  }
  return out;
}
