"use client";
import { useTranslations } from "next-intl";
import { OnboardingCard } from "@/components/billing/onboarding-card";
import { Icon } from "@/components/icon";
import { Card, PageHeader } from "@/components/ui";
import { sortedNav } from "@/config/nav";
import { Link } from "@/i18n/navigation";
import { useSession } from "@/lib/session";

/** Home: greeting + a shortcut card for every feature (features register themselves in config/nav.ts). */
export default function HomePage() {
  const t = useTranslations("home");
  const nav = useTranslations("nav");
  const { me, workspace, can } = useSession();
  const items = sortedNav(can).filter((i) => i.href !== "/" && i.group !== "settings");
  return (
    <div className="pt-2">
      <PageHeader icon="auto_awesome" title={t("hello", { name: me?.user.name.split(" ")[0] ?? "" })} subtitle={t("subtitle", { workspace: workspace?.name ?? "" })} />
      <OnboardingCard />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {items.map((item) => (
          <Link key={item.href} href={item.href}>
            <Card className="h-full transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-lift)]">
              <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-fill-2">
                <Icon name={item.icon} size={22} duo />
              </span>
              <div className="font-semibold">{nav(item.label)}</div>
              <p className="mt-1 text-sm text-muted">{t.has(`cards.${item.label}`) ? t(`cards.${item.label}`) : ""}</p>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
