"use client";
/** Small pieces shared by the platform admin pages. */
import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui";

export type AdminRow = {
  id: number; name: string; slug: string; status: string; plan: string; subscription_status: string; blocked: string | null;
  interval: string; trial_ends_at: string | null; current_period_end: string | null; provider: string; owner_email: string | null;
  members: number; social_accounts: number; posts_month: number; created_at: string;
};

export function StatusBadge({ row }: { row: Pick<AdminRow, "status" | "subscription_status" | "blocked"> }) {
  const t = useTranslations("admin");
  const tb = useTranslations("billing");
  if (row.status !== "active") return <Badge tone="bad">{t("statuses.suspended")}</Badge>;
  if (row.blocked) return <Badge tone="bad">{tb(`blocked.${row.blocked}`)}</Badge>;
  const tone = row.subscription_status === "active" ? "ok" : row.subscription_status === "past_due" ? "warn" : "neutral";
  return <Badge tone={tone}>{t(`statuses.${row.subscription_status}`)}</Badge>;
}
