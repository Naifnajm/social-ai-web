"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Avatar, Badge, Button, Card, Field, IconButton, Input, Modal, SectionTitle, Select, toast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { type Role, useSession } from "@/lib/session";

type Member = { id: number; user_id: number; name: string; email: string; role: Role; avatar_url?: string | null };
type Invitation = { id: number; email: string; role: Role; expires_at: string };
const ROLES: Role[] = ["viewer", "editor", "approver", "admin", "owner"];

export default function MembersPage() {
  const t = useTranslations("settings");
  const qc = useQueryClient();
  const { can, me } = useSession();
  const isAdmin = can("admin");
  const members = useQuery({ queryKey: ["members"], queryFn: () => api.get<Member[]>("/workspace/members") });
  const invitations = useQuery({ queryKey: ["invitations"], queryFn: () => api.get<Invitation[]>("/workspace/invitations"), enabled: isAdmin });
  const [inviteOpen, setInviteOpen] = useState(false);
  const [invite, setInvite] = useState({ email: "", role: "editor" as Role });
  const onError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : String(err));

  const changeRole = useMutation({
    mutationFn: ({ id, role }: { id: number; role: Role }) => api.patch(`/workspace/members/${id}`, { role }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["members"] }),
    onError,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/workspace/members/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["members"] }),
    onError,
  });
  const sendInvite = useMutation({
    mutationFn: () => api.post("/workspace/invitations", invite),
    onSuccess: () => {
      setInviteOpen(false);
      setInvite({ email: "", role: "editor" });
      toast.success(t("inviteSent"));
      qc.invalidateQueries({ queryKey: ["invitations"] });
    },
    onError,
  });
  const revoke = useMutation({
    mutationFn: (id: number) => api.delete(`/workspace/invitations/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["invitations"] }),
    onError,
  });

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <SectionTitle icon="group" actions={isAdmin && <Button variant="primary" size="sm" icon="add" onClick={() => setInviteOpen(true)}>{t("invite")}</Button>}>
          {t("members")}
        </SectionTitle>
        <ul className="divide-y divide-line">
          {members.data?.map((m) => (
            <li key={m.id} className="flex items-center gap-3 py-3">
              <Avatar name={m.name} src={m.avatar_url} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold">{m.name}{m.user_id === me?.user.id && <span className="text-muted"> · {t("you")}</span>}</div>
                <div className="truncate text-xs text-muted" dir="ltr">{m.email}</div>
              </div>
              {isAdmin ? (
                <Select className="!h-9 !w-36 shrink-0" value={m.role} onChange={(e) => changeRole.mutate({ id: m.id, role: e.target.value as Role })}>
                  {ROLES.map((r) => <option key={r} value={r}>{t(`roles.${r}`)}</option>)}
                </Select>
              ) : (
                <Badge>{t(`roles.${m.role}`)}</Badge>
              )}
              {isAdmin && m.user_id !== me?.user.id && <IconButton icon="delete" label={t("remove")} onClick={() => remove.mutate(m.id)} />}
            </li>
          ))}
        </ul>
      </Card>

      {isAdmin && !!invitations.data?.length && (
        <Card>
          <SectionTitle icon="mail">{t("pendingInvitations")}</SectionTitle>
          <ul className="divide-y divide-line">
            {invitations.data.map((inv) => (
              <li key={inv.id} className="flex items-center gap-3 py-3">
                <span className="flex-1 truncate text-sm" dir="ltr">{inv.email}</span>
                <Badge>{t(`roles.${inv.role}`)}</Badge>
                <IconButton icon="close" label={t("revoke")} onClick={() => revoke.mutate(inv.id)} />
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card className="text-sm text-muted">
        <SectionTitle icon="info">{t("rolesTitle")}</SectionTitle>
        <ul className="grid gap-1.5">
          {ROLES.map((r) => <li key={r}><b className="text-text">{t(`roles.${r}`)}:</b> {t(`roleHelp.${r}`)}</li>)}
        </ul>
      </Card>

      <Modal open={inviteOpen} onClose={() => setInviteOpen(false)} title={t("invite")}
        footer={<><Button onClick={() => setInviteOpen(false)}>{t("cancel")}</Button><Button variant="primary" loading={sendInvite.isPending} onClick={() => sendInvite.mutate()}>{t("sendInvite")}</Button></>}>
        <div className="flex flex-col gap-4">
          <Field label={t("email")}><Input type="email" dir="ltr" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} /></Field>
          <Field label={t("role")}>
            <Select value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value as Role })}>
              {ROLES.filter((r) => r !== "owner").map((r) => <option key={r} value={r}>{t(`roles.${r}`)}</option>)}
            </Select>
          </Field>
        </div>
      </Modal>
    </div>
  );
}
