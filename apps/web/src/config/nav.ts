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
  { href: "/quick", label: "quick", icon: "bolt", order: 15, group: "main", mobile: true, minRole: "editor" },
  { href: "/inbox", label: "inbox", icon: "inbox", order: 20, group: "main", mobile: true },
  { href: "/studio", label: "studio", icon: "wand_stars", order: 10, group: "main", mobile: true },
  { href: "/posts", label: "posts", icon: "view_list", order: 20, group: "main" },
  { href: "/approvals", label: "approvals", icon: "verified_user", order: 310, group: "plan", minRole: "approver" },
  { href: "/performance", label: "performance", icon: "bar_chart", order: 500, group: "results" },
  { href: "/settings/general", label: "settings", icon: "settings", order: 900, group: "settings", minRole: "admin" },
  { href: "/admin", label: "admin", icon: "verified_user", order: 990, group: "settings", superadmin: true },
];

export const sortedNav = (role: (r: Role) => boolean) =>
  NAV.filter((item) => (!item.minRole || role(item.minRole)) && (!item.superadmin || !!useSession.getState().me?.user.is_superadmin))
    .sort((a, b) => a.order - b.order);
