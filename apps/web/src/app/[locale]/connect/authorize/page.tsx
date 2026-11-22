"use client";
/**
 * OAuth consent page for AI assistants (Claude, ChatGPT, MCP clients). The API's /oauth2/authorize validates the
 * request and sends the browser here with ?request=…; the signed-in user picks the workspace and what the app may do,
 * then approves or denies. Signed-out users go through the login page and come back.
 */
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { BrandLogo, BrandMark } from "@/components/brand-mark";
import { Icon } from "@/components/icon";
import { Button, Select, Spinner, cx } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";

type Scope = { key: string; label: string; selected: boolean; sensitive: boolean };
type Workspace = { id: number; name: string; role: string; active: boolean; plan_ok: boolean };
type RequestInfo = {
  client: { name: string; verified_host: string | null; client_uri: string | null; redirect_host: string | null; redirect_uri: string; loopback_only: boolean; kind: string };
  scopes: Scope[];
  workspaces: Workspace[];
  current_workspace_id: number | null;
  user: { name: string; email: string };
};

export default function ConnectAuthorizePage() {
  return (
    <Suspense fallback={<Shell><div className="flex justify-center py-16"><Spinner /></div></Shell>}>
      <Consent />
    </Suspense>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative min-h-screen overflow-hidden bg-[#f6f6f8] px-4 py-8 sm:py-14">
      <div className="pointer-events-none absolute -top-48 start-1/2 h-[520px] w-[720px] -translate-x-1/2 rounded-full bg-[radial-gradient(closest-side,rgba(255,61,139,.18),transparent)] rtl:translate-x-1/2" />
      <div className="relative mx-auto w-full max-w-[500px]">
        <div className="mb-6 flex justify-center"><BrandLogo size={30} /></div>
        {children}
      </div>
    </div>
  );
}

function Consent() {
  const t = useTranslations("connect.authorize");
  const router = useRouter();
  const params = useSearchParams();
  const requestId = params.get("request") || "";
  const presetError = params.get("error");
  const info = useQuery({
    queryKey: ["connect-request", requestId],
    queryFn: () => api.get<RequestInfo>("/connect/authorize/request", { request: requestId }),
    enabled: !!requestId && !presetError,
    retry: false,
  });
  const unauthenticated = info.error instanceof ApiError && info.error.status === 401;
  useEffect(() => {
    if (unauthenticated) router.replace(`/login?next=${encodeURIComponent(`/connect/authorize?request=${requestId}`)}`);
  }, [unauthenticated, requestId, router]);

  if (presetError || !requestId || (info.error && !unauthenticated)) {
    const code = presetError || (info.error instanceof ApiError ? info.error.code : "generic");
    const known = ["invalid_client", "invalid_redirect_uri", "request_expired"].includes(code) ? code : "generic";
    return (
      <Shell>
        <section className="glass-strong rounded-[28px] p-7 text-center shadow-[var(--shadow-float)]">
          <span className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-bad-bg text-bad"><Icon name="error" size={24} /></span>
          <h1 className="text-lg font-bold tracking-tight">{t("errorTitle")}</h1>
          <p className="mt-2 text-sm text-muted">{t(`errors.${known}`)}</p>
          <Link href="/" className="mt-6 inline-flex h-10 items-center rounded-full px-4 text-sm font-medium text-text-2 hover:bg-fill-2">{t("back")}</Link>
        </section>
      </Shell>
    );
  }
  if (!info.data) return <Shell><div className="flex justify-center py-16"><Spinner /></div></Shell>;
  return <Shell><ConsentCard info={info.data} requestId={requestId} /></Shell>;
}

function ConsentCard({ info, requestId }: { info: RequestInfo; requestId: string }) {
  const t = useTranslations("connect.authorize");
  const usable = info.workspaces.filter((w) => w.plan_ok);
  const [workspaceId, setWorkspaceId] = useState<number | null>(
    usable.find((w) => w.id === info.current_workspace_id)?.id ?? usable[0]?.id ?? null);
  const [chosen, setChosen] = useState<string[]>(info.scopes.filter((s) => s.selected || s.key === "read").map((s) => s.key));
  const [busy, setBusy] = useState<"approve" | "deny" | null>(null);
  const [leaving, setLeaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const workspace = info.workspaces.find((w) => w.id === workspaceId);
  const host = info.client.redirect_host || "";
  const initial = useMemo(() => (info.client.name.trim()[0] || "?").toUpperCase(), [info.client.name]);

  const decide = async (approve: boolean) => {
    setBusy(approve ? "approve" : "deny");
    setError(null);
    try {
      const out = await api.post<{ redirect_url: string }>("/connect/authorize/decision",
        { request: requestId, approve, workspace_id: approve ? workspaceId : null, scopes: chosen });
      setLeaving(true);
      window.location.assign(out.redirect_url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setBusy(null);
    }
  };

  if (leaving) {
    return (
      <section className="glass-strong flex flex-col items-center gap-3 rounded-[28px] p-10 text-center shadow-[var(--shadow-float)]">
        <Spinner />
        <p className="text-sm text-muted">{t("redirecting", { host })}</p>
      </section>
    );
  }

  const toggle = (key: string) => setChosen((list) => list.includes(key) ? list.filter((k) => k !== key) : [...list, key]);
  return (
    <section className="glass-strong overflow-hidden rounded-[28px] shadow-[var(--shadow-float)]">
      <div className="px-6 pb-5 pt-7 sm:px-8">
        <div className="mb-5 flex items-center justify-center gap-3" dir="ltr">
          <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-ink text-xl font-bold text-white shadow-[0_10px_24px_-12px_rgba(0,0,0,.6)]">{initial}</span>
          <span className="flex items-center gap-1 text-faint"><span className="h-1 w-1 rounded-full bg-current" /><Icon name="swap_horiz" size={18} /><span className="h-1 w-1 rounded-full bg-current" /></span>
          <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white shadow-[var(--shadow)]"><BrandMark size={34} /></span>
        </div>
        <h1 className="text-center text-xl font-bold leading-snug tracking-tight">
          {t.rich("title", { client: info.client.name, b: (chunks) => <span className="text-accent-deep">{chunks}</span> })}
        </h1>
        <p className="mt-2 text-center text-[13px] text-muted">
          {t("signedInAs", { name: info.user.name })} · <span dir="ltr">{info.user.email}</span>
        </p>

        <div className="mt-5 rounded-2xl border border-line bg-white/70 p-3.5 text-[13px]">
          <div className="flex items-center gap-2">
            <Icon name={info.client.verified_host ? "verified_user" : "info"} size={17} className={info.client.verified_host ? "text-ok" : "text-muted"} />
            <span className="text-text-2">{info.client.verified_host ? t("verifiedBy", { host: info.client.verified_host }) : t("selfDeclared")}</span>
          </div>
          <div className="mt-2 flex items-center gap-2">
            <Icon name="open_in_new" size={17} className="text-muted" />
            <span className="text-text-2">{t("returnTo")}</span>
            <b className="ms-auto rounded-lg bg-fill-2 px-2 py-0.5 font-mono text-[12.5px] font-semibold text-text" dir="ltr">{host}</b>
          </div>
        </div>
        {info.client.loopback_only && (
          <div className="mt-3 flex gap-2 rounded-2xl bg-warn-bg p-3.5 text-[13px] text-warn">
            <Icon name="warning" size={17} className="mt-px shrink-0" />
            <span>{t("loopbackWarning", { host })}</span>
          </div>
        )}

        <div className="mt-6">
          <label className="mb-1.5 block text-[13px] font-semibold">{t("workspace")}</label>
          {usable.length ? (
            <Select value={workspaceId ?? ""} onChange={(e) => setWorkspaceId(Number(e.target.value))}>
              {info.workspaces.map((w) => (
                <option key={w.id} value={w.id} disabled={!w.plan_ok}>{w.name}{w.plan_ok ? "" : ` — ${t("planMissing")}`}</option>
              ))}
            </Select>
          ) : (
            <p className="rounded-2xl bg-warn-bg p-3.5 text-[13px] text-warn">{t("noWorkspace")}</p>
          )}
          <p className="mt-1.5 text-xs text-muted">{t("workspaceHint")}</p>
        </div>

        <div className="mt-6">
          <div className="mb-2 text-[13px] font-semibold">{t("permissions")}</div>
          <ul className="flex flex-col gap-2">
            {info.scopes.map((scope) => {
              const fixed = scope.key === "read";
              const on = fixed || chosen.includes(scope.key);
              return (
                <li key={scope.key}>
                  <label className={cx("flex cursor-pointer items-start gap-3 rounded-2xl border p-3.5 transition",
                    on ? (scope.sensitive ? "border-accent/40 bg-accent-soft" : "border-ink/15 bg-white") : "border-line bg-white/50 hover:bg-white",
                    fixed && "cursor-default")}>
                    <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 accent-[#ff3d8b]" checked={on} disabled={fixed}
                      onChange={() => toggle(scope.key)} />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-1.5 text-sm font-semibold">
                        {t(`scope.${scope.key}`)}
                        {fixed && <span className="rounded-full bg-fill-2 px-2 py-0.5 text-[11px] font-semibold text-text-2">{t("required")}</span>}
                        {scope.key === "publish" && <SensitiveTag icon="send" text={t("publicWarning")} />}
                        {scope.key === "inbox" && <SensitiveTag icon="forum" text={t("peopleWarning")} />}
                      </span>
                      <span className="mt-0.5 block text-[13px] leading-relaxed text-muted">{scope.label}</span>
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
          {workspace && (
            <p className="mt-3 flex items-start gap-1.5 text-xs text-muted">
              <Icon name="shield" size={14} className="mt-px shrink-0" />
              {workspace.role === "viewer" ? t("viewerNote") : t("roleNote", { role: t(`roles.${workspace.role}`) })}
            </p>
          )}
        </div>
        {error && <p className="mt-4 rounded-2xl bg-bad-bg p-3 text-[13px] text-bad">{error}</p>}
      </div>
      <div className="flex flex-col-reverse gap-2 border-t border-line bg-white/60 px-6 py-4 sm:flex-row sm:justify-end sm:px-8">
        <Button variant="secondary" size="lg" loading={busy === "deny"} disabled={!!busy} onClick={() => decide(false)}>{t("deny")}</Button>
        <button type="button" disabled={!!busy || !workspaceId} onClick={() => decide(true)}
          className="inline-flex h-12 items-center justify-center gap-1.5 rounded-full bg-accent px-6 text-[15px] font-semibold text-white shadow-[0_10px_24px_-10px_rgba(255,61,139,.9)] transition hover:bg-accent-deep disabled:pointer-events-none disabled:opacity-50">
          {busy === "approve" ? <Icon name="progress_activity" spin size={16} /> : <Icon name="check" size={16} />}
          {t("approve")}
        </button>
      </div>
      <p className="border-t border-line px-6 py-3.5 text-center text-[12px] leading-relaxed text-muted sm:px-8">{t("footer")}</p>
    </section>
  );
}

function SensitiveTag({ icon, text }: { icon: string; text: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-accent px-2 py-0.5 text-[11px] font-semibold text-white">
      <Icon name={icon} size={11} />{text}
    </span>
  );
}
