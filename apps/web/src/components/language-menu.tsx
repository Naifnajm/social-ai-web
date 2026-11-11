"use client";
/**
 * Language picker: a button with the current language and a small list of all of them.
 *
 *   <LanguageMenu />                      links to the same page in the chosen language
 *   <LanguageMenu href="/welcome" />      links to a fixed page instead
 *   <LanguageMenu onPick={(code) => …} /> also run something first (the app saves the choice on the account)
 *   <LanguageLinks />                     all the other languages as plain links, for footers and menus
 */
import { useLocale } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { Link, usePathname } from "@/i18n/navigation";
import { LOCALE_NAMES, routing, type Locale } from "@/i18n/routing";

function Globe({ size = 16 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden className="shrink-0">
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.6 2.5 3.9 5.5 3.9 9s-1.3 6.5-3.9 9c-2.6-2.5-3.9-5.5-3.9-9S9.4 5.5 12 3z" />
    </svg>
  );
}

export function LanguageMenu({ href, onPick, className = "", up = false }: {
  href?: string; onPick?: (locale: Locale) => void; className?: string; up?: boolean;
}) {
  const locale = useLocale() as Locale;
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);

  return (
    <div ref={root} className="relative inline-flex">
      <button type="button" onClick={() => setOpen(!open)} aria-haspopup="listbox" aria-expanded={open}
        className={`inline-flex items-center gap-1.5 ${className}`}>
        <Globe /> <span>{LOCALE_NAMES[locale]}</span>
      </button>
      {open && (
        <ul role="listbox" className={`pop-in absolute end-0 z-[70] min-w-[168px] rounded-2xl bg-white p-1.5 text-[14px] font-medium text-[#111] shadow-[0_18px_50px_-12px_rgba(0,0,0,.35)] ring-1 ring-black/10 ${up ? "bottom-full mb-2" : "top-full mt-2"}`}>
          {routing.locales.map((code) => (
            <li key={code} role="option" aria-selected={code === locale}>
              <Link href={href ?? pathname} locale={code} lang={code} onClick={() => { setOpen(false); onPick?.(code); }}
                className={`flex items-center justify-between gap-3 rounded-xl px-3 py-2 hover:bg-black/[.05] ${code === locale ? "text-[#e0246f]" : ""}`}>
                <span>{LOCALE_NAMES[code]}</span>
                <span className="text-[11px] uppercase tracking-wide opacity-50" dir="ltr">{code}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function LanguageLinks({ href, className = "", onPick }: { href?: string; className?: string; onPick?: (locale: Locale) => void }) {
  const locale = useLocale();
  const pathname = usePathname();
  return (
    <>
      {routing.locales.filter((code) => code !== locale).map((code) => (
        <Link key={code} href={href ?? pathname} locale={code} lang={code} className={className} onClick={() => onPick?.(code)}>{LOCALE_NAMES[code]}</Link>
      ))}
    </>
  );
}
