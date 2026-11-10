"use client";
import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { PricingTable } from "@/components/billing/pricing";
import { Icon, PlatformBadge } from "@/components/icon";
import { cx } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { usePlans } from "@/lib/billing";

const PLATFORMS = ["instagram", "tiktok", "facebook", "x", "linkedin", "threads", "telegram", "whatsapp"];
const FEATURES: { key: string; icon: string; wide?: boolean }[] = [
  { key: "studio", icon: "auto_awesome", wide: true },
  { key: "production", icon: "movie" },
  { key: "templates", icon: "photo_frame" },
  { key: "inbox", icon: "support_agent", wide: true },
  { key: "planning", icon: "calendar_today" },
  { key: "analytics", icon: "bar_chart" },
  { key: "mobile", icon: "smartphone" },
];
const FAQ = ["1", "2", "3", "4", "5", "6"];

function Logo() {
  return (
    <span className="flex items-center gap-2">
      <span className="flex h-8 w-8 items-center justify-center rounded-[10px] bg-white text-black">
        <Icon name="auto_awesome" size={18} duo />
      </span>
      <span className="whitespace-nowrap text-[15px] font-bold tracking-tight max-[380px]:hidden" dir="ltr">Stravica Social</span>
    </span>
  );
}

function Pill({ href, children, light = true, size = "md" }: { href: string; children: ReactNode; light?: boolean; size?: "md" | "lg" }) {
  return (
    <Link href={href}
      className={cx("inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full font-semibold transition active:scale-[.98]",
        size === "lg" ? "h-12 px-6 text-[15px]" : "h-9 px-4 text-sm",
        light ? "bg-white text-black shadow-[0_10px_30px_-10px_rgba(255,255,255,.5)] hover:bg-white/90" : "text-white ring-1 ring-white/20 hover:bg-white/10")}>
      {children}
    </Link>
  );
}

function SectionHead({ title, text }: { title: string; text?: string }) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <h2 className="text-[28px] font-bold leading-tight tracking-tight sm:text-4xl">{title}</h2>
      {text && <p className="mt-3 text-[15px] leading-relaxed text-white/60">{text}</p>}
    </div>
  );
}

function HeroPreview() {
  const t = useTranslations("landing.preview");
  return (
    <div className="relative mx-auto mt-14 grid max-w-5xl grid-cols-1 gap-4 text-start md:grid-cols-[1fr_1.45fr_1fr] md:items-center">
      <div aria-hidden className="pointer-events-none absolute inset-x-10 -top-10 bottom-0 rounded-full bg-white/10 blur-3xl" />
      {/* inbox assistant */}
      <div className="relative order-2 rounded-[22px] bg-white/[.06] p-4 ring-1 ring-white/10 backdrop-blur-xl md:order-1 md:-rotate-2">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-white/70">
          <Icon name="support_agent" size={16} duo /> {t("inbox")}
        </div>
        <div className="flex items-end gap-2">
          <PlatformBadge platform="instagram" size={22} />
          <p className="bidi rounded-2xl rounded-es-md bg-white/10 px-3 py-2 text-[13px]">{t("question")}</p>
        </div>
        <div className="mt-2 flex items-end justify-end gap-2">
          <p className="bidi rounded-2xl rounded-ee-md bg-white px-3 py-2 text-[13px] font-medium text-black">{t("answer")}</p>
          <span className="flex h-[22px] w-[22px] items-center justify-center rounded-full bg-white/15"><Icon name="smart_toy" size={13} /></span>
        </div>
      </div>
      {/* studio */}
      <div className="relative order-1 rounded-[26px] bg-white/[.08] p-4 ring-1 ring-white/15 backdrop-blur-2xl shadow-[0_40px_120px_-40px_rgba(255,255,255,.25)] md:order-2 sm:p-5">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-white/70">
          <Icon name="auto_awesome" size={16} duo /> {t("studio")}
          <span className="ms-auto flex gap-1">{["instagram", "tiktok", "x"].map((p) => <PlatformBadge key={p} platform={p} size={20} />)}</span>
        </div>
        <div className="flex items-center gap-2 rounded-2xl bg-black/40 px-3 py-2.5 text-[13px] text-white/70 ring-1 ring-white/10">
          <Icon name="wand_stars" size={16} className="text-white" />
          <span className="bidi truncate">{t("prompt")}</span>
        </div>
        <div className="mt-3 grid grid-cols-[88px_1fr] gap-3 sm:grid-cols-[112px_1fr]">
          <div className="relative aspect-[4/5] overflow-hidden rounded-2xl bg-[radial-gradient(circle_at_30%_20%,#f5e6d3,#8a6a4f_55%,#2b2018)]">
            <span className="absolute bottom-2 start-2 rounded-full bg-black/50 px-2 py-0.5 text-[10px] backdrop-blur" dir="ltr">4:5</span>
          </div>
          <div className="flex min-w-0 flex-col">
            <p className="bidi text-[14px] font-medium leading-relaxed">{t("caption")}</p>
            <p className="bidi mt-1 truncate text-[12px] text-white/50">#رمضان #قهوة_مختصة</p>
            <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-3">
              <span className="inline-flex items-center gap-1 rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-black">
                <Icon name="schedule" size={12} /> {t("scheduled")}
              </span>
              <span className="inline-flex items-center gap-1 rounded-full bg-white/10 px-2.5 py-1 text-[11px] text-white/80">
                <Icon name="bolt" size={12} /> {t("best")}
              </span>
            </div>
          </div>
        </div>
      </div>
      {/* analytics */}
      <div className="relative order-3 rounded-[22px] bg-white/[.06] p-4 ring-1 ring-white/10 backdrop-blur-xl md:rotate-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-white/70"><Icon name="trending_up" size={16} /> {t("reach")}</div>
        <div className="mt-1 text-2xl font-bold tracking-tight" dir="ltr">128.4K</div>
        <svg viewBox="0 0 120 36" className="mt-2 h-10 w-full" aria-hidden preserveAspectRatio="none">
          <path d="M0 30 C 15 28, 22 22, 35 24 S 55 14, 68 16 S 92 6, 104 8 L 120 3" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" />
        </svg>
        <div className="mt-3 flex items-center gap-2 border-t border-white/10 pt-3">
          <Icon name="shopping_cart" size={16} className="text-white/70" />
          <span className="text-xs text-white/60">{t("sales")}</span>
          <span className="ms-auto text-sm font-bold" dir="ltr">SAR 12,480</span>
        </div>
      </div>
    </div>
  );
}

export function Landing() {
  const t = useTranslations("landing");
  const tb = useTranslations("billing");
  const locale = useLocale();
  const other = locale === "ar" ? "en" : "ar";
  const plans = usePlans();
  const days = plans.data?.trial_days ?? 14;
  const me = useQuery({ queryKey: ["landing-me"], queryFn: () => api.get("/auth/me"), retry: false, staleTime: 300_000 });
  const signedIn = me.isSuccess;

  return (
    <div className="relative min-h-screen overflow-x-clip bg-[#050505] text-white">
      {/* backdrop */}
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-40 start-1/2 h-[640px] w-[1100px] -translate-x-1/2 rounded-full bg-[radial-gradient(closest-side,rgba(255,255,255,.14),transparent)] rtl:translate-x-1/2" />
        <div className="absolute top-[1200px] -start-40 h-[520px] w-[520px] rounded-full bg-[radial-gradient(closest-side,rgba(148,163,184,.12),transparent)]" />
        <div className="absolute top-[2400px] -end-40 h-[620px] w-[620px] rounded-full bg-[radial-gradient(closest-side,rgba(214,211,209,.10),transparent)]" />
        <div className="absolute inset-x-0 top-0 h-[900px] bg-[linear-gradient(rgba(255,255,255,.035)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.035)_1px,transparent_1px)] bg-[size:56px_56px] [mask-image:radial-gradient(ellipse_at_top,black,transparent_70%)]" />
      </div>

      {/* nav */}
      <header className="sticky top-3 z-40 px-3">
        <nav className="mx-auto flex h-14 max-w-6xl items-center gap-2 rounded-full bg-black/55 ps-3 pe-2 sm:ps-4 ring-1 ring-white/10 backdrop-blur-xl">
          <Link href="/welcome"><Logo /></Link>
          <div className="ms-6 hidden items-center gap-1 text-sm text-white/70 md:flex">
            <a href="#features" className="rounded-full px-3 py-1.5 hover:bg-white/10 hover:text-white">{t("nav.features")}</a>
            <a href="#pricing" className="rounded-full px-3 py-1.5 hover:bg-white/10 hover:text-white">{t("nav.pricing")}</a>
            <a href="#faq" className="rounded-full px-3 py-1.5 hover:bg-white/10 hover:text-white">{t("nav.faq")}</a>
          </div>
          <div className="ms-auto flex items-center gap-1">
            <Link href="/welcome" locale={other} className="hidden h-9 items-center rounded-full px-3 text-sm text-white/70 hover:bg-white/10 hover:text-white sm:inline-flex">
              {other === "ar" ? "العربية" : "English"}
            </Link>
            {signedIn ? (
              <Pill href="/">{t("nav.app")}</Pill>
            ) : (
              <>
                <Link href="/login" className="inline-flex h-9 items-center whitespace-nowrap rounded-full px-2.5 sm:px-3 text-sm text-white/80 hover:bg-white/10 hover:text-white">{t("nav.login")}</Link>
                <Pill href="/signup">{t("nav.signup")}</Pill>
              </>
            )}
          </div>
        </nav>
      </header>

      <main className="relative">
        {/* hero */}
        <section className="mx-auto max-w-6xl px-4 pb-16 pt-14 text-center sm:pt-24">
          <span className="inline-flex items-center gap-2 rounded-full bg-white/[.06] px-3 py-1.5 text-xs font-medium text-white/80 ring-1 ring-white/10 backdrop-blur">
            <span className="h-1.5 w-1.5 rounded-full bg-white shadow-[0_0_10px_white]" /> {t("badge")}
          </span>
          <h1 className="mx-auto mt-6 max-w-4xl text-[38px] font-bold leading-[1.15] tracking-tight sm:text-6xl sm:leading-[1.08]">
            {t("heroTitle")}{" "}
            <span className="bg-gradient-to-b from-white to-white/45 bg-clip-text text-transparent">{t("heroHighlight")}</span>
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-[15px] leading-relaxed text-white/60 sm:text-lg">{t("heroText")}</p>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Pill href="/signup" size="lg">{t("ctaPrimary", { days })} <Icon name="arrow_back" size={18} className="ltr:rotate-180" /></Pill>
            <a href="#pricing" className="inline-flex h-12 items-center rounded-full px-6 text-[15px] font-semibold text-white ring-1 ring-white/20 hover:bg-white/10">{t("ctaSecondary")}</a>
          </div>
          <p className="mt-4 text-xs text-white/45">{t("trust")}</p>
          <HeroPreview />
        </section>

        {/* platforms */}
        <section className="mx-auto max-w-6xl px-4 py-10 text-center">
          <p className="text-sm text-white/50">{t("platformsTitle")}</p>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-3" dir="ltr">
            {PLATFORMS.map((p) => (
              <span key={p} className="rounded-2xl bg-white/[.05] p-2 ring-1 ring-white/10"><PlatformBadge platform={p} size={34} /></span>
            ))}
          </div>
        </section>

        {/* features */}
        <section id="features" className="mx-auto max-w-6xl scroll-mt-24 px-4 py-16 sm:py-24">
          <SectionHead title={t("featuresTitle")} text={t("featuresText")} />
          <div className="mt-12 grid grid-cols-1 gap-4 md:grid-cols-3">
            {FEATURES.map((f) => (
              <article key={f.key}
                className={cx("group relative overflow-hidden rounded-[24px] bg-white/[.04] p-6 ring-1 ring-white/10 backdrop-blur-xl transition hover:bg-white/[.07]",
                  f.wide && "md:col-span-2")}>
                <div aria-hidden className="pointer-events-none absolute -end-16 -top-16 h-48 w-48 rounded-full bg-white/10 opacity-0 blur-3xl transition group-hover:opacity-100" />
                <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white text-black shadow-[0_10px_30px_-12px_rgba(255,255,255,.6)]">
                  <Icon name={f.icon} size={22} duo />
                </span>
                <h3 className="mt-5 text-lg font-semibold tracking-tight">{t(`features.${f.key}.title`)}</h3>
                <p className="mt-2 max-w-xl text-sm leading-relaxed text-white/60">{t(`features.${f.key}.text`)}</p>
              </article>
            ))}
          </div>
        </section>

        {/* steps */}
        <section className="mx-auto max-w-6xl px-4 pb-16 sm:pb-24">
          <SectionHead title={t("stepsTitle")} />
          <ol className="mt-10 grid grid-cols-1 gap-4 md:grid-cols-3">
            {["1", "2", "3"].map((n) => (
              <li key={n} className="flex gap-4 rounded-[22px] p-5 ring-1 ring-white/10">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/10 text-sm font-bold" dir="ltr">{n}</span>
                <div>
                  <h3 className="font-semibold">{t(`steps.${n}.title`)}</h3>
                  <p className="mt-1 text-sm leading-relaxed text-white/55">{t(`steps.${n}.text`)}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        {/* pricing */}
        <section id="pricing" className="mx-auto max-w-6xl scroll-mt-24 px-4 py-16 sm:py-24">
          <SectionHead title={t("pricingTitle")} text={t("pricingText", { days })} />
          <div className="mt-10">
            <PricingTable
              tone="dark"
              action={(plan) =>
                plan.self_service ? (
                  <Link href={`/signup?plan=${plan.code}`}
                    className={cx("flex h-11 w-full items-center justify-center rounded-full text-sm font-semibold transition",
                      plan.highlight ? "bg-black text-white hover:bg-black/85" : "bg-white text-black hover:bg-white/90")}>
                    {tb("startTrial")}
                  </Link>
                ) : (
                  <a href={`mailto:${tb("contactEmail")}`} className="flex h-11 w-full items-center justify-center rounded-full text-sm font-semibold text-white ring-1 ring-white/25 hover:bg-white/10">
                    {tb("contactSales")}
                  </a>
                )
              }
            />
          </div>
        </section>

        {/* faq */}
        <section id="faq" className="mx-auto max-w-3xl scroll-mt-24 px-4 py-16 sm:py-24">
          <SectionHead title={t("faqTitle")} />
          <div className="mt-10 flex flex-col gap-3">
            {FAQ.map((n) => (
              <details key={n} className="group rounded-[20px] bg-white/[.04] ring-1 ring-white/10 open:bg-white/[.07]">
                <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-4 text-[15px] font-semibold [&::-webkit-details-marker]:hidden">
                  <span className="flex-1">{t(`faq.q${n}`)}</span>
                  <Icon name="add" size={18} className="shrink-0 text-white/60 transition group-open:rotate-45" />
                </summary>
                <p className="px-5 pb-5 text-sm leading-relaxed text-white/60">{t(`faq.a${n}`, { days })}</p>
              </details>
            ))}
          </div>
        </section>

        {/* final CTA */}
        <section className="mx-auto max-w-6xl px-4 pb-20">
          <div className="relative overflow-hidden rounded-[32px] bg-white/[.06] px-6 py-14 text-center ring-1 ring-white/15 backdrop-blur-2xl sm:py-20">
            <div aria-hidden className="pointer-events-none absolute -top-24 start-1/2 h-64 w-[700px] -translate-x-1/2 rounded-full bg-white/15 blur-3xl rtl:translate-x-1/2" />
            <h2 className="relative text-[28px] font-bold tracking-tight sm:text-4xl">{t("finalTitle")}</h2>
            <p className="relative mx-auto mt-3 max-w-xl text-white/60">{t("finalText")}</p>
            <div className="relative mt-8 flex justify-center">
              <Pill href="/signup" size="lg">{t("ctaPrimary", { days })}</Pill>
            </div>
          </div>
        </section>
      </main>

      <footer className="relative border-t border-white/10">
        <div className="mx-auto flex max-w-6xl flex-col items-center gap-3 px-4 py-8 text-xs text-white/45 sm:flex-row">
          <Logo />
          <span className="sm:ms-4">{t("footer.madeFor")}</span>
          <span className="sm:ms-auto">{t("footer.rights", { year: new Date().getFullYear() })}</span>
        </div>
      </footer>
    </div>
  );
}
