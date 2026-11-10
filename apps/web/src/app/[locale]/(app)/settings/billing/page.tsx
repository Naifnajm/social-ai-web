"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { Suspense, useEffect, useRef } from "react";
import { PricingTable } from "@/components/billing/pricing";
import { Icon } from "@/components/icon";
import { Badge, Button, Card, EmptyState, SectionTitle, Spinner, cx, toast } from "@/components/ui";
import { usePathname, useRouter } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { type BillingSummary, type Interval, type Plan, RESOURCES, type Resource, formatDate, formatMoney, useBillingSummary, usePlans } from "@/lib/billing";
import { useSession } from "@/lib/session";

type Invoice = { id: string; number: string | null; status: string; amount: number; currency: string; created: string; hosted_url: string | null; pdf_url: string | null };

const RANK: Record<string, number> = { trial: 0, starter: 1, pro: 2, business: 3, enterprise: 4 };
const RESOURCE_ICONS: Record<Resource, string> = {
  social_accounts: "link", members: "group", posts_month: "send", ai_credits: "auto_awesome", storage_gb: "photo_library",
};

function useNumber() {
  const locale = useLocale();
  return (value: number, digits = 0) =>
    value.toLocaleString(locale === "ar" ? "ar-SA-u-nu-latn" : "en-US", { maximumFractionDigits: digits });
}

function Meter({ resource, used, limit }: { resource: Resource; used: number; limit: number | null }) {
  const t = useTranslations("billing");
  const num = useNumber();
  const fmt = (v: number) => resource === "ai_credits" ? formatMoney(v, "USD", "en") : resource === "storage_gb" ? `${num(v, 2)} GB` : num(v);
  const ratio = limit ? Math.min(1, used / limit) : 0;
  const tone = limit && ratio >= 1 ? "bad" : limit && ratio >= 0.8 ? "warn" : "ok";
  return (
    <div className="rounded-2xl bg-white/60 p-3.5 ring-1 ring-line">
      <div className="flex items-center gap-2 text-[13px] text-text-2">
        <Icon name={RESOURCE_ICONS[resource]} size={16} />
        <span className="font-medium">{t(`resources.${resource}`)}</span>
        {tone !== "ok" && <Icon name="warning" size={14} className={tone === "bad" ? "text-bad" : "text-warn"} />}
      </div>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="text-xl font-bold tracking-tight" dir="ltr">{fmt(used)}</span>
        <span className="text-xs text-muted">{limit == null ? t("unlimited") : <>{t("of")} <bdi dir="ltr">{fmt(limit)}</bdi></>}</span>
      </div>
      <div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-track" role="meter" aria-valuemin={0} aria-valuemax={limit ?? 0} aria-valuenow={used}
        aria-label={t(`resources.${resource}`)}>
        {limit != null && (
          <div className={cx("h-full rounded-full transition-all", tone === "bad" ? "bg-[var(--bad-solid)]" : tone === "warn" ? "bg-[#c77700]" : "bg-ink")}
            style={{ width: `${Math.max(ratio * 100, used > 0 ? 3 : 0)}%` }} />
        )}
      </div>
    </div>
  );
}

function StatusLine({ data }: { data: BillingSummary }) {
  const t = useTranslations("billing");
  const locale = useLocale();
  if (data.blocked) return <p className="text-sm font-medium text-bad">{t("blockedText")}</p>;
  if (data.status === "past_due") return <p className="text-sm font-medium text-warn">{t("pastDue", { date: formatDate(data.grace_ends_at, locale) })}</p>;
  if (data.status === "trialing" && data.trial_ends_at) return <p className="text-sm text-text-2">{t("trialEnds", { date: formatDate(data.trial_ends_at, locale), days: data.trial_days_left ?? 0 })}</p>;
  if (data.current_period_end) {
    return <p className="text-sm text-text-2">{data.cancel_at_period_end || data.status === "canceled"
      ? t("endsOn", { date: formatDate(data.current_period_end, locale) })
      : t("renews", { date: formatDate(data.current_period_end, locale) })}</p>;
  }
  return null;
}

function BillingContent() {
  const t = useTranslations("billing");
  const locale = useLocale();
  const qc = useQueryClient();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const can = useSession((s) => s.can);
  const refreshWorkspace = useSession((s) => s.refreshWorkspace);
  const isOwner = can("owner");
  const summary = useBillingSummary();
  const plans = usePlans();
  const invoices = useQuery({ queryKey: ["billing-invoices"], queryFn: () => api.get<Invoice[]>("/billing/invoices"), enabled: isOwner });
  const handled = useRef(false);
  const onError = (err: unknown) => {
    if (err instanceof ApiError && err.code === "limit_reached") return; // the upgrade dialog shows it
    toast.error(err instanceof ApiError ? err.message : String(err));
  };

  useEffect(() => {
    const result = params.get("checkout");
    if (!result || handled.current) return;
    handled.current = true;
    if (result === "success") {
      toast.success(t("checkoutSuccess"));
      // the webhook may land a few seconds after the redirect
      for (const ms of [1500, 5000]) {
        setTimeout(() => {
          qc.invalidateQueries({ queryKey: ["billing-summary"] });
          refreshWorkspace().catch(() => undefined);
        }, ms);
      }
    } else {
      toast.info(t("checkoutCancel"));
    }
    router.replace(pathname);
  }, [params, qc, refreshWorkspace, router, pathname, t]);

  const checkout = useMutation({
    mutationFn: (vars: { plan: string; interval: Interval }) => api.post<{ url: string | null; updated: boolean }>("/billing/checkout", vars),
    onSuccess: async (result) => {
      if (result.url) {
        window.location.assign(result.url);
        return;
      }
      toast.success(t("planUpdated"));
      await qc.invalidateQueries({ queryKey: ["billing-summary"] });
      refreshWorkspace().catch(() => undefined);
    },
    onError,
  });
  const portal = useMutation({
    mutationFn: () => api.post<{ url: string }>("/billing/portal"),
    onSuccess: (result) => window.location.assign(result.url),
    onError,
  });

  if (!isOwner) {
    return <Card><EmptyState icon="lock" title={t("title")} text={t("ownerOnly")} /></Card>;
  }
  const data = summary.data;
  if (!data) return <div className="flex justify-center py-16"><Spinner size={26} /></div>;

  const planAction = (plan: Plan, interval: Interval) => {
    const current = plan.code === data.plan && (data.interval === interval || data.status === "trialing");
    const live = data.status !== "trialing" && !data.blocked;
    if (!plan.self_service) {
      return <a href={`mailto:${t("contactEmail")}`} className="flex h-10 w-full items-center justify-center rounded-full text-sm font-semibold ring-1 ring-line hover:bg-fill-2">{t("contactSales")}</a>;
    }
    if (current && live) return <Button className="w-full" disabled icon="check">{t("currentPlan")}</Button>;
    const label = !live ? t("choose", { plan: t(`plans.${plan.code}`) }) : RANK[plan.code] > RANK[data.plan] ? t("upgrade") : t("downgrade");
    return (
      <Button className="w-full" variant={plan.highlight ? "primary" : "secondary"} disabled={!data.payments_enabled}
        loading={checkout.isPending && checkout.variables?.plan === plan.code && checkout.variables?.interval === interval}
        onClick={() => checkout.mutate({ plan: plan.code, interval })}>
        {label}
      </Button>
    );
  };

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <div className="flex flex-wrap items-start gap-4">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-ink text-white shadow-[0_10px_24px_-10px_rgba(0,0,0,.6)]">
            <Icon name="verified" size={24} duo />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-xl font-bold tracking-tight">{t(`plans.${data.plan}`)}</h2>
              {data.blocked ? <Badge tone="bad">{t(`blocked.${data.blocked}`)}</Badge>
                : <Badge tone={data.status === "active" ? "ok" : data.status === "trialing" ? "neutral" : "warn"}>{t(`status.${data.status}`)}</Badge>}
              {data.status !== "trialing" && data.plan !== "trial" && <Badge>{data.interval === "year" ? t("yearly") : t("monthly")}</Badge>}
            </div>
            <div className="mt-1"><StatusLine data={data} /></div>
          </div>
          <div className="flex w-full flex-wrap gap-2 sm:w-auto">
            {data.has_payment_method && (
              <Button icon="payments" loading={portal.isPending} onClick={() => portal.mutate()}>{t("manage")}</Button>
            )}
            <Button variant="primary" icon="rocket_launch" onClick={() => document.getElementById("plans")?.scrollIntoView({ behavior: "smooth" })}>
              {t("changePlan")}
            </Button>
          </div>
        </div>
      </Card>

      <Card>
        <SectionTitle icon="bar_chart">{t("usage")}</SectionTitle>
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
          {RESOURCES.map((r) => <Meter key={r} resource={r} used={data.usage[r].used} limit={data.usage[r].limit} />)}
        </div>
      </Card>

      <section id="plans" className="scroll-mt-20">
        {!data.payments_enabled && (
          <p className="mb-3 flex items-center gap-2 rounded-2xl bg-warn-bg px-4 py-2.5 text-sm text-warn">
            <Icon name="info" size={16} /> {t("paymentsOff")}{" "}
            <a className="font-semibold underline" href={`mailto:${t("contactEmail")}`} dir="ltr">{t("contactEmail")}</a>
          </p>
        )}
        {plans.data && <PricingTable tone="light" currentPlan={data.plan} initialInterval={data.interval} action={planAction} />}
      </section>

      <Card>
        <SectionTitle icon="description">{t("invoices")}</SectionTitle>
        {invoices.isLoading ? <div className="flex justify-center py-6"><Spinner /></div>
          : !invoices.data?.length ? <p className="py-4 text-sm text-muted">{t("noInvoices")}</p> : (
            <ul className="divide-y divide-line">
              {invoices.data.map((inv) => (
                <li key={inv.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3 text-sm">
                  <span className="min-w-0 flex-1 font-medium" dir="ltr">{inv.number || inv.id}</span>
                  <span className="text-muted">{formatDate(inv.created, locale)}</span>
                  <span className="font-semibold" dir="ltr">{formatMoney(inv.amount, inv.currency === "SAR" ? "SAR" : "USD", locale)}</span>
                  <Badge tone={inv.status === "paid" ? "ok" : inv.status === "open" ? "warn" : "neutral"}>
                    {t.has(`invoiceStatus.${inv.status}`) ? t(`invoiceStatus.${inv.status}`) : inv.status}
                  </Badge>
                  {(inv.pdf_url || inv.hosted_url) && (
                    <a href={inv.pdf_url || inv.hosted_url || "#"} target="_blank" rel="noreferrer"
                      className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium text-text-2 hover:bg-fill-2">
                      <Icon name="download" size={14} /> {t("download")}
                    </a>
                  )}
                </li>
              ))}
            </ul>
          )}
      </Card>
    </div>
  );
}

export default function BillingSettingsPage() {
  return (
    <Suspense>
      <BillingContent />
    </Suspense>
  );
}
