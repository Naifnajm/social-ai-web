"use client";
/** "To approve": posts editors sent for approval — approve (publishes or schedules) or request changes. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import { MediaThumb } from "@/components/publishing/media-picker";
import type { Post } from "@/components/publishing/types";
import { errorText, useFormat } from "@/components/publishing/util";
import { Badge, Button, Card, EmptyState, Field, Modal, PageHeader, Spinner, Textarea, toast } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";

export default function ApprovalsPage() {
  const t = useTranslations("publishing.approvals");
  const qc = useQueryClient();
  const fmt = useFormat();
  const queue = useQuery({ queryKey: ["approvals"], queryFn: () => api.get<Post[]>("/approvals") });
  const [changes, setChanges] = useState<Post | null>(null);
  const [note, setNote] = useState("");
  const refresh = () => ["approvals", "posts", "studio"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const approve = useMutation({
    mutationFn: (id: number) => api.post<Post>(`/posts/${id}/approve`),
    onSuccess: (p) => { refresh(); toast.success(p.state === "scheduled" ? t("approvedScheduled") : t("approvedPublished")); },
    onError: (err) => toast.error(errorText(err)),
  });
  const requestChanges = useMutation({
    mutationFn: () => api.post(`/posts/${changes!.id}/request-changes`, { note }),
    onSuccess: () => { refresh(); setChanges(null); setNote(""); toast.success(t("changesSent")); },
    onError: (err) => toast.error(errorText(err)),
  });
  return (
    <div className="pt-2">
      <PageHeader icon="verified_user" title={t("title")} subtitle={t("subtitle")} />
      {queue.isLoading ? <div className="flex justify-center py-20"><Spinner /></div> : !queue.data?.length ? (
        <Card><EmptyState icon="check_circle" title={t("emptyTitle")} text={t("emptyText")} /></Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {queue.data.map((p) => (
            <Card key={p.id} className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="warn"><Icon name="schedule" size={12} />{p.requested_action === "schedule" ? t("wantsSchedule", { date: fmt.dateTime(p.scheduled_at) }) : t("wantsPublish")}</Badge>
                <span className="text-xs text-muted">{t("by", { name: p.approval_requested_by_name || "—", date: fmt.dateTime(p.approval_requested_at) })}</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {p.accounts.map((a) => (
                  <span key={a.id} className="inline-flex items-center gap-1.5 rounded-full bg-fill-2 py-0.5 ps-0.5 pe-2.5 text-xs font-medium">
                    <PlatformBadge platform={a.platform} size={20} /><span className="bidi">{a.name}</span>
                  </span>
                ))}
                {p.publish_as !== "feed" && <Badge><Icon name="smartphone" size={12} />{t(`publishAs.${p.publish_as}`)}</Badge>}
              </div>
              <p className="bidi whitespace-pre-wrap rounded-2xl bg-fill p-3 text-sm leading-relaxed">{p.content || "—"}</p>
              {Object.keys(p.variants).length > 0 && (
                <div className="flex flex-col gap-1.5">
                  {Object.entries(p.variants).map(([pf, text]) => (
                    <div key={pf} className="flex gap-2 text-xs"><PlatformBadge platform={pf} size={18} /><p className="bidi flex-1 whitespace-pre-wrap text-text-2">{text}</p></div>
                  ))}
                </div>
              )}
              {p.media.length > 0 && <div className="flex flex-wrap gap-2">{p.media.map((m) => <div key={m.id} className="h-20 w-20 overflow-hidden rounded-xl"><MediaThumb media={m} /></div>)}</div>}
              <div className="mt-auto flex flex-wrap justify-end gap-2 border-t border-line pt-3">
                <Link href={`/studio?post=${p.id}`} className="me-auto"><Button variant="ghost" icon="edit_square">{t("edit")}</Button></Link>
                <Button icon="mode_comment" onClick={() => setChanges(p)}>{t("requestChanges")}</Button>
                <Button variant="primary" icon="check" loading={approve.isPending && approve.variables === p.id} onClick={() => approve.mutate(p.id)}>{t("approve")}</Button>
              </div>
            </Card>
          ))}
        </div>
      )}
      <Modal open={!!changes} onClose={() => setChanges(null)} title={t("requestChanges")}
        footer={<><Button onClick={() => setChanges(null)}>{t("cancel")}</Button><Button variant="primary" loading={requestChanges.isPending} onClick={() => requestChanges.mutate()}>{t("send")}</Button></>}>
        <Field label={t("noteLabel")} hint={t("noteHint")}>
          <Textarea rows={4} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </Modal>
    </div>
  );
}
