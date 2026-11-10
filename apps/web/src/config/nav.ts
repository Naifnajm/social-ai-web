/**
 * Main navigation. Each feature adds its entries here (one line each, keep the `order` numbers unique).
 * `label` is a key in messages/<locale>/nav.json. Paths are relative to the locale (e.g. "/inbox").
 */
import { type Role, useSession } from "@/lib/session";

export type NavItem = {
  href: string;
  label: string;
  icon: string;
  order: number;
  minRole?: Role;
  group?: "main" | "plan" | "results" | "settings";
  mobile?: boolean; // shown in the phone bottom bar
  superadmin?: boolean; // platform administrators only (whatever their workspace role)
};

export const NAV: NavItem[] = [
  { href: "/", label: "home", icon: "apps", order: 0, group: "main", mobile: true },
  { href: "/studio", label: "studio", icon: "wand_stars", order: 10, group: "main", mobile: true },
  { href: "/quick", label: "quick", icon: "bolt", order: 12, group: "main", mobile: true, minRole: "editor" },
  { href: "/inbox", label: "inbox", icon: "inbox", order: 14, group: "main", mobile: true },
  { href: "/production", label: "production", icon: "account_tree", order: 16, group: "main" },
  { href: "/posts", label: "posts", icon: "view_list", order: 18, group: "main" },
  { href: "/library", label: "library", icon: "photo_library", order: 19, group: "main" },
  { href: "/planner", label: "planner", icon: "calendar_today", order: 30, group: "plan", mobile: true },
  { href: "/campaigns", label: "campaigns", icon: "campaign", order: 32, group: "plan" },
  { href: "/approvals", label: "approvals", icon: "verified_user", order: 34, group: "plan", minRole: "approver" },
  { href: "/performance", label: "performance", icon: "bar_chart", order: 50, group: "results" },
  { href: "/links", label: "links", icon: "link", order: 52, group: "results" },
  { href: "/reports", label: "reports", icon: "description", order: 54, group: "results", minRole: "admin" },
  { href: "/ai-costs", label: "aiCosts", icon: "payments", order: 56, group: "results", minRole: "admin" },
  { href: "/settings/general", label: "settings", icon: "settings", order: 900, group: "settings", minRole: "admin" },
  { href: "/admin", label: "admin", icon: "verified_user", order: 990, group: "settings", superadmin: true },
];

export const sortedNav = (role: (r: Role) => boolean) =>
  NAV.filter((item) => (!item.minRole || role(item.minRole)) && (!item.superadmin || !!useSession.getState().me?.user.is_superadmin))
    .sort((a, b) => a.order - b.order);
