"use client";
/**
 * Production hub: ready-made board templates and the workspace's boards (covers, status).
 * Other features can open a board from a post or a file: /production?post=<id> or /production?media=<id>&text=…
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useFormatter, useNow, useTranslations } from "next-intl";
import { Suspense, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/icon";
import { Badge, Button, Card, EmptyState, Modal, PageHeader, SectionTitle, Spinner, cx, toast } from "@/components/ui";
import type { BoardCard, BoardTemplate } from "@/components/production/types";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";

const onError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : String(err));

export default function ProductionHubPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <ProductionHub />
    </Suspense>
  );
}

function ProductionHub() {
  const t = useTranslations("production");
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const { can } = useSession();
  const editor = can("editor");
  const templates = useQuery({ queryKey: ["production", "templates"], queryFn: () => api.get<BoardTemplate[]>("/production/templates") });
  const boards = useQuery({ queryKey: ["production", "boards"], queryFn: () => api.get<BoardCard[]>("/production/boards") });
  const [confirm, setConfirm] = useState<BoardCard | null>(null);
  const [menu, setMenu] = useState<number | null>(null);

  const create = useMutation({
    mutationFn: (key: string) => api.post<BoardCard>("/production/boards", { template: key }),
    onSuccess: (board) => router.push(`/production/${board.id}`),
    onError,
  });
  const duplicate = useMutation({
    mutationFn: (id: number) => api.post<BoardCard>(`/production/boards/${id}/duplicate`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["production", "boards"] }),
    onError,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/production/boards/${id}`),
    onSuccess: () => {
      setConfirm(null);
      qc.invalidateQueries({ queryKey: ["production", "boards"] });
    },
    onError,
  });

  // links from other features: open a post or a file in a new board
  const opened = useRef(false);
  useEffect(() => {
    const post = params.get("post");
    const media = params.get("media");
    if (opened.current || !editor || (!post && !media)) return;
    opened.current = true;
    const request = post
      ? api.post<BoardCard>("/production/boards/from-post", { post_id: Number(post) })
      : api.post<BoardCard>("/production/boards/from-media", { media_id: Number(media), text: params.get("text") || null });
    request.then((board) => router.replace(`/production/${board.id}`)).catch(onError);
  }, [params, editor, router]);

  return (
    <div className="pt-2">
      <PageHeader icon="account_tree" title={t("title")} subtitle={t("subtitle")}
        actions={editor && <Button variant="primary" icon="add" loading={create.isPending && create.variables === "blank"} onClick={() => create.mutate("blank")}>{t("newBoard")}</Button>} />

      {editor && (
        <section className="mb-8">
          <SectionTitle icon="auto_awesome">{t("startFrom")}</SectionTitle>
          {templates.isLoading ? <Spinner /> : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
              {templates.data?.map((tpl) => {
                const blank = tpl.key === "blank";
                return (
                  <button key={tpl.key} type="button" disabled={create.isPending} onClick={() => create.mutate(tpl.key)}
                    className={cx("group relative flex flex-col gap-1.5 rounded-[20px] p-4 text-start transition hover:-translate-y-0.5 disabled:opacity-60",
                      blank ? "border-[1.5px] border-dashed border-black/15 bg-white/30 hover:bg-white/60" : "glass hover:shadow-[var(--shadow-lift)]")}>
                    <span className={cx("mb-1 flex h-10 w-10 items-center justify-center rounded-xl",
                      blank ? "bg-white/80 text-ink shadow-[var(--ring)]" : "bg-gradient-to-b from-[#3a3a3c] to-[#0a0a0a] text-white shadow-[0_6px_14px_-6px_rgba(0,0,0,.45)]")}>
                      {create.isPending && create.variables === tpl.key ? <Icon name="progress_activity" spin size={20} /> : <Icon name={tpl.icon} size={20} />}
                    </span>
                    <span className="font-semibold tracking-tight">{tpl.name}</span>
                    <span className="text-[13px] leading-snug text-muted">{tpl.description}</span>
                    {!blank && <span className="absolute end-4 top-4 text-[11px] text-muted">{t("blocks", { count: tpl.blocks })}</span>}
                  </button>
                );
              })}
            </div>
          )}
        </section>
      )}

      <section>
        <SectionTitle icon="photo_library">{t("myBoards")}</SectionTitle>
        {boards.isLoading ? <Spinner /> : !boards.data?.length ? (
          <Card><EmptyState icon="account_tree" title={t("noBoards")} text={t("noBoardsText")} /></Card>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {boards.data.map((board) => (
              <div key={board.id} className="glass group relative overflow-hidden rounded-[22px] transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-lift)]">
                <Link href={`/production/${board.id}`} className="block">
                  <div className="relative flex h-40 items-center justify-center bg-[radial-gradient(120%_90%_at_20%_0%,#52525b_0%,transparent_60%),linear-gradient(160deg,#27272a,#0a0a0a)] text-white/80">
                    {board.cover_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={board.cover_url} alt="" className="h-full w-full object-cover" />
                    ) : <Icon name="account_tree" size={40} duo />}
                    {board.status !== "idle" && (
                      <span className={cx("absolute start-3 top-3 rounded-full px-2.5 py-0.5 text-[11px] font-semibold backdrop-blur-md",
                        board.status === "running" ? "bg-black/70 text-white" : "bg-[#d92d20]/85 text-white")}>
                        {t(`boardStatus.${board.status}`)}
                      </span>
                    )}
                  </div>
                  <div className="px-4 pb-4 pt-3">
                    <div className="bidi truncate font-semibold tracking-tight" dir="auto">{board.name}</div>
                    <div className="mt-1 flex items-center gap-2 text-xs text-muted">
                      <span>{t("blocks", { count: board.node_count })}</span>
                      {board.output_count > 0 && <Badge>{t("results", { count: board.output_count })}</Badge>}
                      {board.updated_at && <span className="ms-auto">{format.relativeTime(new Date(board.updated_at), now)}</span>}
                    </div>
                  </div>
                </Link>
                {editor && (
                  <div className="absolute end-2 top-2">
                    <button type="button" aria-label={t("more")} onClick={() => setMenu(menu === board.id ? null : board.id)}
                      className="flex h-8 w-8 items-center justify-center rounded-full bg-white/80 text-ink opacity-90 shadow backdrop-blur-md transition hover:bg-white sm:opacity-0 sm:group-hover:opacity-100">
                      <Icon name="menu" size={16} />
                    </button>
                    {menu === board.id && (
                      <div className="glass-strong pop-in absolute end-0 top-9 z-10 w-44 rounded-2xl p-1.5">
                        <button type="button" className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-start text-sm hover:bg-fill-2"
                          onClick={() => { setMenu(null); duplicate.mutate(board.id); }}>
                          <Icon name="content_copy" size={16} /> {t("duplicate")}
                        </button>
                        <button type="button" className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-start text-sm text-bad hover:bg-bad-bg"
                          onClick={() => { setMenu(null); setConfirm(board); }}>
                          <Icon name="delete" size={16} /> {t("delete")}
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <Modal open={!!confirm} onClose={() => setConfirm(null)} size="sm" title={t("deleteBoard")}
        footer={<>
          <Button variant="ghost" onClick={() => setConfirm(null)}>{t("cancel")}</Button>
          <Button variant="danger" icon="delete" loading={remove.isPending} onClick={() => confirm && remove.mutate(confirm.id)}>{t("delete")}</Button>
        </>}>
        <p className="bidi text-sm text-text-2">{t("deleteBoardText", { name: confirm?.name || "" })}</p>
      </Modal>
    </div>
  );
}
