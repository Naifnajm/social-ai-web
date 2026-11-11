/**
 * Sign-in, sign-up and password pages: the form on one half, a brand panel with a real screenshot on the other.
 * The form comes first in the markup, so it sits on the right in Arabic and on the left in English.
 */
import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { BrandLogo } from "@/components/brand-mark";
import { Icon, PlatformIcon } from "@/components/icon";
import { Link } from "@/i18n/navigation";
import { shotLocale } from "@/i18n/routing";
import { LocaleSwitch } from "./locale-switch";

const PLATFORMS = ["instagram", "tiktok", "x", "facebook", "linkedin", "whatsapp"];

export default function AuthLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("auth");
  const locale = useLocale();
  return (
    <div className="grid min-h-screen bg-white lg:grid-cols-[minmax(0,1fr)_minmax(0,1.08fr)]">
      <div className="flex min-h-screen flex-col px-5 py-6 sm:px-10 sm:py-8">
        <header className="flex items-center justify-between">
          <Link href="/welcome" className="text-[15px]"><BrandLogo size={34} /></Link>
          <LocaleSwitch />
        </header>
        <main className="flex flex-1 items-center justify-center py-10">
          <div className="w-full max-w-[400px]">{children}</div>
        </main>
        <p className="text-center text-xs text-faint" dir="ltr">© {new Date().getFullYear()} Stravica Social</p>
      </div>

      <aside className="relative m-3 hidden overflow-hidden rounded-[32px] bg-[#0b0b0e] text-white lg:flex lg:flex-col" aria-hidden>
        <div className="pointer-events-none absolute -top-40 end-[-10%] h-[520px] w-[520px] rounded-full bg-[radial-gradient(closest-side,rgba(255,61,139,.42),transparent)]" />
        <div className="pointer-events-none absolute bottom-[-30%] start-[-15%] h-[620px] w-[620px] rounded-full bg-[radial-gradient(closest-side,rgba(143,123,255,.22),transparent)]" />
        <svg className="pointer-events-none absolute inset-0 h-full w-full opacity-[.07]" viewBox="0 0 600 800" preserveAspectRatio="none" fill="none" stroke="#fff">
          {[0, 1, 2, 3, 4, 5].map((i) => <path key={i} d={`M-50 ${120 + i * 130} C 150 ${40 + i * 130}, 350 ${220 + i * 130}, 650 ${90 + i * 130}`} />)}
        </svg>

        <div className="relative px-12 pt-14 xl:px-16 xl:pt-16">
          <span className="inline-flex items-center gap-2 rounded-full bg-white/[.08] px-3 py-1.5 text-xs font-semibold ring-1 ring-white/10">
            <span className="h-1.5 w-1.5 rounded-full bg-[#ff3d8b] shadow-[0_0_10px_#ff3d8b]" />{t("panelKicker")}
          </span>
          <h2 className="mt-6 max-w-[15ch] text-[clamp(34px,3.4vw,52px)] font-bold leading-[1.12] tracking-tight">
            {t("panelTitle")} <span className="text-[#ff5c9d]">{t("panelHighlight")}</span>
          </h2>
          <p className="mt-4 max-w-[44ch] text-[15px] leading-relaxed text-white/60">{t("panelText")}</p>
          <div className="mt-6 flex items-center gap-2">
            {PLATFORMS.map((p) => (
              <span key={p} className="flex h-9 w-9 items-center justify-center rounded-full bg-white/[.08] ring-1 ring-white/10"><PlatformIcon platform={p} size={16} /></span>
            ))}
          </div>
        </div>

        <div className="relative mt-10 flex-1">
          <div className="absolute inset-x-12 top-0 xl:inset-x-16">
            <div className="relative rotate-[-1.5deg] overflow-hidden rounded-[18px] bg-white shadow-[0_40px_120px_-30px_rgba(255,61,139,.55)] ring-1 ring-white/20 rtl:rotate-[1.5deg]">
              <div className="flex items-center gap-1.5 bg-[#f4f4f5] px-3.5 py-2.5" dir="ltr">
                {["#ff5f57", "#febc2e", "#28c840"].map((c) => <span key={c} className="h-2.5 w-2.5 rounded-full" style={{ background: c }} />)}
              </div>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`/landing/shots/${shotLocale(locale)}/planning.webp`} alt="" width={1040} height={780} className="block w-full" />
            </div>
            <div className="absolute -start-6 top-[38%] flex items-center gap-2.5 rounded-2xl bg-white px-3.5 py-2.5 text-[13px] font-semibold text-black shadow-[0_20px_50px_-15px_rgba(0,0,0,.6)]">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#ff3d8b] text-white"><Icon name="check" size={16} /></span>
              {t("panelChipPublished")}
            </div>
            <div className="absolute -end-5 top-[12%] flex items-center gap-2.5 rounded-2xl bg-[#18181b] px-3.5 py-2.5 text-[13px] font-semibold shadow-[0_20px_50px_-15px_rgba(0,0,0,.7)] ring-1 ring-white/10">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-white/10"><Icon name="support_agent" size={16} /></span>
              {t("panelChipReplied")}
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
