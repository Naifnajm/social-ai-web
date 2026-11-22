"use client";
/** What to do with a mention, beyond reading it: reply (inbox for your own comments, an AI draft and the original link
 *  for public posts), turn it into a post in Studio or a production board, put it in the next report, or give it
 *  to a teammate. Every draft is written in the brand's voice and checked by the brand guard (API side). */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/icon";
import { onError } from "@/components/planning/ui";
import { Button, Field, Modal, Select, Spinner, Textarea, toast } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { api } from "@/lib/api";
import type { Mention } from "./types";

type ReplyOut = { draft: string; notes: string[]; ai: boolean; url: string | null; conversation_id: number | null; inbox_url: string | null };
type Member = { user_id: number; name: string; email: string };

export function MentionActions({ mention, onChanged }: { mention: Mention; onChanged?: () => void }) {
  const t = useTranslations("radar.actions");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [reply, setReply] = useState<ReplyOut | null>(null);
  const [assigning, setAssigning] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (menu.current && !menu.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const draft = useMutation({
    mutationFn: () => api.post<ReplyOut>(`/listening/mentions/${mention.id}/reply`),
    onSuccess: (r) => { setReply(r); onChanged?.(); },
    onError,
  });
  const post = useMutation({
    mutationFn: () => api.post<{ url: string; notes: string[] }>(`/listening/mentions/${mention.id}/post`),
    onSuccess: (r) => { toast.success(t("postCreated")); onChanged?.(); router.push(r.url); },
    onError,
  });
  const board = useMutation({
    mutationFn: () => api.post<{ url: string }>(`/listening/mentions/${mention.id}/board`, { template: "pipeline_quick" }),
    onSuccess: (r) => { toast.success(t("boardCreated")); onChanged?.(); router.push(r.url); },
    onError,
  });
  const report = useMutation({
    mutationFn: (on: boolean) => api.post<Mention>(`/listening/mentions/${mention.id}/report`, { on }),
    onSuccess: (m) => { toast.success(m.in_report ? t("inReport") : t("outOfReport")); onChanged?.(); },
    onError,
  });
  const busy = draft.isPending || post.isPending || board.isPending || report.isPending;
  const item = (icon: string, label: string, run: () => void) => (
    <button type="button" role="menuitem" onClick={() => { setOpen(false); run(); }}
      className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-start text-[13px] hover:bg-fill-2">
      <Icon name={icon} size={15} className="text-text-2" />{label}
    </button>
  );

  return (
    <>
      <Button size="sm" icon="reply" loading={draft.isPending} onClick={() => draft.mutate()}>{t("reply")}</Button>
      <div ref={menu} className="relative">
        <Button size="sm" variant="ghost" icon="more_vert" aria-haspopup="menu" aria-expanded={open} loading={busy && !draft.isPending}
          onClick={() => setOpen((v) => !v)}>{t("more")}</Button>
        {open && (
          <div role="menu" className="glass absolute start-0 top-full z-30 mt-1 w-60 rounded-2xl p-1.5 shadow-[var(--shadow-lift)]">
            {item("auto_awesome", t("createPost"), () => post.mutate())}
            {item("account_tree", t("makeBoard"), () => board.mutate())}
            {item("description", mention.in_report ? t("removeFromReport") : t("addToReport"), () => report.mutate(!mention.in_report))}
            {item("person", t("assign"), () => setAssigning(true))}
          </div>
        )}
      </div>
      {reply && <ReplyDialog mention={mention} reply={reply} onClose={() => setReply(null)} />}
      {assigning && <AssignDialog mention={mention} onClose={() => setAssigning(false)} onDone={() => { setAssigning(false); onChanged?.(); }} />}
    </>
  );
}

function ReplyDialog({ mention, reply, onClose }: { mention: Mention; reply: ReplyOut; onClose: () => void }) {
  const t = useTranslations("radar.actions");
  const [text, setText] = useState(reply.draft);
  return (
    <Modal open onClose={onClose} title={t("replyTitle")}
      footer={<>
        <Button variant="ghost" onClick={onClose}>{t("close")}</Button>
        {reply.inbox_url ? (
          <Link href={reply.inbox_url}><Button variant="primary" icon="inbox">{t("openInbox")}</Button></Link>
        ) : reply.url && (
          <a href={reply.url} target="_blank" rel="noopener noreferrer"><Button variant="primary" icon="open_in_new">{t("openOriginal")}</Button></a>
        )}
      </>}>
      <p className="bidi mb-3 line-clamp-3 rounded-2xl bg-fill p-3 text-sm leading-relaxed text-text-2">{mention.text}</p>
      <Field label={reply.ai ? t("draftAi") : t("draftTemplate")}>
        <Textarea rows={4} dir="auto" value={text} onChange={(e) => setText(e.target.value)} />
      </Field>
      <Button size="sm" variant="ghost" icon="content_copy" className="mt-2"
        onClick={() => navigator.clipboard?.writeText(text).then(() => toast.success(t("copied")))}>{t("copy")}</Button>
      {reply.notes.length > 0 && <p className="mt-2 text-xs text-warn">{reply.notes.join(" ")}</p>}
      <p className="mt-3 text-xs text-muted">{reply.inbox_url ? t("inboxHint") : t("publicHint")}</p>
    </Modal>
  );
}

function AssignDialog({ mention, onClose, onDone }: { mention: Mention; onClose: () => void; onDone: () => void }) {
  const t = useTranslations("radar.actions");
  const members = useQuery({ queryKey: ["members"], queryFn: () => api.get<Member[]>("/workspace/members") });
  const [userId, setUserId] = useState<string>(mention.assigned_to_id ? String(mention.assigned_to_id) : "");
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () => api.post(`/listening/mentions/${mention.id}/assign`, { user_id: userId ? Number(userId) : null, note: note.trim() || null }),
    onSuccess: () => { toast.success(userId ? t("assigned") : t("unassigned")); onDone(); },
    onError,
  });
  return (
    <Modal open onClose={onClose} title={t("assignTitle")} size="sm"
      footer={<>
        <Button variant="ghost" onClick={onClose}>{t("close")}</Button>
        <Button variant="primary" icon="send" loading={save.isPending} onClick={() => save.mutate()}>{t("assignSave")}</Button>
      </>}>
      {members.isLoading ? <div className="flex justify-center py-6"><Spinner /></div> : (
        <div className="flex flex-col gap-4">
          <Field label={t("teammate")}>
            <Select value={userId} onChange={(e) => setUserId(e.target.value)}>
              <option value="">{t("nobody")}</option>
              {(members.data ?? []).map((m) => <option key={m.user_id} value={m.user_id}>{m.name || m.email}</option>)}
            </Select>
          </Field>
          <Field label={t("note")} hint={t("noteHint")}>
            <Textarea rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </div>
      )}
    </Modal>
  );
}
