/**
 * Settings tabs. Features add their own tab here (one line; page at src/app/[locale]/(app)/settings/<x>/page.tsx;
 * label = key under "settings.tabs" in messages/<locale>/settings.json — or put the label in your own namespace
 * file and add it to settings.json at merge time).
 */
import type { Role } from "@/lib/session";

export type SettingsTab = { href: string; label: string; icon: string; order: number; minRole?: Role };

export const SETTINGS_TABS: SettingsTab[] = [
  { href: "/settings/general", label: "general", icon: "settings", order: 0, minRole: "admin" },
  { href: "/settings/accounts", label: "accounts", icon: "link", order: 5 },
  { href: "/settings/members", label: "members", icon: "group", order: 10 },
  { href: "/settings/ai", label: "ai", icon: "smart_toy", order: 20, minRole: "admin" },
  { href: "/settings/brand", label: "brand", icon: "branding", order: 22 },
  { href: "/settings/templates", label: "templates", icon: "photo_frame", order: 24, minRole: "editor" },
  { href: "/settings/inbox", label: "inbox", icon: "forum", order: 26, minRole: "admin" },
  { href: "/settings/pillars", label: "pillars", icon: "flag", order: 28, minRole: "admin" },
  { href: "/settings/billing", label: "billing", icon: "payments", order: 40, minRole: "owner" },
  { href: "/settings/profile", label: "profile", icon: "person", order: 50 },
];
