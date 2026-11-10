"use client";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { Icon } from "@/components/icon";
import { Card, EmptyState, PageHeader, cx } from "@/components/ui";
import { Link, usePathname } from "@/i18n/navigation";
import { useSession } from "@/lib/session";

const TABS = [
  { href: "/admin", label: "overview", icon: "bar_chart" },
  { href: "/admin/settings", label: "settings", icon: "settings" },
];

/** Platform admin (superadmins only; the API enforces it too). */
export default function AdminLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("admin");
  const pathname = usePathname();
  const me = useSession((s) => s.me);
  if (!me?.user.is_superadmin) {
    return <Card className="mt-2"><EmptyState icon="lock" title={t("title")} text={t("forbidden")} /></Card>;
  }
  const active = (href: string) => (href === "/admin" ? pathname === "/admin" || pathname.startsWith("/admin/workspaces") : pathname.startsWith(href));
  return (
    <div className="pt-2">
      <PageHeader icon="verified_user" title={t("title")} subtitle={t("subtitle")} />
      <nav className="mb-5 flex gap-1 overflow-x-auto">
        {TABS.map((tab) => (
          <Link key={tab.href} href={tab.href}
            className={cx("flex h-10 shrink-0 items-center gap-2 rounded-xl px-3 text-sm font-medium transition",
              active(tab.href) ? "glass text-text" : "text-text-2 hover:bg-fill-2")}>
            <Icon name={tab.icon} size={17} /> {t(`tabs.${tab.label}`)}
          </Link>
        ))}
      </nav>
      {children}
    </div>
  );
}
