"use client";
/**
 * Mounted once in the app shell:
 * - a slim banner for trials, failed payments, read-only workspaces and platform announcements;
 * - the upgrade dialog, opened whenever any API call answers `code: "limit_reached"` (see lib/api.ts).
 */
import { useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Icon } from "@/components/icon";
import { Button, Modal, cx } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { type LimitDetail, formatDate, formatMoney, onLimitReached, useBillingSummary, usePlans } from "@/lib/billing";
import { useSession } from "@/lib/session";

const DISMISS_KEY = "sai.trialBannerHidden";

function readDismissed(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(DISMISS_KEY);
  } catch {
    return null;
  }
}

export function BillingOverlay() {
  return (
    <>
      <BillingBanner />
      <UpgradeDialog />
    </>
  );
}

function BillingBanner() {
  const t = useTranslations("billing");
  const locale = useLocale();
  const workspace = useSession((s) => s.workspace);
  const { data } = useBillingSummary(!!workspace);
  // the shell renders this only in the browser (after the session loaded), so storage can be read at once
  const [hidden, setHidden] = useState<string | null>(readDismissed);
  if (!data) return null;

  let tone: "info" | "warn" | "bad" = "info";
  let text = "";
  let cta: string | null = t("banner.cta");
  let dismissible = false;
  if (data.blocked) {
    tone = "bad";
    text = t(`banner.${data.blocked}`);
    if (data.blocked === "suspended") cta = null;
    if (data.blocked === "payment_overdue") cta = t("banner.fix");
  } else if (data.status === "past_due") {
    tone = "warn";
    text = t("banner.pastDue", { date: formatDate(data.grace_ends_at, locale) });
    cta = t("banner.fix");
  } else if (data.status === "trialing" && data.trial_days_left != null) {
    tone = data.trial_days_left <= 3 ? "warn" : "info";
    text = t("banner.trial", { days: data.trial_days_left });
    dismissible = data.trial_days_left > 3;
  } else if (data.announcement) {
    text = data.announcement;
    cta = null;
    dismissible = true;
  } else {
    return null;
  }
  const key = `${workspace?.id}:${data.status}:${data.trial_days_left}:${data.announcement ?? ""}`;
  if (dismissible && hidden === key) return null;

  return (
    <div className={cx("pop-in mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl px-4 py-2.5 text-sm",
      tone === "bad" ? "bg-bad-bg text-bad" : tone === "warn" ? "bg-warn-bg text-warn" : "glass text-text-2")}>
      <Icon name={tone === "info" ? "rocket_launch" : "warning"} size={18} duo className={cx("shrink-0", tone === "info" && "text-accent-deep")} />
      <span className="bidi min-w-0 flex-1 font-medium">{text}</span>
      {cta && data.can_manage && (
        <Link href="/settings/billing" className={cx("inline-flex h-8 items-center rounded-full px-3.5 text-[13px] font-semibold",
          tone === "info" ? "bg-accent text-ink shadow-[0_8px_22px_-10px_var(--accent)]" : "bg-white/80 text-text shadow-sm")}>
          {cta}
        </Link>
      )}
      {dismissible && (
        <button
          className="inline-flex h-8 w-8 items-center justify-center rounded-full hover:bg-fill-2"
          aria-label={t("banner.dismiss")}
          onClick={() => {
            setHidden(key);
            try {
              window.sessionStorage.setItem(DISMISS_KEY, key);
            } catch {
              /* storage unavailable */
            }
          }}
        >
          <Icon name="close" size={16} />
        </button>
      )}
    </div>
  );
}

function UpgradeDialog() {
  const t = useTranslations("billing");
  const locale = useLocale();
  const router = useRouter();
  const qc = useQueryClient();
  const can = useSession((s) => s.can);
  const [detail, setDetail] = useState<LimitDetail | null>(null);
  const plans = usePlans();

  useEffect(() => onLimitReached((d) => {
    setDetail(d);
    qc.invalidateQueries({ queryKey: ["billing-summary"] });
  }), [qc]);

  if (!detail) return null;
  const reason = detail.reason || "limit";
  const suggested = plans.data?.plans.find((p) => p.code === detail.upgrade);
  const currency = locale === "ar" ? "SAR" : "USD";
  const price = suggested ? (currency === "SAR" ? suggested.price_month_sar : suggested.price_month) : null;
  const isOwner = can("owner");
  const close = () => setDetail(null);

  return (
    // above any dialog that triggered the request (its own z-50)
    <div className="relative z-[55]">
    <Modal open onClose={close} size="sm">
      <div className="flex flex-col items-center gap-3 pt-2 text-center">
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-ink text-white shadow-[0_10px_24px_-10px_rgba(0,0,0,.6)]">
          <Icon name={reason === "feature" ? "lock" : reason === "limit" ? "rocket_launch" : "warning"} size={26} duo />
        </span>
        <h3 className="text-lg font-bold tracking-tight">{t(`modal.title.${reason}`)}</h3>
        <p className="bidi text-sm leading-relaxed text-text-2">{detail.detail}</p>
        {suggested && reason !== "suspended" && (
          <div className="glass mt-1 w-full rounded-2xl p-3 text-start">
            <div className="flex items-center gap-2">
              <Icon name="verified" size={18} duo />
              <span className="text-sm font-semibold">{t("modal.suggest", { plan: t(`plans.${suggested.code}`) })}</span>
            </div>
            {price != null && <p className="ms-[26px] mt-0.5 text-xs text-muted">{t("modal.from", { price: formatMoney(price, currency, locale) })}</p>}
          </div>
        )}
        {!isOwner && reason !== "suspended" && <p className="text-xs text-muted">{t("modal.askOwner")}</p>}
        <div className="mt-2 flex w-full flex-col gap-2 sm:flex-row-reverse">
          {isOwner && reason !== "suspended" && (
            <Button variant="primary" className="flex-1" icon="rocket_launch" onClick={() => { close(); router.push("/settings/billing#plans"); }}>
              {t("modal.seePlans")}
            </Button>
          )}
          <Button variant="ghost" className="flex-1" onClick={close}>{t("modal.later")}</Button>
        </div>
      </div>
    </Modal>
    </div>
  );
}
