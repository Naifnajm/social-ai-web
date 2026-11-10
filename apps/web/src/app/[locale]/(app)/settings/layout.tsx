"use client";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { Icon } from "@/components/icon";
import { PageHeader, cx } from "@/components/ui";
import { SETTINGS_TABS } from "@/config/settings";
import { Link, usePathname } from "@/i18n/navigation";
import { useSession } from "@/lib/session";

export default function SettingsLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("settings");
  const pathname = usePathname();
  const can = useSession((s) => s.can);
  const tabs = SETTINGS_TABS.filter((tab) => !tab.minRole || can(tab.minRole)).sort((a, b) => a.order - b.order);
  return (
    <div className="pt-2">
      <PageHeader icon="settings" title={t("title")} subtitle={t("subtitle")} />
      <div className="flex flex-col gap-5 lg:flex-row">
        <nav className="flex shrink-0 gap-1 overflow-x-auto lg:w-56 lg:flex-col">
          {tabs.map((tab) => (
            <Link key={tab.href} href={tab.href}
              className={cx("flex h-10 shrink-0 items-center gap-2 rounded-xl px-3 text-sm font-medium transition",
                pathname === tab.href ? "glass text-text" : "text-text-2 hover:bg-fill-2")}>
              <Icon name={tab.icon} size={17} /> {t(`tabs.${tab.label}`)}
            </Link>
          ))}
        </nav>
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </div>
  );
}
