"use client";
/**
 * Brand health: the completeness of a brand kit (score ring + gaps grouped, each with a fix hint), from
 * GET /brand-kits/{id}/completeness, live from the unsaved form (POST /brand-kits/completeness/preview, debounced
 * 400 ms) or a report already in hand (import preview). "Fix" jumps to the field; "Suggest with AI" asks
 * POST /brand-kits/{id}/suggest and shows the answers to accept one by one.
 *
 *   <BrandHealth kitId={kit?.id} values={form} onFix={(field, tab) => …} onAccept={(values) => setForm(…)} />
 *   <HealthSummary report={draft.completeness} />          // read-only (import preview)
 */
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Icon } from "@/components/icon";
import { Badge, Button, Spinner, cx, toast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

export type Check = {
  key: string; group: string; status: "ok" | "weak" | "missing"; weight: number; field: string; tab: string; ai: boolean;
  detail: Record<string, unknown>;
};
export type Completeness = { score: number; checks: Check[]; missing: number; weak: number };
export type Suggestions = Record<string, string | Record<string, string>>;

const GROUP_ICONS: Record<string, string> = {
  identity: "storefront", colours: "palette", fonts: "text_fields", voice: "campaign", rules: "verified_user", visual: "photo_camera",
};
const GROUPS = ["identity", "colours", "fonts", "voice", "rules", "visual"];

/** Load font files into the page (FontFace) so previews draw with them; returns true once they are ready. */
const loaded = new Map<string, Promise<void>>();
export function useFontFaces(faces: { family: string; url: string; weight?: number; style?: string }[]) {
  const key = faces.map((f) => `${f.family}|${f.url}`).join(",");
  const [ready, setReady] = useState(0);
  useEffect(() => {
    if (!faces.length || typeof FontFace === "undefined") return;
    let alive = true;
    Promise.allSettled(faces.map((f) => {
      const id = `${f.family}|${f.url}`;
      if (!loaded.has(id)) {
        const face = new FontFace(f.family, `url(${f.url})`, { weight: String(f.weight ?? 400), style: f.style ?? "normal" });
        loaded.set(id, face.load().then((ff) => { document.fonts.add(ff); }));
      }
      return loaded.get(id)!;
    })).then(() => alive && setReady((n) => n + 1));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return ready;
}

export function ScoreRing({ score, size = 76 }: { score: number; size?: number }) {
  const stroke = 7;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const tone = score >= 85 ? "var(--ok)" : score >= 60 ? "var(--accent)" : "var(--warn)";
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--track)" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={tone} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - Math.max(0, Math.min(100, score)) / 100)} className="transition-[stroke-dashoffset] duration-700" />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-[19px] font-bold tabular-nums" dir="ltr">{score}<span className="text-[11px] font-semibold text-muted">%</span></span>
    </div>
  );
}

function level(score: number) {
  return score >= 85 ? "great" : score >= 60 ? "good" : "low";
}

const STATUS_ICON = { ok: "check_circle", weak: "warning", missing: "error" } as const;
const STATUS_TONE = { ok: "text-ok", weak: "text-warn", missing: "text-bad" } as const;

function CheckRow({ check, onFix, onSuggest, suggesting }: {
  check: Check; onFix?: (c: Check) => void; onSuggest?: (c: Check) => void; suggesting?: boolean;
}) {
  const t = useTranslations("brandkit");
  const ratio = typeof check.detail.ratio === "number" ? ` · ${check.detail.ratio}:1` : "";
  return (
    <li className="flex items-start gap-2.5 py-2">
      <Icon name={STATUS_ICON[check.status]} size={17} className={cx("mt-0.5 shrink-0", STATUS_TONE[check.status])} />
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-semibold leading-tight">{t(`checks.${check.key}.label`)}<span className="font-normal text-muted" dir="ltr">{ratio}</span></div>
        {check.status !== "ok" && <p className="mt-0.5 text-xs leading-snug text-muted">{t(`checks.${check.key}.hint`)}</p>}
      </div>
      {check.status !== "ok" && (onFix || onSuggest) && (
        <div className="flex shrink-0 items-center gap-1">
          {check.ai && onSuggest && (
            <button type="button" onClick={() => onSuggest(check)} disabled={suggesting} title={t("health.suggest")} aria-label={t("health.suggest")}
              className="flex h-7 w-7 items-center justify-center rounded-full text-accent-deep transition hover:bg-accent-soft disabled:opacity-50">
              <Icon name="wand_stars" size={15} />
            </button>
          )}
          {onFix && <Button size="sm" variant="ghost" onClick={() => onFix(check)}>{t("health.fix")}</Button>}
        </div>
      )}
    </li>
  );
}

/** Score, level and the gaps of a report (no actions unless given). */
export function HealthSummary({ report, onFix, onSuggest, suggesting, compact = false, title }: {
  report: Completeness; onFix?: (c: Check) => void; onSuggest?: (c: Check) => void; suggesting?: boolean; compact?: boolean; title?: string;
}) {
  const t = useTranslations("brandkit.health");
  const [showDone, setShowDone] = useState(false);
  const gaps = report.checks.filter((c) => c.status !== "ok");
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <ScoreRing score={report.score} size={compact ? 64 : 76} />
        <div className="min-w-0">
          <div className="text-[15px] font-semibold tracking-tight">{title ?? t("title")}</div>
          <div className="text-xs font-semibold" style={{ color: report.score >= 85 ? "var(--ok)" : report.score >= 60 ? "var(--accent-deep)" : "var(--warn)" }}>{t(`levels.${level(report.score)}`)}</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {report.missing > 0 && <Badge tone="bad">{t("missing", { count: report.missing })}</Badge>}
            {report.weak > 0 && <Badge tone="warn">{t("weak", { count: report.weak })}</Badge>}
            {!gaps.length && <Badge tone="ok">{t("allGood")}</Badge>}
          </div>
        </div>
      </div>
      {GROUPS.map((group) => {
        const items = report.checks.filter((c) => c.group === group && (showDone || c.status !== "ok"));
        if (!items.length) return null;
        return (
          <div key={group}>
            <div className="flex items-center gap-1.5 text-[11.5px] font-semibold uppercase tracking-wide text-muted">
              <Icon name={GROUP_ICONS[group]} size={13} />{t(`groups.${group}`)}
            </div>
            <ul className="divide-y divide-line">
              {items.map((c) => <CheckRow key={c.key} check={c} onFix={onFix} onSuggest={onSuggest} suggesting={suggesting} />)}
            </ul>
          </div>
        );
      })}
      <button type="button" className="self-start text-xs font-medium text-muted underline-offset-2 hover:underline" onClick={() => setShowDone((v) => !v)}>
        <Icon name={showDone ? "expand_less" : "expand_more"} size={14} className="align-middle" /> {t("status.ok")} · {report.checks.length - gaps.length}
      </button>
    </div>
  );
}

function suggestionText(value: Suggestions[string]) {
  return typeof value === "string" ? value : Object.entries(value).filter(([k]) => k !== "mode").map(([k, v]) => `${k}: ${v}`).join(" · ");
}

/** ``value`` once it has not changed for ``ms`` milliseconds. */
export function useDebounced<T>(value: T, ms = 400): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

/** The panel of the kit editor: health of the saved kit, or live from the unsaved ``values`` (recalculated while
 * the person edits), fixes, and AI suggestions to accept into the form (saved kits only). */
export function BrandHealth({ kitId, values, version, onFix, onAccept, canEdit = true }: {
  kitId?: number | null; values?: Record<string, unknown>; version?: unknown; onFix: (field: string, tab: string) => void;
  onAccept: (values: Suggestions) => void; canEdit?: boolean;
}) {
  const t = useTranslations("brandkit");
  const tb = useTranslations("ai.brand");
  const body = useDebounced(values ? JSON.stringify(values) : null, 400);
  const health = useQuery({
    queryKey: body !== null ? ["brand-kits", kitId ?? "new", "completeness-preview", body] : ["brand-kits", kitId, "completeness", version],
    queryFn: () => body !== null
      ? api.post<Completeness>("/brand-kits/completeness/preview", { brand_kit_id: kitId ?? null, values: JSON.parse(body) })
      : api.get<Completeness>(`/brand-kits/${kitId}/completeness`),
    enabled: body !== null || !!kitId,
    placeholderData: keepPreviousData,
  });
  const [suggestions, setSuggestions] = useState<Suggestions>({});
  const suggest = useMutation({
    mutationFn: (fields: string[]) => api.post<{ suggestions: Suggestions }>(`/brand-kits/${kitId}/suggest`, { fields }),
    onSuccess: (r) => {
      if (!Object.keys(r.suggestions).length) toast.info(t("health.noSuggestions"));
      setSuggestions((s) => ({ ...s, ...r.suggestions }));
    },
    onError: (err) => toast.error(err instanceof ApiError && err.code === "no_ai_provider" ? tb("aiNoProvider") : err instanceof ApiError ? err.message : String(err)),
  });
  const accept = (keys: string[]) => {
    onAccept(Object.fromEntries(keys.map((k) => [k, suggestions[k]])));
    setSuggestions((s) => Object.fromEntries(Object.entries(s).filter(([k]) => !keys.includes(k))));
    toast.success(t("health.accepted"));
  };
  if (health.isLoading || !health.data) return <div className="py-6 text-center"><Spinner /></div>;
  const aiGaps = health.data.checks.filter((c) => c.ai).map((c) => c.field);
  const pending = Object.keys(suggestions);
  return (
    <div className="flex flex-col gap-3">
      <HealthSummary report={health.data} compact
        onFix={(c) => onFix(c.field, c.tab)}
        onSuggest={canEdit && kitId ? (c) => suggest.mutate([c.field]) : undefined} suggesting={suggest.isPending} />
      {values && (
        <p className="flex items-center gap-1.5 text-[11.5px] text-muted" aria-live="polite">
          <Icon name={health.isFetching ? "autorenew" : "bolt"} size={13} className={health.isFetching ? "animate-spin" : undefined} />
          {t("health.live")}
        </p>
      )}
      {canEdit && kitId && aiGaps.length > 1 && (
        <Button size="sm" icon="auto_awesome" loading={suggest.isPending} onClick={() => suggest.mutate(aiGaps)}>{t("health.suggestAll")}</Button>
      )}
      {pending.length > 0 && (
        <div className="rounded-2xl bg-[linear-gradient(135deg,rgba(255,61,139,.07),rgba(124,58,237,.07))] p-3 ring-1 ring-[rgba(255,61,139,.22)]">
          <div className="mb-2 flex items-center gap-2">
            <Icon name="wand_stars" size={15} className="text-accent-deep" />
            <span className="text-[13px] font-semibold">{t("health.suggestionsTitle")}</span>
            <Button size="sm" variant="ghost" className="ms-auto" onClick={() => accept(pending)}>{t("health.acceptAll")}</Button>
          </div>
          <ul className="flex flex-col gap-2">
            {pending.map((key) => (
              <li key={key} className="rounded-xl bg-white/80 p-2.5 ring-1 ring-line">
                <div className="mb-1 text-[11.5px] font-semibold text-muted">{t(`checks.${key}.label`)}</div>
                <p className="bidi whitespace-pre-line text-[13px] leading-relaxed">{suggestionText(suggestions[key])}</p>
                <div className="mt-1.5 flex justify-end gap-1">
                  <Button size="sm" variant="ghost" onClick={() => setSuggestions((s) => Object.fromEntries(Object.entries(s).filter(([k]) => k !== key)))}>{t("health.dismiss")}</Button>
                  <Button size="sm" variant="primary" icon="check" onClick={() => accept([key])}>{t("health.accept")}</Button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
