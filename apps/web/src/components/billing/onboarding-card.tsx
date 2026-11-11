"use client";
/** Home page checklist: five first steps, computed by the API from existing rows (GET /onboarding). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Icon } from "@/components/icon";
import { Card, IconButton, cx } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

type Step = { key: string; done: boolean; href: string };
type Onboarding = { steps: Step[]; done: number; total: number; dismissed: boolean };

const ICONS: Record<string, string> = {
  connect_account: "link",
  ai_provider: "auto_awesome",
  brand_kit: "palette",
  invite_teammate: "group",
  first_post: "send",
};

export function OnboardingCard() {
  const t = useTranslations("billing.onboarding");
  const qc = useQueryClient();
  const can = useSession((s) => s.can);
  const { data } = useQuery({ queryKey: ["onboarding"], queryFn: () => api.get<Onboarding>("/onboarding") });
  const dismiss = useMutation({
    mutationFn: () => api.post<Onboarding>("/onboarding/dismiss"),
    onSuccess: (value) => qc.setQueryData(["onboarding"], value),
  });
  if (!data || data.dismissed || data.done === data.total) return null;
  const progress = Math.round((data.done / data.total) * 100);

  return (
    <Card className="mb-5">
      <div className="flex items-start gap-3">
        <div className="relative h-12 w-12 shrink-0">
          <svg viewBox="0 0 36 36" className="h-12 w-12 -rotate-90" aria-hidden>
            <circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--track)" strokeWidth="3" />
            {progress > 0 && (
              <circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--accent)" strokeWidth="3" strokeLinecap="round"
                strokeDasharray={`${(progress / 100) * 97.4} 97.4`} />
            )}
          </svg>
          <span className="absolute inset-0 flex items-center justify-center text-xs font-bold" dir="ltr">{data.done}/{data.total}</span>
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold tracking-tight">{t("title")}</h2>
          <p className="mt-0.5 text-sm text-muted">{t("subtitle", { done: data.done, total: data.total })}</p>
        </div>
        {can("admin") && <IconButton icon="close" label={t("dismiss")} onClick={() => dismiss.mutate()} />}
      </div>
      <ol className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-5">
        {data.steps.map((step) => (
          <li key={step.key}>
            <Link href={step.href}
              className={cx("flex h-full items-start gap-3 rounded-2xl p-3 transition",
                step.done ? "bg-fill text-muted" : "bg-white/70 ring-1 ring-line hover:-translate-y-0.5 hover:shadow-[var(--shadow-lift)]")}>
              <span className={cx("flex h-8 w-8 shrink-0 items-center justify-center rounded-xl",
                step.done ? "bg-ok-bg text-ok" : "bg-ink text-white")}>
                <Icon name={step.done ? "check" : ICONS[step.key] || "check"} size={16} duo={!step.done} />
              </span>
              <span className="min-w-0">
                <span className={cx("block text-sm font-semibold", step.done ? "line-through decoration-1" : "text-text")}>{t(`steps.${step.key}`)}</span>
                <span className="mt-0.5 block text-xs leading-snug text-muted">{t(`hints.${step.key}`)}</span>
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </Card>
  );
}
