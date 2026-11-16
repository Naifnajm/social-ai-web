"use client";
/** One idea of the day: format, title, why it was suggested, the preview, the time and the accounts, then act on it. */
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon } from "@/components/icon";
import { Button, cx } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { CarouselPreview, PostPreview, VideoStoryboard } from "./previews";
import { AccountStack, FormatChip, ReasonPill, hasBestTime, useDone, useIdeaActions, useIdeaFormat, whyOf } from "./shared";
import { type ApproveResult, type Idea, type IdeaAccount, REJECT_REASONS } from "./types";

export function IdeaCard({ idea, accounts, canEdit, now, index, onEdit }: {
  idea: Idea; accounts: IdeaAccount[]; canEdit: boolean; now: number; index: number; onEdit: (idea: Idea) => void;
}) {
  const t = useTranslations("ideas");
  const fmt = useIdeaFormat();
  const router = useRouter();
  const { approve, reject, renderSlides } = useIdeaActions();
  const result = useDone((s) => s.results[idea.id]);
  const leaving = useDone((s) => !!s.skipped[idea.id]);
  const [skipping, setSkipping] = useState(false);
  const [real, setReal] = useState(false);

  const targets = accounts.filter((a) => idea.account_ids.includes(a.id));
  const platforms = targets.length ? [...new Set(targets.map((a) => a.platform))] : idea.platforms;
  const busy = approve.isPending && approve.variables?.id === idea.id;
  const isVideo = idea.format === "video";

  if (result || idea.state === "scheduled" || idea.state === "draft") {
    return <DoneCard idea={idea} result={result} now={now} />;
  }

  const go = () => {
    if (!isVideo && !idea.account_ids.length) return onEdit(idea);
    approve.mutate(
      { id: idea.id, mode: isVideo ? "draft" : "suggested" },
      { onSuccess: (r) => isVideo && router.push(r.url) },
    );
  };
  const showReal = (value: boolean) => {
    if (!value || idea.media_urls.length) return setReal(value);
    renderSlides.mutate(idea.id, { onSuccess: () => setReal(true) });
  };

  return (
    <article
      className={cx("glass idea-in flex flex-col gap-3.5 rounded-[22px] p-4 transition-shadow hover:shadow-[var(--shadow-lift)]", leaving && "idea-out")}
      style={{ animationDelay: leaving ? undefined : `${Math.min(index, 6) * 60}ms` }}
    >
      <div className="flex items-center gap-2">
        <FormatChip format={idea.format} />
        {idea.edited && <span className="text-[11px] font-medium text-faint">{t("card.edited")}</span>}
      </div>

      <h3 dir="auto" className="text-[17px] font-bold leading-snug tracking-tight">{idea.title}</h3>

      {whyOf(idea).length > 0 && (
        <div className="flex flex-col items-start gap-1.5" aria-label={t("card.why")}>
          {whyOf(idea).map((r, i) => <ReasonPill key={i} reason={r} />)}
        </div>
      )}

      <div className="mt-0.5">
        {idea.format === "post" && <PostPreview idea={idea} platforms={platforms} />}
        {idea.format === "carousel" && (
          <CarouselPreview idea={idea} real={real} onShowReal={showReal} rendering={renderSlides.isPending} canRender={canEdit} />
        )}
        {isVideo && <VideoStoryboard video={idea.video} compact />}
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="inline-flex min-w-0 items-center gap-1.5 rounded-full bg-fill px-2.5 py-1 text-[12.5px] text-text-2">
          <Icon name="schedule" size={14} className="shrink-0" />
          <span className="font-semibold">{idea.suggested_at ? fmt.slot(idea.suggested_at, now) : t("time.auto")}</span>
          {idea.suggested_at && hasBestTime(idea) && <span className="truncate text-muted">· {t("time.best")}</span>}
        </span>
        {targets.length ? <span className="ms-auto"><AccountStack accounts={targets} size={24} /></span> : (
          <span className="ms-auto inline-flex items-center gap-1 text-[12px] font-medium text-warn"><Icon name="warning" size={14} />{t("card.noAccount")}</span>
        )}
      </div>

      {canEdit && (skipping ? (
        <div className="pop-in rounded-2xl bg-fill p-3">
          <div className="mb-2 flex items-center text-[13px] font-semibold">
            {t("skip.question")}
            <button type="button" onClick={() => setSkipping(false)} className="ms-auto text-[12px] font-medium text-muted hover:text-text">{t("skip.cancel")}</button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {REJECT_REASONS.map((r) => (
              <button key={r} type="button" disabled={reject.isPending}
                onClick={() => reject.mutate({ id: idea.id, reason: r })}
                className="inline-flex h-8 items-center rounded-full bg-white px-3 text-[12.5px] font-medium text-text-2 shadow-[var(--ring)] transition hover:bg-ink hover:text-white disabled:opacity-50">
                {t(`skip.reasons.${r}`)}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-auto flex flex-wrap items-center gap-2 pt-1">
          <Button variant="primary" icon={isVideo ? "wand_stars" : idea.account_ids.length ? "event_add" : "group"} loading={busy} onClick={go} className="flex-1 sm:flex-none">
            {isVideo ? t("card.openStudio") : idea.account_ids.length ? t("card.approve") : t("card.chooseAccounts")}
          </Button>
          <Button icon="edit_square" onClick={() => onEdit(idea)} disabled={busy}>{t("card.edit")}</Button>
          <Button variant="ghost" onClick={() => setSkipping(true)} disabled={busy} className="ms-auto">{t("card.skip")}</Button>
        </div>
      ))}
    </article>
  );
}

/** The card after approval: a calm green confirmation with where to find the post now. */
function DoneCard({ idea, result, now }: { idea: Idea; result?: ApproveResult; now: number }) {
  const t = useTranslations("ideas.done");
  const fmt = useIdeaFormat();
  const state = result?.post_state ?? idea.post?.state ?? idea.state;
  const at = result?.scheduled_at ?? idea.post?.scheduled_at ?? null;
  const url = result?.url ?? (idea.post ? `/planner?post=${idea.post.id}` : "/planner");
  const kind = idea.state === "draft" || state === "draft" ? "draft" : state === "to_approve" ? "approval" : "scheduled";
  return (
    <article className="idea-flip flex flex-col items-center justify-center gap-3 rounded-[22px] border border-[rgba(52,199,89,.25)] bg-[linear-gradient(180deg,rgba(52,199,89,.12),rgba(255,255,255,.7))] p-6 text-center shadow-[var(--shadow)]">
      <span className="flex h-14 w-14 items-center justify-center rounded-full bg-ok text-white shadow-[0_10px_24px_-10px_rgba(31,122,61,.8)]">
        <Icon name={kind === "draft" ? "wand_stars" : kind === "approval" ? "verified_user" : "check"} size={26} />
      </span>
      <div>
        <div className="text-[16px] font-bold tracking-tight text-ok">
          {kind === "draft" ? t("draft") : kind === "approval" ? t("approval") : at ? t("scheduledFor", { when: fmt.slot(at, now) }) : t("scheduled")}
        </div>
        <p dir="auto" className="mt-1 line-clamp-2 text-[13px] text-muted">{idea.title}</p>
      </div>
      <Link href={url} className="inline-flex h-9 items-center gap-1.5 rounded-full bg-white px-4 text-[13px] font-semibold text-text shadow-[var(--ring)] hover:bg-white/80">
        {kind === "draft" ? t("openStudio") : kind === "approval" ? t("openApprovals") : t("openPlanner")}
        <Icon name="east" size={15} className="rtl:-scale-x-100" />
      </Link>
    </article>
  );
}

/** Placeholder while new ideas are being prepared. */
export function IdeaSkeleton({ index }: { index: number }) {
  return (
    <div className="glass idea-in flex flex-col gap-3.5 rounded-[22px] p-4" style={{ animationDelay: `${index * 80}ms` }} aria-hidden>
      <span className="skeleton h-7 w-24 rounded-full" />
      <span className="skeleton h-5 w-4/5 rounded-lg" />
      <span className="skeleton h-8 w-3/5 rounded-xl" />
      <span className="skeleton aspect-[4/3] w-full rounded-2xl" />
      <div className="flex gap-2">
        <span className="skeleton h-10 w-40 rounded-full" />
        <span className="skeleton h-10 w-20 rounded-full" />
      </div>
    </div>
  );
}
