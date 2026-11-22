"use client";
/** Account center › Workspaces: every workspace the person is in, their role and the plan; switch or leave. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Icon } from "@/components/icon";
import { Badge, Button, Card, SectionTitle, Spinner, toast } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { type Me, useSession } from "@/lib/session";

type MyWorkspace = { workspace_id: number; name: string; role: string; plan: string; status: string; members: number; sole_owner: boolean };

export default function AccountWorkspacesPage() {
  const t = useTranslations("account.workspaces");
  const tr = useTranslations("settings.roles");
  const ts = useTranslations("shell.plan");
  const client = useQueryClient();
  const { workspace, switchWorkspace, setMe } = useSession();
  const list = useQuery({ queryKey: ["account-workspaces"], queryFn: () => api.get<MyWorkspace[]>("/account/workspaces") });
  const leave = async (w: MyWorkspace) => {
    if (!window.confirm(t("leaveConfirm", { name: w.name }))) return;
    try {
      await api.post(`/account/workspaces/${w.workspace_id}/leave`);
      toast.success(t("left"));
      setMe(await api.get<Me>("/auth/me"));
      if (w.workspace_id === workspace?.id) window.location.reload();
      client.invalidateQueries({ queryKey: ["account-workspaces"] });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : String(err));
    }
  };
  return (
    <Card>
      <SectionTitle icon="business_center" actions={<Link href="/workspaces/new"><Button size="sm" icon="add">{t("new")}</Button></Link>}>{t("title")}</SectionTitle>
      {!list.data ? <div className="flex justify-center py-10"><Spinner /></div> : (
        <ul className="divide-y divide-line/60">
          {list.data.map((w) => (
            <li key={w.workspace_id} className="flex flex-wrap items-center gap-3 py-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-ink text-sm font-bold text-white">{w.name.slice(0, 1).toUpperCase()}</span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 font-semibold">
                  {w.name}
                  {w.workspace_id === workspace?.id && <Badge tone="ink">{t("current")}</Badge>}
                  {w.status !== "active" && <Badge tone="bad">{w.status}</Badge>}
                </div>
                <div className="text-xs text-muted">{tr(w.role)} · {ts.has(w.plan) ? ts(w.plan) : w.plan} · {t("members", { n: w.members })}</div>
                {w.sole_owner && <div className="mt-1 flex items-center gap-1 text-xs text-warn"><Icon name="info" size={13} /> {t("soleOwner")}</div>}
              </div>
              <div className="flex gap-2">
                {w.workspace_id !== workspace?.id && <Button size="sm" onClick={() => switchWorkspace(w.workspace_id).then(() => window.location.assign("/"))}>{t("switch")}</Button>}
                <Button size="sm" variant="ghost" disabled={w.sole_owner || list.data.length < 2} onClick={() => leave(w)}>{t("leave")}</Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
