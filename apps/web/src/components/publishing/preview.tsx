"use client";
/** Live preview of the post as it will look on one network. */
import { useTranslations } from "next-intl";
import { Icon, PlatformBadge } from "@/components/icon";
import { Avatar, cx } from "@/components/ui";
import { MediaThumb } from "./media-picker";
import type { Media, PublishAs } from "./types";
import { kindOf } from "./util";

export function PostPreview({ platform, name, username, avatar, text, media, story, publishAs }: {
  platform: string; name: string; username?: string | null; avatar?: string | null; text: string; media: Media[]; story: Media[]; publishAs: PublishAs;
}) {
  const t = useTranslations("publishing.studio");
  const showStory = publishAs !== "feed" && (platform === "instagram" || platform === "facebook");
  const feedVisible = publishAs !== "story";
  const visual = media.filter((m) => kindOf(m.mimetype) !== "audio");
  const audio = media.find((m) => kindOf(m.mimetype) === "audio");
  const mediaFirst = platform === "instagram" || platform === "tiktok";
  const grid = (
    visual.length > 0 && (
      <div className={cx("grid gap-0.5 overflow-hidden bg-fill-2", mediaFirst ? "" : "rounded-2xl", visual.length > 1 ? "grid-cols-2" : "grid-cols-1")}>
        {visual.slice(0, 4).map((m, i) => (
          <div key={m.id} className={cx("relative", visual.length === 1 ? (platform === "tiktok" ? "aspect-[9/16] max-h-[420px]" : "aspect-square") : "aspect-square")}>
            <MediaThumb media={m} />
            {i === 3 && visual.length > 4 && <span className="absolute inset-0 flex items-center justify-center bg-black/50 text-lg font-bold text-white">+{visual.length - 4}</span>}
          </div>
        ))}
      </div>
    )
  );
  const body = text ? <p className="bidi whitespace-pre-wrap break-words text-[14px] leading-relaxed">{text}</p> : <p className="text-sm text-faint">{t("previewEmpty")}</p>;
  return (
    <div className="flex flex-col gap-3">
      {feedVisible && (
        <div className="overflow-hidden rounded-2xl border border-line bg-white">
          <div className="flex items-center gap-2.5 p-3">
            <Avatar name={name} src={avatar} size={36} />
            <div className="min-w-0 flex-1">
              <div className="bidi truncate text-sm font-semibold">{name}</div>
              <div className="truncate text-xs text-muted" dir="ltr">{username ? `@${username.replace(/^@/, "")} · ` : ""}{t("now")}</div>
            </div>
            <PlatformBadge platform={platform} size={22} />
          </div>
          {mediaFirst ? <>{grid}<div className="p-3">{body}</div></> : <><div className="px-3 pb-3">{body}</div>{visual.length > 0 && <div className="px-3 pb-3">{grid}</div>}</>}
          {audio && <div className="px-3 pb-3"><audio controls preload="metadata" src={audio.url} className="w-full" /></div>}
          <div className="flex gap-5 border-t border-line px-3 py-2 text-muted">
            <Icon name="favorite" size={18} /><Icon name="mode_comment" size={18} /><Icon name="share" size={18} />
          </div>
        </div>
      )}
      {showStory && (story.length > 0 || media.length > 0) && (
        <div className="mx-auto w-44">
          <div className="mb-1.5 text-center text-xs font-medium text-muted">{t("storyPreview")}</div>
          <div className="relative aspect-[9/16] overflow-hidden rounded-[22px] bg-black shadow-[var(--shadow-lift)]">
            <MediaThumb media={(story[0] || visual[0] || media[0])} />
            <div className="absolute inset-x-2 top-2 h-0.5 rounded-full bg-white/70" />
            <div className="absolute start-2 top-4 flex items-center gap-1.5 text-[11px] font-semibold text-white drop-shadow">
              <Avatar name={name} src={avatar} size={20} />{name}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
