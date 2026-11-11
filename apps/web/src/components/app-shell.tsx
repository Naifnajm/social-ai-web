"use client";
/** The signed-in layout: sidebar (desktop) / bottom bar (phone), workspace switcher, notifications, user menu. */
import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { type ReactNode, useEffect, useState } from "react";
import { Link, usePathname, useRouter } from "@/i18n/navigation";
import { LOCALE_NAMES, routing } from "@/i18n/routing";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { sortedNav } from "@/config/nav";
import { BillingOverlay } from "./billing/billing-overlay";
import { SupportDialog } from "./support/support-dialog";
import { Icon } from "./icon";
import { BrandLogo } from "./brand-mark";
import { Avatar, Spinner, cx } from "./ui";

export function AppShell({ children }: { children: ReactNode }) {
  const { me, workspace, loading, load, can } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const t = useTranslations("nav");

  useEffect(() => {
    if (!me) {
      load().then((result) => {
        // signed-out visitors of the home page see the marketing page
        if (!result) router.replace(pathname === "/" ? "/welcome" : `/login?next=${encodeURIComponent(pathname)}`);
      });
    }
  }, [me, load, router, pathname]);

  if (loading || !me || !workspace) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner size={28} />
      </div>
    );
  }

  const items = sortedNav(can);
  const active = (href: string) => (href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(href + "/"));

  return (
    <div className="flex min-h-screen">
      <aside className="glass sticky top-3 m-3 hidden h-[calc(100vh-24px)] w-[232px] shrink-0 flex-col rounded-[22px] p-3 lg:flex">
        <div className="mb-2 px-2 pt-1 text-[13px]"><BrandLogo size={24} /></div>
        <WorkspaceSwitcher />
        <nav className="mt-3 flex flex-1 flex-col gap-0.5 overflow-y-auto">
          {items.map((item, index) => (
            <div key={item.href}>
              {index > 0 && items[index - 1].group !== item.group && <div className="mx-2 my-2 h-px bg-line" />}
              <Link
                href={item.href}
                className={cx(
                  "flex h-10 items-center gap-2.5 rounded-xl px-3 text-sm font-medium transition",
                  active(item.href) ? "bg-ink text-white shadow-[0_6px_16px_-8px_rgba(0,0,0,.6)]" : "text-text-2 hover:bg-fill-2 hover:text-text",
                )}
              >
                <Icon name={item.icon} size={18} duo={active(item.href)} className={active(item.href) ? "text-[#ff8fbc]" : undefined} />
                {t(item.label)}
              </Link>
            </div>
          ))}
        </nav>
        <UserMenu />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 px-4 lg:px-6">
          <div className="lg:hidden">
            <WorkspaceSwitcher compact />
          </div>
          <div className="ms-auto flex items-center gap-1">
            <NotificationsBell />
            <div className="lg:hidden">
              <UserMenu compact />
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 pb-28 lg:px-6 lg:pb-10">
          <BillingOverlay />
          <SupportDialog />
          {children}
        </main>
      </div>

      <nav className="glass-strong fixed inset-x-3 bottom-3 z-40 flex justify-around rounded-[22px] px-2 py-1.5 lg:hidden">
        {items.filter((i) => i.mobile).slice(0, 5).map((item) => (
          <Link key={item.href} href={item.href} className={cx("flex flex-col items-center gap-0.5 rounded-xl px-3 py-1 text-[11px]", active(item.href) ? "text-accent-deep font-semibold" : "text-muted")}>
            <Icon name={item.icon} size={22} duo={active(item.href)} />
            {t(item.label)}
          </Link>
        ))}
      </nav>
    </div>
  );
}

function WorkspaceSwitcher({ compact = false }: { compact?: boolean }) {
  const { me, workspace, switchWorkspace } = useSession();
  const [open, setOpen] = useState(false);
  const t = useTranslations("shell");
  if (!me || !workspace) return null;
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} className={cx("flex w-full items-center gap-2.5 rounded-2xl p-2 text-start transition hover:bg-fill-2", compact && "p-1.5")}>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-ink text-sm font-bold text-white">{workspace.name.slice(0, 1).toUpperCase()}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold">{workspace.name}</span>
          {!compact && <span className="block truncate text-xs text-muted">{t(`plan.${workspace.plan_code}`)}</span>}
        </span>
        <Icon name="expand_more" size={16} className="text-muted" />
      </button>
      {open && (
        <div className="glass-strong pop-in absolute start-0 top-full z-50 mt-1 w-64 rounded-2xl p-1.5">
          {me.workspaces.map((w) => (
            <button key={w.workspace_id} onClick={() => { setOpen(false); switchWorkspace(w.workspace_id).then(() => window.location.reload()); }}
              className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-start text-sm hover:bg-fill-2">
              <span className="flex-1 truncate">{w.workspace_name}</span>
              {w.workspace_id === workspace.id && <Icon name="check" size={16} />}
            </button>
          ))}
          <div className="my-1 h-px bg-line" />
          <Link href="/workspaces/new" onClick={() => setOpen(false)} className="flex items-center gap-2 rounded-xl px-3 py-2 text-sm hover:bg-fill-2">
            <Icon name="add" size={16} /> {t("newWorkspace")}
          </Link>
        </div>
      )}
    </div>
  );
}

function NotificationsBell() {
  const t = useTranslations("shell");
  const { data } = useQuery({ queryKey: ["notifications-count"], queryFn: () => api.get<{ unread: number }>("/notifications/count"), refetchInterval: 30000 });
  return (
    <Link href="/notifications" className="relative inline-flex h-10 w-10 items-center justify-center rounded-full text-text-2 hover:bg-fill-2" aria-label={t("notifications")}>
      <Icon name="mail" size={20} />
      {!!data?.unread && (
        <span className="absolute end-1 top-1 min-w-[18px] rounded-full bg-ink px-1 text-center text-[10px] font-bold leading-[18px] text-white">{data.unread > 99 ? "99+" : data.unread}</span>
      )}
    </Link>
  );
}

function UserMenu({ compact = false }: { compact?: boolean }) {
  const { me, clear } = useSession();
  const [open, setOpen] = useState(false);
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const t = useTranslations("shell");
  if (!me) return null;
  const logout = async () => {
    await api.post("/auth/logout").catch(() => undefined);
    clear();
    router.replace("/login");
  };
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} className={cx("flex w-full items-center gap-2.5 rounded-2xl p-2 text-start hover:bg-fill-2", compact && "p-1")}>
        <Avatar name={me.user.name} src={me.user.avatar_url} size={compact ? 32 : 34} />
        {!compact && (
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold">{me.user.name}</span>
            <span className="block truncate text-xs text-muted">{me.user.email}</span>
          </span>
        )}
      </button>
      {open && (
        <div className={cx("glass-strong pop-in absolute z-50 w-56 rounded-2xl p-1.5", compact ? "end-0 top-full mt-1" : "bottom-full start-0 mb-1")}>
          <Link href="/settings/profile" onClick={() => setOpen(false)} className="flex items-center gap-2 rounded-xl px-3 py-2 text-sm hover:bg-fill-2">
            <Icon name="person" size={16} /> {t("profile")}
          </Link>
          <Link href="/settings/support" onClick={() => setOpen(false)} className="flex items-center gap-2 rounded-xl px-3 py-2 text-sm hover:bg-fill-2">
            <Icon name="support_agent" size={16} /> {t("support")}
          </Link>
          <div className="my-1 h-px bg-line" />
          <div className="flex flex-wrap gap-1 px-1.5 py-1" role="group" aria-label="Language">
            {routing.locales.map((code) => (
              <button key={code} title={LOCALE_NAMES[code]} aria-pressed={code === locale}
                onClick={() => { if (code === locale) return; api.patch("/auth/me", { locale: code }).catch(() => undefined); router.replace(pathname, { locale: code }); }}
                className={cx("rounded-lg px-2 py-1 text-xs font-semibold uppercase", code === locale ? "bg-accent-soft text-accent-deep" : "text-muted hover:bg-fill-2 hover:text-text")}>
                {code}
              </button>
            ))}
          </div>
          <div className="my-1 h-px bg-line" />
          <button onClick={logout} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-start text-sm text-bad hover:bg-bad-bg">
            <Icon name="outbox" size={16} /> {t("logout")}
          </button>
        </div>
      )}
    </div>
  );
}
