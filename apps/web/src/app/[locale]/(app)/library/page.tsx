"use client";
/** Media library: every image, video and audio file of the team — search, filters, tags, favourites, usage. */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { Icon } from "@/components/icon";
import type { LibraryItem, LibraryPage } from "@/components/planning/types";
import { Chip, StateBadge, onError, useFormat } from "@/components/planning/ui";
import { Badge, Button, Card, EmptyState, Field, IconButton, Input, Modal, PageHeader, Segmented, Select, Spinner, cx, toast } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";

type Kind = "" | "image" | "video" | "audio";
const PAGE = 48;

export default function LibraryPageView() {
  const t = useTranslations("library");
  const qc = useQueryClient();
  const { can } = useSession();
  const canEdit = can("editor");
  const fileInput = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<Kind>("");
  const [q, setQ] = useState("");
  const [source, setSource] = useState("");
  const [tag, setTag] = useState("");
  const [favorite, setFavorite] = useState(false);
  const [unused, setUnused] = useState(false);
  const [sort, setSort] = useState("new");
  const [openId, setOpenId] = useState<number | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [uploading, setUploading] = useState(0);

  const filters = { q, kind, source, tag, favorite: favorite || undefined, unused: unused || undefined, sort };
  const query = useInfiniteQuery({
    queryKey: ["library", filters],
    queryFn: ({ pageParam }) => api.get<LibraryPage>("/library/media", { ...filters, offset: pageParam, limit: PAGE }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => (pages.length * PAGE < last.total ? pages.length * PAGE : undefined),
  });
  const first = query.data?.pages[0];
  const items = query.data?.pages.flatMap((p) => p.items) || [];
  const refresh = () => qc.invalidateQueries({ queryKey: ["library"] });

  const toggleFavorite = useMutation({
    mutationFn: (id: number) => api.post<LibraryItem>(`/library/media/${id}/favorite`),
    onSuccess: refresh,
    onError,
  });
  const bulk = useMutation({
    mutationFn: (body: { action: string; tag?: string }) => api.post<{ done: number[]; skipped: number[] }>("/library/media/bulk", { ids: selected, ...body }),
    onSuccess: (r, vars) => {
      refresh();
      setSelected([]);
      if (vars.action === "delete") toast[r.skipped.length ? "info" : "success"](r.skipped.length ? t("bulkSkipped", { done: r.done.length, skipped: r.skipped.length }) : t("deletedMany", { count: r.done.length }));
    },
    onError,
  });

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(files.length);
    let ok = 0;
    for (const file of Array.from(files)) {
      try {
        await api.upload("/media", file);
        ok += 1;
      } catch (err) {
        toast.error(`${file.name}: ${err instanceof ApiError ? err.message : String(err)}`);
      }
      setUploading((n) => n - 1);
    }
    if (ok) toast.success(t("uploaded", { count: ok }));
    refresh();
    if (fileInput.current) fileInput.current.value = "";
  };

  const toggleSelect = (id: number) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const counts = first?.counts || {};
  const total = (counts.image || 0) + (counts.video || 0) + (counts.audio || 0);

  return (
    <div className="pt-2"
      onDragOver={(e) => canEdit && e.dataTransfer.types.includes("Files") && e.preventDefault()}
      onDrop={(e) => { if (canEdit && e.dataTransfer.files.length) { e.preventDefault(); upload(e.dataTransfer.files); } }}>
      <PageHeader icon="photo_library" title={t("title")} subtitle={t("subtitle")}
        actions={canEdit && (
          <>
            <input ref={fileInput} type="file" multiple accept="image/*,video/*,audio/*" className="hidden" onChange={(e) => upload(e.target.files)} />
            <Button variant="primary" icon="upload" loading={uploading > 0} onClick={() => fileInput.current?.click()}>
              {uploading > 0 ? t("uploading", { count: uploading }) : t("upload")}
            </Button>
          </>
        )} />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 basis-full sm:basis-auto sm:max-w-xs">
          <Icon name="search" size={16} className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-faint" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("search")} className="ps-9" />
        </div>
        <div className="-mx-4 flex max-w-[100vw] gap-2 overflow-x-auto px-4 sm:mx-0 sm:px-0">
          <Segmented size="sm" value={kind} onChange={setKind} className="shrink-0" options={[
            { value: "", label: `${t("kinds.all")} ${total || ""}` },
            { value: "image", label: `${t("kinds.image")} ${counts.image || ""}`, icon: "image" },
            { value: "video", label: `${t("kinds.video")} ${counts.video || ""}`, icon: "movie" },
            { value: "audio", label: `${t("kinds.audio")} ${counts.audio || ""}`, icon: "music_note" },
          ]} />
          <Select className="!h-8 !w-auto shrink-0 text-[13px]" value={source} onChange={(e) => setSource(e.target.value)} aria-label={t("source")}>
            <option value="">{t("sources.all")}</option>
            {["upload", "ai", "template", "production", "inbox"].map((s) => <option key={s} value={s}>{t(`sources.${s}`)}</option>)}
          </Select>
          <Select className="!h-8 !w-auto shrink-0 text-[13px]" value={sort} onChange={(e) => setSort(e.target.value)} aria-label={t("sort")}>
            {["new", "old", "name", "size"].map((s) => <option key={s} value={s}>{t(`sorts.${s}`)}</option>)}
          </Select>
          <Chip active={favorite} onClick={() => setFavorite(!favorite)}><Icon name="favorite" size={14} />{t("favorites")}</Chip>
          <Chip active={unused} onClick={() => setUnused(!unused)}>{t("unused")}</Chip>
        </div>
      </div>

      {!!first?.tags.length && (
        <div className="-mx-4 mb-4 flex gap-1.5 overflow-x-auto px-4 sm:mx-0 sm:flex-wrap sm:px-0">
          <Icon name="tag" size={16} className="mt-2 shrink-0 text-faint" />
          {first.tags.map((tg) => (
            <Chip key={tg.name} active={tag === tg.name} onClick={() => setTag(tag === tg.name ? "" : tg.name)} className="!h-7 !text-[12px]">
              <span className="bidi">{tg.name}</span> <span className="opacity-60">{tg.count}</span>
            </Chip>
          ))}
        </div>
      )}

      {selected.length > 0 && canEdit && <BulkBar count={selected.length} busy={bulk.isPending} onClear={() => setSelected([])} onAction={(action, tg) => bulk.mutate({ action, tag: tg })} />}

      {query.isLoading ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : !items.length ? (
        <Card>
          <EmptyState icon="photo_library" title={q || kind || source || tag || favorite || unused ? t("noMatch") : t("emptyTitle")} text={t("emptyText")}
            action={canEdit && <Button variant="primary" icon="upload" onClick={() => fileInput.current?.click()}>{t("upload")}</Button>} />
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
            {items.map((item) => (
              <Tile key={item.id} item={item} selected={selected.includes(item.id)} selecting={selected.length > 0} canEdit={canEdit}
                onOpen={() => setOpenId(item.id)} onSelect={() => toggleSelect(item.id)} onFavorite={() => toggleFavorite.mutate(item.id)} />
            ))}
          </div>
          {query.hasNextPage && (
            <div className="mt-5 flex justify-center">
              <Button loading={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>{t("loadMore")}</Button>
            </div>
          )}
          <p className="mt-3 text-center text-[12px] text-faint">{t("count", { shown: items.length, total: first?.total || 0 })}</p>
        </>
      )}

      {openId !== null && <ItemModal id={openId} onClose={() => setOpenId(null)} onChanged={refresh} />}
    </div>
  );
}

function Thumb({ item, className }: { item: LibraryItem; className?: string }) {
  if (item.kind === "image") {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={item.thumb_url} alt="" loading="lazy" className={cx("h-full w-full object-cover", className)} />;
  }
  if (item.kind === "video") {
    return (
      <div className={cx("relative h-full w-full bg-ink", className)}>
        <video src={`${item.url}#t=0.5`} preload="metadata" muted playsInline className="h-full w-full object-cover opacity-90" />
        <span className="absolute inset-0 flex items-center justify-center"><span className="flex h-10 w-10 items-center justify-center rounded-full bg-white/85 text-ink"><Icon name="play_arrow" size={20} /></span></span>
      </div>
    );
  }
  return (
    <div className={cx("flex h-full w-full items-center justify-center bg-gradient-to-br from-zinc-800 to-black text-white", className)}>
      <Icon name="graphic_eq" size={34} duo />
    </div>
  );
}

function Tile({ item, selected, selecting, canEdit, onOpen, onSelect, onFavorite }: {
  item: LibraryItem; selected: boolean; selecting: boolean; canEdit: boolean; onOpen: () => void; onSelect: () => void; onFavorite: () => void;
}) {
  const t = useTranslations("library");
  return (
    <div className={cx("group glass relative overflow-hidden rounded-[18px] transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-lift)]", selected && "ring-2 ring-ink")}>
      <button type="button" className="block aspect-square w-full overflow-hidden" onClick={selecting ? onSelect : onOpen} aria-label={item.filename}>
        <Thumb item={item} className="transition group-hover:scale-[1.03]" />
      </button>
      {canEdit && (
        <button type="button" onClick={onSelect} aria-label={t("select")}
          className={cx("absolute start-2 top-2 flex h-6 w-6 items-center justify-center rounded-full border-2 transition",
            selected ? "border-ink bg-ink text-white" : "border-white/90 bg-black/20 text-transparent opacity-0 group-hover:opacity-100", selecting && "opacity-100")}>
          <Icon name="check" size={13} />
        </button>
      )}
      <button type="button" onClick={onFavorite} disabled={!canEdit} aria-label={t("favorite")}
        className={cx("absolute end-2 top-2 flex h-7 w-7 items-center justify-center rounded-full bg-white/85 transition",
          item.favorite ? "text-bad opacity-100" : "text-muted opacity-0 group-hover:opacity-100")}>
        <Icon name="favorite" size={15} duo={item.favorite} />
      </button>
      <div className="flex items-center gap-1.5 px-2.5 py-2">
        <span className="min-w-0 flex-1 truncate text-[12px] font-medium bidi" title={item.filename}>{item.filename}</span>
        {item.used > 0 && <span className="shrink-0 rounded-full bg-ink px-1.5 text-[10px] font-semibold text-white" title={t("usedTitle")}>{item.used}</span>}
        {item.source !== "upload" && <span className="shrink-0 text-[10px] text-muted">{t(`sources.${item.source}`)}</span>}
      </div>
    </div>
  );
}

function BulkBar({ count, busy, onClear, onAction }: { count: number; busy: boolean; onClear: () => void; onAction: (a: string, tag?: string) => void }) {
  const t = useTranslations("library");
  const [tag, setTag] = useState("");
  return (
    <div className="glass-strong sticky top-16 z-20 mb-4 flex flex-wrap items-center gap-2 rounded-2xl px-3 py-2">
      <IconButton icon="close" label={t("clearSelection")} onClick={onClear} />
      <span className="text-[13px] font-semibold">{t("selected", { count })}</span>
      <div className="ms-auto flex flex-wrap items-center gap-2">
        <Button size="sm" icon="favorite" disabled={busy} onClick={() => onAction("favorite")}>{t("favorite")}</Button>
        <div className="flex items-center gap-1">
          <Input value={tag} onChange={(e) => setTag(e.target.value)} placeholder={t("tagPlaceholder")} className="!h-8 !w-32 text-[13px]" />
          <Button size="sm" icon="tag" disabled={busy || !tag.trim()} onClick={() => { onAction("add_tag", tag.trim()); setTag(""); }}>{t("addTag")}</Button>
        </div>
        <Button size="sm" variant="danger" icon="delete" disabled={busy} onClick={() => window.confirm(t("confirmDeleteMany", { count })) && onAction("delete")}>{t("delete")}</Button>
      </div>
    </div>
  );
}

function ItemModal({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const t = useTranslations("library");
  const fmt = useFormat();
  const router = useRouter();
  const { can, me } = useSession();
  const qc = useQueryClient();
  const { data: item } = useQuery({ queryKey: ["library-item", id], queryFn: () => api.get<LibraryItem>(`/library/media/${id}`) });
  const usage = useQuery({ queryKey: ["library-usage", id], queryFn: () => api.get<{ posts: { id: number; name: string; state: string; date: string | null }[]; products: { id: number; name: string }[]; total: number }>(`/library/media/${id}/usage`) });
  const [name, setName] = useState<string | null>(null);
  const [newTag, setNewTag] = useState("");

  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.patch<LibraryItem>(`/library/media/${id}`, body),
    onSuccess: (row) => { qc.setQueryData(["library-item", id], row); onChanged(); },
    onError,
  });
  const use = useMutation({
    mutationFn: () => api.post<{ post_id: number; studio_url: string }>(`/library/media/${id}/use`),
    onSuccess: (r) => router.push(r.studio_url),
    onError,
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/library/media/${id}`),
    onSuccess: () => { toast.success(t("deleted")); onChanged(); onClose(); },
    onError,
  });

  const canEdit = can("editor");
  const canDelete = can("admin") || item?.created_by_id === me?.user.id;
  const tags = item?.tags || [];

  return (
    <Modal open onClose={onClose} size="lg" title={item ? <span className="bidi">{item.filename}</span> : "…"}
      footer={item && (
        <>
          {canEdit && canDelete && (
            <Button variant="danger" icon="delete" disabled={item.used > 0} title={item.used ? t("inUse") : undefined} loading={remove.isPending}
              onClick={() => window.confirm(t("confirmDelete")) && remove.mutate()}>{t("delete")}</Button>
          )}
          <a href={item.url} download={item.filename} className="ms-auto"><Button icon="download">{t("download")}</Button></a>
          {canEdit && <Button variant="primary" icon="edit_square" loading={use.isPending} onClick={() => use.mutate()}>{t("useInStudio")}</Button>}
        </>
      )}>
      {!item ? <div className="flex justify-center py-10"><Spinner /></div> : (
        <div className="grid gap-5 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
          <div className="flex items-center justify-center overflow-hidden rounded-2xl bg-black/[0.04]">
            {item.kind === "image" ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={item.url} alt="" className="max-h-[52vh] w-full object-contain" />
            ) : item.kind === "video" ? (
              <video src={item.url} controls playsInline className="max-h-[52vh] w-full bg-black" />
            ) : (
              <div className="flex w-full flex-col items-center gap-4 p-8"><Icon name="graphic_eq" size={48} duo /><audio src={item.url} controls className="w-full" /></div>
            )}
          </div>
          <div className="flex flex-col gap-4">
            <Field label={t("name")}>
              <div className="flex gap-2">
                <Input value={name ?? item.filename} disabled={!canEdit} onChange={(e) => setName(e.target.value)} className="bidi" />
                {name !== null && name !== item.filename && <Button size="sm" variant="primary" className="!h-10" onClick={() => { update.mutate({ filename: name }); setName(null); }}>{t("save")}</Button>}
              </div>
            </Field>
            <div>
              <div className="mb-1.5 text-[13px] font-medium text-text-2">{t("tags")}</div>
              <div className="flex flex-wrap gap-1.5">
                {tags.map((tg) => (
                  <span key={tg} className="inline-flex items-center gap-1 rounded-full bg-fill-2 py-1 ps-2.5 pe-1 text-[12px] font-medium">
                    <span className="bidi">{tg}</span>
                    {canEdit && <button type="button" aria-label={t("removeTag")} onClick={() => update.mutate({ tags: tags.filter((x) => x !== tg) })} className="rounded-full p-0.5 hover:bg-black/10"><Icon name="close" size={12} /></button>}
                  </span>
                ))}
                {canEdit && (
                  <form onSubmit={(e) => { e.preventDefault(); if (newTag.trim()) { update.mutate({ tags: [...tags, newTag.trim()] }); setNewTag(""); } }}>
                    <input value={newTag} onChange={(e) => setNewTag(e.target.value)} placeholder={t("tagPlaceholder")}
                      className="h-7 w-28 rounded-full border border-dashed border-line-strong bg-transparent px-2.5 text-[12px] outline-none focus:border-ink" />
                  </form>
                )}
              </div>
            </div>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-2 rounded-2xl bg-fill p-3 text-[12.5px]">
              <dt className="text-muted">{t("info.type")}</dt><dd className="text-end" dir="ltr">{item.mimetype}</dd>
              <dt className="text-muted">{t("info.size")}</dt><dd className="text-end">{fmt.size(item.size)}</dd>
              {item.width && <><dt className="text-muted">{t("info.dimensions")}</dt><dd className="text-end" dir="ltr">{item.width} × {item.height}</dd></>}
              <dt className="text-muted">{t("source")}</dt><dd className="text-end">{t(`sources.${item.source}`)}</dd>
              <dt className="text-muted">{t("info.added")}</dt><dd className="text-end">{fmt.date(item.created_at)}{item.author && ` · ${item.author}`}</dd>
              <dt className="text-muted">{t("favorite")}</dt>
              <dd className="text-end"><button type="button" disabled={!canEdit} onClick={() => update.mutate({ favorite: !item.favorite })} className={item.favorite ? "text-bad" : "text-faint"}><Icon name="favorite" size={16} duo={item.favorite} /></button></dd>
            </dl>
            <div>
              <div className="mb-1.5 flex items-center gap-2 text-[13px] font-medium text-text-2">
                {t("usage")} <Badge tone={usage.data?.total ? "ink" : "neutral"}>{usage.data?.total ?? 0}</Badge>
              </div>
              {usage.data?.total ? (
                <ul className="flex flex-col gap-1">
                  {usage.data.posts.map((p) => (
                    <li key={p.id}>
                      <Link href={`/planner?post=${p.id}`} className="flex items-center gap-2 rounded-xl px-2 py-1.5 text-[12.5px] hover:bg-fill">
                        <Icon name="send" size={14} className="text-muted" /><span className="min-w-0 flex-1 truncate bidi">{p.name || t("untitled")}</span><StateBadge state={p.state} />
                      </Link>
                    </li>
                  ))}
                  {usage.data.products.map((p) => (
                    <li key={`p${p.id}`} className="flex items-center gap-2 px-2 py-1.5 text-[12.5px]"><Icon name="storefront" size={14} className="text-muted" /><span className="bidi">{p.name}</span></li>
                  ))}
                </ul>
              ) : <p className="text-[12.5px] text-faint">{t("notUsed")}</p>}
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
