"use client";
import { useTranslations } from "next-intl";
import { Badge } from "../ui";

export type AdminUser = {
  id: number; name: string; email: string; username: string | null; is_active: boolean; is_superadmin: boolean;
  email_verified: boolean; totp_enabled: boolean; must_change_password: boolean; deleted_at: string | null;
  last_login_at: string | null; created_at: string; workspaces: string[]; plans: string[];
};
export function UserBadges({ user }: { user: AdminUser }) {
  const t = useTranslations("adminUsers.badges");
  return (
    <div className="flex flex-wrap gap-1.5">
      {user.deleted_at ? <Badge tone="bad">{t("deleted")}</Badge> : <Badge tone={user.is_active ? "ok" : "bad"}>{user.is_active ? t("active") : t("disabled")}</Badge>}
      {user.is_superadmin && <Badge tone="ink">{t("admin")}</Badge>}
      {!user.deleted_at && !user.email_verified && <Badge tone="warn">{t("unverified")}</Badge>}
      {user.totp_enabled && <Badge tone="ok">{t("twoFactor")}</Badge>}
      {user.must_change_password && <Badge tone="warn">{t("mustChange")}</Badge>}
    </div>
  );
}

