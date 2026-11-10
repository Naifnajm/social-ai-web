"use client";
/**
 * Unified inbox — three panes: filters + list / thread / customer panel.
 * Phone (390px): one pane at a time (list → thread → info).
 */
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import { Badge, Button, EmptyState, IconButton, Input, Segmented, Spinner, cx } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { INTENT_ICON, type ConversationPage, type ConversationRow, type Folder, type InboxMeta, type Thread } from "../_lib/types";
import { ConvAvatar, Dot, showError, useWhen } from "./bits";
import { CustomerPanel } from "./customer-panel";
import { ThreadPane } from "./thread";

type Filters = { folder: Folder; platform: string; kind: "" | "dm" | "comment"; search: string };
const FOLDERS: { key: Folder; icon: string }[] = [
  { key: "all", icon: "inbox" },
  { key: "unassigned", icon: "group_off" },
  { key: "mine", icon: "person" },
  { key: "pending", icon: "support_agent" },
  { key: "done", icon: "check_circle" },
];

export function InboxScreen({ initialId }: { initialId: number | null }) {
  const t = useTranslations("inbox");
  const qc = useQueryClient();
  const can = useSession((s) => s.can);
  const [filters, setFilters] = useState<Filters>({ folder: "all", platform: "", kind: "", search: "" });
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(initialId);
  const [view, setView] = useState<"list" | "thread" | "info">(initialId ? "thread" : "list");
  const [sideOpen, setSideOpen] = useState(true);
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    const id = setTimeout(() => setFilters((f) => (f.search === search ? f : { ...f, search })), 300);
    return () => clearTimeout(id);
  }, [search]);

  const meta = useQuery({ queryKey: ["inbox", "meta"], queryFn: () => api.get<InboxMeta>("/inbox/meta") });
  const list = useInfiniteQuery({
    queryKey: ["inbox", "list", filters],
    queryFn: ({ pageParam }) => api.get<ConversationPage>("/inbox/conversations", {
      folder: filters.folder, platform: filters.platform, kind: filters.kind, search: filters.search, cursor: pageParam, limit: 40,
    }),
    initialPageParam: "" as string,
    getNextPageParam: (last) => last.next_cursor || undefined,
    refetchInterval: 15_000,
  });
  const thread = useQuery({
    queryKey: ["inbox", "thread", selectedId],
    queryFn: () => api.get<Thread>(`/inbox/conversations/${selectedId}`),
    enabled: !!selectedId,
    refetchInterval: 10_000,
  });

  const items = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data]);
  const counts = list.data?.pages[0]?.counts;

  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["inbox", "list"] });
    qc.invalidateQueries({ queryKey: ["inbox-unread"] });
  }, [qc]);

  const setThread = useCallback((data: Thread) => {
    qc.setQueryData(["inbox", "thread", data.id], data);
    refresh();
  }, [qc, refresh]);

  const select = (row: ConversationRow) => {
    setSelectedId(row.id);
    setView("thread");
    try {
      window.history.replaceState(null, "", window.location.pathname.replace(/\/inbox(\/\d+)?$/, `/inbox/${row.id}`));
    } catch {
      /* history unavailable */
    }
    setTimeout(refresh, 600); // the thread read marks it as read
  };

  const back = () => {
    setView("list");
    try {
      window.history.replaceState(null, "", window.location.pathname.replace(/\/inbox\/\d+$/, "/inbox"));
    } catch {
      /* ignore */
    }
  };

  const sync = async () => {
    setSyncing(true);
    try {
      const result = await api.post<{ new: number; errors: string[] }>("/inbox/sync");
      if (result.errors.length) showError(result.errors.join(" · "));
      else qc.invalidateQueries({ queryKey: ["inbox"] });
    } catch (err) {
      showError(err);
    } finally {
      setSyncing(false);
    }
  };

  const hasAccounts = (meta.data?.accounts.length ?? 0) > 0;
  const current = thread.data && thread.data.id === selectedId ? thread.data : null;

  return (
    <div className="-mx-4 flex h-[calc(100dvh-10rem)] min-h-[480px] gap-3 px-2 pt-1 lg:mx-0 lg:h-[calc(100dvh-5rem)] lg:px-0">
      {/* ------------------------------------------------------------------ list */}
      <aside className={cx("glass flex min-w-0 flex-col overflow-hidden rounded-[22px] lg:flex lg:w-[340px] lg:shrink-0",
        view === "list" ? "flex w-full" : "hidden")}>
        <header className="flex items-center gap-2 px-4 pt-4">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-ink text-white"><Icon name="inbox" size={19} duo /></span>
          <h1 className="text-lg font-bold tracking-tight">{t("title")}</h1>
          {!!counts?.unread && <Badge tone="ink">{counts.unread}</Badge>}
          <div className="ms-auto flex items-center">
            <IconButton icon={syncing ? "progress_activity" : "refresh"} label={t("sync")} onClick={sync} disabled={syncing}
              className={syncing ? "[&_svg]:animate-spin" : ""} />
            {can("admin") && (
              <Link href="/settings/inbox" aria-label={t("assistantSettings")} title={t("assistantSettings")}
                className="inline-flex h-9 w-9 items-center justify-center rounded-full text-text-2 hover:bg-fill-2">
                <Icon name="settings" size={18} />
              </Link>
            )}
          </div>
        </header>

        <nav className="mt-3 flex flex-wrap gap-1 px-3 pb-1" role="tablist">
          {FOLDERS.map((f) => {
            const count = f.key === "done" ? 0 : counts?.[f.key as keyof typeof counts] ?? 0;
            const active = filters.folder === f.key;
            return (
              <button key={f.key} role="tab" aria-selected={active} onClick={() => setFilters({ ...filters, folder: f.key })}
                className={cx("inline-flex h-8 shrink-0 items-center gap-1 rounded-full px-2.5 text-[13px] font-medium transition",
                  active ? "bg-ink text-white" : "text-text-2 hover:bg-fill-2",
                  f.key === "pending" && count > 0 && !active && "text-warn")}>
                {f.key === "pending" && <Icon name={f.icon} size={14} />}
                {t(`folders.${f.key}`)}
                {count > 0 && <span className={cx("min-w-5 rounded-full px-1.5 text-[11px] leading-5", active ? "bg-white/20" : "bg-fill-2")}>{count}</span>}
              </button>
            );
          })}
        </nav>

        <div className="flex flex-col gap-2 border-b border-line px-3 pb-3 pt-2">
          <div className="relative">
            <Icon name="search" size={16} className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-faint" />
            <Input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("searchPlaceholder")} className="!h-9 ps-9" />
          </div>
          <div className="flex items-center justify-between gap-2">
            <Segmented size="sm" value={filters.kind} onChange={(kind) => setFilters({ ...filters, kind })}
              options={[{ value: "", label: t("kinds.all") }, { value: "dm", label: t("kinds.dm") }, { value: "comment", label: t("kinds.comment") }]} />
            <div className="flex items-center gap-1">
              {meta.data?.platforms.map((p) => (
                <button key={p} title={t(`platforms.${p}`)} onClick={() => setFilters({ ...filters, platform: filters.platform === p ? "" : p })}
                  className={cx("rounded-[10px] p-0.5 transition", filters.platform === p ? "ring-2 ring-ink" : filters.platform ? "opacity-35" : "hover:opacity-80")}>
                  <PlatformBadge platform={p} size={22} />
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {list.isLoading && <div className="flex justify-center py-10"><Spinner /></div>}
          {!list.isLoading && !items.length && (
            <EmptyState icon="check_circle" title={t("emptyList")} text={hasAccounts ? t("emptyListText") : t("noAccountsText")} />
          )}
          <ul>
            {items.map((row) => <ConversationItem key={row.id} row={row} selected={row.id === selectedId} onSelect={() => select(row)} />)}
          </ul>
          {list.hasNextPage && (
            <div className="flex justify-center p-3">
              <Button size="sm" variant="ghost" loading={list.isFetchingNextPage} onClick={() => list.fetchNextPage()}>{t("loadMore")}</Button>
            </div>
          )}
        </div>
      </aside>

      {/* ------------------------------------------------------------------ thread */}
      <main className={cx("glass min-w-0 flex-1 flex-col overflow-hidden rounded-[22px] lg:flex", view === "thread" ? "flex" : "hidden")}>
        {current && meta.data ? (
          <ThreadPane thread={current} meta={meta.data} onBack={back} onChanged={setThread}
            onToggleInfo={() => { setSideOpen((o) => !o); setView((v) => (v === "info" ? "thread" : "info")); }} />
        ) : selectedId && thread.isLoading ? (
          <div className="flex flex-1 items-center justify-center"><Spinner size={26} /></div>
        ) : (
          <div className="flex flex-1 items-center justify-center">
            <EmptyState icon="forum" title={t("pickTitle")} text={t("pickText")}
              action={!hasAccounts && can("admin") ? <Link href="/settings/inbox"><Button variant="primary" icon="add">{t("connectAccount")}</Button></Link> : undefined} />
          </div>
        )}
      </main>

      {/* ------------------------------------------------------------------ customer panel */}
      {current && meta.data && (
        <aside className={cx("glass min-w-0 flex-col overflow-y-auto rounded-[22px]",
          view === "info" ? "flex w-full" : "hidden", sideOpen && "xl:flex xl:w-[300px] xl:shrink-0")}>
          <CustomerPanel key={current.id} thread={current} meta={meta.data} onChanged={setThread} onClose={() => { setSideOpen(false); setView("thread"); }} />
        </aside>
      )}
    </div>
  );
}

function ConversationItem({ row, selected, onSelect }: { row: ConversationRow; selected: boolean; onSelect: () => void }) {
  const t = useTranslations("inbox");
  const when = useWhen();
  return (
    <li>
      <button onClick={onSelect} className={cx("flex w-full items-start gap-3 border-b border-line/60 px-4 py-3 text-start transition",
        selected ? "bg-ink/[0.06]" : "hover:bg-fill")}>
        <ConvAvatar name={row.name} src={row.avatar_url} platform={row.platform} size={42} />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className={cx("bidi min-w-0 flex-1 truncate text-sm", row.unread ? "font-bold" : "font-semibold")}>{row.name}</span>
            <time className={cx("shrink-0 text-[11px]", row.unread ? "font-semibold text-text" : "text-muted")}>{when(row.last_message_at)}</time>
            {row.unread && <Dot />}
          </span>
          <span className={cx("mt-0.5 flex items-center gap-1 text-[13px]", row.unread ? "text-text" : "text-muted")}>
            {row.kind === "comment" && <Icon name="mode_comment" size={13} className="shrink-0" />}
            <span className="bidi truncate">{row.snippet || "…"}</span>
          </span>
          {(row.state === "pending" || row.has_suggestion || row.intent || row.sentiment === "negative" || row.assignee || row.tags.length > 0) && (
            <span className="mt-1.5 flex flex-wrap items-center gap-1">
              {row.state === "pending" && <Badge tone="warn"><Icon name="support_agent" size={11} />{t("needsHuman")}</Badge>}
              {row.has_suggestion && <Badge tone="ink"><Icon name="smart_toy" size={11} />{t("draft")}</Badge>}
              {row.intent && <Badge><Icon name={INTENT_ICON[row.intent]} size={11} />{t(`intents.${row.intent}`)}</Badge>}
              {row.sentiment === "negative" && <Badge tone="bad"><Icon name="mood_bad" size={11} /></Badge>}
              {row.tags.slice(0, 2).map((tag) => <Badge key={tag.id}><Icon name="tag" size={11} /><span className="bidi">{tag.name}</span></Badge>)}
              {row.assignee && (
                <span className="ms-auto inline-flex h-5 w-5 items-center justify-center rounded-full bg-fill-2 text-[10px] font-bold text-text-2" title={row.assignee.name}>
                  {row.assignee.name.slice(0, 1).toUpperCase()}
                </span>
              )}
            </span>
          )}
        </span>
      </button>
    </li>
  );
}
