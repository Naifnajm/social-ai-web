"use client";
/**
 * Radar sources: the status pill, the cost line and the button that fixes a source (connect an account, ask the
 * platform admin for a key, request a Meta/Google permission, edit the setup, buy credits, upgrade, test again).
 *
 *   const sources = useRadarSources(queryId);   // GET /listening/sources
 *   <StatusPill status={row.health.status} />  <FixButton row={row} queryId={queryId} />
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon } from "@/components/icon";
import { onError, useFormat } from "@/components/planning/ui";
import { ConnectDialog, type ConnectView, startOAuth } from "@/components/publishing/connect-dialog";
import type { PlatformOption } from "@/components/publishing/types";
import { Badge, Button, Modal, toast } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { HealthStatus, SourceRow, SourcesOut } from "./types";

export const useRadarSources = (queryId: number | null, enabled = true) =>
  useQuery({
    queryKey: ["radar", "sources", queryId],
    queryFn: () => api.get<SourcesOut>("/listening/sources", queryId ? { query_id: queryId } : undefined),
    enabled,
  });

const TONE: Record<HealthStatus, "ok" | "warn" | "bad" | "neutral"> = {
  ready: "ok", needs_connection: "warn", needs_key: "warn", needs_permission: "warn", needs_setup: "warn",
  quota_exhausted: "warn", out_of_credits: "bad", not_in_plan: "neutral", disabled: "neutral", error: "bad",
};
const STATUS_ICON: Record<HealthStatus, string> = {
  ready: "check_circle", needs_connection: "link", needs_key: "key", needs_permission: "verified_user", needs_setup: "settings",
  quota_exhausted: "schedule", out_of_credits: "wallet", not_in_plan: "lock", disabled: "block", error: "error",
};

export function StatusPill({ status }: { status: HealthStatus }) {
  const t = useTranslations("radar.sourcesPage.status");
  return <Badge tone={TONE[status]}><Icon name={STATUS_ICON[status]} size={11} />{t(status)}</Badge>;
}

/** "Free" or "≈ $5.50 per 1,000 queries, charged from AI credits" (or "your own key: not charged"). */
export function CostLine({ row }: { row: SourceRow }) {
  const t = useTranslations("radar.sourcesPage");
  const fmt = useFormat();
  if (row.cost.own_key) return <span className="text-ok">{t("cost.ownKey")}</span>;
  if (row.cost.free || !row.cost.unit) return <span>{row.quota ? t("cost.freeQuota") : t("cost.free")}</span>;
  return <span>{t("cost.paid", { price: `$${fmt.number(row.cost.per_1000, 2)}`, unit: t(`units.${row.cost.unit}`) })}</span>;
}

/** The button that does the fix for the source's current state. */
export function FixButton({ row, queryId }: { row: SourceRow; queryId: number | null }) {
  const t = useTranslations("radar.sourcesPage");
  const qc = useQueryClient();
  const isSuper = useSession((s) => !!s.me?.user.is_superadmin);
  const canEdit = useSession((s) => s.can("editor"));
  const [connect, setConnect] = useState<ConnectView | null>(null);
  const [explain, setExplain] = useState(false);
  const action = row.health.action;
  const test = useMutation({
    mutationFn: () => api.post<{ health: { status: HealthStatus }; result: { new: number; error: string | null } | null }>(`/listening/sources/${row.key}/test`, { query_id: queryId }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["radar"] });
      if (r.result?.error) toast.error(r.result.error);
      else if (r.result) toast.success(t("tested", { n: r.result.new }));
      else toast.success(t("checked"));
    },
    onError,
  });
  const openConnect = async (platform: string) => {
    try {
      const platforms = await qc.fetchQuery({ queryKey: ["account-platforms"], queryFn: () => api.get<PlatformOption[]>("/accounts/platforms") });
      const option = platforms.find((o) => o.key === platform);
      if (!option) return setConnect({ kind: "list" });
      if (option.method === "token") return setConnect({ kind: "token", platform });
      if (!option.configured) return setConnect({ kind: "setup", platform });
      await startOAuth(platform);
    } catch (err) {
      onError(err);
    }
  };
  if (!action || !row.available) {
    return row.health.status === "ready" && canEdit && row.in_query
      ? <Button size="sm" variant="ghost" icon="refresh" loading={test.isPending} onClick={() => test.mutate()}>{t("actions.test")}</Button>
      : null;
  }
  let button = null;
  switch (action.kind) {
    case "connect":
      button = canEdit && <Button size="sm" variant="primary" icon="link" onClick={() => openConnect(action.platform)}>{t("actions.connect")}</Button>;
      break;
    case "ask_admin":
      button = <Button size="sm" icon="support_agent" onClick={() => setExplain(true)}>{isSuper ? t("actions.addKey") : t("actions.askAdmin")}</Button>;
      break;
    case "request_permission":
      button = <Button size="sm" icon="verified_user" onClick={() => setExplain(true)}>{t("actions.permission")}</Button>;
      break;
    case "edit_setup":
      button = <Link href="/radar/setup"><Button size="sm" icon="settings">{t("actions.editSetup")}</Button></Link>;
      break;
    case "buy_credits":
    case "upgrade":
      button = <Link href="/settings/billing"><Button size="sm" variant="primary" icon={action.kind === "upgrade" ? "rocket_launch" : "wallet"}>{t(action.kind === "upgrade" ? "actions.upgrade" : "actions.buyCredits")}</Button></Link>;
      break;
    case "test":
      button = canEdit && <Button size="sm" icon="refresh" loading={test.isPending} onClick={() => test.mutate()}>{t("actions.test")}</Button>;
      break;
  }
  return (
    <>
      {button}
      {connect && <ConnectDialog key={JSON.stringify(connect)} initial={connect} open onClose={() => { setConnect(null); qc.invalidateQueries({ queryKey: ["radar"] }); }} />}
      {explain && (
        <Modal open onClose={() => setExplain(false)} size="sm" title={action.kind === "request_permission" ? t("permissionTitle") : t("adminTitle")}
          footer={<>
            <Button variant="ghost" onClick={() => setExplain(false)}>{t("close")}</Button>
            {isSuper && <Link href="/admin/radar"><Button variant="primary" icon="key">{t("openAdmin")}</Button></Link>}
          </>}>
          <p className="text-sm leading-relaxed">{row.health.message}</p>
          {action.kind === "request_permission" && (
            <>
              <p className="mt-3 text-sm text-text-2">{t("permissionText", { permission: action.permission })}</p>
              {action.doc && <a className="mt-2 inline-flex items-center gap-1 text-sm font-semibold underline" href={action.doc} target="_blank" rel="noopener noreferrer"><Icon name="open_in_new" size={14} />{t("permissionDoc")}</a>}
            </>
          )}
          {action.kind === "ask_admin" && <p className="mt-3 text-sm text-text-2">{isSuper ? t("adminSelf") : t("adminText", { what: action.what })}</p>}
        </Modal>
      )}
    </>
  );
}
