/**
 * The Stravica Social logo ("Layers": posts stacked in the publishing queue, the top one ready to go).
 *
 *   <BrandMark size={36} />                      the mark alone
 *   <BrandLogo />                                mark + "Stravica Social" wordmark
 *
 * Colours are fixed (the brand's pinks), so it reads on white and on the dark landing background alike.
 */
import { useId } from "react";

export function BrandMark({ size = 36, className }: { size?: number; className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg viewBox="10 8 80 80" width={size} height={size} role="img" aria-label="Stravica Social" className={`shrink-0 ${className ?? ""}`}>
      <defs>
        <linearGradient id={`${id}a`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#b3124f" /><stop offset="1" stopColor="#7d0a36" /></linearGradient>
        <linearGradient id={`${id}b`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#ff5c9d" /><stop offset="1" stopColor="#e0246f" /></linearGradient>
        <linearGradient id={`${id}c`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#ffc4dc" /><stop offset="1" stopColor="#ff7fb2" /></linearGradient>
      </defs>
      <rect x="14" y="12" width="48" height="48" rx="13" fill={`url(#${id}a)`} />
      <rect x="27.5" y="25.5" width="48" height="48" rx="13" fill="#000" opacity=".16" />
      <rect x="26" y="24" width="48" height="48" rx="13" fill={`url(#${id}b)`} />
      <rect x="39.5" y="37.5" width="48" height="48" rx="13" fill="#000" opacity=".16" />
      <rect x="38" y="36" width="48" height="48" rx="13" fill={`url(#${id}c)`} />
      <circle cx="51" cy="50" r="5.5" fill="#fff" />
      <rect x="60" y="46.5" width="17" height="7" rx="3.5" fill="#fff" />
      <rect x="46" y="62" width="31" height="7" rx="3.5" fill="#fff" opacity=".85" />
    </svg>
  );
}

export function BrandLogo({ size = 36, className }: { size?: number; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className ?? ""}`} dir="ltr">
      <BrandMark size={size} />
      <span className="text-[1.15em] tracking-tight"><b className="font-extrabold">Stravica</b> <span className="font-normal">Social</span></span>
    </span>
  );
}
