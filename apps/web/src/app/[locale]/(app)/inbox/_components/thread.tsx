"use client";
import { useFormatter, useTranslations } from "next-intl";
import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/icon";
import { Badge, Button, IconButton, Segmented, cx } from "@/components/ui";
import { api } from "@/lib/api";
import type { Canned, Channel, InboxMeta, Message, Thread } from "../_lib/types";
import { ConvAvatar, showError, useWhen } from "./bits";

type SendResult = { message: Message; thread: Thread };

export function ThreadPane({ thread, meta, onBack, onToggleInfo, onChanged }: {
  thread: Thread;
  meta: InboxMeta;
  onBack: () => void;
  onToggleInfo: () => void;
  onChanged: (t: Thread) => void;
}) {
  const t = useTranslations("inbox");
  const format = useFormatter();
  const when = useWhen();
  const scroller = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const groups = useMemo(() => {
    const out: { day: string; label: string; messages: Message[] }[] = [];
    for (const m of thread.messages) {
      const date = new Date(m.sent_at);
      const day = date.toDateString();
      let group = out[out.length - 1];
      if (!group || group.day !== day) {
        group = { day, label: format.dateTime(date, { weekday: "long", day: "numeric", month: "long" }), messages: [] };
        out.push(group);
      }
      group.messages.push(m);
    }
    return out;
  }, [thread.messages, format]);

  const lastId = thread.messages[thread.messages.length - 1]?.id;
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [thread.id, lastId, thread.suggestion?.id]);

  const run = async (key: string, action: () => Promise<Thread | void>) => {
    setBusy(key);
    try {
      const result = await action();
      if (result) onChanged(result);
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  const setState = (state: "open" | "done") => run("state", () => api.patch<Thread>(`/inbox/conversations/${thread.id}`, { state }));
  const hide = (value: boolean) => run("hide", () => api.post<Thread>(`/inbox/conversations/${thread.id}/hide`, { hide: value }));
  const like = () => run("like", async () => { await api.post(`/inbox/conversations/${thread.id}/like`); });

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-center gap-2 border-b border-line px-3 py-2.5 sm:px-4">
        <IconButton icon="arrow_back" label={t("back")} onClick={onBack} className="lg:hidden rtl:[&_svg]:-scale-x-100" />
        <button onClick={onToggleInfo} className="flex min-w-0 flex-1 items-center gap-2.5 text-start">
          <ConvAvatar name={thread.name} src={thread.avatar_url} platform={thread.platform} size={38} />
          <span className="min-w-0">
            <span className="bidi block truncate text-[15px] font-semibold">{thread.name}</span>
            <span className="block truncate text-xs text-muted">
              {t(thread.kind === "comment" ? "kinds.commentOne" : "kinds.dmOne")} · {thread.account_name}
              {thread.handle && <> · <span className="bidi" dir="ltr">{thread.handle}</span></>}
            </span>
          </span>
        </button>
        {meta.can_reply && (
          <div className="flex shrink-0 items-center gap-1">
            {thread.can_like && <IconButton icon="thumb_up" label={t("like")} onClick={like} disabled={busy === "like"} />}
            {thread.can_hide && (
              <IconButton icon={thread.is_hidden ? "visibility" : "visibility_off"} label={thread.is_hidden ? t("unhide") : t("hide")}
                onClick={() => hide(!thread.is_hidden)} disabled={busy === "hide"} />
            )}
            {thread.state !== "done" ? (
              <Button size="sm" variant="primary" icon="check" loading={busy === "state"} onClick={() => setState("done")}>
                <span className="hidden sm:inline">{t("done")}</span>
              </Button>
            ) : (
              <Button size="sm" icon="undo" loading={busy === "state"} onClick={() => setState("open")}>
                <span className="hidden sm:inline">{t("reopen")}</span>
              </Button>
            )}
          </div>
        )}
        <IconButton icon="person" label={t("customerDetails")} onClick={onToggleInfo} className="shrink-0" />
      </header>

      {thread.post && (thread.post.preview || thread.post.url) && (
        <a href={thread.post.url || undefined} target="_blank" rel="noreferrer"
          className="mx-3 mt-3 flex items-center gap-2.5 rounded-2xl bg-fill px-3 py-2 text-sm hover:bg-fill-2">
          <Icon name="campaign" size={18} className="shrink-0 text-text-2" />
          <span className="min-w-0 flex-1">
            <span className="block text-[11px] text-muted">{t("onYourPost")}</span>
            <span className="bidi block truncate">{thread.post.preview || thread.post.url}</span>
          </span>
          {thread.post.url && <Icon name="open_in_new" size={15} className="shrink-0 text-muted" />}
        </a>
      )}
      {thread.state === "pending" && (
        <div className="mx-3 mt-3 flex items-start gap-2 rounded-2xl bg-warn-bg px-3 py-2 text-sm text-warn">
          <Icon name="support_agent" size={18} className="mt-0.5 shrink-0" />
          <div><b>{t("humanNeeded")}</b> {thread.handover_reason && <span className="bidi">{thread.handover_reason}</span>}</div>
        </div>
      )}
      {thread.bot_error && (
        <div className="mx-3 mt-3 flex items-start gap-2 rounded-2xl bg-bad-bg px-3 py-2 text-sm text-bad">
          <Icon name="error" size={18} className="mt-0.5 shrink-0" />
          <div><b>{t("assistantError")}</b> <span className="bidi">{thread.bot_error}</span></div>
        </div>
      )}

      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto px-3 py-3 sm:px-5">
        {groups.map((group) => (
          <div key={group.day}>
            <div className="my-3 flex justify-center">
              <span className="rounded-full bg-fill-2 px-3 py-0.5 text-[11px] font-medium text-muted">{group.label}</span>
            </div>
            {group.messages.map((m) => <Bubble key={m.id} m={m} kind={thread.kind} when={when} />)}
          </div>
        ))}
      </div>

      {thread.suggestion && meta.can_reply && (
        <SuggestionCard key={thread.suggestion.id} thread={thread} onChanged={onChanged} />
      )}
      {meta.can_reply ? (
        <Composer key={thread.id} thread={thread} meta={meta} onChanged={onChanged} />
      ) : (
        <div className="border-t border-line p-3 text-center text-xs text-muted">{t("readOnly")}</div>
      )}
    </div>
  );
}

function Bubble({ m, kind, when }: { m: Message; kind: string; when: (v?: string | null, short?: boolean) => string }) {
  const t = useTranslations("inbox");
  const out = m.direction === "out";
  const showAuthor = out || kind === "comment";
  return (
    <div className={cx("mb-2.5 flex flex-col", out ? "items-end" : "items-start")}>
      {showAuthor && (
        <div className="mb-1 flex flex-wrap items-center gap-1.5 px-1 text-[11px] text-muted">
          {m.is_bot ? <span className="inline-flex items-center gap-1 font-semibold text-text-2"><Icon name="smart_toy" size={12} />{t("assistant")}</span>
            : <span className="bidi font-semibold text-text-2">{out ? m.user?.name || m.author : m.author}</span>}
          {m.channel === "private" && <span className="inline-flex items-center gap-0.5"><Icon name="lock" size={11} />{t("privateReply")}</span>}
          {m.channel === "public" && out && <span className="inline-flex items-center gap-0.5"><Icon name="reply" size={11} />{t("publicReply")}</span>}
          {m.trigger && <span className="inline-flex items-center gap-0.5"><Icon name="bolt" size={11} /><span className="bidi">{m.trigger}</span></span>}
          {m.hidden && <span className="inline-flex items-center gap-0.5"><Icon name="visibility_off" size={11} />{t("hidden")}</span>}
        </div>
      )}
      <div className={cx("max-w-[85%] overflow-hidden rounded-[20px] text-[14px] leading-relaxed sm:max-w-[72%]",
        out ? (m.is_bot ? "rounded-ee-md bg-ink-2 text-white" : "rounded-ee-md bg-ink text-white") : "rounded-es-md bg-white/90 shadow-[var(--ring)]",
        m.state === "failed" && "opacity-70 ring-2 ring-bad/50", m.hidden && "opacity-50")}>
        {m.attachments.length > 0 && (
          <div className="flex flex-wrap gap-1 p-1">
            {m.attachments.map((a) => a.mimetype.startsWith("image/") ? (
              <a key={a.id} href={a.url} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-2xl">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={a.url} alt={a.filename} loading="lazy" className="max-h-64 w-auto max-w-full object-cover" />
              </a>
            ) : a.mimetype.startsWith("audio/") ? (
              <audio key={a.id} controls src={a.url} className="max-w-full" />
            ) : a.mimetype.startsWith("video/") ? (
              <video key={a.id} controls src={a.url} className="max-h-64 max-w-full rounded-2xl" />
            ) : (
              <a key={a.id} href={a.url} target="_blank" rel="noreferrer" className="flex items-center gap-1.5 rounded-xl bg-black/5 px-3 py-2 text-xs">
                <Icon name="description" size={15} /><span className="truncate" dir="ltr">{a.filename}</span>
              </a>
            ))}
          </div>
        )}
        {m.body && <div className="bidi whitespace-pre-wrap break-words px-3.5 py-2">{m.body}</div>}
      </div>
      <div className="mt-0.5 flex items-center gap-1 px-1 text-[11px] text-muted">
        <time title={new Date(m.sent_at).toLocaleString()}>{when(m.sent_at)}</time>
        {m.state === "failed" && <span className="inline-flex items-center gap-0.5 text-bad"><Icon name="error" size={11} />{t("notSent")}</span>}
      </div>
      {m.state === "failed" && m.error && <div className="bidi max-w-[85%] px-1 text-[11px] text-bad">{m.error}</div>}
    </div>
  );
}

function SuggestionCard({ thread, onChanged }: { thread: Thread; onChanged: (t: Thread) => void }) {
  const t = useTranslations("inbox");
  const suggestion = thread.suggestion!;
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(suggestion.body);
  const [busy, setBusy] = useState<string | null>(null);
  const windowClosed = thread.window.limited && !thread.window.open && !thread.window.human_agent;

  const send = async () => {
    setBusy("send");
    try {
      const result = await api.post<SendResult>(`/inbox/suggestions/${suggestion.id}/send`, { body: editing ? text : null });
      if (result.message.state === "failed") showError(result.message.error || t("notSent"));
      onChanged(result.thread);
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };
  const discard = async () => {
    setBusy("discard");
    try {
      onChanged(await api.delete<Thread>(`/inbox/suggestions/${suggestion.id}`));
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-3 mb-2 rounded-[18px] border border-line bg-white/80 p-3 shadow-[var(--shadow)]">
      <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[13px]">
        <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-ink text-white"><Icon name="smart_toy" size={14} /></span>
        <b>{t("suggestedReply")}</b>
        {suggestion.confidence > 0 && <Badge tone={suggestion.confidence >= 75 ? "ok" : "warn"}>{suggestion.confidence}%</Badge>}
        {suggestion.channel === "private" && <Badge><Icon name="lock" size={11} />{t("privateReply")}</Badge>}
        {suggestion.channel === "public" && <Badge><Icon name="reply" size={11} />{t("publicReply")}</Badge>}
      </div>
      {editing ? (
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} autoFocus
          className="bidi w-full resize-none rounded-xl border border-line bg-white px-3 py-2 text-sm outline-none focus:border-black/30" />
      ) : (
        <p className="bidi whitespace-pre-wrap text-sm">{suggestion.body}</p>
      )}
      {suggestion.note && <p className="bidi mt-1 flex items-start gap-1 text-xs text-muted"><Icon name="info" size={13} className="mt-0.5 shrink-0" />{suggestion.note}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button size="sm" variant="primary" icon="send" loading={busy === "send"} disabled={windowClosed || !text.trim()} onClick={send}>{t("send")}</Button>
        {!editing && <Button size="sm" icon="edit_square" onClick={() => setEditing(true)}>{t("edit")}</Button>}
        <Button size="sm" variant="ghost" loading={busy === "discard"} onClick={discard}>{t("discard")}</Button>
      </div>
    </div>
  );
}

function Composer({ thread, meta, onChanged }: { thread: Thread; meta: InboxMeta; onChanged: (t: Thread) => void }) {
  const t = useTranslations("inbox");
  const [draft, setDraft] = useState("");
  const [channel, setChannel] = useState<Channel>(thread.kind === "comment" ? "public" : "dm");
  const [cannedOpen, setCannedOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const area = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [draft]);

  const w = thread.window;
  const windowClosed = w.limited && !w.open && !w.human_agent;
  const windowNote = !w.limited ? "" : w.open
    ? (w.hours_left < 4 ? t("windowHoursLeft", { hours: w.hours_left }) : "")
    : w.human_agent ? t("windowHumanAgent") : t("windowClosed");

  const slash = draft.startsWith("/") && !draft.includes(" ") ? draft.slice(1).toLowerCase() : null;
  const matches: Canned[] = meta.canned.filter((c) => slash === null
    || (c.shortcut || "").toLowerCase().startsWith(slash) || c.name.toLowerCase().includes(slash));
  const showCanned = cannedOpen || slash !== null;

  const firstName = (thread.name || "").split(" ")[0];
  const insert = (c: Canned) => {
    const body = c.body.replaceAll("{name}", firstName).replace(/ {2,}/g, " ").trim();
    setDraft((d) => (slash !== null ? body : d ? `${d} ${body}` : body));
    setCannedOpen(false);
    area.current?.focus();
  };

  const send = async () => {
    if (!draft.trim()) return;
    setBusy("send");
    try {
      const result = await api.post<SendResult>(`/inbox/conversations/${thread.id}/messages`, { body: draft, channel });
      if (result.message.state === "failed") showError(result.message.error || t("notSent"));
      else setDraft("");
      onChanged(result.thread);
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  const suggest = async () => {
    setBusy("ai");
    try {
      onChanged(await api.post<Thread>(`/inbox/conversations/${thread.id}/suggest`));
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      if (showCanned && slash !== null && matches[0]) {
        e.preventDefault();
        insert(matches[0]);
        return;
      }
      if (window.matchMedia("(pointer: fine)").matches) {
        e.preventDefault();
        send();
      }
    }
    if (e.key === "Escape") setCannedOpen(false);
  };

  return (
    <footer className="border-t border-line p-2.5 sm:p-3">
      {windowNote && (
        <div className={cx("mb-2 flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs", windowClosed ? "bg-bad-bg text-bad" : "bg-warn-bg text-warn")}>
          <Icon name="schedule" size={14} className="shrink-0" /><span>{windowNote}</span>
        </div>
      )}
      {thread.kind === "comment" && thread.can_private && (
        <Segmented size="sm" className="mb-2" value={channel} onChange={setChannel}
          options={[{ value: "public", label: t("replyPublicly"), icon: "reply" }, { value: "private", label: t("replyPrivately"), icon: "lock" }]} />
      )}
      <div className="relative rounded-[18px] border border-line bg-white/80 focus-within:border-black/25">
        {showCanned && (
          <div className="glass-strong absolute inset-x-0 bottom-full z-20 mb-2 max-h-64 overflow-y-auto rounded-2xl p-1.5">
            <div className="px-2 pb-1 text-[11px] font-semibold text-muted">{t("cannedReplies")}</div>
            {matches.map((c) => (
              <button key={c.id} onClick={() => insert(c)} className="flex w-full flex-col items-start rounded-xl px-2.5 py-2 text-start hover:bg-fill-2">
                <span className="flex items-center gap-2 text-sm font-semibold"><span className="bidi">{c.name}</span>
                  {c.shortcut && <span className="rounded-md bg-fill-2 px-1.5 text-[11px] font-medium text-muted" dir="ltr">/{c.shortcut}</span>}</span>
                <span className="bidi line-clamp-1 text-xs text-muted">{c.body}</span>
              </button>
            ))}
            {!matches.length && <div className="px-2.5 py-2 text-xs text-muted">{t("noCanned")}</div>}
          </div>
        )}
        <textarea ref={area} rows={1} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} disabled={windowClosed}
          placeholder={windowClosed ? t("windowClosedShort") : thread.kind === "comment" ? (channel === "private" ? t("placeholderPrivate") : t("placeholderPublic")) : t("placeholder")}
          className="bidi block max-h-40 w-full resize-none bg-transparent px-3.5 pt-3 pb-1 text-sm outline-none placeholder:text-faint" />
        <div className="flex items-center gap-1 px-1.5 pb-1.5">
          <IconButton icon="bolt" label={t("cannedReplies")} onClick={() => setCannedOpen((o) => !o)} />
          <Button size="sm" variant="ghost" icon="wand_stars" loading={busy === "ai"} disabled={!meta.has_provider}
            title={meta.has_provider ? t("writeWithAiHint") : t("noProvider")} onClick={suggest}>
            <span className="hidden whitespace-nowrap sm:inline">{t("writeWithAi")}</span>
          </Button>
          <span className="ms-auto hidden truncate text-[11px] text-faint 2xl:inline">{t("enterHint")}</span>
          <Button size="sm" variant="primary" icon="send" loading={busy === "send"} disabled={!draft.trim() || windowClosed} onClick={send}
            className="ms-auto 2xl:ms-2">
            {t("send")}
          </Button>
        </div>
      </div>
    </footer>
  );
}
