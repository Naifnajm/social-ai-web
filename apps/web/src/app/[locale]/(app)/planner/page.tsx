"use client";
/**
 * Planner: the content calendar. Month / week / agenda views, drag & drop (desktop), filters, pillar balance,
 * best-time hints per weekday, a "to plan" tray of undated drafts and a post panel (schedule, campaign, evergreen).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { type DragEvent, useEffect, useMemo, useState } from "react";
import { Icon } from "@/components/icon";
import { ExternalScheduled } from "@/components/planning/external-scheduled";
import { PostPanel } from "@/components/planning/post-panel";
import type { PlannerData, PlannerPost } from "@/components/planning/types";
import { ColorDot, PlatformStack, StateBadge, onError, useFormat, useWeekdays } from "@/components/planning/ui";
import { Button, Card, EmptyState, IconButton, PageHeader, Segmented, Select, Spinner, cx, toast } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

type View = "month" | "week" | "agenda";
type Filters = { account_id: string; campaign_id: string; pillar_id: string; state: string };
const VIEW_KEY = "sai.planner.view";

// ---- day strings ("YYYY-MM-DD") computed in UTC so no time zone shifts the calendar
const toDate = (day: string) => new Date(`${day}T00:00:00Z`);
const toDay = (d: Date) => d.toISOString().slice(0, 10);
const addDays = (day: string, n: number) => toDay(new Date(toDate(day).getTime() + n * 86400000));
const mondayIndex = (day: string) => (toDate(day).getUTCDay() + 6) % 7;
const monthStart = (day: string) => `${day.slice(0, 8)}01`;
const addMonths = (day: string, n: number) => {
  const d = toDate(monthStart(day));
  d.setUTCMonth(d.getUTCMonth() + n);
  return toDay(d);
};
const browserToday = () => {
  const now = new Date();
  return toDay(new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())));
};

function initialParams() {
  if (typeof window === "undefined") return new URLSearchParams();
  return new URLSearchParams(window.location.search);
}

export default function PlannerPage() {
  const t = useTranslations("planner");
  const locale = useLocale();
  const qc = useQueryClient();
  const { can } = useSession();
  const fmt = useFormat();
  const weekdays = useWeekdays("short");
  const canEdit = can("editor");
  const weekStart = locale === "ar" ? 6 : 0; // Sunday first in the Gulf, Monday otherwise (0 = Monday)

  const [params] = useState(initialParams);
  const [view, setView] = useState<View>("month");
  const [anchor, setAnchor] = useState(() => params.get("date") || browserToday());
  const [filters, setFilters] = useState<Filters>({ account_id: "", campaign_id: params.get("campaign") || "", pillar_id: "", state: "" });
  const [openId, setOpenId] = useState<number | null>(params.get("post") ? Number(params.get("post")) : null);
  const [dragId, setDragId] = useState<number | null>(null);
  const [dropDay, setDropDay] = useState<string | null>(null);
  const [mobileDay, setMobileDay] = useState<string | null>(null);

  useEffect(() => {
    let saved: string | null = null;
    try {
      saved = window.localStorage.getItem(VIEW_KEY);
    } catch {
      /* storage unavailable */
    }
    const phone = window.matchMedia("(max-width: 639px)").matches;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- read once from the browser after mount
    setView(saved === "month" || saved === "week" || saved === "agenda" ? (saved as View) : phone ? "agenda" : "month");
  }, []);

  const changeView = (v: View) => {
    setView(v);
    try {
      window.localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* storage unavailable */
    }
  };

  const range = useMemo(() => {
    if (view === "week") {
      const start = addDays(anchor, -((mondayIndex(anchor) - weekStart + 7) % 7));
      return { start, end: addDays(start, 7) };
    }
    const first = monthStart(anchor);
    if (view === "agenda") return { start: first, end: addMonths(first, 1) };
    const start = addDays(first, -((mondayIndex(first) - weekStart + 7) % 7));
    const next = addMonths(first, 1);
    const weeks = Math.ceil((toDate(next).getTime() - toDate(start).getTime()) / (7 * 86400000));
    return { start, end: addDays(start, weeks * 7) };
  }, [view, anchor, weekStart]);

  const queryKey = ["planner", range.start, range.end, filters];
  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () => api.get<PlannerData>("/planner", { start: range.start, end: range.end, ...filters }),
    placeholderData: (prev) => prev,
  });

  const today = data?.today || browserToday();
  const byDay = useMemo(() => {
    const map = new Map<string, PlannerPost[]>();
    for (const post of data?.posts || []) {
      if (!post.day) continue;
      map.set(post.day, [...(map.get(post.day) || []), post]);
    }
    return map;
  }, [data]);

  const move = useMutation({
    mutationFn: ({ id, day }: { id: number; day: string }) => api.post<PlannerPost>(`/planner/posts/${id}/move`, { day }),
    onMutate: async ({ id, day }) => {
      await qc.cancelQueries({ queryKey: ["planner"] });
      const previous = qc.getQueryData<PlannerData>(queryKey);
      if (previous) {
        const moved = [...previous.posts, ...previous.unplanned].find((p) => p.id === id);
        if (moved) {
          qc.setQueryData<PlannerData>(queryKey, {
            ...previous,
            posts: [...previous.posts.filter((p) => p.id !== id), { ...moved, day }],
            unplanned: previous.unplanned.filter((p) => p.id !== id),
          });
        }
      }
      return { previous };
    },
    onError: (err, _vars, context) => {
      if (context?.previous) qc.setQueryData(queryKey, context.previous);
      onError(err);
    },
    onSuccess: () => toast.success(t("moved")),
    onSettled: () => qc.invalidateQueries({ queryKey: ["planner"] }),
  });

  const step = (dir: number) => {
    if (view === "week") setAnchor(addDays(anchor, dir * 7));
    else setAnchor(addMonths(anchor, dir));
  };

  const title = view === "week"
    ? `${fmt.date(range.start, { day: "numeric", month: "short" })} – ${fmt.date(addDays(range.end, -1), { day: "numeric", month: "short", year: "numeric" })}`
    : fmt.date(monthStart(anchor), { month: "long", year: "numeric" });

  // ---- drag & drop
  const onDragStart = (post: PlannerPost) => (e: DragEvent) => {
    if (!post.movable || !canEdit) return e.preventDefault();
    e.dataTransfer.setData("text/plain", String(post.id));
    e.dataTransfer.effectAllowed = "move";
    setDragId(post.id);
  };
  const dropProps = (day: string) => ({
    onDragOver: (e: DragEvent) => {
      if (dragId === null || day < today) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      if (dropDay !== day) setDropDay(day);
    },
    onDragLeave: () => setDropDay((d) => (d === day ? null : d)),
    onDrop: (e: DragEvent) => {
      e.preventDefault();
      const id = Number(e.dataTransfer.getData("text/plain"));
      setDropDay(null);
      setDragId(null);
      if (!id || day < today) return;
      const post = [...(data?.posts || []), ...(data?.unplanned || [])].find((p) => p.id === id);
      if (post && post.day !== day) move.mutate({ id, day });
    },
  });

  const studioHref = (day?: string) => {
    const q = new URLSearchParams();
    if (day) q.set("date", day);
    if (filters.campaign_id) q.set("campaign", filters.campaign_id);
    const s = q.toString();
    return `/studio${s ? `?${s}` : ""}`;
  };

  const columns = Array.from({ length: 7 }, (_, i) => (i + weekStart) % 7);
  const hints = data?.best || [];

  const days = useMemo(() => {
    const out: string[] = [];
    for (let d = range.start; d < range.end; d = addDays(d, 1)) out.push(d);
    return out;
  }, [range]);

  return (
    <div className="pt-2">
      <PageHeader icon="calendar_today" title={t("title")} subtitle={t("subtitle")}
        actions={canEdit && <Link href={studioHref()}><Button variant="primary" icon="add">{t("newPost")}</Button></Link>} />

      <ExternalScheduled />

      {/* toolbar */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          <IconButton icon="east" label={t("previous")} className="rotate-180 rtl:rotate-0" onClick={() => step(-1)} />
          <Button size="sm" onClick={() => setAnchor(today)}>{t("today")}</Button>
          <IconButton icon="east" label={t("next")} className="rtl:rotate-180" onClick={() => step(1)} />
        </div>
        <h2 className="order-first w-full min-w-0 truncate text-lg font-semibold tracking-tight sm:order-none sm:w-auto sm:flex-1">{title}</h2>
        {isLoading && <Spinner size={18} />}
        <Segmented value={view} onChange={changeView} size="sm" className="ms-auto sm:ms-0" options={[
          { value: "month", label: t("views.month") },
          { value: "week", label: t("views.week") },
          { value: "agenda", label: t("views.agenda") },
        ]} />
      </div>

      <FiltersBar data={data} filters={filters} setFilters={setFilters} />
      <PillarStrip data={data} />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_270px]">
        <div className="min-w-0">
          {view === "month" && (
            <Card padded={false} className="overflow-hidden">
              <div className="grid grid-cols-7 border-b border-line">
                {columns.map((wd) => {
                  const hint = hints.find((h) => h.weekday === wd);
                  return (
                    <div key={wd} className="px-1 py-2 text-center">
                      <div className="text-[12px] font-semibold text-text-2">{weekdays[wd]}</div>
                      {hint?.time && (
                        <div className={cx("mt-0.5 hidden text-[10.5px] sm:block", hint.top ? "font-semibold text-ink" : "text-faint")} title={t("bestTimeHint")}>
                          {hint.top ? "★ " : ""}<span dir="ltr">{hint.time}</span>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
              <div className="grid grid-cols-7">
                {days.map((day) => {
                  const posts = byDay.get(day) || [];
                  const inMonth = day.slice(0, 7) === anchor.slice(0, 7);
                  const past = day < today;
                  return (
                    <div key={day} {...dropProps(day)}
                      onClick={() => setMobileDay(day)}
                      className={cx("group relative min-h-[64px] border-b border-e border-line p-1 transition sm:min-h-[118px] sm:p-1.5",
                        !inMonth && "bg-black/[0.015]", past && "bg-black/[0.025]",
                        dropDay === day && "bg-ink/[0.06] ring-2 ring-inset ring-ink/30",
                        mobileDay === day && "max-sm:bg-ink/[0.05]")}>
                      <div className="flex items-center justify-between">
                        <span className={cx("inline-flex h-6 min-w-6 items-center justify-center rounded-full px-1 text-[12px] font-semibold",
                          day === today ? "bg-ink text-white" : inMonth ? "text-text" : "text-faint")}>
                          {Number(day.slice(8))}
                        </span>
                        {canEdit && !past && (
                          <Link href={studioHref(day)} onClick={(e) => e.stopPropagation()}
                            className="hidden h-6 w-6 items-center justify-center rounded-full text-muted opacity-0 transition hover:bg-ink hover:text-white group-hover:opacity-100 sm:inline-flex"
                            aria-label={t("addOnDay")} title={t("addOnDay")}>
                            <Icon name="add" size={15} />
                          </Link>
                        )}
                      </div>
                      {/* phone: dots; desktop: chips */}
                      <div className="mt-1 flex flex-wrap gap-0.5 sm:hidden">
                        {posts.slice(0, 6).map((p) => <ColorDot key={p.id} color={p.campaign?.color || p.pillar?.color || "#0a0a0a"} size={7} />)}
                      </div>
                      <div className="mt-1 hidden flex-col gap-1 sm:flex">
                        {posts.slice(0, 4).map((p) => (
                          <PostChip key={p.id} post={p} compact draggable={canEdit && p.movable} onDragStart={onDragStart(p)}
                            onDragEnd={() => { setDragId(null); setDropDay(null); }} onOpen={() => setOpenId(p.id)} />
                        ))}
                        {posts.length > 4 && (
                          <button onClick={() => { setAnchor(day); changeView("week"); }} className="text-start text-[11px] font-medium text-muted hover:text-text">
                            {t("more", { count: posts.length - 4 })}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
              {mobileDay && (
                <div className="border-t border-line p-3 sm:hidden">
                  <DayList day={mobileDay} posts={byDay.get(mobileDay) || []} today={today} canEdit={canEdit}
                    studioHref={studioHref} onOpen={setOpenId} hint={hints.find((h) => h.weekday === mondayIndex(mobileDay))?.time} />
                </div>
              )}
            </Card>
          )}

          {view === "week" && (
            <div className="grid gap-2 sm:grid-cols-7">
              {days.map((day) => {
                const posts = byDay.get(day) || [];
                const hint = hints.find((h) => h.weekday === mondayIndex(day));
                const past = day < today;
                return (
                  <div key={day} {...dropProps(day)}
                    className={cx("glass flex min-h-[120px] flex-col rounded-[18px] p-2 transition sm:min-h-[420px]",
                      past && "opacity-80", dropDay === day && "ring-2 ring-ink/40")}>
                    <div className="mb-2 flex items-center gap-2 px-1">
                      <span className={cx("flex h-8 w-8 items-center justify-center rounded-full text-sm font-bold", day === today ? "bg-ink text-white" : "bg-fill-2")}>
                        {Number(day.slice(8))}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="text-[12px] font-semibold">{weekdays[mondayIndex(day)]}</div>
                        {hint?.time && <div className={cx("text-[10.5px]", hint.top ? "font-semibold text-ink" : "text-faint")}>{hint.top ? "★ " : ""}<span dir="ltr">{hint.time}</span></div>}
                      </div>
                      {canEdit && !past && (
                        <Link href={studioHref(day)} className="inline-flex h-7 w-7 items-center justify-center rounded-full text-muted hover:bg-ink hover:text-white" aria-label={t("addOnDay")}>
                          <Icon name="add" size={16} />
                        </Link>
                      )}
                    </div>
                    <div className="flex flex-col gap-1.5">
                      {posts.map((p) => (
                        <PostChip key={p.id} post={p} draggable={canEdit && p.movable} onDragStart={onDragStart(p)}
                          onDragEnd={() => { setDragId(null); setDropDay(null); }} onOpen={() => setOpenId(p.id)} />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {view === "agenda" && (
            <Card>
              {(() => {
                const shown = days.filter((d) => byDay.has(d) || d === today);
                if (!shown.length || !data?.posts.length) {
                  return <EmptyState icon="calendar_today" title={t("emptyTitle")} text={t("emptyText")}
                    action={canEdit && <Link href={studioHref()}><Button variant="primary" icon="add">{t("newPost")}</Button></Link>} />;
                }
                return (
                  <div className="flex flex-col divide-y divide-line">
                    {shown.map((day) => (
                      <div key={day} className="py-3 first:pt-0 last:pb-0">
                        <DayList day={day} posts={byDay.get(day) || []} today={today} canEdit={canEdit} studioHref={studioHref}
                          onOpen={setOpenId} hint={hints.find((h) => h.weekday === mondayIndex(day))?.time} />
                      </div>
                    ))}
                  </div>
                );
              })()}
            </Card>
          )}
        </div>

        <UnplannedTray posts={data?.unplanned || []} canEdit={canEdit} onOpen={setOpenId}
          onDragStart={onDragStart} onDragEnd={() => { setDragId(null); setDropDay(null); }} />
      </div>

      {openId !== null && data && (
        <PostPanel postId={openId} data={data} onClose={() => setOpenId(null)} />
      )}
    </div>
  );
}

function FiltersBar({ data, filters, setFilters }: { data?: PlannerData; filters: Filters; setFilters: (f: Filters) => void }) {
  const t = useTranslations("planner");
  const states = useTranslations("planning.states");
  const set = (key: keyof Filters) => (e: { target: { value: string } }) => setFilters({ ...filters, [key]: e.target.value });
  const active = Object.values(filters).some(Boolean);
  return (
    <div className="-mx-4 mb-3 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0">
      <Select className="!h-9 !w-auto min-w-36 shrink-0" value={filters.account_id} onChange={set("account_id")} aria-label={t("filters.account")}>
        <option value="">{t("filters.allAccounts")}</option>
        {data?.accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
      </Select>
      <Select className="!h-9 !w-auto min-w-36 shrink-0" value={filters.campaign_id} onChange={set("campaign_id")} aria-label={t("filters.campaign")}>
        <option value="">{t("filters.allCampaigns")}</option>
        {data?.campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </Select>
      <Select className="!h-9 !w-auto min-w-36 shrink-0" value={filters.pillar_id} onChange={set("pillar_id")} aria-label={t("filters.pillar")}>
        <option value="">{t("filters.allPillars")}</option>
        {data?.pillars.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </Select>
      <Select className="!h-9 !w-auto min-w-32 shrink-0" value={filters.state} onChange={set("state")} aria-label={t("filters.state")}>
        <option value="">{t("filters.allStates")}</option>
        {["draft", "to_approve", "scheduled", "posted", "failed"].map((s) => <option key={s} value={s}>{states(s)}</option>)}
      </Select>
      {active && (
        <Button size="sm" variant="ghost" icon="close" className="shrink-0" onClick={() => setFilters({ account_id: "", campaign_id: "", pillar_id: "", state: "" })}>
          {t("filters.clear")}
        </Button>
      )}
    </div>
  );
}

function PillarStrip({ data }: { data?: PlannerData }) {
  const t = useTranslations("planner");
  const { can } = useSession();
  const pillars = data?.pillars || [];
  if (!pillars.length) {
    return can("admin") ? (
      <div className="mb-4 flex items-center gap-2 rounded-2xl border border-dashed border-line-strong px-4 py-2.5 text-[13px] text-muted">
        <Icon name="flag" size={16} /> {t("pillars.none")}
        <Link href="/settings/pillars" className="ms-auto font-semibold text-text hover:underline">{t("pillars.setup")}</Link>
      </div>
    ) : null;
  }
  const total = pillars.reduce((s, p) => s + p.share_30, 0);
  return (
    <Card className="mb-4 !p-3.5">
      <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold">
        <Icon name="flag" size={16} className="text-text-2" /> {t("pillars.title")}
        <span className="text-[11.5px] font-normal text-muted">{t("pillars.hint")}</span>
      </div>
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-track">
        {total > 0 && pillars.map((p) => <div key={p.id} style={{ width: `${(p.share_30 / Math.max(total, 100)) * 100}%`, background: p.color }} title={`${p.name} ${p.share_30}%`} />)}
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5">
        {pillars.map((p) => (
          <span key={p.id} className="inline-flex items-center gap-1.5 text-[12px]">
            <ColorDot color={p.color} size={9} />
            <span className="font-medium">{p.name}</span>
            <span className="text-muted bidi">{p.share_30}% / {p.target_share}%</span>
            {p.gap <= -5 && <span className="rounded-full bg-ink px-1.5 text-[10px] font-semibold text-white">{t("pillars.more")}</span>}
          </span>
        ))}
      </div>
    </Card>
  );
}

function PostChip({ post, compact = false, draggable, onDragStart, onDragEnd, onOpen }: {
  post: PlannerPost; compact?: boolean; draggable: boolean; onDragStart: (e: DragEvent) => void; onDragEnd: () => void; onOpen: () => void;
}) {
  const t = useTranslations("planner");
  const color = post.campaign?.color || post.pillar?.color || "#0a0a0a";
  return (
    <button type="button" draggable={draggable} onDragStart={onDragStart} onDragEnd={onDragEnd}
      onClick={(e) => { e.stopPropagation(); onOpen(); }}
      className={cx("group/chip relative flex w-full items-center gap-1.5 overflow-hidden rounded-[10px] border border-line bg-white/85 text-start shadow-[0_1px_2px_rgba(0,0,0,.04)] transition hover:border-black/20 hover:shadow-[var(--shadow)]",
        compact ? "p-1 ps-2" : "p-1.5 ps-2.5", draggable && "cursor-grab active:cursor-grabbing", post.state === "posted" && "opacity-75")}>
      <span className="absolute inset-y-0 start-0 w-[3px]" style={{ background: color }} />
      {post.media && post.media.kind === "image" ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={post.media.url} alt="" className={cx("shrink-0 rounded-md object-cover", compact ? "h-6 w-6" : "h-10 w-10")} draggable={false} />
      ) : post.media ? (
        <span className={cx("flex shrink-0 items-center justify-center rounded-md bg-ink text-white", compact ? "h-6 w-6" : "h-10 w-10")}><Icon name="play_arrow" size={compact ? 12 : 16} /></span>
      ) : null}
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1 text-[10.5px] text-muted">
          {post.time ? <span dir="ltr" className="font-semibold text-text-2">{post.time}</span> : <span>{t("noTime")}</span>}
          {post.evergreen && <Icon name="recycle" size={11} />}
          {post.recycled && <Icon name="autorenew" size={11} />}
          {post.state === "to_approve" && <Icon name="verified_user" size={11} className="text-warn" />}
          {post.state === "failed" && <Icon name="error" size={11} className="text-bad" />}
        </span>
        <span className={cx("block truncate font-medium bidi", compact ? "text-[11.5px]" : "text-[12.5px]")}>{post.name || post.preview || t("untitled")}</span>
        {!compact && (
          <span className="mt-1 flex items-center gap-1.5">
            <PlatformStack platforms={post.platforms} size={15} />
            <span className="ms-auto"><StateBadge state={post.state} /></span>
          </span>
        )}
      </span>
    </button>
  );
}

function DayList({ day, posts, today, canEdit, studioHref, onOpen, hint }: {
  day: string; posts: PlannerPost[]; today: string; canEdit: boolean; studioHref: (day?: string) => string; onOpen: (id: number) => void; hint?: string | null;
}) {
  const t = useTranslations("planner");
  const fmt = useFormat();
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className={cx("text-[13px] font-semibold", day === today && "rounded-full bg-ink px-2.5 py-0.5 text-white")}>
          {fmt.date(day, { weekday: "long", day: "numeric", month: "long" })}
        </span>
        {hint && <span className="text-[11px] text-muted">★ {t("bestAt")} <span dir="ltr">{hint}</span></span>}
        {canEdit && day >= today && (
          <Link href={studioHref(day)} className="ms-auto inline-flex h-8 items-center gap-1 rounded-full px-3 text-[12px] font-medium text-text-2 hover:bg-fill-2">
            <Icon name="add" size={15} /> {t("addOnDay")}
          </Link>
        )}
      </div>
      {posts.length ? (
        <div className="grid gap-2 sm:grid-cols-2">
          {posts.map((p) => (
            <PostChip key={p.id} post={p} draggable={false} onDragStart={() => undefined} onDragEnd={() => undefined} onOpen={() => onOpen(p.id)} />
          ))}
        </div>
      ) : (
        <p className="text-[12.5px] text-faint">{t("nothingThisDay")}</p>
      )}
    </div>
  );
}

function UnplannedTray({ posts, canEdit, onOpen, onDragStart, onDragEnd }: {
  posts: PlannerPost[]; canEdit: boolean; onOpen: (id: number) => void; onDragStart: (p: PlannerPost) => (e: DragEvent) => void; onDragEnd: () => void;
}) {
  const t = useTranslations("planner");
  const [open, setOpen] = useState(true);
  return (
    <Card className="h-fit !p-3.5 xl:sticky xl:top-16">
      <button className="flex w-full items-center gap-2 text-start" onClick={() => setOpen(!open)}>
        <Icon name="inbox" size={17} className="text-text-2" />
        <span className="text-[14px] font-semibold">{t("tray.title")}</span>
        <span className="rounded-full bg-fill-2 px-2 text-[11px] font-semibold text-text-2">{posts.length}</span>
        <Icon name={open ? "expand_less" : "expand_more"} size={16} className="ms-auto text-muted" />
      </button>
      {open && (
        <>
          <p className="mt-1 mb-3 text-[12px] text-muted">{canEdit ? t("tray.hint") : t("tray.hintViewer")}</p>
          {posts.length ? (
            <div className="flex max-h-[60vh] flex-col gap-1.5 overflow-y-auto">
              {posts.map((p) => (
                <PostChip key={p.id} post={p} draggable={canEdit} onDragStart={onDragStart(p)} onDragEnd={onDragEnd} onOpen={() => onOpen(p.id)} />
              ))}
            </div>
          ) : (
            <p className="rounded-xl bg-fill px-3 py-4 text-center text-[12px] text-faint">{t("tray.empty")}</p>
          )}
        </>
      )}
    </Card>
  );
}
