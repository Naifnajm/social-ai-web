"use client";
/**
 * AI credits on the billing page: the bought balance, the plan's monthly AI (used / left), credit packs to buy
 * (Stripe one-time payment) and the latest movements. Opened from "Buy credits" links as /settings/billing#credits.
 */
import { useMutation } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useEffect } from "react";
import { Icon } from "@/components/icon";
import { Badge, Button, Card, SectionTitle, Spinner, cx, toast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { type CreditRow, formatDate, formatMoney, useCredits } from "@/lib/billing";

const KIND_ICONS: Record<CreditRow["kind"], string> = {
  purchase: "shopping_cart", usage: "auto_awesome", grant: "verified", refund: "undo", adjust: "edit_square",
};

export function CreditsCard() {
  const t = useTranslations("billing.credits");
  const locale = useLocale();
  const credits = useCredits();
  const num = (v: number) => Math.round(v).toLocaleString(locale === "ar" ? "ar-SA-u-nu-latn" : "en-US");
  const usd = (v: number) => formatMoney(v, "USD", locale);

  const buy = useMutation({
    mutationFn: (packId: number) => api.post<{ url: string | null }>("/billing/credits/checkout", { pack_id: packId }),
    onSuccess: (result) => { if (result.url) window.location.assign(result.url); },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });

  const data = credits.data;
  const loaded = !!data;
  // "Buy credits" links land on #credits: scroll there once the section has its height
  useEffect(() => {
    if (loaded && window.location.hash === "#credits") document.getElementById("credits")?.scrollIntoView({ behavior: "smooth" });
  }, [loaded]);
  return (
    <Card>
      <div id="credits" className="scroll-mt-24" />
      <SectionTitle icon="toll">{t("title")}</SectionTitle>
      {!data ? <div className="flex justify-center py-8"><Spinner /></div> : (
        <div className="flex flex-col gap-5">
          <p className="-mt-1 text-sm text-muted">{t("subtitle", { n: num(data.credits_per_usd), price: usd(1) })}</p>

          <div className="grid gap-3 md:grid-cols-[1fr_1.4fr]">
            <div className="rounded-2xl bg-ink p-4 text-white shadow-[0_14px_30px_-16px_rgba(0,0,0,.7)]">
              <div className="flex items-center gap-2 text-[13px] text-white/70"><Icon name="toll" size={16} /> {t("balance")}</div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-4xl font-bold tracking-tight tabular-nums" dir="ltr">{num(data.balance)}</span>
                <span className="text-sm text-white/70">{t("unit")}</span>
              </div>
              <div className="mt-1 text-xs text-white/60">≈ <bdi dir="ltr">{usd(data.balance / data.credits_per_usd)}</bdi></div>
              <div className="mt-3 border-t border-white/15 pt-2.5 text-xs text-white/80">
                {data.available == null ? t("availableUnlimited") : t("available", { n: num(data.available) })}
              </div>
            </div>

            <IncludedMeter included={data.included} used={data.included_used} left={data.included_left} num={num} />
          </div>

          <div>
            <h4 className="mb-2 text-[13px] font-semibold text-text-2">{t("packs")}</h4>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {data.packs.map((pack) => (
                <div key={pack.id} className={cx("relative flex flex-col gap-2 rounded-2xl bg-white/60 p-3.5 ring-1",
                  pack.bonus > 0 ? "ring-[rgba(255,61,139,.35)]" : "ring-line")}>
                  {pack.bonus > 0 && (
                    <span className="absolute -top-2 end-3 rounded-full bg-accent px-2 py-0.5 text-[11px] font-bold text-ink shadow-[0_6px_16px_-8px_var(--accent)]">
                      {t("bonus", { n: pack.bonus })}
                    </span>
                  )}
                  <div className="flex items-baseline gap-1.5">
                    <span className="text-2xl font-bold tracking-tight tabular-nums" dir="ltr">{num(pack.credits)}</span>
                    <span className="text-xs text-muted">{t("unit")}</span>
                  </div>
                  <span className="text-sm font-semibold text-text-2" dir="ltr">{usd(pack.usd)}</span>
                  {data.can_buy && (
                    <Button size="sm" variant={pack.bonus >= 10 ? "primary" : "secondary"} icon="shopping_cart" className="mt-auto w-full"
                      loading={buy.isPending && buy.variables === pack.id} disabled={buy.isPending} onClick={() => buy.mutate(pack.id)}>
                      {t("buy")}
                    </Button>
                  )}
                </div>
              ))}
            </div>
            {!data.can_buy && <p className="mt-2 flex items-center gap-1.5 text-xs text-muted"><Icon name="info" size={14} /> {t("cannotBuy")}</p>}
          </div>

          <div>
            <h4 className="mb-1 text-[13px] font-semibold text-text-2">{t("history")}</h4>
            {!data.history.length ? <p className="py-3 text-sm text-muted">{t("noHistory")}</p> : (
              <div className="-mx-1 overflow-x-auto">
                <table className="w-full min-w-[520px] text-sm">
                  <thead>
                    <tr className="text-start text-xs text-muted">
                      <th className="px-1 py-2 text-start font-medium">{t("cols.date")}</th>
                      <th className="px-1 py-2 text-start font-medium">{t("cols.kind")}</th>
                      <th className="px-1 py-2 text-start font-medium">{t("cols.note")}</th>
                      <th className="px-1 py-2 text-end font-medium">{t("cols.credits")}</th>
                      <th className="px-1 py-2 text-end font-medium">{t("cols.balance")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line border-t border-line">
                    {data.history.map((row) => (
                      <tr key={row.id}>
                        <td className="whitespace-nowrap px-1 py-2.5 text-muted">{formatDate(row.created_at, locale)}</td>
                        <td className="px-1 py-2.5">
                          <Badge tone={row.kind === "purchase" || row.kind === "grant" ? "ok" : row.kind === "usage" ? "neutral" : "warn"}>
                            <Icon name={KIND_ICONS[row.kind] ?? "info"} size={12} />{t.has(`kinds.${row.kind}`) ? t(`kinds.${row.kind}`) : row.kind}
                          </Badge>
                        </td>
                        <td className="max-w-[240px] truncate px-1 py-2.5 text-text-2">
                          <span className="bidi">{row.note || "—"}</span>
                          {row.amount_paid ? <span className="ms-1 text-xs text-muted" dir="ltr">({formatMoney(row.amount_paid, row.currency === "SAR" ? "SAR" : "USD", locale)})</span> : null}
                        </td>
                        <td className={cx("whitespace-nowrap px-1 py-2.5 text-end font-semibold tabular-nums", row.credits >= 0 ? "text-ok" : "text-text")} dir="ltr">
                          {row.credits >= 0 ? "+" : "−"}{num(Math.abs(row.credits))}
                        </td>
                        <td className="whitespace-nowrap px-1 py-2.5 text-end tabular-nums text-text-2" dir="ltr">{num(row.balance_after)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

function IncludedMeter({ included, used, left, num }: { included: number | null; used: number | null; left: number | null; num: (v: number) => string }) {
  const t = useTranslations("billing.credits");
  const ratio = included ? Math.min(1, (used ?? 0) / included) : 0;
  const tone = included && ratio >= 1 ? "bad" : included && ratio >= 0.8 ? "warn" : "ok";
  return (
    <div className="flex flex-col justify-between rounded-2xl bg-white/60 p-4 ring-1 ring-line">
      <div className="flex items-center gap-2 text-[13px] text-text-2">
        <Icon name="auto_awesome" size={16} />
        <span className="font-medium">{t("included")}</span>
      </div>
      {included == null ? (
        <div className="mt-2 text-xl font-bold tracking-tight">{t("unlimited")}</div>
      ) : (
        <>
          <div className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="text-xl font-bold tracking-tight tabular-nums" dir="ltr">{num(used ?? 0)}</span>
            <span className="text-xs text-muted">{t("usedOf", { n: num(included) })}</span>
            <span className={cx("ms-auto text-xs font-semibold", tone === "bad" ? "text-bad" : tone === "warn" ? "text-warn" : "text-ok")}>
              {t("left", { n: num(left ?? 0) })}
            </span>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-track" role="meter" aria-valuemin={0} aria-valuemax={included} aria-valuenow={used ?? 0} aria-label={t("included")}>
            <div className={cx("h-full rounded-full transition-all", tone === "bad" ? "bg-[var(--bad-solid)]" : tone === "warn" ? "bg-[#c77700]" : "bg-ink")}
              style={{ width: `${Math.max(ratio * 100, (used ?? 0) > 0 ? 3 : 0)}%` }} />
          </div>
          <p className="mt-2 text-xs text-muted">{ratio >= 1 ? t("includedDone") : t("includedHint")}</p>
        </>
      )}
    </div>
  );
}
