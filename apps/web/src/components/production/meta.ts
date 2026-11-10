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
