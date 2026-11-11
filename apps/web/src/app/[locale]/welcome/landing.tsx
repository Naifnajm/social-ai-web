"use client";
import "@fontsource-variable/archivo/wdth.css";
import "@fontsource/alexandria/500.css";
import "@fontsource/alexandria/800.css";
import "@fontsource/ibm-plex-sans-arabic/300.css";
import "@fontsource/ibm-plex-sans-arabic/400.css";
import "@fontsource/instrument-serif/400.css";
import "@fontsource/instrument-serif/400-italic.css";
import "lenis/dist/lenis.css";
import "./landing.css";

import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { PricingTable } from "@/components/billing/pricing";
import { Icon, PlatformBadge, PlatformIcon } from "@/components/icon";
import { LanguageLinks, LanguageMenu } from "@/components/language-menu";
import { cx } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { shotLocale } from "@/i18n/routing";
import { api } from "@/lib/api";
import { usePlans } from "@/lib/billing";
import { scroller, setupLanding } from "./motion";
import {
  Arrow, Contours, Cursor, Kicker, Loader, Logo, MarqueeRow, Pixels, Scribble, ScrubWords, StarCanvas, Title, Words,
} from "./parts";

const PLATFORMS = ["instagram", "tiktok", "facebook", "x", "linkedin", "threads", "telegram", "whatsapp"];
const PLATFORM_NAMES: Record<string, string> = {
  instagram: "Instagram", tiktok: "TikTok", facebook: "Facebook", x: "X", linkedin: "LinkedIn", threads: "Threads", telegram: "Telegram", whatsapp: "WhatsApp",
};
const FEATURES: { key: string; icon: string }[] = [
  { key: "studio", icon: "auto_awesome" },
  { key: "production", icon: "movie" },
  { key: "templates", icon: "photo_frame" },
  { key: "inbox", icon: "support_agent" },
  { key: "planning", icon: "calendar_today" },
  { key: "analytics", icon: "bar_chart" },
  { key: "mobile", icon: "smartphone" },
];
const FAQ = ["1", "2", "3", "4", "5", "6"];

function useReducedMotion() {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => false,
  );
}

/** The logo's three tiles in one colour: the separator between marquee items. */
function Spark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={cx("lx-mq-sep", className)} fill="currentColor">
      <rect x="1" y="1" width="14" height="14" rx="4.2" opacity=".35" />
      <rect x="5" y="5" width="14" height="14" rx="4.2" opacity=".6" />
      <rect x="9" y="9" width="14" height="14" rx="4.2" />
    </svg>
  );
}

/* ---------------------------------------------------------------------------------------------
 * Product glimpses (same content as before, now dark cards floating on paper).
 * ------------------------------------------------------------------------------------------- */
function InboxCard() {
  const t = useTranslations("landing.preview");
  return (
    <div className="lx-card-dark p-4">
      <div className="mb-3 flex items-center gap-2 text-xs font-semibold opacity-70"><Icon name="support_agent" size={16} duo /> {t("inbox")}</div>
      <div className="flex items-end gap-2">
        <PlatformBadge platform="instagram" size={22} />
        <p className="bidi rounded-2xl rounded-es-md bg-white/10 px-3 py-2 text-[13px]">{t("question")}</p>
      </div>
      <div className="mt-2 flex items-end justify-end gap-2">
        <p className="bidi rounded-2xl rounded-ee-md px-3 py-2 text-[13px] font-semibold" style={{ background: "var(--accent)", color: "var(--on-accent)" }}>{t("answer")}</p>
        <span className="flex h-[22px] w-[22px] items-center justify-center rounded-full bg-white/15"><Icon name="smart_toy" size={13} /></span>
      </div>
    </div>
  );
}

function StudioCard() {
  const t = useTranslations("landing.preview");
  return (
    <div className="lx-card-dark p-4 sm:p-5">
      <div className="mb-3 flex items-center gap-2 text-xs font-semibold opacity-70">
        <Icon name="auto_awesome" size={16} duo /> {t("studio")}
        <span className="ms-auto flex gap-1">{["instagram", "tiktok", "x"].map((p) => <PlatformBadge key={p} platform={p} size={20} />)}</span>
      </div>
      <div className="flex items-center gap-2 rounded-2xl bg-black/40 px-3 py-2.5 text-[13px] ring-1 ring-white/10">
        <Icon name="wand_stars" size={16} className="text-[var(--accent)]" />
        <span className="bidi truncate opacity-75">{t("prompt")}</span>
      </div>
      <div className="mt-3 grid grid-cols-[96px_1fr] gap-3 sm:grid-cols-[128px_1fr]">
        <div className="relative aspect-[4/5] overflow-hidden rounded-2xl bg-[radial-gradient(circle_at_30%_20%,#f5e6d3,#8a6a4f_55%,#2b2018)]">
          <span className="absolute bottom-2 start-2 rounded-full bg-black/50 px-2 py-0.5 text-[10px] backdrop-blur" dir="ltr">4:5</span>
        </div>
        <div className="flex min-w-0 flex-col">
          <p className="bidi text-[14px] font-medium leading-relaxed">{t("caption")}</p>
          <p className="bidi mt-1 truncate text-[12px] opacity-50">#رمضان #قهوة_مختصة</p>
          <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-3">
            <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-bold" style={{ background: "var(--accent)", color: "var(--on-accent)" }}>
              <Icon name="schedule" size={12} /> {t("scheduled")}
            </span>
            <span className="inline-flex items-center gap-1 rounded-full bg-white/10 px-2.5 py-1 text-[11px] opacity-80"><Icon name="bolt" size={12} /> {t("best")}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function AnalyticsCard() {
  const t = useTranslations("landing.preview");
  return (
    <div className="lx-card-dark p-4">
      <div className="flex items-center gap-2 text-xs font-semibold opacity-70"><Icon name="trending_up" size={16} /> {t("reach")}</div>
      <div className="lx-display mt-1 text-3xl" dir="ltr">128.4K</div>
      <svg viewBox="0 0 120 36" className="mt-2 h-12 w-full" aria-hidden preserveAspectRatio="none">
        <path d="M0 30 C 15 28, 22 22, 35 24 S 55 14, 68 16 S 92 6, 104 8 L 120 3" fill="none" stroke="var(--accent)" strokeWidth="2.4" strokeLinecap="round" />
      </svg>
      <div className="mt-3 flex items-center gap-2 border-t border-white/10 pt-3">
        <Icon name="shopping_cart" size={16} className="opacity-70" />
        <span className="text-xs opacity-60">{t("sales")}</span>
        <span className="ms-auto text-sm font-bold" dir="ltr">SAR 12,480</span>
      </div>
    </div>
  );
}

function PostTile() {
  return (
    <div className="relative aspect-[4/5] overflow-hidden rounded-[22px] bg-[radial-gradient(circle_at_30%_25%,#ffd7c2,#c2607a_45%,#3a1730_80%)] shadow-[0_40px_80px_-40px_rgba(18,16,22,.7)]">
      <div className="absolute inset-x-3 bottom-3 flex items-center gap-2 rounded-full bg-black/35 p-1.5 pe-3 text-[11px] text-white backdrop-blur">
        <PlatformBadge platform="tiktok" size={20} /> <span dir="ltr">@brand · 24.1K ♥</span>
      </div>
    </div>
  );
}

function PlatformsTile() {
  return (
    <div className="lx-card-dark grid grid-cols-4 gap-2 p-4" dir="ltr">
      {PLATFORMS.map((p) => <span key={p} className="flex items-center justify-center rounded-xl bg-white/[.05] p-2"><PlatformBadge platform={p} size={30} /></span>)}
    </div>
  );
}

/* ---------------------------------------------------------------------------------------------
 * Page
 * ------------------------------------------------------------------------------------------- */
export function Landing() {
  const t = useTranslations("landing");
  const m = useTranslations("landing.motion");
  const tb = useTranslations("billing");
  const locale = useLocale();
  const plans = usePlans();
  const days = plans.data?.trial_days ?? 14;
  const me = useQuery({ queryKey: ["landing-me"], queryFn: () => api.get("/auth/me"), retry: false, staleTime: 300_000 });
  const signedIn = me.isSuccess;
  const reduce = useReducedMotion();

  const rootRef = useRef<HTMLDivElement>(null);
  const menuBtn = useRef<HTMLButtonElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const [menu, setMenu] = useState(false);
  const [faq, setFaq] = useState<string | null>("1");

  useEffect(() => {
    if (!rootRef.current) return;
    return setupLanding(rootRef.current, reduce);
  }, [reduce]);

  useEffect(() => {
    if (!menu) return;
    scroller.stop();
    closeBtn.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMenu(false); };
    window.addEventListener("keydown", onKey);
    const trigger = menuBtn.current;
    return () => {
      window.removeEventListener("keydown", onKey);
      scroller.start();
      trigger?.focus({ preventScroll: true });
    };
  }, [menu]);

  const startHref = signedIn ? "/" : "/signup";
  const startLabel = signedIn ? t("nav.app") : t("nav.signup");
  const menuLinks = [
    { href: "#top", label: m("home") },
    { href: "#features", label: t("nav.features") },
    { href: "#pricing", label: t("nav.pricing") },
    { href: "#faq", label: t("nav.faq") },
  ];

  return (
    <div ref={rootRef} className="lx">
      <Loader label={m("loading")} />
      <Cursor reduce={reduce} />

      {/* ---------------------------------------------------------------- header */}
      <header data-header data-tone="dark" className="lx-header">
        <div data-intro="header" className="flex items-center gap-1.5 px-4 py-4 sm:gap-2 sm:px-7 sm:py-5">
          <Link href="/welcome" aria-label="Stravica Social"><Logo /></Link>
          <div className="ms-auto flex items-center gap-1 sm:gap-2">
            <span className="hidden sm:inline-flex"><LanguageMenu href="/welcome" className="lx-header-link" /></span>
            {!signedIn && <Link href="/login" className="lx-header-link hidden md:inline-flex">{t("nav.login")}</Link>}
            <span data-magnetic className="inline-flex">
              <Link href={startHref} className="lx-pill max-[360px]:px-3 max-[360px]:text-[13px]">{startLabel} <Arrow /></Link>
            </span>
            <button ref={menuBtn} type="button" className="lx-menu-btn" onClick={() => setMenu(true)} aria-label={m("menu")} aria-expanded={menu} aria-controls="lx-menu">
              <i /><i />
            </button>
          </div>
        </div>
      </header>

      {/* ---------------------------------------------------------------- menu */}
      <div id="lx-menu" role="dialog" aria-modal="true" aria-label={m("menu")} data-open={menu} inert={!menu} className="lx-menu">
        <Contours seed={7} />
        <div className="relative flex h-full flex-col px-4 py-4 sm:px-7 sm:py-5">
          <div className="flex items-center gap-2">
            <Logo />
            <button ref={closeBtn} type="button" onClick={() => setMenu(false)} className="lx-menu-btn ms-auto" aria-label={m("close")}>
              <Icon name="close" size={18} />
            </button>
          </div>
          <div className="grid flex-1 content-center gap-12 py-8 lg:grid-cols-[1fr_1.1fr] lg:items-center">
            <nav aria-label={m("menu")} className="lg:order-2">
              {menuLinks.map((l, i) => (
                <a key={l.href} href={l.href} onClick={() => setMenu(false)} className="lx-menu-link overflow-hidden" style={{ ["--i" as string]: i }}>
                  <span>{l.label}</span>
                </a>
              ))}
              <div className="lx-menu-tile mt-8 flex flex-wrap items-center gap-3" style={{ ["--i" as string]: 4 }}>
                {signedIn ? (
                  <Link href="/" className="lx-pill lx-pill-lg">{t("nav.app")} <Arrow /></Link>
                ) : (
                  <>
                    <Link href="/signup" className="lx-pill lx-pill-lg">{t("nav.signup")} <Arrow /></Link>
                    <Link href="/login" className="lx-ghost">{t("nav.login")}</Link>
                  </>
                )}
                <LanguageMenu href="/welcome" className="lx-ghost" up />
              </div>
            </nav>
            <div className="hidden grid-cols-2 gap-4 lg:grid">
              {FEATURES.slice(0, 4).map((f, i) => (
                <div key={f.key} className="lx-menu-tile lx-feature flex aspect-[5/4] flex-col justify-between p-5" style={{ ["--i" as string]: i }}>
                  <div className="lx-feature-orb" />
                  <span className="lx-tag relative" dir="ltr">0{i + 1}</span>
                  <Icon name={f.icon} size={46} duo className="relative mx-auto text-[var(--accent)]" />
                  <span className="relative text-sm font-semibold">{t(`features.${f.key}.title`)}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-4 text-xs opacity-60" dir="ltr">
            {PLATFORMS.map((p) => <PlatformIcon key={p} platform={p} size={16} />)}
          </div>
        </div>
      </div>

      <main>
        {/* ---------------------------------------------------------------- hero */}
        <section id="top" data-hero data-tone="dark" className="lx-hero lx-dark lx-on-dark">
          <Contours seed={3} />
          <StarCanvas variant="hero" reduce={reduce} />
          <Scribble kind="hero" className="lx-scribble-hero left-1/2 top-[47%] z-[5] w-[min(78vw,600px)] -translate-x-1/2 -translate-y-1/2" />
          <div data-hero-content className="relative z-10 flex min-h-[inherit] flex-col px-4 pb-6 pt-24 sm:px-7 sm:pb-8 sm:pt-28">
            <div data-intro="fade"><Kicker>{t("badge")}</Kicker></div>
            <div className="mt-auto grid gap-8 pt-[34vh] lg:grid-cols-[1fr_minmax(300px,390px)] lg:items-end lg:gap-14 lg:pt-0">
              <h1 data-hero-title className="lx-display lx-hero-title max-w-[16ch] text-balance">
                <Words text={t("heroTitle")} /> <Words text={t("heroHighlight")} className="lx-serif" />
              </h1>
              <div className="flex flex-col gap-5 lg:pb-3">
                <p data-intro="fade" className="lx-dim text-[15px] leading-relaxed sm:text-base">{t("heroText")}</p>
                <div data-intro="fade" className="flex flex-wrap gap-3">
                  <span data-magnetic className="inline-flex">
                    <Link href="/signup" className="lx-pill lx-pill-lg">{t("ctaPrimary", { days })} <Arrow /></Link>
                  </span>
                  <a href="#pricing" className="lx-ghost">{t("ctaSecondary")}</a>
                </div>
                <p data-intro="fade" className="lx-dim text-xs">{t("trust")}</p>
              </div>
            </div>
            <div data-intro="fade" className="mt-10 flex items-center justify-between gap-4">
              <span className="lx-scroll-hint"><i /> {m("scroll")}</span>
              <span className="flex items-center gap-3 opacity-60" dir="ltr">
                {PLATFORMS.map((p) => <PlatformIcon key={p} platform={p} size={15} />)}
              </span>
            </div>
          </div>
        </section>

        {/* ---------------------------------------------------------------- platforms marquee */}
        <section data-tone="dark" aria-label={t("platformsTitle")} className="lx-dark lx-on-dark relative overflow-hidden py-16 sm:py-24">
          <div className="mb-8 flex flex-wrap items-center justify-between gap-4 px-4 sm:mb-10 sm:px-7">
            <Kicker>{m("platformsKicker")}</Kicker>
            <p data-reveal="fade" className="lx-dim max-w-sm text-sm">{t("platformsTitle")}</p>
          </div>
          <MarqueeRow duration={46}>
            {PLATFORMS.map((p, i) => (
              <span key={p} className="lx-mq-item">
                <PlatformIcon platform={p} size={64} />
                <span className={i % 2 ? "lx-serif" : "lx-display"}>{PLATFORM_NAMES[p]}</span>
                <Spark />
              </span>
            ))}
          </MarqueeRow>
          <MarqueeRow rev duration={58} className="mt-2 opacity-90">
            {FEATURES.map((f, i) => (
              <span key={f.key} className="lx-mq-item">
                <span dir={locale === "ar" ? "rtl" : "ltr"} className={i % 2 ? "lx-display" : "lx-serif"}>{t(`features.${f.key}.title`)}</span>
                <Spark />
              </span>
            ))}
          </MarqueeRow>
        </section>

        {/* ---------------------------------------------------------------- manifesto + block transition */}
        <section data-tone="dark" className="lx-dark lx-on-dark relative">
          <div className="px-4 pb-24 pt-8 sm:px-7 sm:pb-36">
            <Kicker>Stravica Social</Kicker>
            <ScrubWords raw={m.raw("manifesto") as string} className="lx-display mt-8 max-w-[22ch] text-[clamp(32px,5.4vw,92px)] lg:max-w-[20ch]" />
          </div>
          <div className="hidden md:block"><Pixels cols={14} rows={3} /></div>
          <div className="md:hidden"><Pixels cols={7} rows={3} /></div>
        </section>

        {/* ---------------------------------------------------------------- how it works: floating glimpses */}
        <section id="how" data-tone="light" className="lx-light lx-on-light relative overflow-hidden pb-24 pt-6 sm:pb-40">
          <Contours seed={11} />
          <div className="relative px-4 text-center sm:px-7">
            <Kicker className="justify-center">{m("stepsKicker")}</Kicker>
            <Title a={m("titles.steps.a")} b={m("titles.steps.b")} className="mx-auto mt-6 text-[clamp(44px,8.4vw,148px)]" />
          </div>
          <div className="relative mx-auto mt-14 flex max-w-[1400px] flex-col gap-12 px-4 sm:px-7 lg:mt-4 lg:block lg:h-[1240px]">
            {(["1", "2", "3"] as const).map((n, i) => {
              const pos = ["lg:top-[150px] lg:start-[4%]", "lg:top-[650px] lg:end-[7%]", "lg:top-[1030px] lg:end-[16%]"][i];
              return (
                <div key={n} data-speed={[1.06, 0.94, 1.1][i]} className={cx("w-full max-w-[320px] lg:absolute", i % 2 ? "self-end" : "self-start", pos)}>
                  <div data-reveal="fade">
                    <span className="lx-tag">{m("step")} <span dir="ltr">0{n}</span></span>
                    <p className="lx-quote mt-3"><b className="font-[inherit]">{t(`steps.${n}.title`)}.</b> {t(`steps.${n}.text`)}</p>
                    <Scribble kind="line" className="mt-3 h-4 w-28" />
                  </div>
                </div>
              );
            })}
            <div data-speed="1.14" className="w-full max-w-[340px] self-end lg:absolute lg:end-[5%] lg:top-[110px] lg:w-[340px]">
              <div data-reveal="fade"><div className="lg:rotate-2"><span className="lx-tag mb-2 block">{t("preview.inbox")}</span><InboxCard /></div></div>
            </div>
            <div data-speed="0.9" className="w-full max-w-[480px] self-center lg:absolute lg:start-[29%] lg:top-[290px] lg:w-[480px]">
              <div data-reveal="fade"><span className="lx-tag mb-2 block">{t("preview.studio")}</span><StudioCard /></div>
            </div>
            <div data-speed="1.08" className="w-full max-w-[240px] self-end lg:absolute lg:end-[11%] lg:top-[400px]">
              <div data-reveal="fade"><div className="lg:-rotate-3"><PlatformsTile /></div></div>
            </div>
            <div data-speed="1.2" className="w-full max-w-[260px] self-start lg:absolute lg:start-[6%] lg:top-[560px]">
              <div data-reveal="fade"><div className="-rotate-2"><PostTile /></div></div>
            </div>
            <div data-speed="0.86" className="w-full max-w-[350px] self-start lg:absolute lg:start-[38%] lg:top-[830px]">
              <div data-reveal="fade"><div className="lg:rotate-1"><span className="lx-tag mb-2 block">{t("preview.reach")}</span><AnalyticsCard /></div></div>
            </div>
          </div>
        </section>

        {/* ---------------------------------------------------------------- features */}
        <section id="features" data-tone="dark" className="lx-dark lx-on-dark lx-panel z-10 px-4 pb-28 pt-20 sm:px-7 sm:pb-40 sm:pt-28">
          <div className="grid gap-8 lg:grid-cols-[1.5fr_1fr] lg:items-end">
            <div>
              <Kicker>{m("featuresKicker")}</Kicker>
              <Title a={m("titles.features.a")} b={m("titles.features.b")} className="mt-6 text-[clamp(44px,7vw,124px)]" />
            </div>
            <p data-reveal="fade" className="lx-dim max-w-md text-[15px] leading-relaxed lg:justify-self-end lg:pb-3">{t("featuresText")}</p>
          </div>
          <div className="mt-16 grid grid-cols-1 items-start gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {FEATURES.map((f, i) => (
              <div key={f.key} data-reveal="fade" className="sm:max-xl:even:mt-14 xl:[&:nth-child(3n+2)]:mt-14">
                <article className="lx-feature flex h-full flex-col p-5 sm:p-6">
                  <div className="lx-feature-orb" />
                  <div className="relative flex items-center justify-between">
                    <span className="lx-tag" dir="ltr">0{i + 1}</span>
                    <span className="h-2 w-2 rounded-full bg-[var(--accent)] shadow-[0_0_12px_var(--accent)]" />
                  </div>
                  <div className={cx("lx-shot relative my-5", f.key === "mobile" && "lx-shot-phone")}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={`/landing/shots/${shotLocale(locale)}/${f.key}.webp`} alt="" loading="lazy" decoding="async" width={f.key === "mobile" ? 585 : 1040} height={f.key === "mobile" ? 1170 : 780} />
                  </div>
                  <h3 className="lx-display relative text-[22px] !leading-tight">{t(`features.${f.key}.title`)}</h3>
                  <p className="relative mt-2 text-[13.5px] leading-relaxed opacity-60">{t(`features.${f.key}.text`)}</p>
                </article>
              </div>
            ))}
            <div data-reveal="fade" className="sm:max-xl:even:mt-14 xl:[&:nth-child(3n+2)]:mt-14">
              <Link href="/signup" className="lx-feature lx-feature-cta flex h-full min-h-[220px] flex-col justify-between p-6 sm:min-h-[360px]">
                <span className="flex items-center justify-between"><span className="lx-tag !opacity-80" dir="ltr">08</span><Arrow className="h-7 w-7" /></span>
                <span className="lx-display text-[clamp(28px,2.6vw,40px)] !leading-[1.05]">{t("ctaPrimary", { days })}</span>
              </Link>
            </div>
          </div>
        </section>

        {/* ---------------------------------------------------------------- pricing */}
        <section id="pricing" data-tone="light" className="lx-light lx-on-light lx-panel z-20 px-4 pb-28 pt-20 sm:px-7 sm:pb-40 sm:pt-28">
          <Contours seed={17} />
          <div className="relative grid gap-8 lg:grid-cols-[1.4fr_1fr] lg:items-end">
            <div>
              <Kicker>{m("pricingKicker")}</Kicker>
              <Title a={m("titles.pricing.a")} b={m("titles.pricing.b")} className="mt-6 text-[clamp(44px,7vw,124px)]" />
            </div>
            <p data-reveal="fade" className="lx-dim max-w-md text-[15px] leading-relaxed lg:justify-self-end lg:pb-3">{t("pricingText", { days })}</p>
          </div>
          <div data-reveal="fade" className="relative mx-auto mt-12 max-w-[1240px]">
            <PricingTable
              tone="light"
              compact
              action={(plan) =>
                plan.self_service ? (
                  <Link href={`/signup?plan=${plan.code}`}
                    className={cx("flex h-12 w-full items-center justify-center gap-2 rounded-full text-sm font-bold transition",
                      plan.highlight ? "lx-pill w-full" : "bg-[var(--ink)] text-[var(--paper)] hover:opacity-90")}>
                    {tb("startTrial")} <Arrow />
                  </Link>
                ) : (
                  <a href={`mailto:${tb("contactEmail")}`} className="lx-ghost !h-12 w-full !text-sm">
                    {tb("contactSales")}
                  </a>
                )
              }
            />
          </div>
        </section>

        {/* ---------------------------------------------------------------- faq */}
        <section id="faq" data-tone="dark" className="lx-dark lx-on-dark lx-panel z-30 px-4 pb-32 pt-20 sm:px-7 sm:pb-44 sm:pt-28">
          <div className="grid gap-12 lg:grid-cols-[1fr_1.35fr] lg:gap-20">
            <div className="self-start lg:sticky lg:top-28">
              <Kicker>{m("faqKicker")}</Kicker>
              <Title a={m("titles.faq.a")} b={m("titles.faq.b")} className="mt-6 text-[clamp(44px,6.4vw,112px)]" />
            </div>
            <div>
              {FAQ.map((n) => {
                const open = faq === n;
                return (
                  <div key={n} data-reveal="fade" className="lx-faq-row">
                    <h3>
                      <button type="button" aria-expanded={open} aria-controls={`lx-faq-${n}`} onClick={() => setFaq(open ? null : n)}
                        className="flex w-full items-center gap-4 py-6 text-start sm:gap-6">
                        <span className="lx-tag w-7 shrink-0" dir="ltr">0{n}</span>
                        <span className="lx-faq-q flex-1">{t(`faq.q${n}`)}</span>
                        <span className="lx-faq-plus" aria-hidden />
                      </button>
                    </h3>
                    <div id={`lx-faq-${n}`} role="region" className="lx-faq-a" data-open={open}>
                      <div><p className="max-w-2xl pb-7 ps-11 text-[15px] leading-relaxed opacity-65 sm:ps-[3.25rem]">{t(`faq.a${n}`, { days })}</p></div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      </main>

      {/* ---------------------------------------------------------------- final call + footer */}
      <footer data-tone="light" className="lx-light lx-panel relative z-40 px-2.5 pb-3 pt-2.5 sm:px-4 sm:pb-4 sm:pt-4">
        <div data-grow className="lx-foot-panel lx-on-dark">
          <Contours seed={23} />
          <div className="relative px-5 pt-16 text-center sm:px-10 sm:pt-24">
            <span className="lx-logo-mark mx-auto"><Icon name="auto_awesome" size={18} duo /></span>
            <Title a={m("titles.final.a")} b={m("titles.final.b")} className="mx-auto mt-8 max-w-6xl text-[clamp(40px,7.4vw,128px)]" />
            <p data-reveal="fade" className="lx-dim mx-auto mt-6 max-w-lg text-[15px] leading-relaxed">{t("finalText")}</p>
            <div data-reveal="fade" className="mt-8 flex justify-center">
              <span data-magnetic className="inline-flex"><Link href="/signup" className="lx-pill lx-pill-lg">{t("ctaPrimary", { days })} <Arrow /></Link></span>
            </div>
          </div>
          <div className="relative grid grid-cols-2 gap-x-6 gap-y-2 px-5 pt-14 sm:px-10 lg:grid-cols-[1fr_minmax(0,520px)_1fr] lg:items-end">
            <nav aria-label={m("footerExplore")} className="flex flex-col items-start gap-1 lg:pb-12">
              <span className="lx-tag mb-2">{m("footerExplore")}</span>
              {[{ h: "#how", l: m("stepsKicker") }, { h: "#features", l: t("nav.features") }, { h: "#pricing", l: t("nav.pricing") }, { h: "#faq", l: t("nav.faq") }].map((x) => (
                <a key={x.h} href={x.h} className="lx-foot-link">{x.l}</a>
              ))}
            </nav>
            <div className="lx-foot-star order-last col-span-2 lg:order-none lg:col-span-1">
              <StarCanvas variant="footer" reduce={reduce} />
            </div>
            <nav aria-label={m("footerAccount")} className="flex flex-col items-end gap-1 text-end lg:pb-12">
              <span className="lx-tag mb-2">{m("footerAccount")}</span>
              {signedIn ? (
                <Link href="/" className="lx-foot-link">{t("nav.app")}</Link>
              ) : (
                <>
                  <Link href="/signup" className="lx-foot-link">{t("nav.signup")}</Link>
                  <Link href="/login" className="lx-foot-link">{t("nav.login")}</Link>
                </>
              )}
              <span className="mt-3 flex flex-wrap justify-end gap-x-4 gap-y-1 text-sm opacity-70"><LanguageLinks href="/welcome" className="hover:text-[var(--accent)]" /></span>
            </nav>
          </div>
        </div>
        <MarqueeRow duration={40} className="lx-mq-small mt-3 opacity-55">
          {PLATFORMS.map((p) => (
            <span key={p} className="lx-mq-item"><PlatformIcon platform={p} size={28} /><span className="lx-display">{PLATFORM_NAMES[p]}</span></span>
          ))}
        </MarqueeRow>
        <div className="flex flex-col items-center gap-1 px-2 pb-1 pt-3 text-xs opacity-60 sm:flex-row sm:justify-between">
          <span>{t("footer.rights", { year: new Date().getFullYear() })}</span>
          <span>{t("footer.madeFor")}</span>
        </div>
      </footer>
    </div>
  );
}
