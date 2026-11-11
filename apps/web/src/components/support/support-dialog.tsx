"use client";
/** "Write to support": opened from an error message (its details attached) or from the support page. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Button, Field, Input, Modal, Select, Textarea, toast } from "@/components/ui";
import { api } from "@/lib/api";
import { type Failure, useSupport } from "./store";

export const CATEGORIES = ["problem", "question", "billing", "idea"] as const;

export function SupportDialog() {
  const { open, failure, hide } = useSupport();
  // while this is mounted (inside the app, signed in) error messages offer "report"
  useEffect(() => {
    useSupport.setState({ enabled: true });
    return () => useSupport.setState({ enabled: false });
  }, []);
  return open ? <TicketForm key={failure?.at ?? "new"} failure={failure} hide={hide} /> : null;
}

function TicketForm({ failure, hide }: { failure: Failure | null; hide: () => void }) {
  const t = useTranslations("support");
  const locale = useLocale();
  const client = useQueryClient();
  const [form, setForm] = useState({ subject: failure ? failure.message.slice(0, 120) : "", body: "", category: "problem" });

  const send = useMutation({
    mutationFn: () => api.post<{ id: number }>("/support/tickets", {
      ...form, error_ref: failure?.ref || undefined,
      context: { ...(failure ? context(failure) : { page: window.location.pathname }), browser: navigator.userAgent, locale, app: "web" },
    }),
    onSuccess: (ticket) => {
      client.invalidateQueries({ queryKey: ["support-tickets"] });
      toast.success(t("sent", { id: ticket.id }));
      hide();
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : String(err)),
  });

  return (
    <Modal open onClose={hide} title={t("newTitle")}
      footer={<><Button onClick={hide}>{t("cancel")}</Button><Button variant="primary" icon="send" loading={send.isPending} disabled={form.subject.trim().length < 3 || !form.body.trim()} onClick={() => send.mutate()}>{t("send")}</Button></>}>
      <div className="flex flex-col gap-4">
        {failure && (
          <div className="rounded-2xl bg-bad-bg px-4 py-3 text-sm">
            <div className="font-semibold text-bad">{t("attached")}</div>
            <p className="bidi mt-1 text-text-2">{failure.message}</p>
            <div className="mt-2 flex flex-wrap gap-1.5 font-mono text-[11px] text-muted" dir="ltr">
              {failure.ref && <span className="rounded-md bg-white/70 px-1.5 py-0.5">ref {failure.ref}</span>}
              {failure.status > 0 && <span className="rounded-md bg-white/70 px-1.5 py-0.5">{failure.status} {failure.code}</span>}
              {failure.request && <span className="rounded-md bg-white/70 px-1.5 py-0.5">{failure.request}</span>}
              <span className="rounded-md bg-white/70 px-1.5 py-0.5">{failure.page}</span>
            </div>
          </div>
        )}
        <div className="grid gap-4 sm:grid-cols-[1fr_180px]">
          <Field label={t("subject")}><Input value={form.subject} maxLength={200} onChange={(e) => setForm({ ...form, subject: e.target.value })} /></Field>
          <Field label={t("category")}>
            <Select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
              {CATEGORIES.map((c) => <option key={c} value={c}>{t(`categories.${c}`)}</option>)}
            </Select>
          </Field>
        </div>
        <Field label={t("details")} hint={failure ? t("detailsHintError") : t("detailsHint")}>
          <Textarea rows={5} value={form.body} maxLength={8000} onChange={(e) => setForm({ ...form, body: e.target.value })} />
        </Field>
      </div>
    </Modal>
  );
}

function context(failure: Failure) {
  return { code: failure.code, message: failure.message, status: failure.status || undefined, page: failure.page, request: failure.request || undefined };
}
