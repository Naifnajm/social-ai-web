"use client";
/** Publishing results per network (polls the post while the worker is still sending). */
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Icon, PlatformBadge } from "@/components/icon";
import { Button, Modal, Spinner } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import type { Post, Target } from "./types";
import { StateBadge, useFormat } from "./util";

export function TargetRow({ target }: { target: Target }) {
  const t = useTranslations("publishing.results");
  const sending = target.state === "pending" || target.state === "sending";
  return (
    <li className="flex items-start gap-3 py-2.5">
      <PlatformBadge platform={target.platform} size={28} />
      <div className="min-w-0 flex-1">
        <div className="bidi truncate text-sm font-semibold">{target.account_name}</div>
        {target.error && <div className="bidi mt-0.5 text-xs break-words text-bad">{target.error}</div>}
        {target.story_state && target.story_state !== "skipped" && (
          <div className="mt-0.5 flex items-center gap-1 text-xs text-muted">
            <Icon name="smartphone" size={13} />
            {t(`story.${target.story_state}`)}
            {target.story_error && <span className="bidi text-bad"> · {target.story_error}</span>}
            {target.story_url && <a href={target.story_url} target="_blank" rel="noopener noreferrer" className="underline">{t("open")}</a>}
          </div>
        )}
        {target.external_url && (
          <a href={target.external_url} target="_blank" rel="noopener noreferrer" className="mt-0.5 inline-flex items-center gap-1 text-xs font-medium underline underline-offset-2">
            {t("openPost")} <Icon name="open_in_new" size={12} />
          </a>
        )}
      </div>
      {sending ? <Spinner size={18} /> : target.state === "posted" ? <Icon name="check_circle" size={20} className="text-ok" /> : <Icon name="error" size={20} className="text-bad" />}
    </li>
  );
}

export function ResultsDialog({ postId, onClose }: { postId: number | null; onClose: () => void }) {
  const t = useTranslations("publishing.results");
  const fmt = useFormat();
  const { data: post } = useQuery({
    queryKey: ["post", postId],
    queryFn: () => api.get<Post>(`/posts/${postId}`),
    enabled: !!postId,
    refetchInterval: (q) => (q.state.data?.state === "publishing" ? 2000 : false),
  });
  const title = !post ? t("title") : post.state === "to_approve" ? t("sentForApproval") : post.state === "scheduled" ? t("scheduled") : post.state === "publishing" ? t("publishing") : t("title");
  return (
    <Modal open={!!postId} onClose={onClose} title={title}
      footer={<><Link href={`/posts?post=${postId}`}><Button>{t("openPosts")}</Button></Link><Button variant="primary" onClick={onClose}>{t("done")}</Button></>}>
      {!post ? <div className="flex justify-center py-8"><Spinner /></div> : (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-sm">
            <StateBadge state={post.state} />
            {post.state === "scheduled" && <span className="text-muted">{fmt.dateTime(post.scheduled_at)}</span>}
          </div>
          {post.state === "to_approve" ? (
            <p className="text-sm text-muted">{t("approvalText")}</p>
          ) : post.state === "scheduled" ? (
            <p className="text-sm text-muted">{t("scheduledText")}</p>
          ) : (
            <ul className="divide-y divide-line">{post.targets.map((target) => <TargetRow key={target.id} target={target} />)}</ul>
          )}
        </div>
      )}
    </Modal>
  );
}
