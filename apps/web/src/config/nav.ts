/**
 * Main navigation. Each feature adds its entries here (one line each, keep the `order` numbers unique).
 * `label` is a key in messages/<locale>/nav.json. Paths are relative to the locale (e.g. "/inbox").
 */
import type { Role } from "@/lib/session";

export type NavItem = {
  href: string;
  label: string;
  icon: string;
  order: number;
  minRole?: Role;
  group?: "main" | "plan" | "results" | "settings";
  mobile?: boolean; // shown in the phone bottom bar
};

export const NAV: NavItem[] = [
  { href: "/", label: "home", icon: "apps", order: 0, group: "main", mobile: true },
  { href: "/production", label: "production", icon: "account_tree", order: 40, group: "main", mobile: false },
  { href: "/settings/general", label: "settings", icon: "settings", order: 900, group: "settings", minRole: "admin" },
];

export const sortedNav = (role: (r: Role) => boolean) =>
  NAV.filter((item) => !item.minRole || role(item.minRole)).sort((a, b) => a.order - b.order);
