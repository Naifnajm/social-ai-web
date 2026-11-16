"use client";
/**
 * What an idea will look like: a social post, a carousel in the brand's colours (live, or the real rendered images)
 * or a vertical video storyboard.
 */
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import { Avatar, cx } from "@/components/ui";
import { mediaUrl } from "@/lib/api";
import { useSession } from "@/lib/session";
import { type BrandLook, useBrandLook } from "./shared";
import type { Idea, Slide, VideoScript } from "./types";

// ------------------------------------------------------------------------------------------------ post
export function PostPreview({ idea, platforms }: { idea: Idea; platforms: string[] }) {
  const t = useTranslations("ideas.preview");
  const workspace = useSession((s) => s.workspace);
  const [open, setOpen] = useState(false);
  const caption = idea.caption.trim();
  const long = caption.length > 240 || caption.split("\n").length > 5;
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-white">
      <div className="flex items-center gap-2.5 px-3 pt-3">
        <Avatar name={workspace?.name ?? ""} src={workspace?.logo_media_id ? mediaUrl(workspace.logo_media_id) : null} size={32} />
        <div className="min-w-0 flex-1">
          <div dir="auto" className="truncate text-[13px] font-semibold">{workspace?.name}</div>
          <div className="text-[11px] text-muted">{t("label")}</div>
        </div>
        <span className="flex items-center gap-1">
          {platforms.slice(0, 4).map((p) => <PlatformBadge key={p} platform={p} size={18} />)}
        </span>
      </div>
      <div className="px-3 pb-3 pt-2.5">
        {caption ? (
          <>
            <p dir="auto" className={cx("whitespace-pre-wrap break-words text-[13.5px] leading-relaxed", !open && "line-clamp-5")}>
              {caption}
            </p>
            {(long || open) && (
              <button type="button" onClick={() => setOpen(!open)} className="mt-0.5 text-[12.5px] font-semibold text-muted hover:text-text">
                {open ? t("less") : t("more")}
              </button>
            )}
          </>
        ) : <p className="text-sm text-faint">{t("empty")}</p>}
        {idea.hashtags.length > 0 && (
          <p dir="auto" className="mt-2 flex flex-wrap gap-x-1.5 text-[13px] font-medium text-accent-deep">
            {idea.hashtags.map((h) => <bdi key={h}>{h}</bdi>)}
          </p>
        )}
      </div>
      <div className="flex gap-5 border-t border-line px-3 py-2 text-faint">
        <Icon name="favorite" size={17} /><Icon name="mode_comment" size={17} /><Icon name="share" size={17} />
      </div>
    </div>
  );
}

// -------------------------------------------------------------------------------------------- carousel
/** One slide drawn live in the brand's colours; scales with its box (container query units). */
export function SlideFace({ slide, index, total, look, className }: { slide: Slide; index: number; total: number; look: BrandLook; className?: string }) {
  const first = index === 0;
  const last = index === total - 1;
  return (
    <div className={cx("relative aspect-[4/5] w-full overflow-hidden [container-type:inline-size]", className)} style={{ background: look.background, color: look.text }}>
      <div className="absolute inset-0 flex flex-col p-[9cqw]">
        <div className="flex items-center justify-between">
          <span className="h-[1.2cqw] w-[11cqw] rounded-full" style={{ background: look.accent }} />
          <span dir="ltr" className="text-[3cqw] font-medium opacity-80 tabular-nums">{index + 1}/{total}</span>
        </div>
        <div dir="auto" className={cx("mt-[7cqw] font-bold leading-[1.15] tracking-tight [overflow-wrap:anywhere]", first ? "text-[9.5cqw]" : "text-[7.6cqw]")}>
          {slide.title}
        </div>
        {slide.body && <div dir="auto" className="mt-[3.5cqw] line-clamp-6 text-[4.6cqw] leading-[1.45] opacity-90 [overflow-wrap:anywhere]">{slide.body}</div>}
        {last && <span className="mt-auto mb-[3cqw] h-[0.4cqw] w-full rounded-full" style={{ background: look.accent }} />}
        <div className={cx("flex items-center gap-[2cqw]", !last && "mt-auto")}>
          {look.logo && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={look.logo} alt="" className="h-[9cqw] w-auto max-w-[24cqw] object-contain" />
          )}
          <span dir="auto" className="ms-auto truncate text-[3.2cqw] font-bold">{look.name}</span>
        </div>
      </div>
    </div>
  );
}

export function CarouselPreview({ idea, real, onShowReal, rendering, canRender }: {
  idea: Idea; real: boolean; onShowReal: (real: boolean) => void; rendering: boolean; canRender: boolean;
}) {
  const t = useTranslations("ideas.preview");
  const look = useBrandLook();
  const strip = useRef<HTMLDivElement>(null);
  const [index, setIndex] = useState(0);
  const images = real && idea.media_urls.length > 0;
  const total = images ? idea.media_urls.length : idea.slides.length;
  const onScroll = () => {
    const el = strip.current;
    if (el) setIndex(Math.min(total - 1, Math.round(Math.abs(el.scrollLeft) / Math.max(1, el.clientWidth))));
  };
  const go = (i: number) => {
    const el = strip.current?.children[i] as HTMLElement | undefined;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "nearest", inline: "start" });
  };
  if (!total) return <p className="rounded-2xl bg-fill px-3 py-6 text-center text-sm text-muted">{t("noSlides")}</p>;
  return (
    <div>
      <div className="relative overflow-hidden rounded-2xl bg-fill-2 shadow-[var(--ring)]">
        <div ref={strip} onScroll={onScroll} className="flex snap-x snap-mandatory overflow-x-auto overscroll-x-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          role="group" aria-roledescription={t("carousel")}>
          {images
            ? idea.media_urls.map((src, i) => (
              <div key={src} className="w-full shrink-0 snap-start" aria-label={t("slideOf", { n: i + 1, total })}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={src} alt="" className="aspect-[4/5] w-full object-cover" loading="lazy" />
              </div>
            ))
            : idea.slides.map((s, i) => (
              <div key={i} className="w-full shrink-0 snap-start" aria-label={t("slideOf", { n: i + 1, total })}>
                <SlideFace slide={s} index={i} total={total} look={look} />
              </div>
            ))}
        </div>
        {index > 0 && (
          <button type="button" onClick={() => go(index - 1)} aria-label={t("previous")}
            className="absolute start-2 top-1/2 hidden h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full bg-white/85 text-text shadow sm:flex">
            <Icon name="east" size={16} className="ltr:-scale-x-100" />
          </button>
        )}
        {index < total - 1 && (
          <button type="button" onClick={() => go(index + 1)} aria-label={t("next")}
            className="absolute end-2 top-1/2 hidden h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full bg-white/85 text-text shadow sm:flex">
            <Icon name="east" size={16} className="rtl:-scale-x-100" />
          </button>
        )}
        {images && <span className="absolute start-2 top-2 rounded-full bg-black/55 px-2 py-0.5 text-[11px] font-medium text-white">{t("realImages")}</span>}
      </div>
      <div className="mt-2 flex items-center gap-2">
        <div className="flex flex-1 items-center gap-1.5">
          {Array.from({ length: total }, (_, i) => (
            <button key={i} type="button" onClick={() => go(i)} aria-label={t("slideOf", { n: i + 1, total })}
              className={cx("h-1.5 rounded-full transition-all", i === index ? "w-4 bg-ink" : "w-1.5 bg-black/20 hover:bg-black/35")} />
          ))}
        </div>
        {images ? (
          <button type="button" onClick={() => onShowReal(false)} className="text-[12px] font-medium text-muted hover:text-text">{t("livePreview")}</button>
        ) : canRender || idea.media_urls.length > 0 ? (
          <button type="button" disabled={rendering} onClick={() => onShowReal(true)}
            className="inline-flex items-center gap-1 text-[12px] font-medium text-muted hover:text-text disabled:opacity-60">
            <Icon name={rendering ? "progress_activity" : "image"} size={14} spin={rendering} />
            {rendering ? t("rendering") : t("seeReal")}
          </button>
        ) : null}
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------------------------- video
export function VideoStoryboard({ video, compact = false }: { video: VideoScript | null; compact?: boolean }) {
  const t = useTranslations("ideas.preview");
  const [voice, setVoice] = useState(false);
  if (!video) return null;
  const scenes = compact ? video.scenes.slice(0, 4) : video.scenes;
  return (
    <div className="rounded-2xl bg-ink p-4 text-white shadow-[0_14px_30px_-16px_rgba(0,0,0,.7)]">
      <div className="flex items-center gap-2 text-[11px] font-semibold text-white/60">
        <Icon name="smartphone" size={14} />
        <span>{t("vertical")}</span>
        <span className="ms-auto inline-flex items-center gap-1 rounded-full bg-white/12 px-2 py-0.5 text-white/85">
          <Icon name="schedule" size={12} />{t("seconds", { n: video.duration })}
        </span>
      </div>
      <div className="mt-3 text-[11px] font-semibold uppercase tracking-wide text-accent">{t("hook")}</div>
      <p dir="auto" className="mt-1 text-[19px] font-bold leading-snug tracking-tight">{video.hook}</p>
      {scenes.length > 0 && (
        <ol className="mt-4 flex flex-col gap-2.5">
          {scenes.map((s, i) => (
            <li key={i} className="flex gap-2.5">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white/12 text-[11px] font-bold tabular-nums">{i + 1}</span>
              <div className="min-w-0 flex-1">
                <p dir="auto" className="text-[12.5px] leading-snug text-white/65">{s.visual}</p>
                {s.text && <p dir="auto" className="mt-1 inline-block rounded-md bg-white px-1.5 py-0.5 text-[12px] font-semibold text-ink">{s.text}</p>}
              </div>
            </li>
          ))}
          {compact && video.scenes.length > scenes.length && (
            <li className="ps-8 text-[12px] text-white/50">{t("moreScenes", { n: video.scenes.length - scenes.length })}</li>
          )}
        </ol>
      )}
      {video.voiceover && (
        <div className="mt-3 border-t border-white/10 pt-2.5">
          <button type="button" onClick={() => setVoice(!voice)} aria-expanded={voice}
            className="flex w-full items-center gap-1.5 text-[12px] font-semibold text-white/75 hover:text-white">
            <Icon name="mic" size={14} />{t("voiceover")}
            <Icon name={voice ? "expand_less" : "expand_more"} size={16} className="ms-auto" />
          </button>
          {voice && <p dir="auto" className="pop-in mt-2 whitespace-pre-wrap text-[12.5px] leading-relaxed text-white/80">{video.voiceover}</p>}
        </div>
      )}
    </div>
  );
}
