"use client";
/** Quick publish: photos → brand template set → framed post & story → caption → accounts → publish. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import type { Choice, MediaItem, PostResult, PublishAs, QuickData, QuickPreview } from "@/components/templates/types";
import { Avatar, Badge, Button, Card, EmptyState, Input, Modal, PageHeader, Segmented, Spinner, Textarea, cx, toast } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";

type FileItem = { id: number; name: string; mimetype: string; thumb: string };
type When = "now" | "best_time" | "schedule";
const MAX_MB = { image: 20, video: 200 } as const;

export default function QuickPublishPage() {
  const t = useTranslations("templates");
  const format = useFormatter();
  const can = useSession((s) => s.can);
  const qc = useQueryClient();
  const data = useQuery({ queryKey: ["quick-data"], queryFn: () => api.get<QuickData>("/templates/quick") });

  const [files, setFiles] = useState<FileItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [choiceKey, setChoiceKey] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [content, setContent] = useState("");
  const [brief, setBrief] = useState("");
  const [accountIds, setAccountIds] = useState<number[] | null>(null);
  const [publishAs, setPublishAs] = useState<PublishAs>("feed_story");
  const [grouping, setGrouping] = useState<"single" | "carousel">("single");
  const [when, setWhen] = useState<When>("now");
  const [scheduleAt, setScheduleAt] = useState("");
  const [result, setResult] = useState<{ mode: string; posts: PostResult[] } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const choices = useMemo(() => data.data?.choices ?? [], [data.data]);
  const current: Choice | undefined = choices.find((c) => c.key === choiceKey) ?? choices[0];
  const accounts = useMemo(() => (data.data?.accounts ?? []).filter((a) => a.platform !== "whatsapp"), [data.data]);
  const selected = accountIds ?? accounts.filter((a) => a.can_story && a.state === "connected").map((a) => a.id);
  const roles = new Set(current?.templates.map((x) => x.role));
  const textTemplate = current?.templates.find((x) => x.text_enabled);

  const chooseSet = (c: Choice) => {
    setChoiceKey(c.key);
    const r = new Set(c.templates.map((x) => x.role));
    if (r.size === 1) setPublishAs(r.has("story") ? "story" : "feed");
    else if (publishAs !== "feed_story") setPublishAs("feed_story");
  };

  // ------------------------------------------------------------ files
  const upload = async (list: File[]) => {
    if (!list.length) return;
    setUploading(true);
    try {
      for (const file of list) {
        const kind = file.type.split("/")[0] as keyof typeof MAX_MB;
        if (!(kind in MAX_MB)) {
          toast.error(t("quick.notMedia", { name: file.name }));
          continue;
        }
        if (file.size > MAX_MB[kind] * 1024 * 1024) {
          toast.error(t("quick.tooLarge", { name: file.name, mb: MAX_MB[kind] }));
          continue;
        }
        const media = await api.upload<MediaItem>("/media", file);
        setFiles((f) => [...f, { id: media.id, name: media.filename, mimetype: media.mimetype, thumb: media.thumb_url }]);
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  };
  const addRecent = (m: MediaItem) => {
    if (!files.some((f) => f.id === m.id)) setFiles((f) => [...f, { id: m.id, name: m.filename, mimetype: m.mimetype, thumb: m.thumb_url }]);
  };

  // ------------------------------------------------------------ previews (debounced)
  const [previews, setPreviews] = useState<QuickPreview[]>([]);
  const [previewBusy, setPreviewBusy] = useState(false);
  const seq = useRef(0);
  const previewKey = current && files.length ? JSON.stringify([current.key, files.map((f) => f.id), text]) : "";
  useEffect(() => {
    if (!previewKey) return;
    const mine = ++seq.current;
    const [choice, mediaIds, value] = JSON.parse(previewKey) as [string, number[], string];
    const timer = setTimeout(async () => {
      setPreviewBusy(true);
      try {
        const res = await api.post<QuickPreview[]>("/templates/quick/preview", { choice, media_ids: mediaIds, text: value || null });
        if (mine === seq.current) setPreviews(res);
      } catch (err) {
        if (mine === seq.current) toast.error(err instanceof ApiError ? err.message : String(err));
      } finally {
        if (mine === seq.current) setPreviewBusy(false);
      }
    }, value ? 450 : 150);
    return () => clearTimeout(timer);
  }, [previewKey]);
  const shownPreviews = previewKey ? previews.filter((p) => files.some((f) => f.id === p.media_id)) : [];

  // ------------------------------------------------------------ AI caption
  const writeAi = useMutation({
    mutationFn: () => api.post<{ text: string }>("/ai/text", {
      brief: [brief || content, text].filter(Boolean).join(" — "), length: "short", account_ids: selected,
      hashtags: true, emojis: true,
    }),
    onSuccess: (res) => setContent(res.text),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });

  // ------------------------------------------------------------ publish
  const publish = useMutation({
    mutationFn: (mode: "draft" | When) => api.post<{ mode: string; posts: PostResult[] }>("/templates/quick/publish", {
      choice: current!.key, media_ids: files.map((f) => f.id), text: text || null, content,
      account_ids: selected, publish_as: publishAs, grouping, mode,
      scheduled_at: mode === "schedule" && scheduleAt ? new Date(scheduleAt).toISOString() : null,
    }),
    onSuccess: (res) => {
      setResult(res);
      qc.invalidateQueries({ queryKey: ["posts"] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
  const reset = () => {
    setResult(null);
    setFiles([]);
    setPreviews([]);
    setContent("");
    setBrief("");
    setText("");
    qc.invalidateQueries({ queryKey: ["quick-data"] });
  };

  if (data.isLoading) return <div className="flex justify-center py-24"><Spinner size={26} /></div>;
  const d = data.data;
  if (!d) return null;

  const noStory = publishAs !== "feed" ? accounts.filter((a) => selected.includes(a.id) && !a.can_story) : [];
  const hasVideo = files.some((f) => f.mimetype.startsWith("video/"));
  const canSubmit = !!files.length && !!current && !publish.isPending;
  const canPublish = canSubmit && selected.length > 0 && (when !== "schedule" || !!scheduleAt);
  const bestSlot = d.best_slots[0];
  const primaryLabel = when === "now" ? t("quick.publishNow") : when === "best_time" ? t("quick.scheduleBest") : t("quick.schedule");

  const previewPanel = (
    <PreviewPanel busy={previewBusy} previews={shownPreviews} current={current} files={files.length} publishAs={publishAs}
      caption={content} />
  );

  return (
    <div className="pt-2">
      <PageHeader icon="bolt" title={t("quick.title")} subtitle={t("quick.subtitle")}
        actions={d.can_manage && <Link href="/settings/templates"><Button icon="photo_frame">{t("title")}</Button></Link>} />

      {!choices.length ? (
        <Card>
          <EmptyState icon="photo_frame" title={t("quick.noTemplatesTitle")} text={t("quick.noTemplatesText")}
            action={can("editor") ? <Link href="/templates/new"><Button variant="primary" icon="add">{t("newTemplate")}</Button></Link> : <span className="text-sm text-muted">{t("quick.askAdmin")}</span>} />
        </Card>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
          <Card className="flex min-w-0 flex-col gap-6">
            {/* 1 · photos */}
            <Step n={1} title={t("quick.photos")} aside={files.length ? <span className="text-xs text-muted">{t("quick.selected", { count: files.length })}</span> : null}>
              <div
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false); }}
                onDrop={(e) => { e.preventDefault(); setDragging(false); upload([...(e.dataTransfer.files || [])]); }}
                className={cx("rounded-2xl border-2 border-dashed p-3 transition", dragging ? "border-ink bg-fill-2" : "border-black/10 bg-white/40")}>
                <input ref={fileInput} type="file" multiple accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime" className="hidden"
                  onChange={(e) => { upload([...(e.target.files || [])]); e.target.value = ""; }} />
                <div className="flex flex-wrap gap-2">
                  {files.map((f) => (
                    <div key={f.id} className="group relative h-20 w-20 overflow-hidden rounded-xl bg-fill-2">
                      {f.mimetype.startsWith("video/") ? (
                        <span className="flex h-full w-full items-center justify-center text-text-2"><Icon name="movie" size={24} /></span>
                      ) : (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={f.thumb || `/api/media/${f.id}/file`} alt="" className="h-full w-full object-cover" />
                      )}
                      <button onClick={() => setFiles((all) => all.filter((x) => x.id !== f.id))} aria-label={t("quick.remove")}
                        className="absolute end-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-black/60 text-white backdrop-blur">
                        <Icon name="close" size={13} />
                      </button>
                    </div>
                  ))}
                  <button onClick={() => fileInput.current?.click()}
                    className="flex h-20 w-20 flex-col items-center justify-center gap-1 rounded-xl bg-white/70 text-xs font-medium text-text-2 shadow-[inset_0_0_0_1px_rgba(0,0,0,.08)] hover:bg-white">
                    {uploading ? <Spinner size={18} /> : <Icon name="add_photo" size={22} />}
                    {t("quick.add")}
                  </button>
                </div>
                {!files.length && <p className="mt-3 flex items-center gap-1.5 text-xs text-muted"><Icon name="upload" size={14} />{t("quick.dropHint")}</p>}
                {!!d.recent.length && (
                  <div className="mt-3 flex gap-1.5 overflow-x-auto pb-1">
                    {d.recent.map((m) => {
                      const used = files.some((f) => f.id === m.id);
                      return (
                        <button key={m.id} onClick={() => addRecent(m)} title={m.filename}
                          className={cx("h-12 w-12 shrink-0 overflow-hidden rounded-lg ring-2 transition", used ? "opacity-40 ring-ink" : "ring-transparent hover:ring-black/20")}>
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img src={m.thumb_url} alt="" className="h-full w-full object-cover" />
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            </Step>

            {/* 2 · template */}
            <Step n={2} title={t("quick.template")}>
              <div className="-mx-1 flex gap-3 overflow-x-auto px-1 pb-2">
                {choices.map((c) => {
                  const on = current?.key === c.key;
                  return (
                    <button key={c.key} onClick={() => chooseSet(c)}
                      className={cx("flex w-[156px] shrink-0 flex-col gap-2 rounded-2xl p-2 text-start transition",
                        on ? "bg-ink text-white shadow-[0_10px_24px_-12px_rgba(0,0,0,.7)]" : "bg-white/60 hover:bg-white")}>
                      <span className="flex h-[118px] items-end justify-center gap-1.5 rounded-xl bg-black/5 p-1.5">
                        {c.templates.slice(0, 2).map((tpl) => (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img key={tpl.id} src={tpl.preview_url} alt="" className={cx("rounded-md object-cover shadow", tpl.role === "story" ? "h-full" : "h-[78%]")} />
                        ))}
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="bidi flex-1 truncate text-sm font-semibold">{c.name}</span>
                        {on && <Icon name="check_circle" size={16} />}
                      </span>
                      <span className="flex gap-1">
                        {c.templates.map((tpl) => (
                          <span key={tpl.id} dir="ltr" className={cx("rounded-full px-1.5 text-[10px] font-semibold", on ? "bg-white/20" : "bg-fill-2 text-text-2")}>{tpl.aspect}</span>
                        ))}
                      </span>
                    </button>
                  );
                })}
              </div>
              {textTemplate && (
                <label className="flex flex-col gap-1.5">
                  <span className="text-[13px] font-medium text-text-2">{t("quick.textOnImage")}</span>
                  <Input value={text} onChange={(e) => setText(e.target.value)} placeholder={textTemplate.text_default || t("quick.textPlaceholder")} className="bidi" maxLength={300} />
                </label>
              )}
            </Step>

            <div className="lg:hidden">{previewPanel}</div>

            {/* 3 · caption */}
            <Step n={3} title={t("quick.caption")}>
              <Textarea rows={4} value={content} onChange={(e) => setContent(e.target.value)} placeholder={t("quick.captionPlaceholder")} />
              {d.has_ai && (
                <div className="flex items-center gap-2 rounded-2xl bg-fill p-1.5 ps-3">
                  <Icon name="wand_stars" size={18} className="shrink-0 text-text-2" />
                  <input value={brief} onChange={(e) => setBrief(e.target.value)} placeholder={t("quick.aiPlaceholder")}
                    onKeyDown={(e) => { if (e.key === "Enter" && (brief || content)) writeAi.mutate(); }}
                    className="bidi min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-faint" />
                  <Button size="sm" icon="auto_awesome" loading={writeAi.isPending} disabled={!brief && !content} onClick={() => writeAi.mutate()}>{t("quick.writeAi")}</Button>
                </div>
              )}
            </Step>

            {/* 4 · where & how */}
            <Step n={4} title={t("quick.where")}>
              <div className="flex flex-wrap gap-2">
                {accounts.map((a) => {
                  const on = selected.includes(a.id);
                  return (
                    <button key={a.id} onClick={() => setAccountIds(on ? selected.filter((x) => x !== a.id) : [...selected, a.id])}
                      className={cx("flex h-10 items-center gap-2 rounded-full border ps-1 pe-3 text-sm transition",
                        on ? "border-ink bg-ink text-white" : "border-line bg-white/60 hover:bg-white",
                        (a.state === "expired" || a.state === "error") && "opacity-60")}>
                      <span className="relative">
                        <Avatar name={a.name} src={a.avatar_url} size={30} />
                        <span className="absolute -bottom-1 -end-1"><PlatformBadge platform={a.platform} size={15} /></span>
                      </span>
                      <span className="bidi max-w-[150px] truncate">{a.name}</span>
                      {on && <Icon name="check" size={14} />}
                    </button>
                  );
                })}
                {!accounts.length && <span className="text-sm text-muted">{t("noAccounts")}</span>}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Segmented value={publishAs} onChange={setPublishAs}
                  options={[
                    { value: "feed", label: t("post"), icon: "photo_library" },
                    { value: "story", label: t("story"), icon: "smartphone" },
                    { value: "feed_story", label: t("both"), icon: "flip_to_front" },
                  ]} />
                {files.length > 1 && publishAs !== "story" && !hasVideo && (
                  <Segmented value={grouping} onChange={setGrouping} size="sm"
                    options={[{ value: "single", label: t("quick.onePerPhoto") }, { value: "carousel", label: t("quick.carousel") }]} />
                )}
              </div>
              {(noStory.length > 0 || (roles.size === 1 && publishAs === "feed_story") || (hasVideo && !d.ffmpeg)) && (
                <div className="flex flex-col gap-1 rounded-xl bg-warn-bg px-3 py-2 text-xs text-warn">
                  {noStory.length > 0 && <span className="flex gap-1.5"><Icon name="info" size={14} />{t("quick.noStoryOn", { names: noStory.map((a) => a.name).join("، ") })}</span>}
                  {roles.size === 1 && publishAs === "feed_story" && <span className="flex gap-1.5"><Icon name="info" size={14} />{t("quick.oneFormat")}</span>}
                  {hasVideo && !d.ffmpeg && <span className="flex gap-1.5"><Icon name="info" size={14} />{t("quick.noFfmpeg")}</span>}
                </div>
              )}
            </Step>

            {/* 5 · when */}
            <Step n={5} title={t("quick.when")}>
              <div className="flex flex-wrap items-center gap-2">
                <Segmented value={when} onChange={setWhen}
                  options={[
                    { value: "now", label: t("quick.now"), icon: "send" },
                    { value: "best_time", label: t("quick.bestTime"), icon: "event_upcoming" },
                    { value: "schedule", label: t("quick.pickDate"), icon: "calendar_today" },
                  ]} />
                {when === "schedule" && (
                  <input type="datetime-local" value={scheduleAt} onChange={(e) => setScheduleAt(e.target.value)} dir="ltr"
                    className="h-9 rounded-xl border border-line bg-white/70 px-3 text-sm outline-none focus:border-black/30" />
                )}
                {when === "best_time" && bestSlot && (
                  <Badge tone="ink"><Icon name="trending_up" size={12} />{bestSlot.label || format.dateTime(new Date(bestSlot.at), { weekday: "short", hour: "2-digit", minute: "2-digit" })}</Badge>
                )}
              </div>
              <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line pt-4">
                <Button icon="save" loading={publish.isPending && publish.variables === "draft"} disabled={!canSubmit} onClick={() => publish.mutate("draft")}>{t("quick.saveDraft")}</Button>
                <Button variant="primary" size="lg" icon={when === "now" ? "send" : "schedule"} loading={publish.isPending && publish.variables !== "draft"}
                  disabled={!canPublish} onClick={() => publish.mutate(when)}>{primaryLabel}</Button>
              </div>
            </Step>
          </Card>

          <aside className="hidden lg:block">
            <div className="sticky top-16">{previewPanel}</div>
          </aside>
        </div>
      )}

      <Modal open={!!result} onClose={() => setResult(null)} title={result ? resultTitle(result, t) : ""}
        footer={<>
          <Link href="/posts"><Button>{t("quick.allPosts")}</Button></Link>
          <Button variant="primary" icon="add" onClick={reset}>{t("quick.newQuick")}</Button>
        </>}>
        <div className="flex flex-col gap-3">
          {result?.posts.map((p) => (
            <div key={p.id} className="rounded-2xl border border-line bg-white/50 p-3">
              <div className="flex items-center gap-2">
                <span className="bidi flex-1 truncate text-sm font-semibold">{p.name || t("quick.postN", { id: p.id })}</span>
                <Badge tone={p.state === "posted" ? "ok" : p.state === "failed" || p.state === "partial" ? "bad" : p.state === "to_approve" ? "warn" : "neutral"}>
                  {t.has(`states.${p.state}`) ? t(`states.${p.state}`) : p.state}
                </Badge>
              </div>
              {p.scheduled_at && <p className="mt-1 text-xs text-muted">{format.dateTime(new Date(p.scheduled_at), { dateStyle: "medium", timeStyle: "short" })}</p>}
              {result.mode === "draft" && <p className="mt-1 text-xs text-muted">{t("quick.draftHint")}</p>}
              {p.results.map((r) => (
                <div key={r.account_id} className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                  <PlatformBadge platform={r.platform} size={20} />
                  <span className="bidi min-w-0 flex-1 truncate">{r.account}</span>
                  {r.state === "posted" && <Badge tone="ok"><Icon name="check" size={11} />{t("post")}</Badge>}
                  {r.state === "failed" && <Badge tone="bad"><Icon name="error" size={11} />{t("post")}</Badge>}
                  {r.story_state === "posted" && <Badge tone="ok"><Icon name="check" size={11} />{t("story")}</Badge>}
                  {r.story_state === "failed" && <Badge tone="bad"><Icon name="error" size={11} />{t("story")}</Badge>}
                  {r.url && <a href={r.url} target="_blank" rel="noreferrer" className="text-muted hover:text-text"><Icon name="open_in_new" size={15} /></a>}
                  {(r.error || r.story_error) && <p className="w-full text-xs text-bad">{r.error || r.story_error}</p>}
                </div>
              ))}
            </div>
          ))}
        </div>
      </Modal>
    </div>
  );
}

function resultTitle(result: { mode: string; posts: PostResult[] }, t: (key: string) => string) {
  if (result.mode === "draft") return t("quick.resultDraft");
  if (result.posts.some((p) => p.state === "to_approve")) return t("quick.resultApproval");
  if (result.mode === "best_time" || result.mode === "schedule") return t("quick.resultScheduled");
  return result.posts.some((p) => p.state === "failed" || p.state === "partial") ? t("quick.resultFailed") : t("quick.resultPublished");
}

function Step({ n, title, aside, children }: { n: number; title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center gap-2.5">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-ink text-[12px] font-bold text-white">{n}</span>
        <h2 className="text-[15px] font-semibold tracking-tight">{title}</h2>
        {aside && <div className="ms-auto">{aside}</div>}
      </div>
      {children}
    </section>
  );
}

function PreviewPanel({ busy, previews, current, files, publishAs, caption }: {
  busy: boolean; previews: QuickPreview[]; current?: Choice; files: number; publishAs: PublishAs; caption: string;
}) {
  const t = useTranslations("templates");
  const shown = (role: "post" | "story") => publishAs === "feed_story" || (publishAs === "feed" ? role === "post" : role === "story");
  return (
    <Card>
      <div className="mb-3 flex items-center gap-2">
        <Icon name="visibility" size={18} className="text-text-2" />
        <h2 className="text-[15px] font-semibold">{t("quick.preview")}</h2>
        {busy && <Spinner size={16} className="ms-auto" />}
      </div>
      {!files ? (
        <div>
          <div className="flex items-end justify-center gap-3 rounded-2xl bg-fill p-4 opacity-80">
            {current?.templates.slice(0, 2).map((tpl) => (
              <Phone key={tpl.id} src={tpl.preview_url} story={tpl.role === "story"} label={tpl.role === "story" ? t("story") : t("post")} />
            ))}
          </div>
          <p className="mt-3 text-center text-xs text-muted">{t("quick.previewEmpty")}</p>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {previews.map((p) => {
            const items = p.items.filter((i) => shown(i.role));
            return (
              <div key={p.media_id} className="flex items-end justify-center gap-3 rounded-2xl bg-fill p-3">
                {p.error && <p className="text-xs text-bad">{p.error}</p>}
                {(items.length ? items : p.items.slice(0, 1)).map((i) => (
                  <Phone key={i.role} src={i.src} story={i.role === "story"} video={p.video}
                    label={`${i.role === "story" ? t("story") : t("post")} · ${i.aspect}`} />
                ))}
              </div>
            );
          })}
          {!previews.length && <div className="flex justify-center py-10"><Spinner /></div>}
          {caption && publishAs !== "story" && (
            <p className="bidi line-clamp-4 whitespace-pre-line rounded-2xl bg-white/60 p-3 text-sm text-text-2">{caption}</p>
          )}
        </div>
      )}
    </Card>
  );
}

function Phone({ src, story, label, video }: { src: string; story: boolean; label: string; video?: boolean }) {
  return (
    <figure className={cx("flex flex-col items-center gap-1.5", story ? "w-[38%]" : "w-[52%]")}>
      <span className="relative block w-full overflow-hidden rounded-xl bg-white shadow-[0_12px_28px_-14px_rgba(0,0,0,.55)] ring-1 ring-black/5">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt="" className="block w-full" />
        {video && <span className="absolute end-1.5 top-1.5 rounded-full bg-black/60 p-1 text-white"><Icon name="movie" size={12} /></span>}
      </span>
      <figcaption className="text-[11px] font-medium text-muted" dir="auto">{label}</figcaption>
    </figure>
  );
}
