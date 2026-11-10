"use client";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon } from "@/components/icon";
import { Button, IconButton, Input, Segmented, Select, Switch, Textarea, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { INTENTS, INTENT_ICON, SENTIMENTS, type InboxMeta, type Tag, type Thread } from "../_lib/types";
import { ConvAvatar, TagChip, showError } from "./bits";

export function CustomerPanel({ thread, meta, onChanged, onClose }: {
  thread: Thread;
  meta: InboxMeta;
  onChanged: (t: Thread) => void;
  onClose: () => void;
}) {
  const t = useTranslations("inbox");
  const qc = useQueryClient();
  const [note, setNote] = useState(thread.note || "");
  const [tagOpen, setTagOpen] = useState(false);
  const [newTag, setNewTag] = useState("");
  const editable = meta.can_reply;

  const update = async (values: Record<string, unknown>) => {
    try {
      onChanged(await api.patch<Thread>(`/inbox/conversations/${thread.id}`, values));
    } catch (err) {
      showError(err);
    }
  };

  const addTag = async (tag?: Tag) => {
    try {
      const chosen = tag || await api.post<Tag>("/inbox/tags", { name: newTag.trim() });
      setNewTag("");
      setTagOpen(false);
      if (!tag) qc.invalidateQueries({ queryKey: ["inbox", "meta"] });
      await update({ tag_ids: [...thread.tags.map((x) => x.id), chosen.id] });
    } catch (err) {
      showError(err);
    }
  };

  const available = meta.tags.filter((tag) => !thread.tags.some((x) => x.id === tag.id));
  const markUnread = async () => {
    try {
      await api.post(`/inbox/conversations/${thread.id}/unread`);
      qc.invalidateQueries({ queryKey: ["inbox", "list"] });
    } catch (err) {
      showError(err);
    }
  };

  const botLabel = thread.bot_paused ? t("botPaused") : t(`botModes.${thread.bot_mode}`);

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex justify-end xl:hidden">
        <IconButton icon="close" label={t("close")} onClick={onClose} />
      </div>
      <section className="flex flex-col items-center gap-1 rounded-2xl bg-white/50 p-4 text-center">
        <ConvAvatar name={thread.name} src={thread.avatar_url} platform={thread.platform} size={64} />
        <div className="bidi mt-2 text-base font-semibold">{thread.name}</div>
        <div className="text-xs text-muted">{t(`platforms.${thread.platform}`)} · <span className="bidi">{thread.account_name}</span></div>
        {thread.handle && <div className="text-xs text-muted" dir="ltr">{thread.handle}</div>}
        {thread.contact && (thread.contact.phone || thread.contact.email) && (
          <div className="mt-1 text-xs text-text-2" dir="ltr">{[thread.contact.phone, thread.contact.email].filter(Boolean).join(" · ")}</div>
        )}
        {thread.contact && thread.contact.conversations > 1 && (
          <div className="mt-1 text-[11px] text-muted">{t("contactConversations", { count: thread.contact.conversations })}</div>
        )}
      </section>

      <section className="rounded-2xl bg-white/50 p-3">
        <Label>{t("status")}</Label>
        <Segmented size="sm" className="w-full [&>button]:flex-1 [&>button]:justify-center [&>button]:whitespace-nowrap [&>button]:px-1.5" value={thread.state}
          onChange={(state) => editable && update({ state })}
          options={(["open", "pending", "done"] as const).map((s) => ({ value: s, label: t(`states.${s}`) }))} />

        <Label className="mt-3">{t("assignedTo")}</Label>
        <div className="flex items-center gap-2">
          <Select className="!h-9" disabled={!editable} value={thread.assignee?.id ?? ""}
            onChange={(e) => update({ assignee_id: e.target.value ? Number(e.target.value) : null })}>
            <option value="">{t("nobody")}</option>
            {meta.members.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </Select>
          {editable && thread.assignee?.id !== meta.user_id && (
            <Button size="sm" variant="ghost" onClick={() => update({ assignee_id: meta.user_id })}>{t("me")}</Button>
          )}
        </div>

        <Label className="mt-3">{t("tags")}</Label>
        <div className="flex flex-wrap items-center gap-1">
          {thread.tags.map((tag) => (
            <TagChip key={tag.id} tag={tag} removeLabel={t("remove")}
              onRemove={editable ? () => update({ tag_ids: thread.tags.filter((x) => x.id !== tag.id).map((x) => x.id) }) : undefined} />
          ))}
          {editable && (
            <button onClick={() => setTagOpen((o) => !o)} className="inline-flex h-6 items-center gap-0.5 rounded-full border border-dashed border-line-strong px-2 text-[11px] text-text-2 hover:bg-fill-2">
              <Icon name="add" size={12} />{t("tag")}
            </button>
          )}
        </div>
        {tagOpen && (
          <div className="mt-2 rounded-xl border border-line bg-white/80 p-2">
            <div className="flex flex-wrap gap-1">
              {available.map((tag) => <button key={tag.id} onClick={() => addTag(tag)}><TagChip tag={tag} /></button>)}
            </div>
            <Input className="mt-2 !h-8" value={newTag} placeholder={t("newTag")} onChange={(e) => setNewTag(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && newTag.trim()) addTag(); }} />
          </div>
        )}
      </section>

      <section className="rounded-2xl bg-white/50 p-3">
        <Label>{t("insight")}</Label>
        <div className="grid grid-cols-2 gap-2">
          <label className="relative">
            <Icon name={thread.intent ? INTENT_ICON[thread.intent] : "chat"} size={15} className="pointer-events-none absolute start-2.5 top-1/2 -translate-y-1/2 text-muted" />
            <Select className="!h-9 ps-8 text-[13px]" disabled={!editable} value={thread.intent ?? ""} onChange={(e) => update({ intent: e.target.value || null })}>
              <option value="">{t("intentPlaceholder")}</option>
              {INTENTS.map((i) => <option key={i} value={i}>{t(`intents.${i}`)}</option>)}
            </Select>
          </label>
          <label className="relative">
            <Icon name={thread.sentiment === "negative" ? "mood_bad" : "mood"} size={15}
              className={cx("pointer-events-none absolute start-2.5 top-1/2 -translate-y-1/2", thread.sentiment === "negative" ? "text-bad" : thread.sentiment === "positive" ? "text-ok" : "text-muted")} />
            <Select className="!h-9 ps-8 text-[13px]" disabled={!editable} value={thread.sentiment ?? ""} onChange={(e) => update({ sentiment: e.target.value || null })}>
              <option value="">{t("moodPlaceholder")}</option>
              {SENTIMENTS.map((s) => <option key={s} value={s}>{t(`sentiments.${s}`)}</option>)}
            </Select>
          </label>
        </div>
        <div className="mt-3 flex items-center gap-2.5 rounded-xl bg-fill p-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-ink text-white"><Icon name="smart_toy" size={16} /></span>
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-semibold">{t("assistantHere")}</div>
            <div className="truncate text-[11px] text-muted">{botLabel}</div>
          </div>
          <Switch checked={!thread.bot_paused} disabled={!editable} onChange={(on) => update({ bot_paused: !on })} />
        </div>
      </section>

      <section className="rounded-2xl bg-white/50 p-3">
        <Label>{t("internalNote")}</Label>
        <Textarea rows={3} value={note} disabled={!editable} placeholder={t("notePlaceholder")} onChange={(e) => setNote(e.target.value)}
          onBlur={() => note !== (thread.note || "") && update({ note })} />
        {editable && (
          <button onClick={markUnread} className="mt-2 inline-flex items-center gap-1 text-xs text-muted hover:text-text">
            <Icon name="mail" size={14} />{t("markUnread")}
          </button>
        )}
      </section>
    </div>
  );
}

function Label({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cx("mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted", className)}>{children}</div>;
}
