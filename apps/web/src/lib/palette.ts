/**
 * Colours of an image, read in the browser (nothing is uploaded for it):
 *
 *   const palette = await extractPalette(file);         // ["#1f3d2b", "#d9a441", …] most used first, ≤ 6
 *   const kit = paletteToKit(palette);                   // { primary, secondary, accent, text, background }
 *
 * Transparent pixels are skipped, the backdrop of a flat logo (the colour of its border) is kept apart as the
 * background, and near-identical shades are merged so each swatch is a distinct brand colour.
 */

type Rgb = [number, number, number];

const toHex = ([r, g, b]: Rgb) => `#${[r, g, b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("")}`;
const fromHex = (hex: string): Rgb => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as Rgb;
const dist = (a: Rgb, b: Rgb) => Math.hypot(a[0] - b[0], (a[1] - b[1]) * 1.2, a[2] - b[2]);

/** Distance from colour ``p`` to the straight mix between ``a`` and ``b`` (0 = an exact blend of the two). */
function toSegment(p: Rgb, a: Rgb, b: Rgb) {
  const ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], ap = [p[0] - a[0], p[1] - a[1], p[2] - a[2]];
  const len = ab[0] ** 2 + ab[1] ** 2 + ab[2] ** 2 || 1;
  const t = Math.max(0, Math.min(1, (ap[0] * ab[0] + ap[1] * ab[1] + ap[2] * ab[2]) / len));
  if (t < 0.12 || t > 0.88) return Infinity; // close to an end = a shade of that colour, handled by merging
  return dist(p, [a[0] + ab[0] * t, a[1] + ab[1] * t, a[2] + ab[2] * t]);
}

function saturation([r, g, b]: Rgb) {
  const max = Math.max(r, g, b) / 255, min = Math.min(r, g, b) / 255;
  const l = (max + min) / 2;
  return max === min ? 0 : (max - min) / (1 - Math.abs(2 * l - 1));
}

export function luminance(hex: string) {
  const lin = fromHex(hex).map((v) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}

/** WCAG contrast ratio between two #rrggbb colours (1 to 21). */
export function contrast(a: string, b: string) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** White or near-black, whichever reads better on ``background``. */
export const readableOn = (background: string) => (contrast("#ffffff", background) >= contrast("#111111", background) ? "#ffffff" : "#111111");

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("image"));
    img.src = src;
  });
}

export async function extractPalette(source: File | string, max = 6): Promise<{ colors: string[]; background: string | null }> {
  const url = typeof source === "string" ? source : URL.createObjectURL(source);
  try {
    const img = await loadImage(url);
    const size = 96;
    const scale = Math.min(1, size / Math.max(img.naturalWidth || size, img.naturalHeight || size));
    const w = Math.max(1, Math.round((img.naturalWidth || size) * scale)), h = Math.max(1, Math.round((img.naturalHeight || size) * scale));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return { colors: [], background: null };
    ctx.drawImage(img, 0, 0, w, h);
    const px = ctx.getImageData(0, 0, w, h).data;

    // 1. buckets of 4 bits per channel, averaged
    const buckets = new Map<number, { n: number; r: number; g: number; b: number; edge: number }>();
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = (y * w + x) * 4;
        if (px[i + 3] < 140) continue;
        const r = px[i], g = px[i + 1], b = px[i + 2];
        const key = ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4);
        const cell = buckets.get(key) ?? { n: 0, r: 0, g: 0, b: 0, edge: 0 };
        cell.n++; cell.r += r; cell.g += g; cell.b += b;
        if (x === 0 || y === 0 || x === w - 1 || y === h - 1) cell.edge++;
        buckets.set(key, cell);
      }
    }
    const cells = [...buckets.values()].map((c) => ({ rgb: [c.r / c.n, c.g / c.n, c.b / c.n] as Rgb, n: c.n, edge: c.edge }))
      .sort((a, b) => b.n - a.n);
    if (!cells.length) return { colors: [], background: null };

    // 2. the backdrop: a colour that owns most of the border is the logo's background, not a brand colour
    const border = 2 * (w + h) - 4;
    const backdrop = cells.find((c) => c.edge / border > 0.55) ?? null;

    // 3. merge near-identical shades, keep the most used
    const merged: { rgb: Rgb; n: number }[] = [];
    for (const c of cells) {
      if (backdrop && dist(c.rgb, backdrop.rgb) < 40) continue;
      const near = merged.find((m) => dist(m.rgb, c.rgb) < 46);
      if (near) near.n += c.n;
      else merged.push({ rgb: c.rgb, n: c.n });
    }
    const total = merged.reduce((s, m) => s + m.n, 0) || 1;
    // 4. drop the blends anti-aliasing leaves between two stronger colours (or a colour and the backdrop)
    const kept: Rgb[] = [];
    for (const m of merged.filter((c) => c.n / total > 0.01).sort((a, b) => b.n - a.n)) {
      const anchors = backdrop ? [...kept, backdrop.rgb] : kept;
      const blend = anchors.some((a, i) => anchors.slice(i + 1).some((b) => toSegment(m.rgb, a, b) < 26));
      if (!blend) kept.push(m.rgb);
      if (kept.length === max) break;
    }
    const colors = kept.map(toHex);
    return { colors, background: backdrop ? toHex(backdrop.rgb) : null };
  } finally {
    if (typeof source !== "string") URL.revokeObjectURL(url);
  }
}

/** Brand colours from a palette: main = most used, second = next distinct, accent = the most vivid one left. */
export function paletteToKit(colors: string[], background: string | null) {
  if (!colors.length) return null;
  const primary = colors[0];
  const rest = colors.slice(1);
  const secondary = rest[0] ?? primary;
  const accent = [...rest.slice(1), secondary].sort((a, b) => saturation(fromHex(b)) - saturation(fromHex(a)))[0] ?? secondary;
  return { primary, secondary, accent, text: readableOn(primary), background: background ?? null };
}
