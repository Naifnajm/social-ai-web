"use client";
/** Studio: the composer — accounts, Write with AI, per-network texts, media, live preview, publish / schedule. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { type ChangeEvent, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import { ConnectDialog } from "@/components/publishing/connect-dialog";
import { MediaPicker, MediaThumb } from "@/components/publishing/media-picker";
import { PostPreview } from "@/components/publishing/preview";
import { ResultsDialog } from "@/components/publishing/results-dialog";
import type { Account, BestSlot, Media, Post, Problem, PublishAs, Studio, SubmitAction } from "@/components/publishing/types";
import { PLATFORM_LABELS } from "@/components/publishing/types";
import { AccountAvatar, StateBadge, errorText, kindOf, useFormat } from "@/components/publishing/util";
import { Button, Card, Field, IconButton, Input, PageHeader, Segmented, Select, Spinner, Switch, Textarea, cx, toast } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";

type Draft = {
  postId: number | null;
  content: string;
  variants: Record<string, string>;
  accountIds: number[];
  media: Media[];
  publishAs: PublishAs;
  scheduleOn: boolean;
  scheduleAt: string;
  brief: string;
};
const EMPTY: Draft = { postId: null, content: "", variants: {}, accountIds: [], media: [], publishAs: "feed", scheduleOn: false, scheduleAt: "", brief: "" };
const TONES = ["professional", "friendly", "playful", "inspiring", "informative", "persuasive"];
const LANGUAGES = ["auto", "ar", "en", "nl"];
const LENGTHS = ["short", "medium", "long"];

function StudioComposer() {
  const t = useTranslations("publishing.studio");
  const qc = useQueryClient();
  const fmt = useFormat();
  const params = useSearchParams();
  const studio = useQuery({ queryKey: ["studio"], queryFn: () => api.get<Studio>("/studio") });
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [tab, setTab] = useState<string>("all");
  const [previewPlatform, setPreviewPlatform] = useState<string | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [ai, setAi] = useState({ tone: "friendly", language: "auto", length: "medium", hashtags: true, emojis: true, tailor: false });
  const [generating, setGenerating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [connectOpen, setConnectOpen] = useState(false);
  const [slots, setSlots] = useState<BestSlot[] | null>(null);
  const [submitting, setSubmitting] = useState<SubmitAction | null>(null);
  const [resultId, setResultId] = useState<number | null>(null);
  const [serverProblems, setServerProblems] = useState<Problem[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  // open an existing post: /studio?post=12
  const postParam = params.get("post");
  useEffect(() => {
    if (!postParam) return;
    api.get<Post>(`/posts/${postParam}`).then((p) => {
      setDraft({
        postId: p.can_edit ? p.id : null, content: p.content, variants: p.variants || {}, accountIds: p.account_ids,
        media: p.media, publishAs: p.publish_as, scheduleOn: !!p.scheduled_at && p.state === "scheduled",
        scheduleAt: p.scheduled_at ? fmt.toLocalInput(new Date(p.scheduled_at)) : "", brief: p.ai_brief || "",
      });
      if (!p.can_edit) toast.info(t("copyOfPublished"));
    }).catch((err) => toast.error(errorText(err)));
  }, [postParam, fmt, t]);

  const data = studio.data;
  const accounts = useMemo(() => data?.accounts ?? [], [data]);
  const selected = accounts.filter((a) => draft.accountIds.includes(a.id));
  const platforms = [...new Set(selected.map((a) => a.platform))];
  const rules = data?.rules ?? {};
  const textFor = (p: string) => (draft.variants[p] || draft.content || "").trim();
  const kinds = { image: 0, video: 0, audio: 0 } as Record<string, number>;
  draft.media.forEach((m) => { kinds[kindOf(m.mimetype)] = (kinds[kindOf(m.mimetype)] || 0) + 1; });
  const storyPossible = selected.some((a) => data?.story_platforms.includes(a.platform)) && (kinds.image + kinds.video > 0);
  const publishAs: PublishAs = storyPossible ? draft.publishAs : "feed";

  const counter = (p: string) => {
    const len = textFor(p).length;
    const max = rules[p]?.max_chars || 0;
    return { len, max, level: max && len > max ? "over" : max && len > max * 0.9 ? "near" : "ok" };
  };

  const warnings = (() => {
    const out: string[] = [];
    for (const p of platforms) {
      const rule = rules[p];
      if (!rule) continue;
      const label = PLATFORM_LABELS[p];
      const c = counter(p);
      if (publishAs !== "story") {
        if (c.level === "over") out.push(t("warnTooLong", { network: label, extra: c.len - c.max }));
        if (rule.requires_media && !draft.media.length) out.push(t("warnNeedsMedia", { network: label }));
        if (kinds.video && !rule.video) out.push(t("warnNoVideo", { network: label }));
        if (kinds.audio && !rule.audio) out.push(t("warnNoAudio", { network: label }));
        if (rule.max_images && kinds.image > rule.max_images) out.push(t("warnMaxImages", { network: label, count: rule.max_images }));
      } else if (!rule.story) out.push(t("warnNoStory", { network: label }));
    }
    if ((kinds.video || kinds.audio) && draft.media.length > 1) out.push(t("warnMixed"));
    return [...new Set(out)];
  })();

  const canSubmit = selected.length > 0 && (draft.content.trim() || draft.media.length || Object.values(draft.variants).some(Boolean)) && !warnings.length && !submitting;
  const preview = platforms.includes(previewPlatform as Account["platform"]) ? previewPlatform! : platforms[0] || "facebook";
  const previewAccount = selected.find((a) => a.platform === preview);

  const toggleAccount = (id: number) => set({ accountIds: draft.accountIds.includes(id) ? draft.accountIds.filter((x) => x !== id) : [...draft.accountIds, id] });
  const editorValue = tab === "all" ? draft.content : draft.variants[tab] ?? draft.content;
  const onEdit = (value: string) => (tab === "all" ? set({ content: value }) : set({ variants: { ...draft.variants, [tab]: value } }));
  const removeVariant = (p: string) => {
    const variants = { ...draft.variants };
    delete variants[p];
    set({ variants });
  };

  const generate = async (improve: boolean) => {
    if (!improve && !draft.brief.trim()) return toast.error(t("briefNeeded"));
    setGenerating(true);
    try {
      const res = await api.post<{ text: string; variants?: Record<string, string> }>("/ai/text", {
        brief: improve ? draft.brief || draft.content : draft.brief, current_text: improve ? draft.content : "",
        platforms, tone: ai.tone, language: ai.language, length: ai.length, hashtags: ai.hashtags, emojis: ai.emojis,
        tailor: ai.tailor && platforms.length > 1, purpose: "post caption",
      });
      set({ content: res.text || draft.content, variants: { ...draft.variants, ...(res.variants || {}) } });
      setTab("all");
      toast.success(t("aiDone"));
    } catch (err) {
      if (err instanceof ApiError && (err.status === 404 || err.status === 405)) toast.error(t("aiUnavailable"));
      else toast.error(errorText(err));
    } finally {
      setGenerating(false);
    }
  };

  const onFiles = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    if (!files.length) return;
    setUploading(true);
    try {
      const added: Media[] = [];
      for (const file of files) added.push(await api.upload<Media>("/media", file));
      setDraft((d) => ({ ...d, media: [...d.media, ...added] }));
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setUploading(false);
    }
  };

  const loadSlots = async () => {
    try {
      setSlots(await api.get<BestSlot[]>("/posts/best-slots", { platforms, count: 3 }));
    } catch (err) {
      toast.error(errorText(err));
    }
  };

  const submit = async (action: SubmitAction) => {
    setSubmitting(action);
    setServerProblems([]);
    try {
      const when = action === "schedule" && draft.scheduleAt ? fmt.fromLocalInput(draft.scheduleAt) : undefined;
      if (action === "schedule" && !when) {
        toast.error(t("chooseDate"));
        return;
      }
      const post = await api.post<Post>("/posts/compose", {
        post_id: draft.postId, content: draft.content, variants: draft.variants, account_ids: draft.accountIds,
        media_ids: draft.media.map((m) => m.id), publish_as: publishAs, ai_brief: draft.brief || null, action, when,
      });
      qc.invalidateQueries({ queryKey: ["studio"] });
      qc.invalidateQueries({ queryKey: ["posts"] });
      if (action === "draft") {
        set({ postId: post.id });
        toast.success(t("draftSaved"));
      } else {
        setDraft({ ...EMPTY, accountIds: draft.accountIds });
        setTab("all");
        setSlots(null);
        setResultId(post.id);
      }
    } catch (err) {
      if (err instanceof ApiError && err.code === "invalid_post") setServerProblems((err.data as { problems?: Problem[] })?.problems || []);
      toast.error(errorText(err));
    } finally {
      setSubmitting(null);
    }
  };

  if (studio.isLoading || !data) return <div className="flex justify-center py-24"><Spinner size={28} /></div>;

  const approval = data.needs_approval;
  return (
    <div className="pt-2">
      <PageHeader icon="wand_stars" title={t("title")} subtitle={t("subtitle")}
        actions={<Link href="/posts"><Button icon="view_list">{t("allPosts")}</Button></Link>} />

      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { icon: "send", value: data.kpis.published, label: t("kpiPublished"), href: "/performance" },
          { icon: "schedule", value: data.kpis.scheduled, label: t("kpiScheduled"), href: "/posts?state=scheduled" },
          { icon: "verified_user", value: data.kpis.to_approve, label: t("kpiToApprove"), href: data.is_approver ? "/approvals" : "/posts?state=to_approve" },
          { icon: "error", value: data.kpis.failed, label: t("kpiFailed"), href: "/posts?state=failed", bad: data.kpis.failed > 0 },
        ].map((k) => (
          <Link key={k.label} href={k.href}>
            <Card className="flex items-center gap-3 !p-4 transition hover:-translate-y-0.5">
              <span className={cx("flex h-10 w-10 shrink-0 items-center justify-center rounded-xl", k.bad ? "bg-bad-bg text-bad" : "bg-fill-2")}><Icon name={k.icon} size={20} duo /></span>
              <div className="min-w-0"><div className="text-xl font-bold tabular-nums">{k.value}</div><div className="truncate text-xs text-muted">{k.label}</div></div>
            </Card>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Card className="flex min-w-0 flex-col gap-5">
          {/* 1 · accounts */}
          <section>
            <div className="mb-2.5 flex items-center gap-2">
              <h2 className="text-[15px] font-semibold">{t("stepWhere")}</h2>
              {accounts.length > 1 && (
                <button className="ms-auto text-xs font-medium text-muted hover:text-text" onClick={() => set({ accountIds: draft.accountIds.length === accounts.length ? [] : accounts.map((a) => a.id) })}>
                  {draft.accountIds.length === accounts.length ? t("selectNone") : t("selectAll")}
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              {accounts.map((a) => {
                const on = draft.accountIds.includes(a.id);
                const broken = a.state === "expired" || a.state === "error";
                return (
                  <button key={a.id} onClick={() => toggleAccount(a.id)} title={a.last_error || a.platform_label}
                    className={cx("flex h-11 items-center gap-2 rounded-full border ps-1.5 pe-3 text-sm transition",
                      on ? "border-ink bg-ink text-white shadow-[0_6px_16px_-8px_rgba(0,0,0,.6)]" : "border-line bg-white/70 hover:bg-white")}>
                    <AccountAvatar name={a.name} src={a.avatar_url} platform={a.platform} size={30} dim={!on} />
                    <span className="bidi max-w-[140px] truncate font-medium">{a.name}</span>
                    {broken && <Icon name="warning" size={14} className={on ? "text-white" : "text-bad"} />}
                  </button>
                );
              })}
              {data.can_connect && (
                <button onClick={() => setConnectOpen(true)} className="flex h-11 items-center gap-1.5 rounded-full border border-dashed border-black/15 px-4 text-sm text-muted hover:bg-fill-2 hover:text-text">
                  <Icon name="add" size={16} /> {t("connect")}
                </button>
              )}
              {!accounts.length && !data.can_connect && <p className="text-sm text-muted">{t("noAccounts")}</p>}
            </div>
          </section>

          {approval && (
            <div className="flex items-start gap-2 rounded-2xl bg-warn-bg p-3 text-sm text-warn">
              <Icon name="verified_user" size={18} className="mt-0.5 shrink-0" /> {t("approvalNotice")}
            </div>
          )}

          {/* 2 · write */}
          <section className="flex flex-col gap-3">
            <h2 className="text-[15px] font-semibold">{t("stepWrite")}</h2>
            <div className={cx("rounded-2xl border transition", aiOpen ? "border-black/15 bg-white/60" : "border-line")}>
              <button className="flex w-full items-center gap-3 p-3 text-start" onClick={() => setAiOpen(!aiOpen)}>
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-ink text-white"><Icon name="wand_stars" size={18} duo /></span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold">{t("aiTitle")}</span>
                  <span className="block truncate text-xs text-muted">{t("aiSubtitle")}</span>
                </span>
                <Icon name={aiOpen ? "expand_less" : "expand_more"} size={18} className="text-muted" />
              </button>
              {aiOpen && (
                <div className="flex flex-col gap-3 border-t border-line p-3">
                  <Textarea rows={2} value={draft.brief} placeholder={t("briefPlaceholder")} onChange={(e) => set({ brief: e.target.value })} />
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                    <Field label={t("tone")}>
                      <Select value={ai.tone} onChange={(e) => setAi({ ...ai, tone: e.target.value })}>{TONES.map((v) => <option key={v} value={v}>{t(`tones.${v}`)}</option>)}</Select>
                    </Field>
                    <Field label={t("language")}>
                      <Select value={ai.language} onChange={(e) => setAi({ ...ai, language: e.target.value })}>{LANGUAGES.map((v) => <option key={v} value={v}>{t(`languages.${v}`)}</option>)}</Select>
                    </Field>
                    <Field label={t("length")} className="col-span-2 sm:col-span-1">
                      <Segmented size="sm" value={ai.length} onChange={(v) => setAi({ ...ai, length: v })} options={LENGTHS.map((v) => ({ value: v, label: t(`lengths.${v}`) }))} />
                    </Field>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
                    <Switch checked={ai.hashtags} onChange={(v) => setAi({ ...ai, hashtags: v })} label={t("hashtags")} />
                    <Switch checked={ai.emojis} onChange={(v) => setAi({ ...ai, emojis: v })} label={t("emojis")} />
                    <Switch checked={ai.tailor && platforms.length > 1} disabled={platforms.length < 2} onChange={(v) => setAi({ ...ai, tailor: v })} label={t("tailor")} />
                    <div className="ms-auto flex gap-2">
                      {draft.content.trim() && <Button size="sm" icon="autorenew" disabled={generating} onClick={() => generate(true)}>{t("improve")}</Button>}
                      <Button size="sm" variant="primary" icon="wand_stars" loading={generating} onClick={() => generate(false)}>{generating ? t("writing") : t("generate")}</Button>
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-line bg-white/70">
              {platforms.length > 1 && (
                <div className="flex gap-1 overflow-x-auto border-b border-line p-1.5">
                  <TabButton active={tab === "all"} onClick={() => setTab("all")}>{t("allNetworks")}</TabButton>
                  {platforms.map((p) => (
                    <TabButton key={p} active={tab === p} onClick={() => setTab(p)}>
                      <PlatformBadge platform={p} size={18} />{PLATFORM_LABELS[p]}
                      {draft.variants[p] && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
                    </TabButton>
                  ))}
                </div>
              )}
              <textarea rows={8} value={editorValue} onChange={(e) => onEdit(e.target.value)}
                placeholder={tab === "all" ? t("editorPlaceholder") : t("variantPlaceholder")}
                className="bidi block w-full resize-y bg-transparent p-3.5 text-[15px] leading-relaxed outline-none placeholder:text-faint" />
              <div className="flex flex-wrap items-center gap-2 border-t border-line px-3 py-2">
                {platforms.map((p) => {
                  const c = counter(p);
                  return (
                    <span key={p} title={PLATFORM_LABELS[p]} className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold tabular-nums",
                      c.level === "over" ? "bg-bad-bg text-bad" : c.level === "near" ? "bg-warn-bg text-warn" : "bg-fill-2 text-text-2")}>
                      <PlatformBadge platform={p} size={14} />{c.len}{c.max ? `/${c.max}` : ""}
                    </span>
                  );
                })}
                {tab !== "all" && draft.variants[tab] !== undefined && (
                  <button className="ms-auto text-xs font-medium text-muted hover:text-text" onClick={() => removeVariant(tab)}>{t("useMainText")}</button>
                )}
              </div>
            </div>

            {/* media */}
            <div className="flex flex-wrap gap-2">
              {draft.media.map((m) => (
                <div key={m.id} className="group relative h-24 w-24 overflow-hidden rounded-xl border border-line">
                  <MediaThumb media={m} />
                  <button aria-label={t("remove")} onClick={() => set({ media: draft.media.filter((x) => x.id !== m.id) })}
                    className="absolute end-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-black/60 text-white opacity-90 hover:bg-black">
                    <Icon name="close" size={14} />
                  </button>
                </div>
              ))}
              <button onClick={() => fileRef.current?.click()} disabled={uploading}
                className="flex h-24 w-24 flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-black/15 text-xs text-muted hover:bg-fill-2 hover:text-text">
                {uploading ? <Spinner size={20} /> : <Icon name="upload" size={22} />}{t("upload")}
              </button>
              <button onClick={() => setPickerOpen(true)}
                className="flex h-24 w-24 flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-black/15 text-xs text-muted hover:bg-fill-2 hover:text-text">
                <Icon name="photo_library" size={22} />{t("library")}
              </button>
              <input ref={fileRef} type="file" multiple hidden accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime,audio/mpeg,audio/wav,audio/mp4" onChange={onFiles} />
            </div>

            {(warnings.length > 0 || serverProblems.length > 0) && (
              <ul className="flex flex-col gap-1 rounded-2xl bg-warn-bg p-3 text-sm text-warn">
                {[...new Set([...warnings, ...serverProblems.map((p) => p.message)])].map((w) => (
                  <li key={w} className="flex items-start gap-2"><Icon name="warning" size={16} className="mt-0.5 shrink-0" /><span className="bidi">{w}</span></li>
                ))}
              </ul>
            )}
          </section>

          {/* 3 · publish */}
          <section className="flex flex-col gap-3">
            <h2 className="text-[15px] font-semibold">{t("stepPublish")}</h2>
            {storyPossible && (
              <div className="flex flex-wrap items-center gap-3">
                <Segmented value={draft.publishAs} onChange={(v) => set({ publishAs: v })} options={[
                  { value: "feed", label: t("feed"), icon: "photo_library" },
                  { value: "story", label: t("story"), icon: "smartphone" },
                  { value: "feed_story", label: t("both"), icon: "flip_to_front" },
                ]} />
                {draft.publishAs !== "feed" && <span className="text-xs text-muted">{t("storyHint")}</span>}
              </div>
            )}
            {slots && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-medium text-muted">{t("bestUpcoming")}</span>
                {slots.map((s) => (
                  <button key={s.at} onClick={() => { set({ scheduleOn: true, scheduleAt: fmt.toLocalInput(new Date(s.at)) }); setSlots(null); }}
                    className="inline-flex h-8 items-center gap-1.5 rounded-full bg-fill-2 px-3 text-xs font-medium hover:bg-ink hover:text-white">
                    <Icon name="event_upcoming" size={14} />{s.label}
                  </button>
                ))}
                <IconButton icon="close" label={t("close")} className="!h-8 !w-8" onClick={() => setSlots(null)} />
              </div>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <Switch checked={draft.scheduleOn} onChange={(v) => set({ scheduleOn: v, scheduleAt: v && !draft.scheduleAt ? fmt.toLocalInput(new Date(Date.now() + 3600_000)) : draft.scheduleAt })} label={t("scheduleLater")} />
              {draft.scheduleOn && <Input type="datetime-local" dir="ltr" className="!w-auto" value={draft.scheduleAt} onChange={(e) => set({ scheduleAt: e.target.value })} />}
              <Button size="sm" variant="ghost" icon="schedule" disabled={!platforms.length} onClick={loadSlots}>{t("bestTime")}</Button>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line pt-4">
              {draft.postId && <span className="me-auto text-xs text-muted">{t("editingDraft", { id: draft.postId })}</span>}
              <Button icon="save" loading={submitting === "draft"} disabled={!!submitting || (!draft.content.trim() && !draft.media.length)} onClick={() => submit("draft")}>{t("saveDraft")}</Button>
              {draft.scheduleOn ? (
                <Button variant="primary" icon="schedule" loading={submitting === "schedule"} disabled={!canSubmit} onClick={() => submit("schedule")}>
                  {approval ? t("submitApproval") : t("schedule")}
                </Button>
              ) : (
                <Button variant="primary" icon="send" loading={submitting === "publish"} disabled={!canSubmit} onClick={() => submit("publish")}>
                  {approval ? t("submitApproval") : t("publishNow")}
                </Button>
              )}
            </div>
          </section>
        </Card>

        <aside className="flex min-w-0 flex-col gap-5">
          <Card>
            <div className="mb-3 flex items-center gap-2">
              <Icon name="visibility" size={18} className="text-text-2" />
              <h2 className="text-[15px] font-semibold">{t("preview")}</h2>
              <div className="ms-auto flex gap-1">
                {platforms.map((p) => (
                  <button key={p} onClick={() => setPreviewPlatform(p)} className={cx("rounded-[10px] p-0.5 transition", preview === p ? "ring-2 ring-ink" : "opacity-50 hover:opacity-100")}>
                    <PlatformBadge platform={p} size={24} />
                  </button>
                ))}
              </div>
            </div>
            <PostPreview platform={preview} name={previewAccount?.name || t("yourBrand")} username={previewAccount?.username} avatar={previewAccount?.avatar_url}
              text={textFor(preview)} media={(publishAs === "story" ? [] : draft.media)} story={draft.media} publishAs={publishAs} />
          </Card>
          <Card>
            <div className="mb-2 flex items-center gap-2">
              <Icon name="history" size={18} className="text-text-2" />
              <h2 className="text-[15px] font-semibold">{t("recent")}</h2>
              <Link href="/posts" className="ms-auto text-xs font-medium text-muted hover:text-text">{t("seeAll")}</Link>
            </div>
            {!data.recent_posts.length ? <p className="py-4 text-sm text-muted">{t("nothingYet")}</p> : (
              <ul className="divide-y divide-line">
                {data.recent_posts.map((p) => (
                  <li key={p.id}>
                    <Link href={p.can_edit ? `/studio?post=${p.id}` : `/posts?post=${p.id}`} className="flex items-center gap-3 py-2.5">
                      <div className="min-w-0 flex-1">
                        <div className="bidi truncate text-sm font-medium">{p.name || t("untitled")}</div>
                        <div className="mt-0.5 flex items-center gap-1">
                          {p.platforms.map((pf) => <PlatformBadge key={pf} platform={pf} size={16} />)}
                          <span className="ms-1 truncate text-xs text-muted">{fmt.dateTime(p.published_at || p.scheduled_at || p.updated_at)}</span>
                        </div>
                      </div>
                      <StateBadge state={p.state} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </aside>
      </div>

      <MediaPicker open={pickerOpen} onClose={() => setPickerOpen(false)} selected={draft.media.map((m) => m.id)} onPick={(items) => set({ media: [...draft.media, ...items] })} />
      <ConnectDialog open={connectOpen} onClose={() => setConnectOpen(false)} />
      <ResultsDialog postId={resultId} onClose={() => { setResultId(null); qc.invalidateQueries({ queryKey: ["studio"] }); }} />
    </div>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} className={cx("inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3 text-[13px] font-medium transition",
      active ? "bg-ink text-white" : "text-text-2 hover:bg-fill-2")}>
      {children}
    </button>
  );
}

export default function StudioPage() {
  return (
    <Suspense>
      <StudioComposer />
    </Suspense>
  );
}
