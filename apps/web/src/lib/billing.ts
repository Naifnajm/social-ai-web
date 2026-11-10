"use client";
/**
 * Billing client: plan catalog, the workspace subscription summary and the global "limit reached" event.
 *
 *   const { data } = useBillingSummary();       // plan, status, trial days left, usage meters
 *   onLimitReached((detail) => ...)             // fired by lib/api.ts for every response with code limit_reached
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export type PlanCode = "trial" | "starter" | "pro" | "business" | "enterprise";
export type Interval = "month" | "year";
export type Resource = "social_accounts" | "members" | "posts_month" | "ai_credits" | "storage_gb";
export const RESOURCES: Resource[] = ["social_accounts", "members", "posts_month", "ai_credits", "storage_gb"];

export type Plan = {
  code: PlanCode;
  name: string;
  price_month: number | null;
  price_year: number | null;
  price_month_sar: number | null;
  price_year_sar: number | null;
  limits: Record<Resource, number | null>;
  features: string[];
  highlight: boolean;
  self_service: boolean;
};

export type PlansResponse = { plans: Plan[]; features: string[]; trial_days: number; currency: string; sar_rate: number };

export type BillingSummary = {
  plan: PlanCode;
  plan_name: string;
  status: "trialing" | "active" | "past_due" | "canceled";
  blocked: null | "trial_ended" | "payment_overdue" | "canceled" | "suspended";
  interval: Interval;
  trial_ends_at: string | null;
  trial_days_left: number | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  grace_ends_at: string | null;
  provider: string;
  has_payment_method: boolean;
  payments_enabled: boolean;
  usage: Record<Resource, { used: number; limit: number | null }>;
  features: string[];
  can_manage: boolean;
  announcement: string | null;
};

export type LimitDetail = {
  detail: string;
  code: "limit_reached";
  reason: "limit" | "feature" | "trial_ended" | "payment_overdue" | "canceled" | "suspended";
  resource?: string | null;
  feature?: string | null;
  limit?: number | null;
  used?: number | null;
  plan?: PlanCode;
  upgrade?: PlanCode | null;
};

export const LIMIT_EVENT = "sai:limit-reached";

export function onLimitReached(handler: (detail: LimitDetail) => void) {
  const listener = (e: Event) => handler((e as CustomEvent<LimitDetail>).detail);
  window.addEventListener(LIMIT_EVENT, listener);
  return () => window.removeEventListener(LIMIT_EVENT, listener);
}

export const usePlans = () =>
  useQuery({ queryKey: ["billing-plans"], queryFn: () => api.get<PlansResponse>("/billing/plans"), staleTime: 3600_000 });

export const useBillingSummary = (enabled = true) =>
  useQuery({ queryKey: ["billing-summary"], queryFn: () => api.get<BillingSummary>("/billing/summary"), enabled, staleTime: 60_000 });

/** Price shown for a plan in a currency/interval (yearly plans are shown per month). */
export function planPrice(plan: Plan, interval: Interval, currency: "SAR" | "USD"): number | null {
  const yearly = currency === "SAR" ? plan.price_year_sar : plan.price_year;
  const monthly = currency === "SAR" ? plan.price_month_sar : plan.price_month;
  if (interval === "year") return yearly == null ? null : Math.round(yearly / 12);
  return monthly;
}

export function formatMoney(value: number, currency: "SAR" | "USD", locale: string) {
  return new Intl.NumberFormat(locale === "ar" ? "ar-SA-u-nu-latn" : "en-US", {
    style: "currency", currency, maximumFractionDigits: value % 1 ? 2 : 0,
  }).format(value);
}

export function formatDate(value: string | null | undefined, locale: string) {
  if (!value) return "";
  return new Intl.DateTimeFormat(locale === "ar" ? "ar-SA-u-nu-latn-ca-gregory" : "en-GB", { dateStyle: "medium" }).format(new Date(value));
}
