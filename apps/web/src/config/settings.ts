/**
 * Settings tabs. Features add their own tab here (one line; page at src/app/[locale]/(app)/settings/<x>/page.tsx;
 * label = key under "settings.tabs" in messages/<locale>/settings.json — or put the label in your own namespace
 * file and add it to settings.json at merge time).
 */
import type { Role } from "@/lib/session";

export type SettingsTab = { href: string; label: string; icon: string; order: number; minRole?: Role };

export const SETTINGS_TABS: SettingsTab[] = [
  { href: "/settings/general", label: "general", icon: "settings", order: 0, minRole: "admin" },
  { href: "/settings/members", label: "members", icon: "group", order: 10 },
  { href: "/settings/profile", label: "profile", icon: "person", order: 20 },
  { href: "/settings/billing", label: "billing", icon: "payments", order: 30, minRole: "owner" },
];
