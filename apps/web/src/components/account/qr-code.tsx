"use client";
import { useMemo } from "react";
import { qrMatrix } from "@/lib/qr";

/** A QR code drawn as SVG (black on white with the quiet zone readers need). */
export function QrCode({ value, size = 184, label }: { value: string; size?: number; label?: string }) {
  const rows = useMemo(() => qrMatrix(value), [value]);
  const n = rows.length + 8;
  const path = rows.flatMap((row, y) => row.map((dark, x) => (dark ? `M${x + 4} ${y + 4}h1v1h-1z` : ""))).join("");
  return (
    <svg role="img" aria-label={label} width={size} height={size} viewBox={`0 0 ${n} ${n}`} shapeRendering="crispEdges" className="rounded-xl">
      <rect width={n} height={n} fill="#fff" />
      <path d={path} fill="#000" />
    </svg>
  );
}
