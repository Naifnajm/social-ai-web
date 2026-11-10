"use client";
/** Posts: every post with its state and its result per network; retry, edit, duplicate, unschedule, delete. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useEffect, useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import { MediaThumb } from "@/components/publishing/media-picker";
import { TargetRow } from "@/components/publishing/results-dialog";
import { PUBLISH_PLATFORMS, PLATFORM_LABELS, type Post } from "@/components/publishing/types";
import { StateBadge, errorText, useFormat } from "@/components/publishing/util";
import { Button, Card, EmptyState, Input, Modal, PageHeader, Segmented, Select, Spinner, cx, toast } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

const FILTERS: Record<string, string[]> = {
  all: [], draft: ["draft"], scheduled: ["scheduled"], to_approve: ["to_approve"], posted: ["posted", "partial"], failed: ["failed", "partial"],
};
const PAGE = 20;

function PostsList() {
  const t = useTranslations("publishing.posts");
  const params = useSearchParams();
  const router = useRouter();
  const fmt = useFormat();
  const initial = params.get("state");
  const [filter, setFilter] = useState(initial && FILTERS[initial] ? initial : "all");
  const [platform, setPlatform] = useState("");
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const [openId, setOpenId] = useState<number | null>(params.get("post") ? Number(params.get("post")) : null);
  useEffect(() => {
    const timer = setTimeout(() => setSearch(q), 300);
    return () => clearTimeout(timer);
  }, [q]);
  const posts = useQuery({
    queryKey: ["posts", filter, platform, search, limit],
    queryFn: () => api.get<{ items: Post[]; total: number }>("/posts", { state: FILTERS[filter], platform, q: search, limit }),
    refetchInterval: (query) => (query.state.data?.items.some((p) => p.state === "publishing") ? 3000 : false),
  });
  const items = posts.data?.items ?? [];
  return (
    <div className="pt-2">
      <PageHeader icon="view_list" title={t("title")} subtitle={t("subtitle")}
        actions={<Link href="/studio"><Button variant="primary" icon="add">{t("newPost")}</Button></Link>} />
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
        <div className="-mx-1 overflow-x-auto px-1">
          <Segmented value={filter} onChange={(v) => { setFilter(v); setLimit(PAGE); }} options={Object.keys(FILTERS).map((k) => ({ value: k, label: t(`filters.${k}`) }))} />
        </div>
        <div className="flex flex-1 gap-2 lg:justify-end">
          <Select className="!w-40" value={platform} onChange={(e) => setPlatform(e.target.value)}>
            <option value="">{t("allNetworks")}</option>
            {PUBLISH_PLATFORMS.map((p) => <option key={p} value={p}>{PLATFORM_LABELS[p]}</option>)}
          </Select>
          <Input className="lg:!w-64" placeholder={t("search")} value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>
      {posts.isLoading ? <div className="flex justify-center py-20"><Spinner /></div> : !items.length ? (
        <Card><EmptyState icon="send" title={t("emptyTitle")} text={t("emptyText")} action={<Link href="/studio"><Button variant="primary" icon="wand_stars">{t("openStudio")}</Button></Link>} /></Card>
      ) : (
        <div className="flex flex-col gap-3">
          {items.map((p) => (
            <Card key={p.id} padded={false} className="cursor-pointer transition hover:shadow-[var(--shadow-lift)]">
              <button className="flex w-full items-start gap-3 p-4 text-start" onClick={() => setOpenId(p.id)}>
                <div className="h-16 w-16 shrink-0 overflow-hidden rounded-xl bg-fill-2">
                  {p.media[0] ? <MediaThumb media={p.media[0]} /> : <span className="flex h-full items-center justify-center text-faint"><Icon name="text_fields" size={22} /></span>}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="bidi truncate font-semibold">{p.name || t("untitled")}</span>
                    <StateBadge state={p.state} />
                    {p.publish_as !== "feed" && <span className="inline-flex items-center gap-1 text-xs text-muted"><Icon name="smartphone" size={13} />{t(`publishAs.${p.publish_as}`)}</span>}
                  </div>
                  <p className="bidi mt-1 line-clamp-2 text-sm text-text-2">{p.content}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                    <span className="flex items-center gap-1">
                      {p.targets.length ? p.targets.map((tg) => (
                        <span key={tg.id} className="relative" title={`${tg.account_name}: ${tg.state}`}>
                          <PlatformBadge platform={tg.platform} size={18} />
                          {tg.state === "failed" && <span className="absolute -end-0.5 -top-0.5 h-2 w-2 rounded-full bg-[var(--bad-solid)] ring-2 ring-white" />}
                        </span>
                      )) : p.platforms.map((pf) => <PlatformBadge key={pf} platform={pf} size={18} />)}
                    </span>
                    <span>{p.state === "scheduled" ? t("scheduledFor", { date: fmt.dateTime(p.scheduled_at) }) : fmt.dateTime(p.published_at || p.updated_at)}</span>
                    {p.author_name && <span>· {p.author_name}</span>}
                    {p.totals.engagements > 0 && <span className="flex items-center gap-1"><Icon name="favorite" size={13} />{fmt.compact(p.totals.engagements)}</span>}
                    {p.totals.impressions > 0 && <span className="flex items-center gap-1"><Icon name="visibility" size={13} />{fmt.compact(p.totals.impressions)}</span>}
                  </div>
                </div>
              </button>
            </Card>
          ))}
          {posts.data && posts.data.total > items.length && (
            <div className="flex justify-center"><Button loading={posts.isFetching} onClick={() => setLimit(limit + PAGE)}>{t("more")}</Button></div>
          )}
        </div>
      )}
      {openId && <PostDetail id={openId} onClose={() => { setOpenId(null); router.replace("/posts"); }} />}
    </div>
  );
}

function PostDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const t = useTranslations("publishing.posts");
  const qc = useQueryClient();
  const fmt = useFormat();
  const router = useRouter();
  const canEdit = useSession((s) => s.can("editor"));
  const { data: post } = useQuery({
    queryKey: ["post", id], queryFn: () => api.get<Post>(`/posts/${id}`),
    refetchInterval: (q) => (q.state.data?.state === "publishing" ? 2000 : false),
  });
  const done = (message?: string) => () => {
    qc.invalidateQueries({ queryKey: ["posts"] });
    qc.invalidateQueries({ queryKey: ["post", id] });
    qc.invalidateQueries({ queryKey: ["studio"] });
    if (message) toast.success(message);
  };
  const onError = (err: unknown) => toast.error(errorText(err));
  const retry = useMutation({ mutationFn: () => api.post(`/posts/${id}/retry`), onSuccess: done(t("retrying")), onError });
  const unschedule = useMutation({ mutationFn: () => api.post(`/posts/${id}/submit`, { action: "draft" }), onSuccess: done(t("backToDraft")), onError });
  const duplicate = useMutation({ mutationFn: () => api.post<Post>(`/posts/${id}/duplicate`), onSuccess: (p) => { done()(); router.push(`/studio?post=${p.id}`); }, onError });
  const remove = useMutation({ mutationFn: () => api.delete(`/posts/${id}`), onSuccess: () => { done(t("deleted"))(); onClose(); }, onError });
  const deletable = post && ["draft", "to_approve", "scheduled", "failed"].includes(post.state) && !post.targets.some((x) => x.state === "posted");
  return (
    <Modal open onClose={onClose} size="lg" title={post ? <span className="bidi">{post.name || t("untitled")}</span> : t("post")}
      footer={post && canEdit && (
        <>
          {deletable && <Button variant="danger" icon="delete" className="me-auto" loading={remove.isPending} onClick={() => remove.mutate()}>{t("delete")}</Button>}
          <Button icon="content_copy" loading={duplicate.isPending} onClick={() => duplicate.mutate()}>{t("duplicate")}</Button>
          {(post.state === "scheduled" || post.state === "to_approve") && <Button icon="undo" loading={unschedule.isPending} onClick={() => unschedule.mutate()}>{post.state === "scheduled" ? t("unschedule") : t("withdraw")}</Button>}
          {post.can_edit && <Link href={`/studio?post=${post.id}`}><Button icon="edit_square">{t("edit")}</Button></Link>}
          {post.can_retry && <Button variant="primary" icon="refresh" loading={retry.isPending} onClick={() => retry.mutate()}>{t("retry")}</Button>}
        </>
      )}>
      {!post ? <div className="flex justify-center py-10"><Spinner /></div> : (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <StateBadge state={post.state} />
            <span className="text-muted">
              {post.state === "scheduled" ? t("scheduledFor", { date: fmt.dateTime(post.scheduled_at) }) : post.published_at ? t("publishedOn", { date: fmt.dateTime(post.published_at) }) : t("updatedOn", { date: fmt.dateTime(post.updated_at) })}
            </span>
          </div>
          {post.approval_note && (
            <div className="flex gap-2 rounded-2xl bg-warn-bg p-3 text-sm text-warn"><Icon name="mode_comment" size={16} className="mt-0.5 shrink-0" /><span className="bidi">{t("changesRequested")}: {post.approval_note}</span></div>
          )}
          <p className="bidi whitespace-pre-wrap rounded-2xl bg-fill p-3 text-sm leading-relaxed">{post.content || "—"}</p>
          {Object.entries(post.variants).map(([pf, text]) => (
            <div key={pf} className="flex gap-2 text-sm"><PlatformBadge platform={pf} size={20} /><p className="bidi flex-1 whitespace-pre-wrap text-text-2">{text}</p></div>
          ))}
          {post.media.length > 0 && (
            <div className="flex flex-wrap gap-2">{post.media.map((m) => <div key={m.id} className="h-20 w-20 overflow-hidden rounded-xl"><MediaThumb media={m} /></div>)}</div>
          )}
          {post.targets.length > 0 && (
            <div>
              <h3 className="mb-1 text-sm font-semibold">{t("results")}</h3>
              <ul className="divide-y divide-line">{post.targets.map((tg) => <TargetRow key={tg.id} target={tg} />)}</ul>
            </div>
          )}
          {post.totals.impressions + post.totals.engagements > 0 && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {(["impressions", "engagements", "likes", "comments"] as const).map((k) => (
                <div key={k} className={cx("rounded-2xl bg-fill p-3")}>
                  <div className="text-lg font-bold tabular-nums">{fmt.compact(post.totals[k])}</div>
                  <div className="text-xs text-muted">{t(`metrics.${k}`)}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

export default function PostsPage() {
  return (
    <Suspense>
      <PostsList />
    </Suspense>
  );
}
