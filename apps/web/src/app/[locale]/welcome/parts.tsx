"use client";
import gsap from "gsap";
import { useEffect, useRef, useState, type ElementType, type ReactNode } from "react";
import { BrandMark } from "@/components/brand-mark";
import { cx } from "@/components/ui";
import type { StarHandle, StarVariant } from "./star-scene";

export const ACCENT = "#ff3d8b";

/* ---------------------------------------------------------------------------------------------
 * Text that rises word by word out of a mask. Split on spaces only, so Arabic letters stay joined.
 * ------------------------------------------------------------------------------------------- */
export function Words({ text, className }: { text: string; className?: string }) {
  const parts = text.split(/(\s+)/);
  return (
    <>
      {parts.map((p, i) =>
        /^\s+$/.test(p) || !p ? (
          p
        ) : (
          <span key={i} className="lx-w">
            <span className={cx("lx-wi", className)}>{p}</span>
          </span>
        ),
      )}
    </>
  );
}

/** Two-voice heading: heavy display line + light serif line (the accent colour on dark sections). */
export function Title({
  a, b, as: Tag = "h2", className, serifClass, id,
}: { a: string; b: string; as?: ElementType; className?: string; serifClass?: string; id?: string }) {
  return (
    <Tag id={id} data-reveal="words" className={cx("lx-display", className)}>
      <span className="block"><Words text={a} /></span>
      <span className="block"><Words text={b} className={cx("lx-serif", serifClass)} /></span>
    </Tag>
  );
}

/** Manifesto paragraph: "<hl>…</hl>" marks the words set in the serif accent voice. */
export function ScrubWords({ raw, className }: { raw: string; className?: string }) {
  // Words are groups of pieces so punctuation right after a highlighted word ("أذكى،") stays attached to it.
  const words: { t: string; hl: boolean }[][] = [];
  let openEnd = true; // did the previous segment end with a space?
  raw.split(/(<hl>.*?<\/hl>)/).filter(Boolean).forEach((seg) => {
    const hl = seg.startsWith("<hl>");
    const text = seg.replace(/<\/?hl>/g, "");
    const glued = words.length > 0 && !openEnd && !/^\s/.test(text);
    text.split(/\s+/).filter(Boolean).forEach((w, i) => {
      if (i === 0 && glued) words[words.length - 1].push({ t: w, hl });
      else words.push([{ t: w, hl }]);
    });
    openEnd = /\s$/.test(text);
  });
  return (
    <p data-scrub="words" className={className}>
      {words.map((pieces, i) => (
        <span key={i}>
          <span className="lx-sw">
            {pieces.map((pc, j) => <span key={j} className={pc.hl ? "lx-serif" : undefined}>{pc.t}</span>)}
          </span>{" "}
        </span>
      ))}
    </p>
  );
}

export function Kicker({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={cx("lx-kicker", className)}>
      <span className="lx-kicker-dot" aria-hidden /> {children}
    </span>
  );
}

/* ---------------------------------------------------------------------------------------------
 * Topographic contour lines, drawn on the client only (keeps the HTML light).
 * ------------------------------------------------------------------------------------------- */
function rng(seed: number) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function contourSvg(seed: number) {
  const W = 1600;
  const H = 1000;
  const r = rng(seed);
  const centers = [[W * (0.1 + r() * 0.2), H * (0.2 + r() * 0.3)], [W * (0.7 + r() * 0.2), H * (0.6 + r() * 0.3)], [W * (0.45 + r() * 0.2), H * (-0.1 + r() * 0.2)]];
  let d = "";
  for (const [cx0, cy0] of centers) {
    const ph = [r() * 6.28, r() * 6.28, r() * 6.28];
    const amp = [0.14 + r() * 0.1, 0.07 + r() * 0.05, 0.04 + r() * 0.03];
    for (let i = 1; i <= 9; i++) {
      const base = 46 * Math.pow(i, 1.18);
      const pts: [number, number][] = [];
      const N = 40;
      for (let k = 0; k < N; k++) {
        const th = (k / N) * Math.PI * 2;
        const rr = base * (1 + amp[0] * Math.sin(2 * th + ph[0] + i * 0.22) + amp[1] * Math.sin(3 * th + ph[1] - i * 0.17) + amp[2] * Math.sin(5 * th + ph[2] + i * 0.11));
        pts.push([cx0 + Math.cos(th) * rr * 1.25, cy0 + Math.sin(th) * rr]);
      }
      const mid = (a: [number, number], b: [number, number]) => `${((a[0] + b[0]) / 2).toFixed(0)} ${((a[1] + b[1]) / 2).toFixed(0)}`;
      d += `M${mid(pts[N - 1], pts[0])}`;
      for (let k = 0; k < N; k++) d += `Q${pts[k][0].toFixed(0)} ${pts[k][1].toFixed(0)} ${mid(pts[k], pts[(k + 1) % N])}`;
    }
  }
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid slice" width="100%" height="100%"><path d="${d}" fill="none" stroke="currentColor" stroke-width="1" vector-effect="non-scaling-stroke"/></svg>`;
}

export function Contours({ seed, className }: { seed: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.innerHTML = contourSvg(seed);
  }, [seed]);
  return <div ref={ref} aria-hidden className={cx("lx-contours", className)} />;
}

/* ---------------------------------------------------------------------------------------------
 * Hand-drawn neon strokes (drawn in by GSAP through stroke-dashoffset).
 * ------------------------------------------------------------------------------------------- */
export function Scribble({ kind, className }: { kind: "hero" | "line"; className?: string }) {
  if (kind === "hero") {
    return (
      <svg data-scribble="hero" viewBox="0 0 640 360" className={cx("lx-scribble", className)} aria-hidden fill="none">
        <path pathLength={1} d="M28 300 C 96 252, 150 168, 214 118 C 262 80, 326 70, 334 122 C 342 172, 276 214, 244 182 C 212 150, 262 88, 344 88 C 436 88, 470 182, 544 170 C 594 162, 616 120, 626 92" />
      </svg>
    );
  }
  return (
    <svg data-scribble="line" viewBox="0 0 400 40" preserveAspectRatio="none" className={cx("lx-scribble lx-scribble-line", className)} aria-hidden fill="none">
      <path pathLength={1} d="M6 26 C 90 10, 170 34, 250 18 S 360 14, 394 24" />
    </svg>
  );
}

/* ---------------------------------------------------------------------------------------------
 * Endless rows. Content is rendered twice so the -50% loop is seamless.
 * ------------------------------------------------------------------------------------------- */
export function MarqueeRow({ children, rev, duration, className }: { children: ReactNode; rev?: boolean; duration?: number; className?: string }) {
  return (
    <div data-marquee={rev ? "rev" : ""} data-duration={duration} className={cx("lx-mq", className)} dir="ltr">
      <div className="lx-mq-track">
        <div className="lx-mq-set">{children}</div>
        <div className="lx-mq-set" aria-hidden>{children}</div>
      </div>
    </div>
  );
}

/** Block transition: accent squares, then the next section's colour, fill the band in random order. */
export function Pixels({ cols = 14, rows = 4 }: { cols?: number; rows?: number }) {
  return (
    <div data-pixels aria-hidden className="lx-pixels" style={{ ["--cols" as string]: cols }}>
      {Array.from({ length: cols * rows }, (_, i) => (
        <i key={i}><b className="lx-px-a" /><b className="lx-px-b" /></i>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------------------------------------
 * The 3D sparkle. three.js is loaded only when this mounts; a flat SVG stands in without WebGL.
 * ------------------------------------------------------------------------------------------- */
export function StarCanvas({ variant, reduce, className }: { variant: StarVariant; reduce: boolean; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let handle: StarHandle | null = null;
    let dead = false;
    import("./star-scene").then((m) => {
      if (dead || !ref.current) return;
      handle = m.mountStar(ref.current, { variant, accent: ACCENT, reduce });
      if (!handle) setFailed(true);
    }).catch(() => setFailed(true));
    return () => {
      dead = true;
      handle?.dispose();
    };
  }, [variant, reduce]);
  return (
    <div aria-hidden className={cx("lx-star", className)}>
      <div className="lx-star-glow" />
      {failed ? <StarFallback /> : <canvas ref={ref} className="lx-star-canvas" />}
    </div>
  );
}

function StarFallback() {
  return <span className="lx-star-fallback flex items-center justify-center"><BrandMark size={260} /></span>;
}

/* ---------------------------------------------------------------------------------------------
 * Cursor ring that follows the pointer and opens up over anything clickable (mouse only).
 * ------------------------------------------------------------------------------------------- */
export function Cursor({ reduce }: { reduce: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || reduce || !window.matchMedia("(pointer: fine)").matches) return;
    const xTo = gsap.quickTo(el, "x", { duration: 0.45, ease: "power3" });
    const yTo = gsap.quickTo(el, "y", { duration: 0.45, ease: "power3" });
    const label = el.querySelector("span");
    const move = (e: PointerEvent) => {
      el.dataset.on = "1";
      xTo(e.clientX);
      yTo(e.clientY);
    };
    const over = (e: PointerEvent) => {
      const t = (e.target as HTMLElement).closest<HTMLElement>("a, button, summary, [data-cursor]");
      el.dataset.hover = t ? "1" : "";
      if (label) label.textContent = t?.dataset.cursor || "";
      el.dataset.label = t?.dataset.cursor ? "1" : "";
    };
    const out = () => { el.dataset.on = ""; };
    window.addEventListener("pointermove", move, { passive: true });
    window.addEventListener("pointerover", over, { passive: true });
    document.addEventListener("pointerleave", out);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerover", over);
      document.removeEventListener("pointerleave", out);
    };
  }, [reduce]);
  return <div ref={ref} aria-hidden className="lx-cursor"><span /></div>;
}

/* ---------------------------------------------------------------------------------------------
 * Small pieces of the identity.
 * ------------------------------------------------------------------------------------------- */
export function Logo({ className }: { className?: string }) {
  return (
    <span className={cx("lx-logo", className)}>
      <BrandMark size={36} />
      <span className="lx-logo-word" dir="ltr">Stravica<b>Social</b></span>
    </span>
  );
}

export function Arrow({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden className={cx("lx-arrow", className)} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M7 17 17 7M8 7h9v9" />
    </svg>
  );
}

export function Loader({ label }: { label: string }) {
  return (
    <div data-loader className="lx-loader" role="status" aria-label={label}>
      <div data-loader-inner className="lx-loader-inner">
        <Logo />
        <span data-count className="lx-loader-count" dir="ltr">000</span>
        <span className="lx-loader-bar"><i data-bar /></span>
      </div>
    </div>
  );
}
