"use client";
/**
 * Pricing table (landing page = dark glass, billing settings = light glass).
 *
 *   <PricingTable tone="dark" action={(plan) => <a href="/signup">…</a>} />
 */
import { useLocale, useTranslations } from "next-intl";
import { type ReactNode, useState } from "react";
import { Icon } from "@/components/icon";
import { Spinner, cx } from "@/components/ui";
import { type Interval, type Plan, RESOURCES, formatMoney, planPrice, usePlans } from "@/lib/billing";

export type Currency = "SAR" | "USD";

export function PricingToggles({ interval, setInterval, currency, setCurrency, tone }: {
  interval: Interval; setInterval: (v: Interval) => void; currency: Currency; setCurrency: (v: Currency) => void; tone: "dark" | "light";
}) {
  const t = useTranslations("billing");
  const dark = tone === "dark";
  const pill = (active: boolean) =>
    cx("inline-flex h-8 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium transition",
      active ? (dark ? "bg-white text-black" : "bg-white text-text shadow-[0_1px_3px_rgba(0,0,0,.12)]") : dark ? "text-white/70 hover:text-white" : "text-text-2 hover:text-text");
  const track = dark ? "bg-white/10 ring-1 ring-white/10" : "bg-track";
  return (
    <div className="flex flex-wrap items-center justify-center gap-2">
      <div className={cx("inline-flex rounded-full p-0.5", track)} role="tablist">
        <button role="tab" aria-selected={interval === "month"} className={pill(interval === "month")} onClick={() => setInterval("month")}>{t("monthly")}</button>
        <button role="tab" aria-selected={interval === "year"} className={pill(interval === "year")} onClick={() => setInterval("year")}>
          {t("yearly")}
          <span className={cx("rounded-full px-1.5 py-px text-[10px] font-bold", interval === "year" ? "bg-ok-bg text-ok" : dark ? "bg-white/10 text-white" : "bg-ok-bg text-ok")}>{t("save")}</span>
        </button>
      </div>
      <div className={cx("inline-flex rounded-full p-0.5", track)} role="tablist" dir="ltr">
        {(["SAR", "USD"] as Currency[]).map((c) => (
          <button key={c} role="tab" aria-selected={currency === c} className={pill(currency === c)} onClick={() => setCurrency(c)}>{c}</button>
        ))}
      </div>
    </div>
  );
}

function PlanCard({ plan, previous, interval, currency, tone, action, current, compact }: {
  plan: Plan; previous?: Plan; interval: Interval; currency: Currency; tone: "dark" | "light"; action: ReactNode; current?: boolean; compact?: boolean;
}) {
  const t = useTranslations("billing");
  const locale = useLocale();
  const dark = tone === "dark";
  const price = planPrice(plan, interval, currency);
  const yearly = currency === "SAR" ? plan.price_year_sar : plan.price_year;
  const extraFeatures = previous ? plan.features.filter((f) => !previous.features.includes(f)) : plan.features;
  const highlight = plan.highlight;
  return (
    <div
      className={cx(
        compact ? "relative flex flex-col rounded-[22px] p-5" : "relative flex flex-col rounded-[24px] p-5 sm:p-6",
        dark
          ? highlight ? "bg-white text-black shadow-[0_30px_80px_-30px_rgba(255,255,255,.35)]" : "bg-white/[.04] text-white ring-1 ring-white/10 backdrop-blur-xl"
          : highlight ? "glass-strong ring-2 ring-ink" : "glass",
      )}
    >
      {highlight && (
        <span className={cx("absolute -top-3 start-6 rounded-full px-3 py-1 text-[11px] font-bold", dark ? "bg-black text-white ring-1 ring-white/20" : "bg-ink text-white")}>
          {t("popular")}
        </span>
      )}
      <div className="flex items-center gap-2">
        <h3 className="text-lg font-bold tracking-tight">{t(`plans.${plan.code}`)}</h3>
        {current && <span className={cx("rounded-full px-2 py-0.5 text-[11px] font-semibold", dark ? "bg-white/15" : "bg-ok-bg text-ok")}>{t("currentPlan")}</span>}
      </div>
      <p className={cx("mt-1 min-h-[40px] text-[13px] leading-relaxed", dark && !highlight ? "text-white/60" : "text-muted")}>{t(`planTagline.${plan.code}`)}</p>
      <div className="mt-4 flex items-baseline gap-1.5">
        {price == null ? (
          <span className={cx("whitespace-nowrap font-bold tracking-tight", compact ? "text-[26px] leading-[32px]" : "text-3xl")}>{t("custom")}</span>
        ) : (
          <>
            <span className="inline-flex items-baseline gap-1" dir="ltr">
              {currency === "USD" && <span className="text-xl font-semibold">$</span>}
              <span className={cx(compact ? "text-[32px] leading-none" : "text-4xl", "font-bold tracking-tight")}>{price.toLocaleString("en-US")}</span>
              {currency === "SAR" && <span className="text-base font-semibold">{locale === "ar" ? "ر.س" : "SAR"}</span>}
            </span>
            <span className={cx("text-sm", dark && !highlight ? "text-white/60" : "text-muted")}>{t("perMonth")}</span>
          </>
        )}
      </div>
      <p className={cx("mt-1 h-5 text-xs", dark && !highlight ? "text-white/50" : "text-muted")}>
        {price != null && (interval === "year" && yearly != null ? t("billedYearly", { amount: formatMoney(yearly, currency, locale) }) : t("billedMonthly"))}
      </p>
      <div className="mt-5">{action}</div>
      <ul className={cx("flex flex-col text-[13px]", compact ? "mt-5 gap-2" : "mt-6 gap-2.5")}>
        {RESOURCES.map((r) => {
          const limit = plan.limits[r];
          return (
            <li key={r} className="flex items-start gap-2">
              <Icon name="check_circle" size={16} duo className={cx("mt-px", dark && !highlight ? "text-white" : "text-ink")} />
              <span>{limit == null ? t(`unlimitedLine.${r}`) : t(`limitLine.${r}`, { n: r === "ai_credits" ? formatMoney(limit, "USD", "en") : limit.toLocaleString(locale === "ar" ? "ar-SA-u-nu-latn" : "en-US") })}</span>
            </li>
          );
        })}
      </ul>
      <div className={cx("my-4 h-px", dark && !highlight ? "bg-white/10" : "bg-line")} />
      {previous && <p className={cx("mb-2.5 text-xs font-semibold", dark && !highlight ? "text-white/60" : "text-muted")}>{t("everythingIn", { plan: t(`plans.${previous.code}`) })}</p>}
      <ul className="flex flex-col gap-2.5 text-[13px]">
        {extraFeatures.map((f) => (
          <li key={f} className="flex items-start gap-2">
            <Icon name="check" size={16} className={cx("mt-px", dark && !highlight ? "text-white/80" : "text-text-2")} />
            <span>{t(`features.${f}`)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function PricingTable({ tone, action, currentPlan, initialInterval = "month", compact }: {
  tone: "dark" | "light";
  action: (plan: Plan, interval: Interval) => ReactNode;
  currentPlan?: string;
  initialInterval?: Interval;
  /** Four narrow cards side by side from tablet width up (the landing page). */
  compact?: boolean;
}) {
  const locale = useLocale();
  const t = useTranslations("billing");
  const { data, isLoading } = usePlans();
  const [interval, setInterval] = useState<Interval>(initialInterval);
  const [currency, setCurrency] = useState<Currency>(locale === "ar" ? "SAR" : "USD");
  if (isLoading || !data) {
    return <div className="flex justify-center py-16"><Spinner size={26} className={tone === "dark" ? "text-white/60" : ""} /></div>;
  }
  return (
    <div>
      <PricingToggles interval={interval} setInterval={setInterval} currency={currency} setCurrency={setCurrency} tone={tone} />
      <div className={cx("mt-8 grid grid-cols-1 pt-3", compact ? "gap-3.5 sm:grid-cols-2 min-[60rem]:grid-cols-4" : "gap-5 md:grid-cols-2", !compact && (tone === "dark" ? "xl:grid-cols-4" : "2xl:grid-cols-4"))}>
        {data.plans.map((plan, index) => (
          <PlanCard key={plan.code} plan={plan} previous={index ? data.plans[index - 1] : undefined} interval={interval}
            currency={currency} tone={tone} action={action(plan, interval)} current={plan.code === currentPlan} compact={compact} />
        ))}
      </div>
      {currency === "SAR" && <p className={cx("mt-5 text-center text-xs", tone === "dark" ? "text-white/40" : "text-muted")}>{t("vatNote")}</p>}
    </div>
  );
}
