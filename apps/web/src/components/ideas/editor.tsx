"use client";
/** Edit an idea before approving it: text per network, hashtags, slides or video script, time and accounts. */
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { type KeyboardEvent, type ReactNode, useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import { PLATFORM_LABELS } from "@/components/planning/ui";
import type { Studio } from "@/components/publishing/types";
import { AccountAvatar } from "@/components/publishing/util";
import { Button, Field, IconButton, Input, Modal, Segmented, Textarea, cx, toast } from "@/components/ui";
import { useRouter } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { SlideFace } from "./previews";
import { FormatChip, useBrandLook, useIdeaActions, useIdeaFormat } from "./shared";
import type { Idea, IdeaAccount, IdeaPatch, Scene, Slide, VideoScript } from "./types";

type TimeMode = "suggested" | "best" | "custom";
const MAX_SLIDES = 10;
const MAX_TAGS = 10;

export function IdeaEditor({ idea, accounts, now, onClose }: { idea: Idea; accounts: IdeaAccount[]; now: number; onClose: () => void }) {
  const t = useTranslations("ideas.editor");
  const fmt = useIdeaFormat();
  const router = useRouter();
  const look = useBrandLook();
  const { save, approve } = useIdeaActions();
  const studio = useQuery({ queryKey: ["studio"], queryFn: () => api.get<Studio>("/studio"), staleTime: 60_000 });
  const rules = studio.data?.rules ?? {};
  const isVideo = idea.format === "video";

  const [title, setTitle] = useState(idea.title);
  const [caption, setCaption] = useState(idea.caption);
  const [variants, setVariants] = useState<Record<string, string>>(idea.variants);
  const [tab, setTab] = useState("all");
  const [tags, setTags] = useState<string[]>(idea.hashtags);
  const [tagInput, setTagInput] = useState("");
  const [slides, setSlides] = useState<Slide[]>(idea.slides.length ? idea.slides : [{ title: "", body: "" }]);
  const [video, setVideo] = useState<VideoScript>(idea.video ?? { hook: "", duration: 30, scenes: [], voiceover: "" });
  const [accountIds, setAccountIds] = useState<number[]>(idea.account_ids);
  const [mode, setMode] = useState<TimeMode>(idea.suggested_at ? "suggested" : "best");
  const [custom, setCustom] = useState(() => fmt.toLocalInput(new Date(idea.suggested_at || now + 86_400_000)));

  const selected = accounts.filter((a) => accountIds.includes(a.id));
  const platforms = [...new Set(selected.map((a) => a.platform))];
  const tabs = ["all", ...Object.keys(variants)];
  const text = tab === "all" ? caption : variants[tab] ?? "";
  const setText = (v: string) => (tab === "all" ? setCaption(v) : setVariants({ ...variants, [tab]: v }));
  const tagsLength = tags.length ? tags.join(" ").length + 2 : 0;
  const limitFor = (p: string) => rules[p]?.max_chars || 0;
  const limit = tab === "all"
    ? Math.min(...platforms.filter((p) => !variants[p]).map(limitFor).filter(Boolean), Infinity)
    : limitFor(tab);
  const length = text.length + tagsLength;
  const over = Number.isFinite(limit) && limit > 0 && length > limit;

  const addTag = () => {
    const parts = tagInput.split(/[\s,،]+/).map((p) => p.replace(/^#+/, "").trim()).filter(Boolean).map((p) => `#${p}`);
    const next = [...tags];
    for (const p of parts) if (!next.includes(p) && next.length < MAX_TAGS) next.push(p);
    setTags(next);
    setTagInput("");
  };
  const onTagKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === "," || e.key === " ") {
      e.preventDefault();
      addTag();
    } else if (e.key === "Backspace" && !tagInput && tags.length) setTags(tags.slice(0, -1));
  };

  const moveSlide = (i: number, by: number) => {
    const next = [...slides];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    setSlides(next);
  };
  const editSlide = (i: number, patch: Partial<Slide>) => setSlides(slides.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const editScene = (i: number, patch: Partial<Scene>) => setVideo({ ...video, scenes: video.scenes.map((s, j) => (j === i ? { ...s, ...patch } : s)) });

  const customIso = () => fmt.fromLocalInput(custom);
  const problems = (forApprove: boolean): string | null => {
    if (!title.trim()) return t("needTitle");
    if (forApprove && !isVideo && !accountIds.length) return t("needAccount");
    if (mode === "custom" && !isVideo && (!custom || Date.parse(customIso()) < Date.now() + 5 * 60_000)) return t("needFuture");
    return null;
  };

  const patch = (): IdeaPatch => {
    const out: IdeaPatch = {};
    const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
    if (title.trim() !== idea.title) out.title = title.trim();
    if (caption !== idea.caption) out.caption = caption;
    if (!same(variants, idea.variants)) out.variants = variants;
    if (!same(tags, idea.hashtags)) out.hashtags = tags;
    if (idea.format === "carousel") {
      const clean = slides.filter((s) => s.title.trim() || s.body.trim());
      if (!same(clean, idea.slides)) out.slides = clean;
    }
    if (isVideo) {
      const clean = { ...video, scenes: video.scenes.filter((s) => s.visual.trim() || s.text.trim()) };
      if (!same(clean, idea.video)) out.video = clean;
    }
    if (!same([...accountIds].sort(), [...idea.account_ids].sort())) out.account_ids = accountIds;
    if (mode === "custom" && !isVideo && customIso() !== idea.suggested_at) out.suggested_at = customIso();
    return out;
  };

  const busy = save.isPending || approve.isPending;
  const submit = async (andApprove: boolean) => {
    const problem = problems(andApprove);
    if (problem) return toast.error(problem);
    const body = patch();
    try {
      if (Object.keys(body).length) await save.mutateAsync({ id: idea.id, patch: body });
      if (!andApprove) {
        toast.success(t("saved"));
        return onClose();
      }
      const r = await approve.mutateAsync({
        id: idea.id,
        mode: isVideo ? "draft" : mode === "custom" ? "schedule" : mode === "best" ? "best_time" : "suggested",
        when: mode === "custom" && !isVideo ? customIso() : undefined,
        account_ids: accountIds,
      });
      onClose();
      if (isVideo) router.push(r.url);
    } catch {
      /* the hooks already showed the error */
    }
  };

  return (
    <Modal open onClose={onClose} size="lg" title={
      <span className="flex items-center gap-2">{t("title")} <FormatChip format={idea.format} /></span>
    } footer={
      <>
        <Button variant="ghost" onClick={onClose} disabled={busy}>{t("cancel")}</Button>
        <Button onClick={() => submit(false)} loading={save.isPending && !approve.isPending} disabled={busy}>{t("save")}</Button>
        <Button variant="primary" icon={isVideo ? "wand_stars" : "event_add"} onClick={() => submit(true)} loading={approve.isPending} disabled={busy}>
          {isVideo ? t("saveOpenStudio") : t("saveApprove")}
        </Button>
      </>
    }>
      <div className="flex flex-col gap-6">
        <Field label={t("ideaTitle")}>
          <Input dir="auto" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
        </Field>

        {/* ------------------------------------------------------------ caption */}
        <Section icon="text_fields" title={t("caption")}>
          {tabs.length > 1 && (
            <div className="mb-2 flex flex-wrap gap-1.5" role="tablist">
              {tabs.map((p) => (
                <span key={p} className={cx("inline-flex h-8 items-center gap-1.5 rounded-full ps-3 text-[12.5px] font-medium transition",
                  p === "all" && "pe-3", tab === p ? "bg-ink text-white" : "bg-fill-2 text-text-2 hover:text-text")}>
                  <button type="button" role="tab" aria-selected={tab === p} onClick={() => setTab(p)} className="inline-flex items-center gap-1.5">
                    {p !== "all" && <PlatformBadge platform={p} size={16} />}
                    {p === "all" ? t("allNetworks") : PLATFORM_LABELS[p] ?? p}
                  </button>
                  {p !== "all" && (
                    <button type="button" aria-label={t("removeVariant")} title={t("removeVariant")} className="me-1 rounded-full p-1 opacity-70 hover:opacity-100"
                      onClick={() => {
                        const next = { ...variants };
                        delete next[p];
                        setVariants(next);
                        setTab("all");
                      }}>
                      <Icon name="close" size={12} />
                    </button>
                  )}
                </span>
              ))}
            </div>
          )}
          <Textarea dir="auto" rows={6} value={text} maxLength={5000} onChange={(e) => setText(e.target.value)} placeholder={t("captionPlaceholder")} />
          <div className="mt-1 flex items-center gap-2 text-[11.5px]">
            {tab !== "all" && <span className="text-muted">{t("variantHint", { network: PLATFORM_LABELS[tab] ?? tab })}</span>}
            <span dir="ltr" className={cx("ms-auto tabular-nums", over ? "font-semibold text-bad" : "text-faint")}>
              {Number.isFinite(limit) && limit > 0 ? `${length} / ${limit}` : length}
            </span>
          </div>
        </Section>

        {/* ----------------------------------------------------------- hashtags */}
        <Section icon="tag" title={t("hashtags")} hint={t("hashtagsHint", { n: MAX_TAGS })}>
          <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-line bg-white/70 p-1.5 focus-within:border-black/30 focus-within:ring-4 focus-within:ring-black/5">
            {tags.map((h) => (
              <span key={h} className="inline-flex h-7 items-center gap-1 rounded-full bg-accent-soft ps-2.5 pe-1 text-[12.5px] font-medium text-accent-deep">
                <bdi>{h}</bdi>
                <button type="button" aria-label={t("removeTag", { tag: h })} onClick={() => setTags(tags.filter((x) => x !== h))} className="rounded-full p-0.5 hover:bg-white/60">
                  <Icon name="close" size={12} />
                </button>
              </span>
            ))}
            {tags.length < MAX_TAGS && (
              <input dir="auto" value={tagInput} onChange={(e) => setTagInput(e.target.value)} onKeyDown={onTagKey} onBlur={addTag}
                placeholder={t("addTag")} className="h-7 min-w-[8rem] flex-1 bg-transparent px-1.5 text-sm outline-none placeholder:text-faint" />
            )}
          </div>
        </Section>

        {/* ------------------------------------------------------------- slides */}
        {idea.format === "carousel" && (
          <Section icon="photo_library" title={t("slides")} hint={t("slidesHint")}>
            <ol className="flex flex-col gap-3">
              {slides.map((s, i) => (
                <li key={i} className="flex gap-3 rounded-2xl bg-fill p-2.5">
                  <div className="w-20 shrink-0 overflow-hidden rounded-lg shadow-[var(--ring)] sm:w-24">
                    <SlideFace slide={s} index={i} total={slides.length} look={look} />
                  </div>
                  <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                    <Input dir="auto" value={s.title} maxLength={120} placeholder={t("slideTitle", { n: i + 1 })} onChange={(e) => editSlide(i, { title: e.target.value })} />
                    <Textarea dir="auto" rows={2} value={s.body} maxLength={400} placeholder={t("slideBody")} onChange={(e) => editSlide(i, { body: e.target.value })} />
                  </div>
                  <div className="flex shrink-0 flex-col items-center">
                    <IconButton icon="arrow_upward" label={t("moveUp")} disabled={i === 0} onClick={() => moveSlide(i, -1)} className="h-8 w-8" />
                    <IconButton icon="arrow_downward" label={t("moveDown")} disabled={i === slides.length - 1} onClick={() => moveSlide(i, 1)} className="h-8 w-8" />
                    <IconButton icon="delete" label={t("removeSlide")} disabled={slides.length <= 1} onClick={() => setSlides(slides.filter((_, j) => j !== i))} className="h-8 w-8" />
                  </div>
                </li>
              ))}
            </ol>
            {slides.length < MAX_SLIDES && (
              <Button size="sm" icon="add" className="mt-2" onClick={() => setSlides([...slides, { title: "", body: "" }])}>{t("addSlide")}</Button>
            )}
          </Section>
        )}

        {/* -------------------------------------------------------------- video */}
        {isVideo && (
          <Section icon="movie" title={t("script")}>
            <div className="flex flex-col gap-3">
              <Field label={t("hook")}>
                <Textarea dir="auto" rows={2} value={video.hook} maxLength={300} onChange={(e) => setVideo({ ...video, hook: e.target.value })} />
              </Field>
              <Field label={t("duration")}>
                <div className="flex flex-wrap items-center gap-2">
                  <Segmented size="sm" value={[15, 30, 60, 90].includes(video.duration) ? video.duration : 0}
                    onChange={(d) => d && setVideo({ ...video, duration: d })}
                    options={[15, 30, 60, 90].map((d) => ({ value: d, label: t("seconds", { n: d }) }))} />
                  <Input type="number" min={5} max={180} dir="ltr" value={video.duration} className="w-24"
                    onChange={(e) => setVideo({ ...video, duration: Math.max(5, Math.min(180, Number(e.target.value) || 5)) })} aria-label={t("duration")} />
                </div>
              </Field>
              <div>
                <div className="mb-1.5 text-[13px] font-medium text-text-2">{t("scenes")}</div>
                <ol className="flex flex-col gap-2">
                  {video.scenes.map((s, i) => (
                    <li key={i} className="flex items-start gap-2 rounded-2xl bg-fill p-2.5">
                      <span className="mt-2 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink text-[11px] font-bold text-white tabular-nums">{i + 1}</span>
                      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                        <Input dir="auto" value={s.visual} maxLength={300} placeholder={t("sceneVisual")} onChange={(e) => editScene(i, { visual: e.target.value })} />
                        <Input dir="auto" value={s.text} maxLength={200} placeholder={t("sceneText")} onChange={(e) => editScene(i, { text: e.target.value })} />
                      </div>
                      <IconButton icon="delete" label={t("removeScene")} onClick={() => setVideo({ ...video, scenes: video.scenes.filter((_, j) => j !== i) })} />
                    </li>
                  ))}
                </ol>
                {video.scenes.length < 12 && (
                  <Button size="sm" icon="add" className="mt-2" onClick={() => setVideo({ ...video, scenes: [...video.scenes, { visual: "", text: "" }] })}>{t("addScene")}</Button>
                )}
              </div>
              <Field label={t("voiceover")}>
                <Textarea dir="auto" rows={4} value={video.voiceover} maxLength={2000} onChange={(e) => setVideo({ ...video, voiceover: e.target.value })} />
              </Field>
            </div>
          </Section>
        )}

        {/* --------------------------------------------------------------- time */}
        {isVideo ? (
          <p className="flex items-start gap-2 rounded-2xl bg-fill px-3 py-2.5 text-[13px] text-muted">
            <Icon name="info" size={16} className="mt-0.5 shrink-0" />{t("videoNote")}
          </p>
        ) : (
          <Section icon="schedule" title={t("when")}>
            <div className="grid gap-2 sm:grid-cols-3">
              {idea.suggested_at && (
                <Choice active={mode === "suggested"} onClick={() => setMode("suggested")} icon="event_upcoming"
                  title={t("suggested")} text={fmt.slot(idea.suggested_at, now)} />
              )}
              <Choice active={mode === "best"} onClick={() => setMode("best")} icon="auto_awesome" title={t("bestTime")} text={t("bestTimeHint")} />
              <Choice active={mode === "custom"} onClick={() => setMode("custom")} icon="calendar_today" title={t("custom")} text={t("customHint")} />
            </div>
            {mode === "custom" && (
              <div className="pop-in mt-2.5 flex flex-wrap items-center gap-2">
                <Input type="datetime-local" dir="ltr" value={custom} onChange={(e) => setCustom(e.target.value)} className="w-auto" aria-label={t("custom")} />
                <span className="text-xs text-muted" dir="ltr">{fmt.timeZone}</span>
              </div>
            )}
          </Section>
        )}

        {/* ----------------------------------------------------------- accounts */}
        <Section icon="group" title={t("accounts")} hint={isVideo ? undefined : t("accountsHint")}>
          {!accounts.length ? <p className="text-sm text-muted">{t("noAccounts")}</p> : (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {accounts.map((a) => {
                const on = accountIds.includes(a.id);
                return (
                  <button key={a.id} type="button" role="checkbox" aria-checked={on}
                    onClick={() => setAccountIds(on ? accountIds.filter((x) => x !== a.id) : [...accountIds, a.id])}
                    className={cx("flex items-center gap-2.5 rounded-2xl border p-2 text-start transition",
                      on ? "border-ink bg-white shadow-[0_0_0_1px_var(--ink)]" : "border-line bg-white/60 hover:bg-white")}>
                    <AccountAvatar name={a.name} src={a.avatar_url} platform={a.platform} size={32} dim={!on} />
                    <span className="min-w-0 flex-1">
                      <span dir="auto" className="block truncate text-[13px] font-semibold">{a.name}</span>
                      <span className="block text-[11px] text-muted">{PLATFORM_LABELS[a.platform] ?? a.platform}</span>
                    </span>
                    <span className={cx("flex h-5 w-5 items-center justify-center rounded-md border", on ? "border-ink bg-ink text-white" : "border-black/20")}>
                      {on && <Icon name="check" size={13} />}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </Section>
      </div>
    </Modal>
  );
}

function Section({ icon, title, hint, children }: { icon: string; title: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <section>
      <div className="mb-2 flex items-baseline gap-2">
        <Icon name={icon} size={16} className="self-center text-text-2" />
        <h4 className="text-[14px] font-semibold">{title}</h4>
        {hint && <span className="ms-auto text-[11.5px] text-muted">{hint}</span>}
      </div>
      {children}
    </section>
  );
}

function Choice({ active, onClick, icon, title, text }: { active: boolean; onClick: () => void; icon: string; title: string; text: string }) {
  return (
    <button type="button" role="radio" aria-checked={active} onClick={onClick}
      className={cx("flex items-start gap-2 rounded-2xl border p-3 text-start transition",
        active ? "border-ink bg-white shadow-[0_0_0_1px_var(--ink)]" : "border-line bg-white/60 hover:bg-white")}>
      <Icon name={icon} size={18} className={active ? "text-text" : "text-muted"} />
      <span className="min-w-0">
        <span className="block text-[13px] font-semibold">{title}</span>
        <span className="block text-[12px] text-muted">{text}</span>
      </span>
    </button>
  );
}
