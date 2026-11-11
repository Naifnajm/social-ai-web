"use client";
/** Support: the person's tickets on one side, the conversation with the platform team on the other. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useSupport } from "@/components/support/store";
import { STATUS_TONE, Thread, type Ticket, useWhen } from "@/components/support/thread";
import { Badge, Button, Card, EmptyState, Spinner, Textarea, cx, toast } from "@/components/ui";
import { api } from "@/lib/api";

function SupportSettings() {
  const t = useTranslations("support");
  const when = useWhen();
  const client = useQueryClient();
  const params = useSearchParams();
  const [selected, setSelected] = useState<number | null>(Number(params.get("ticket")) || null);
  const [reply, setReply] = useState("");
  const list = useQuery({ queryKey: ["support-tickets"], queryFn: () => api.get<Ticket[]>("/support/tickets") });
  const current = selected ?? list.data?.[0]?.id ?? null;
  const ticket = useQuery({ queryKey: ["support-tickets", current], queryFn: () => api.get<Ticket>(`/support/tickets/${current}`), enabled: !!current });
  useEffect(() => { if (ticket.data) client.invalidateQueries({ queryKey: ["support-tickets"], exact: true }); }, [ticket.data?.id, client]); // eslint-disable-line react-hooks/exhaustive-deps
  const act = useMutation({
    mutationFn: (what: "reply" | "close") => what === "reply"
      ? api.post<Ticket>(`/support/tickets/${current}/messages`, { body: reply })
      : api.post<Ticket>(`/support/tickets/${current}/close`),
    onSuccess: (data) => { setReply(""); client.setQueryData(["support-tickets", current], data); client.invalidateQueries({ queryKey: ["support-tickets"], exact: true }); },
    onError: (err) => toast.error(err instanceof Error ? err.message : String(err)),
  });

  return (
    <Card>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">{t("title")}</h2>
          <p className="text-sm text-muted">{t("subtitle")}</p>
        </div>
        <Button variant="primary" icon="add_circle" onClick={() => useSupport.getState().show()}>{t("new")}</Button>
      </div>
      {list.isLoading ? <div className="flex justify-center py-12"><Spinner /></div>
        : !list.data?.length ? <EmptyState icon="support_agent" title={t("empty")} text={t("emptyText")} />
          : (
            <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
              <ul className="flex flex-col gap-1.5">
                {list.data.map((item) => (
                  <li key={item.id}>
                    <button onClick={() => setSelected(item.id)} className={cx("w-full rounded-2xl px-3.5 py-3 text-start transition", item.id === current ? "bg-fill-2" : "hover:bg-fill")}>
                      <div className="flex items-center gap-2">
                        {item.unread && <span className="h-2 w-2 shrink-0 rounded-full bg-accent" />}
                        <span className="min-w-0 flex-1 truncate text-sm font-semibold">{item.subject}</span>
                        <span className="text-xs text-faint" dir="ltr">#{item.id}</span>
                      </div>
                      <div className="mt-1.5 flex items-center gap-2 text-xs text-muted">
                        <Badge tone={STATUS_TONE[item.status]}>{t(`status.${item.status}`)}</Badge>
                        <span>{when(item.last_message_at)}</span>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
              <div className="min-w-0 rounded-2xl border border-line p-4">
                {!ticket.data ? <div className="flex justify-center py-12"><Spinner /></div> : (
                  <>
                    <div className="mb-4 flex flex-wrap items-center gap-2">
                      <h3 className="min-w-0 flex-1 font-semibold">{ticket.data.subject}</h3>
                      {ticket.data.error_ref && <span className="rounded-md bg-fill-2 px-1.5 py-0.5 font-mono text-[11px] text-muted" dir="ltr">ref {ticket.data.error_ref}</span>}
                      <Badge tone={STATUS_TONE[ticket.data.status]}>{t(`status.${ticket.data.status}`)}</Badge>
                    </div>
                    <Thread messages={ticket.data.messages ?? []} me="user" />
                    <div className="mt-4 flex flex-col gap-2">
                      <Textarea rows={3} placeholder={t("replyPlaceholder")} value={reply} onChange={(e) => setReply(e.target.value)} />
                      <div className="flex flex-wrap justify-end gap-2">
                        {ticket.data.status !== "closed" && <Button onClick={() => act.mutate("close")} disabled={act.isPending}>{t("markSolved")}</Button>}
                        <Button variant="primary" icon="send" loading={act.isPending} disabled={!reply.trim()} onClick={() => act.mutate("reply")}>{t("reply")}</Button>
                      </div>
                    </div>
                  </>
                )}
              </div>
            </div>
          )}
    </Card>
  );
}

export default function SupportSettingsPage() {
  return <Suspense><SupportSettings /></Suspense>;
}
