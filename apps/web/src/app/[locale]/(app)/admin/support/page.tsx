"use client";
/** Platform support desk: every ticket, what the app knew when it was sent, the stored error, and the answer. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Icon } from "@/components/icon";
import { STATUS_TONE, Thread, type Ticket, useWhen } from "@/components/support/thread";
import { Badge, Button, Card, EmptyState, Input, Segmented, Spinner, Textarea, cx, toast } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";

type ErrorEvent = {
  ref: string; status: number; code: string; method: string; path: string; message: string; detail: string | null;
  workspace: string | null; user: string | null; ticket_id: number | null; created_at: string;
};
type FailedCall = { service: string; operation: string; status_code: number | null; error: string | null; created_at: string };
type AdminTicket = Ticket & {
  workspace_id: number; workspace: string; email: string | null; context: Record<string, string> | null;
  error: ErrorEvent | null; failed_calls: FailedCall[] | null;
};
type Page = { items: AdminTicket[]; total: number; counts: Record<string, number> };
type Filter = "open" | "answered" | "closed" | "all";

function SupportDesk() {
  const t = useTranslations("support");
  const a = useTranslations("support.admin");
  const when = useWhen();
  const client = useQueryClient();
  const params = useSearchParams();
  const [filter, setFilter] = useState<Filter>(params.get("ticket") ? "all" : "open");
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<number | null>(Number(params.get("ticket")) || null);
  const [reply, setReply] = useState("");
  const list = useQuery({ queryKey: ["admin-support", filter, q], queryFn: () => api.get<Page>("/admin/support/tickets", { status: filter === "all" ? undefined : filter, q }), placeholderData: keepPreviousData });
  const errors = useQuery({ queryKey: ["admin-support-errors"], queryFn: () => api.get<ErrorEvent[]>("/admin/support/errors", { limit: 8 }) });
  const current = selected ?? list.data?.items[0]?.id ?? null;
  const ticket = useQuery({ queryKey: ["admin-support-ticket", current], queryFn: () => api.get<AdminTicket>(`/admin/support/tickets/${current}`), enabled: !!current });
  const act = useMutation({
    mutationFn: (v: { status?: string }) => v.status
      ? api.post<AdminTicket>(`/admin/support/tickets/${current}/status`, { status: v.status })
      : api.post<AdminTicket>(`/admin/support/tickets/${current}/messages`, { body: reply }),
    onSuccess: (data) => { setReply(""); client.setQueryData(["admin-support-ticket", current], data); client.invalidateQueries({ queryKey: ["admin-support"] }); },
    onError: (err) => toast.error(err instanceof Error ? err.message : String(err)),
  });
  const counts = list.data?.counts ?? {};
  const data = ticket.data;

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <Segmented value={filter} onChange={(v) => { setFilter(v); setSelected(null); }} options={(["open", "answered", "closed", "all"] as Filter[]).map((s) => ({
            value: s, label: <>{s === "all" ? a("all") : t(`status.${s}`)}{s !== "all" && <span className="ms-1.5 text-xs text-muted">{counts[s] ?? 0}</span>}</>,
          }))} />
          <Input className="max-w-xs" placeholder={a("search")} value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {list.isLoading ? <div className="flex justify-center py-12"><Spinner /></div>
          : !list.data?.items.length ? <EmptyState icon="support_agent" title={a("empty")} text={a("emptyText")} />
            : (
              <div className="grid gap-5 xl:grid-cols-[340px_1fr]">
                <ul className="flex flex-col gap-1.5">
                  {list.data.items.map((item) => (
                    <li key={item.id}>
                      <button onClick={() => setSelected(item.id)} className={cx("w-full rounded-2xl px-3.5 py-3 text-start transition", item.id === current ? "bg-fill-2" : "hover:bg-fill")}>
                        <div className="flex items-center gap-2">
                          <span className="min-w-0 flex-1 truncate text-sm font-semibold">{item.subject}</span>
                          <span className="text-xs text-faint" dir="ltr">#{item.id}</span>
                        </div>
                        <div className="mt-1 truncate text-xs text-muted">{item.workspace} · {item.author ?? "—"}</div>
                        <div className="mt-1.5 flex items-center gap-2 text-xs text-muted">
                          <Badge tone={STATUS_TONE[item.status]}>{t(`status.${item.status}`)}</Badge>
                          <Badge>{t(`categories.${item.category}`)}</Badge>
                          {item.error_ref && <Icon name="error" size={14} className="text-bad" />}
                          <span className="ms-auto">{when(item.last_message_at)}</span>
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
                <div className="min-w-0 rounded-2xl border border-line p-4">
                  {!data ? <div className="flex justify-center py-12"><Spinner /></div> : (
                    <>
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <h3 className="min-w-0 flex-1 text-base font-semibold">{data.subject}</h3>
                        <Badge tone={STATUS_TONE[data.status]}>{t(`status.${data.status}`)}</Badge>
                      </div>
                      <p className="mb-4 text-xs text-muted">
                        <Link href={`/admin/workspaces/${data.workspace_id}`} className="font-semibold text-text underline-offset-2 hover:underline">{data.workspace}</Link>
                        {" · "}{data.author ?? "—"}{data.email && <> · <span dir="ltr">{data.email}</span></>}{" · "}{when(data.created_at)}
                      </p>

                      {(data.context || data.error || !!data.failed_calls?.length) && (
                        <div className="mb-4 rounded-2xl bg-fill px-4 py-3 text-sm">
                          <div className="mb-2 flex items-center gap-2 font-semibold"><Icon name="error" size={16} className="text-bad" /> {a("technical")}</div>
                          {data.context && (
                            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                              {Object.entries(data.context).map(([key, value]) => (
                                <div key={key} className="contents"><dt className="text-muted">{a.has(`context.${key}`) ? a(`context.${key}`) : key}</dt><dd className="min-w-0 break-words" dir="auto">{value}</dd></div>
                              ))}
                            </dl>
                          )}
                          {data.error && (
                            <div className="mt-3 border-t border-line pt-3 text-xs">
                              <div className="font-semibold">{a("stored")} <span className="font-mono" dir="ltr">{data.error.ref}</span></div>
                              <div className="mt-1 font-mono text-text-2" dir="ltr">{data.error.status} · {data.error.method} {data.error.path}</div>
                              <div className="mt-1 break-words font-mono text-bad" dir="ltr">{data.error.message}</div>
                              {data.error.detail && (
                                <details className="mt-2">
                                  <summary className="cursor-pointer text-muted">{a("traceback")}</summary>
                                  <pre className="mt-2 max-h-64 overflow-auto rounded-xl bg-ink p-3 text-[11px] leading-relaxed text-white/85" dir="ltr">{data.error.detail}</pre>
                                </details>
                              )}
                            </div>
                          )}
                          {!!data.failed_calls?.length && (
                            <div className="mt-3 border-t border-line pt-3 text-xs">
                              <div className="mb-1 font-semibold">{a("failedCalls")}</div>
                              <ul className="flex flex-col gap-1">
                                {data.failed_calls.map((c, i) => (
                                  <li key={i} className="flex flex-wrap gap-x-2" dir="ltr">
                                    <span className="text-muted">{when(c.created_at)}</span><span className="font-semibold">{c.operation}</span>
                                    {c.status_code && <span className="text-bad">{c.status_code}</span>}{c.error && <span className="min-w-0 break-words text-text-2">{c.error}</span>}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </div>
                      )}

                      <Thread messages={data.messages ?? []} me="staff" />
                      <div className="mt-4 flex flex-col gap-2">
                        <Textarea rows={3} placeholder={a("replyPlaceholder")} value={reply} onChange={(e) => setReply(e.target.value)} />
                        <div className="flex flex-wrap justify-end gap-2">
                          {data.status === "closed"
                            ? <Button onClick={() => act.mutate({ status: "open" })} disabled={act.isPending}>{a("reopen")}</Button>
                            : <Button onClick={() => act.mutate({ status: "closed" })} disabled={act.isPending}>{a("close")}</Button>}
                          <Button variant="primary" icon="send" loading={act.isPending} disabled={!reply.trim()} onClick={() => act.mutate({})}>{a("answer")}</Button>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}
      </Card>

      <Card>
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="mb-1 font-semibold">{a("errorsTitle")}</h3>
            <p className="text-sm text-muted">{a("errorsText")}</p>
          </div>
          <Button size="sm" icon="warning" onClick={() => api.post("/admin/support/test-error").catch((err) => { toast.error(err instanceof Error ? err.message : String(err)); client.invalidateQueries({ queryKey: ["admin-support-errors"] }); })}>{a("testError")}</Button>
        </div>
        {!errors.data?.length ? <p className="text-sm text-muted">{a("noErrors")}</p> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <tbody>
                {errors.data.map((e) => (
                  <tr key={e.ref} className="border-b border-line/60 align-top">
                    <td className="px-2 py-2.5 font-mono text-xs" dir="ltr">{e.ref}</td>
                    <td className="px-2 py-2.5 text-xs text-muted">{when(e.created_at)}</td>
                    <td className="px-2 py-2.5 font-mono text-xs" dir="ltr"><span className="text-bad">{e.status}</span> {e.method} {e.path}</td>
                    <td className="max-w-[300px] truncate px-2 py-2.5 text-xs text-text-2" dir="ltr" title={e.message}>{e.message}</td>
                    <td className="px-2 py-2.5 text-xs text-text-2">{e.workspace ?? "—"}</td>
                    <td className="px-2 py-2.5 text-end text-xs">
                      {e.ticket_id ? <button className="font-semibold underline-offset-2 hover:underline" onClick={() => { setFilter("all"); setSelected(e.ticket_id); window.scrollTo({ top: 0, behavior: "smooth" }); }}>{a("ticket", { id: e.ticket_id })}</button> : <span className="text-faint">{a("noTicket")}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

export default function AdminSupportPage() {
  return <Suspense><SupportDesk /></Suspense>;
}
