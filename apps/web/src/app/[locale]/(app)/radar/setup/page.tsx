"use client";
/** Radar setup: what to listen for (brand words, filters, languages, countries, competitors), which sources, the X
 *  monthly cap and what it costs. One workspace can have several setups (plan limit). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { type KeyboardEvent, type ReactNode, useState } from "react";
import { Icon } from "@/components/icon";
import { Chip, onError, useFormat } from "@/components/planning/ui";
import { SourceBadge, useRadarQueries, useRadarScope, useRadarStatus, useScope, useSourceLabel } from "@/components/radar/shared";
import { type Estimate, LANGUAGES, type ListeningQuery, type QueryInput, type RadarStatus, type Source } from "@/components/radar/types";
import { Badge, Button, Card, Field, IconButton, Input, Modal, SectionTitle, Select, Spinner, Switch, cx, toast } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

const COUNTRY_SUGGESTIONS = ["SA", "AE", "KW", "QA", "BH", "OM", "EG", "JO"];
const MAX_COMPETITORS = 5;

const EMPTY: QueryInput = {
  name: "", keywords: [], required: [], excluded: [], languages: [], countries: [], competitors: [],
  sources: ["owned", "instagram", "facebook", "youtube", "google_business", "news"], active: true, x_monthly_cap: 3000,
};

export default function RadarSetupPage() {
  const t = useTranslations("radar.setup");
  const status = useRadarStatus();
  const queries = useRadarQueries(!!status.data?.enabled);
  const { queryId } = useScope();
  const setQuery = useRadarScope((s) => s.setQuery);
  const canEdit = useSession((s) => s.can("editor"));
  const [creating, setCreating] = useState(false);
  if (!status.data || queries.isLoading) return <div className="flex justify-center py-24"><Spinner size={28} /></div>;
  const list = queries.data ?? [];
  const current = list.find((q) => q.id === queryId) ?? null;
  const isNew = creating || !current;
  if (isNew && !canEdit) return <Card><p className="p-2 text-sm text-muted">{t("viewerNoSetup")}</p></Card>;
  const { queries_used: used, queries_limit: limit } = status.data;

  return (
    <div className="flex flex-col gap-5">
      {list.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {!creating && list.length > 1 && (
            <Select className="!w-60" aria-label={t("pick")} value={current?.id ?? ""} onChange={(e) => setQuery(Number(e.target.value))}>
              {list.map((q) => <option key={q.id} value={q.id}>{q.name}</option>)}
            </Select>
          )}
          {creating ? (
            <Button variant="ghost" icon="arrow_back" onClick={() => setCreating(false)}>{t("backToSetup")}</Button>
          ) : canEdit && (
            <Button icon="add" onClick={() => setCreating(true)}>{t("new")}</Button>
          )}
          <span className="ms-auto text-xs text-muted">{limit == null ? t("usedUnlimited", { used }) : t("used", { used, limit })}</span>
        </div>
      )}
      <SetupForm key={isNew ? "new" : current!.id} status={status.data} query={isNew ? null : current}
        onSaved={(row) => { setCreating(false); setQuery(row.id); }} />
    </div>
  );
}

function SetupForm({ status, query, onSaved }: { status: RadarStatus; query: ListeningQuery | null; onSaved: (row: ListeningQuery) => void }) {
  const t = useTranslations("radar.setup");
  const tr = useTranslations("radar");
  const fmt = useFormat();
  const router = useRouter();
  const qc = useQueryClient();
  const sourceLabel = useSourceLabel();
  const canEdit = useSession((s) => s.can("editor"));
  const canDelete = useSession((s) => s.can("admin"));
  const [form, setForm] = useState<QueryInput>(() => query ? {
    name: query.name, keywords: query.keywords, required: query.required, excluded: query.excluded, languages: query.languages,
    countries: query.countries, competitors: query.competitors.map((c) => ({ name: c.name, keywords: c.keywords ?? [] })),
    sources: query.sources, active: query.active, x_monthly_cap: query.x_monthly_cap,
  } : EMPTY);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const set = <K extends keyof QueryInput>(key: K, value: QueryInput[K]) => setForm((f) => ({ ...f, [key]: value }));
  const estimate = useQuery({
    queryKey: ["radar", "estimate", query?.id ?? null],
    queryFn: () => api.get<Estimate>("/listening/estimate", { query_id: query?.id }),
  });
  const save = useMutation({
    mutationFn: () => {
      const body = { ...form, name: form.name.trim() || form.keywords[0] || "", competitors: form.competitors.filter((c) => c.name.trim()) };
      return query ? api.patch<ListeningQuery>(`/listening/queries/${query.id}`, body) : api.post<ListeningQuery>("/listening/queries", body);
    },
    onSuccess: (row) => {
      qc.invalidateQueries({ queryKey: ["radar"] });
      onSaved(row);
      if (query) toast.success(t("saved"));
      else { toast.success(t("created")); router.push("/radar"); }
    },
    onError,
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/listening/queries/${query!.id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["radar"] }); useRadarScope.getState().setQuery(null); setConfirmDelete(false); toast.success(t("deleted")); },
    onError,
  });

  const language = names(fmt.locale, "language");
  const region = names(fmt.locale, "region");
  const toggle = <T extends string>(values: T[], value: T) => (values.includes(value) ? values.filter((v) => v !== value) : [...values, value]);
  const xOn = form.sources.includes("x");
  const price = status.x_price_per_post;
  const ro = !canEdit;

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="flex flex-col gap-5">
        <Card>
          <SectionTitle icon="graphic_eq">{query ? t("editTitle") : t("newTitle")}</SectionTitle>
          <div className="flex flex-col gap-4">
            <Field label={t("name")} hint={t("nameHint")}>
              <Input value={form.name} maxLength={120} disabled={ro} placeholder={t("namePlaceholder")} onChange={(e) => set("name", e.target.value)} />
            </Field>
            <Field label={t("keywords")} hint={t("keywordsHint")} error={save.isError && !form.keywords.length ? t("keywordsRequired") : undefined}>
              <TagInput values={form.keywords} onChange={(v) => set("keywords", v)} disabled={ro} placeholder={t("keywordsPlaceholder")} />
            </Field>
            <Field label={t("required")} hint={t("requiredHint")}>
              <TagInput values={form.required} onChange={(v) => set("required", v)} disabled={ro} placeholder={t("wordPlaceholder")} />
            </Field>
            <Field label={t("excluded")} hint={t("excludedHint")}>
              <TagInput values={form.excluded} onChange={(v) => set("excluded", v)} disabled={ro} placeholder={t("wordPlaceholder")} />
            </Field>
            <Group label={t("languages")} hint={t("languagesHint")}>
              <div className="flex flex-wrap gap-2">
                {LANGUAGES.map((l) => (
                  <Chip key={l} active={form.languages.includes(l)} onClick={() => !ro && set("languages", toggle(form.languages, l))}>{language(l)}</Chip>
                ))}
              </div>
            </Group>
            <Group label={t("countries")} hint={t("countriesHint")}>
              <div className="mb-2 flex flex-wrap gap-2">
                {COUNTRY_SUGGESTIONS.map((c) => (
                  <Chip key={c} active={form.countries.includes(c)} onClick={() => !ro && set("countries", toggle(form.countries, c).slice(0, 10))}>{region(c)}</Chip>
                ))}
              </div>
              <TagInput values={form.countries.filter((c) => !COUNTRY_SUGGESTIONS.includes(c))} disabled={ro} placeholder={t("countryPlaceholder")} display={region}
                normalize={(v) => (/^[a-zA-Z]{2}$/.test(v.trim()) ? v.trim().toUpperCase() : null)}
                onChange={(others) => set("countries", [...form.countries.filter((c) => COUNTRY_SUGGESTIONS.includes(c)), ...others].slice(0, 10))} />
            </Group>
          </div>
        </Card>

        <Card>
          <SectionTitle icon="flag" actions={<span className="text-xs text-muted">{t("competitorsCount", { n: form.competitors.length, max: MAX_COMPETITORS })}</span>}>{t("competitors")}</SectionTitle>
          <p className="mb-3 text-xs text-muted">{t("competitorsHint")}</p>
          <div className="flex flex-col gap-3">
            {form.competitors.map((c, i) => (
              <div key={i} className="flex flex-col gap-2 rounded-2xl bg-fill p-3 sm:flex-row sm:items-start">
                <Input className="sm:!w-48" value={c.name} maxLength={120} disabled={ro} placeholder={t("competitorName")} aria-label={t("competitorName")}
                  onChange={(e) => set("competitors", form.competitors.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
                <div className="min-w-0 flex-1">
                  <TagInput values={c.keywords} disabled={ro} placeholder={t("competitorWords")}
                    onChange={(v) => set("competitors", form.competitors.map((x, j) => (j === i ? { ...x, keywords: v.slice(0, 15) } : x)))} />
                </div>
                {!ro && <IconButton icon="delete" label={t("removeCompetitor")} onClick={() => set("competitors", form.competitors.filter((_, j) => j !== i))} />}
              </div>
            ))}
            {!ro && form.competitors.length < MAX_COMPETITORS && (
              <Button className="self-start" icon="add" onClick={() => set("competitors", [...form.competitors, { name: "", keywords: [] }])}>{t("addCompetitor")}</Button>
            )}
          </div>
        </Card>

        <Card>
          <SectionTitle icon="share">{t("sources")}</SectionTitle>
          <ul className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            {status.sources.map((s) => {
              const on = form.sources.includes(s.source);
              return (
                <li key={s.source} className={cx("flex items-start gap-3 rounded-2xl p-3 ring-1 ring-line", on && s.in_plan ? "bg-white/70" : "bg-fill")}>
                  <SourceBadge source={s.source} size={30} />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold">{sourceLabel(s.source)}</div>
                    <p className="mt-0.5 text-xs leading-relaxed text-muted">{t(`sourceHints.${s.source}`)}</p>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {s.paid ? <Badge tone="warn">{t("badges.paid")}</Badge> : <Badge>{t("badges.free")}</Badge>}
                      {!s.in_plan ? <Badge tone="neutral"><Icon name="lock" size={11} />{t("badges.notInPlan")}</Badge>
                        : s.ready ? <Badge tone="ok"><Icon name="check" size={11} />{t("badges.ready")}</Badge>
                          : s.source === "x" || s.source === "youtube"
                            ? <Badge tone="warn">{t("badges.notConfigured")}</Badge>
                            : <Link href="/settings/accounts"><Badge tone="warn"><Icon name="link" size={11} />{t("badges.connect")}</Badge></Link>}
                    </div>
                  </div>
                  <Switch checked={on && s.in_plan} disabled={ro || !s.in_plan} onChange={() => set("sources", toggle(form.sources, s.source as Source))} />
                </li>
              );
            })}
          </ul>
          {xOn && (
            <div className="mt-4 grid gap-3 rounded-2xl bg-fill p-4 sm:grid-cols-2 sm:items-end">
              <Field label={t("xCap")} hint={t("xCapHint")}>
                <Input type="number" min={0} max={1_000_000} step={500} dir="ltr" disabled={ro} value={form.x_monthly_cap}
                  onChange={(e) => set("x_monthly_cap", Math.max(0, Math.min(1_000_000, Number(e.target.value) || 0)))} />
              </Field>
              <div className="text-sm">
                <div className="text-xs text-muted">{t("xCost")}</div>
                <div className="text-xl font-bold tabular-nums" dir="ltr">${fmt.number(form.x_monthly_cap * price, 2)}</div>
                <div className="text-xs text-muted">{t("xPrice", { price: `$${price}` })}</div>
              </div>
            </div>
          )}
        </Card>
      </div>

      <div className="flex flex-col gap-5 xl:sticky xl:top-4 xl:self-start">
        <Card>
          <SectionTitle icon="bar_chart">{t("estimate")}</SectionTitle>
          <dl className="flex flex-col divide-y divide-line text-sm">
            <Row label={t("expected")}>{estimate.data?.expected_month == null ? <span className="text-muted">{t("expectedUnknown")}</span> : t("about", { n: fmt.number(estimate.data.expected_month) })}</Row>
            {estimate.data?.expected_month != null && estimate.data.by_source.x != null && <Row label={t("fromX")}>{t("about", { n: fmt.number(estimate.data.by_source.x) })}</Row>}
            {xOn && <Row label={t("xCostMonth")}><span dir="ltr">${fmt.number(form.x_monthly_cap * price, 2)}</span></Row>}
            {query && query.x_usage.reads > 0 && (
              <Row label={t("xUsed")}><span dir="ltr">{fmt.number(query.x_usage.reads)} / {fmt.number(query.x_usage.cap)} · ${fmt.number(query.x_usage.cost_usd, 2)}</span></Row>
            )}
            <Row label={t("plan")}>{status.queries_limit == null ? t("usedUnlimited", { used: status.queries_used }) : t("used", { used: status.queries_used, limit: status.queries_limit })}</Row>
          </dl>
          {query?.x_usage.capped && <p className="mt-3 text-xs text-warn">{t("xCapped")}</p>}
          {query?.last_error && <p className="bidi mt-3 text-xs text-bad">{tr("waiting.error", { error: query.last_error })}</p>}
        </Card>

        {canEdit && (
          <Card className="flex flex-col gap-3">
            {query && <Switch checked={form.active} onChange={(v) => set("active", v)} label={<span className="text-sm">{form.active ? t("active") : t("paused")}</span>} />}
            <Button variant="primary" size="lg" icon={query ? "save" : "rocket_launch"} loading={save.isPending} disabled={!form.keywords.length} onClick={() => save.mutate()}>
              {query ? t("save") : t("create")}
            </Button>
            {!form.keywords.length && <p className="text-xs text-muted">{t("keywordsRequired")}</p>}
            {query && canDelete && <Button variant="danger" icon="delete" onClick={() => setConfirmDelete(true)}>{t("delete")}</Button>}
          </Card>
        )}
      </div>

      <Modal open={confirmDelete} onClose={() => setConfirmDelete(false)} title={t("deleteTitle")} size="sm"
        footer={<>
          <Button variant="ghost" onClick={() => setConfirmDelete(false)}>{tr("cancel")}</Button>
          <Button variant="danger" icon="delete" loading={remove.isPending} onClick={() => remove.mutate()}>{t("deleteConfirm")}</Button>
        </>}>
        <p className="text-sm">{t("deleteText", { name: query?.name ?? "" })}</p>
      </Modal>
    </div>
  );
}

function names(locale: string, type: "region" | "language") {
  try {
    const n = new Intl.DisplayNames([locale], { type });
    return (code: string) => n.of(code) ?? code;
  } catch {
    return (code: string) => code;
  }
}

function Group({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[13px] font-medium text-text-2">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </div>
  );
}

function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-2.5">
      <dt className="text-muted">{label}</dt>
      <dd className="text-end font-semibold tabular-nums">{children}</dd>
    </div>
  );
}

/** Words as removable chips; Enter or comma adds the typed word. */
function TagInput({ values, onChange, placeholder, disabled, normalize, display }: {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  normalize?: (value: string) => string | null;
  display?: (value: string) => string;
}) {
  const t = useTranslations("radar.setup");
  const [text, setText] = useState("");
  const add = () => {
    const parts = text.split(/[,،\n]/).map((p) => (normalize ? normalize(p) : p.replace(/\s+/g, " ").trim())).filter((p): p is string => !!p);
    const next = [...values];
    parts.forEach((p) => !next.includes(p) && next.push(p));
    if (parts.length) onChange(next.slice(0, 40));
    setText("");
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === "," || e.key === "،") { e.preventDefault(); add(); }
    else if (e.key === "Backspace" && !text && values.length) onChange(values.slice(0, -1));
  };
  return (
    <div className={cx("flex min-h-10 flex-wrap items-center gap-1.5 rounded-xl border border-line bg-white/70 px-2 py-1.5 transition focus-within:border-black/30 focus-within:bg-white focus-within:ring-4 focus-within:ring-black/5", disabled && "opacity-60")}>
      {values.map((v) => (
        <span key={v} className="inline-flex items-center gap-1 rounded-full bg-fill-2 py-0.5 ps-2.5 pe-1 text-[13px] font-medium">
          <span className="bidi">{display ? display(v) : v}</span>
          {!disabled && (
            <button type="button" aria-label={t("removeWord", { word: v })} onClick={() => onChange(values.filter((x) => x !== v))}
              className="flex h-5 w-5 items-center justify-center rounded-full text-text-2 hover:bg-black/10"><Icon name="close" size={12} /></button>
          )}
        </span>
      ))}
      {!disabled && (
        <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} onBlur={add} placeholder={values.length ? "" : placeholder}
          className="h-7 min-w-[8rem] flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-faint" />
      )}
    </div>
  );
}
