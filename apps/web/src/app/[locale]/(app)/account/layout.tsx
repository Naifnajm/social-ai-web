"use client";
/** Account center: the signed-in person's own profile, security, workspaces, e-mails and data (not the company's). */
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { Icon } from "@/components/icon";
import { PageHeader, cx } from "@/components/ui";
import { Link, usePathname } from "@/i18n/navigation";
import { useSession } from "@/lib/session";

const TABS = [
  { href: "/account", label: "profile", icon: "person" },
  { href: "/account/security", label: "security", icon: "shield" },
  { href: "/account/workspaces", label: "workspaces", icon: "business_center" },
  { href: "/settings/connect", label: "apps", icon: "apps" },
  { href: "/account/notifications", label: "notifications", icon: "mail" },
  { href: "/account/data", label: "data", icon: "download" },
  { href: "/settings/billing", label: "billing", icon: "payments", owner: true },
];

export default function AccountLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("account");
  const pathname = usePathname();
  const can = useSession((s) => s.can);
  return (
    <div className="pt-2">
      <PageHeader icon="person" title={t("title")} subtitle={t("subtitle")} />
      <div className="flex flex-col gap-5 lg:flex-row">
        <nav className="flex shrink-0 gap-1 overflow-x-auto lg:w-56 lg:flex-col">
          {TABS.filter((tab) => !tab.owner || can("owner")).map((tab) => (
            <Link key={tab.href} href={tab.href}
              className={cx("flex h-10 shrink-0 items-center gap-2 rounded-xl px-3 text-sm font-medium transition",
                pathname === tab.href ? "glass text-text" : "text-text-2 hover:bg-fill-2")}>
              <Icon name={tab.icon} size={17} /> {t(`tabs.${tab.label}`)}
              {!tab.href.startsWith("/account") && <Icon name="open_in_new" size={13} className="ms-auto text-faint" />}
            </Link>
          ))}
        </nav>
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </div>
  );
}
