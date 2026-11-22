"use client";
/**
 * Import a design system made in Claude (.zip), a brand book (.md), tokens (.json) or tokens.css into a brand kit.
 * Step 1: drop the file → POST /brand-kits/import/preview (nothing saved). Step 2: review what was found — each
 * value with a checkbox and its source, colours by role, fonts with live EN + AR previews, logos (main / dark),
 * brand images — next to the brand health it would give; then POST /brand-kits/import/commit.
 *
 *   <ImportDialog kits={kits} kitId={kit?.id} onClose={…} onDone={(kit) => openKit(kit)} />
 */
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { type ReactNode, useMemo, useRef, useState } from "react";
import { CameraPanel } from "@/components/camera-panel";
import { Icon } from "@/components/icon";
import { Badge, Button, Modal, Select, Spinner, Switch, Textarea, Input, cx, toast } from "@/components/ui";
import type { Shot } from "@/lib/ai";
import { ApiError, api } from "@/lib/api";
import { contrast } from "@/lib/palette";
import { type Completeness, HealthSummary, useFontFaces } from "./health";

type Source = "tokens" | "readme" | "ai" | "heuristic";
type DraftField = { value: unknown; source: Source; token?: string | null };
type Colour = { name: string; value: string; dark: string | null; usage: string };
type FontFile = { key: string; name: string; family: string; weight: number; style: string; role: "heading" | "body" | "other"; size: number; has_arabic: boolean | null; loadable: boolean; format: string };
type Logo = { key: string; name: string; variant: "light" | "dark" | "mono" | "composite"; mimetype: string; size: number; width: number | null; height: number | null };
type Picture = { key: string; name: string; group: string; size: number; selected: boolean };
export type ImportDraft = {
  import_id: string; filename: string; kind: string; brand_kit_id: number | null; name: string;
  fields: Record<string, DraftField>; current: Record<string, unknown> | null; colours: Colour[];
  fonts: FontFile[]; logos: Logo[]; logo_primary: string | null; logo_dark: string | null; imagery: Picture[];
  docs: string[]; components: number; ignored: number; tokens: { colours: number; spacing: number; radius: number; shadow: number };
  book_source: Source | null; warnings: { code: string; message: string; files?: string[] }[]; completeness: Completeness; arabic_needed: boolean;
  missing_fonts?: string[]; missing_assets?: { group: string; name: string }[];
};
export type ImportedKit = { id: number; name: string };
type KitRef = { id: number; name: string };

const COLOR_ROLES = ["color_primary", "color_secondary", "color_accent", "color_text", "color_background"] as const;
const IDENTITY = ["name", "tagline", "description", "industry", "audience"];
const VOICE = ["tone", "personality", "language_style", "emoji_style", "cta", "guidelines", "banned_words", "hashtags", "sample_posts"];
const VISUAL = ["visual_style", "visual_rules", "photo_style"];
const LONG = new Set(["description", "audience", "tone", "guidelines", "banned_words", "sample_posts", "visual_style", "visual_rules"]);
const LABELS: Record<string, string> = {
  name: "name", tagline: "tagline", description: "description", industry: "industry", audience: "audience", tone: "tone",
  personality: "personality", language_style: "languageStyle", emoji_style: "emojiStyle", cta: "cta", guidelines: "guidelines",
  banned_words: "bannedWords", hashtags: "hashtags", sample_posts: "samplePosts", visual_style: "visualStyle",
  visual_rules: "guard.visualRules", photo_style: "guard.photoStyle", color_primary: "colorPrimary", color_secondary: "colorSecondary",
  color_accent: "colorAccent", color_text: "colorText", color_background: "colorBackground", font_heading: "fontHeading", font_family: "fontBody",
};
const SOURCE_TONE: Record<Source, string> = {
  tokens: "bg-[rgba(10,132,255,.1)] text-[#0a5cc2]", readme: "bg-fill-2 text-text-2",
  ai: "bg-accent-soft text-accent-deep", heuristic: "bg-warn-bg text-warn",
};
const isHex = (v: unknown): v is string => typeof v === "string" && /^#[0-9a-f]{6}$/i.test(v);
const fileUrl = (id: string, key: string) => `/api/brand-kits/import/${id}/file?key=${encodeURIComponent(key)}`;
const familyOf = (css: unknown) => (typeof css === "string" ? css.split(",")[0].replace(/['"]/g, "").trim() : "");
const empty = (v: unknown) => v === null || v === undefined || v === "" || (typeof v === "object" && !Object.keys(v as object).length);

function SourceBadge({ source }: { source: Source }) {
  const t = useTranslations("brandkit.import.sources");
  return <span className={cx("inline-flex shrink-0 items-center rounded-full px-1.5 py-px text-[10.5px] font-semibold", SOURCE_TONE[source])}>{t(source)}</span>;
}

function Section({ icon, title, count, actions, children }: { icon: string; title: string; count?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-2xl bg-white/60 p-4 ring-1 ring-line">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-ink text-white"><Icon name={icon} size={15} /></span>
        <h4 className="text-[14px] font-semibold tracking-tight">{title}</h4>
        {count}
        {actions && <div className="ms-auto flex items-center gap-1">{actions}</div>}
      </div>
      <div className="flex flex-col gap-1">{children}</div>
    </section>
  );
}

function Check({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" role="checkbox" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)}
      className={cx("mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-md ring-1 transition",
        checked ? "bg-ink text-white ring-ink" : "bg-white ring-line-strong hover:ring-ink")}>
      {checked && <Icon name="check" size={13} />}
    </button>
  );
}

/* ------------------------------------------------------------------------------------------------ dialog */

export function ImportDialog({ kits, kitId, onClose, onDone }: {
  kits: KitRef[]; kitId?: number | null; onClose: () => void; onDone: (kit: ImportedKit) => void;
}) {
  const t = useTranslations("brandkit.import");
  const tb = useTranslations("ai.brand");
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [draft, setDraft] = useState<ImportDraft | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [apply, setApply] = useState<Set<string>>(new Set());
  const [logo, setLogo] = useState<string | null>(null);
  const [logoDark, setLogoDark] = useState<string | null>(null);
  const [keepLogos, setKeepLogos] = useState<Set<string>>(new Set());
  const [fonts, setFonts] = useState<Set<string>>(new Set());
  const [imagery, setImagery] = useState<Set<string>>(new Set());
  const [target, setTarget] = useState<number | "new">(kitId ?? "new");
  const [makeDefault, setMakeDefault] = useState(!kits.length);

  const start = (d: ImportDraft) => {
    setDraft(d);
    const v = Object.fromEntries(Object.entries(d.fields).map(([k, f]) => [k, f.value]));
    setValues(v);
    // updating a kit: tick what is new or different; a new kit: tick everything found
    setApply(new Set(Object.keys(d.fields).filter((k) => !d.current || empty(d.current[k]) || JSON.stringify(d.current[k]) !== JSON.stringify(v[k]))));
    setLogo(d.logo_primary);
    setLogoDark(d.logo_dark);
    // an SVG main logo: keep its raster (PNG…) variants too, they stay available in the media library
    const primary = d.logos.find((l) => l.key === d.logo_primary);
    setKeepLogos(new Set(primary?.mimetype === "image/svg+xml"
      ? d.logos.filter((l) => l.mimetype !== "image/svg+xml" && l.key !== d.logo_primary && l.key !== d.logo_dark).map((l) => l.key)
      : []));
    setFonts(new Set(d.fonts.filter((f) => f.loadable && f.role !== "other").map((f) => f.key)));
    setImagery(new Set(d.imagery.filter((i) => i.selected).map((i) => i.key)));
  };

  const preview = useMutation({
    mutationFn: (file: File) => api.upload<ImportDraft>("/brand-kits/import/preview", file, "file", kitId ? { brand_kit_id: String(kitId) } : undefined),
    onSuccess: start,
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });

  const commit = useMutation({
    mutationFn: () => {
      const fields = Object.fromEntries([...apply].filter((k) => k in values).map((k) => [k, values[k]]));
      return api.post<{ kit: ImportedKit }>("/brand-kits/import/commit", {
        import_id: draft!.import_id, brand_kit_id: target === "new" ? null : target, fields, make_default: makeDefault,
        assets: { logo, logo_dark: logoDark, logos: [...keepLogos].filter((k) => k !== logo && k !== logoDark), imagery: [...imagery], fonts: [...fonts] },
      });
    },
    onSuccess: (r) => { toast.success(t("done")); onDone(r.kit); },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });

  const pick = (file: File | undefined) => { if (file) preview.mutate(file); };
  const toggle = (set: Set<string>, key: string, on: boolean) => { const next = new Set(set); if (on) next.add(key); else next.delete(key); return next; };
  const setApplied = (key: string, on: boolean) => setApply((s) => toggle(s, key, on));
  const setValue = (key: string, value: unknown) => { setValues((v) => ({ ...v, [key]: value })); setApplied(key, true); };

  // live font previews: the uploaded font files, under their own family names
  const faces = useMemo(() => (draft?.fonts ?? []).filter((f) => f.loadable).map((f) => ({ family: `bk-${f.family}`, url: fileUrl(draft!.import_id, f.key), weight: f.weight, style: f.style })), [draft]);
  useFontFaces(faces);
  const fontStack = (css: unknown) => {
    const family = familyOf(css);
    return draft?.fonts.some((f) => f.family.toLowerCase() === family.toLowerCase() && f.loadable) ? `"bk-${draft.fonts.find((f) => f.family.toLowerCase() === family.toLowerCase())!.family}", ${String(css)}` : String(css ?? "inherit");
  };

  const title = (
    <span className="inline-flex items-center gap-2"><Icon name="data_object" size={18} className="text-accent-deep" />{t("title")}</span>
  );

  /* -------------------------------------------------------------------------------- step 1: choose a file */
  if (!draft) {
    return (
      <Modal open onClose={onClose} size="lg" title={title}>
        <p className="mb-4 text-sm text-text-2">{t("subtitle")}</p>
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0]); }}
          className={cx("flex flex-col items-center justify-center gap-3 rounded-3xl border-2 border-dashed px-6 py-12 text-center transition",
            dragging ? "border-accent bg-accent-soft" : "border-line-strong bg-white/50")}
        >
          {preview.isPending ? (
            <>
              <Spinner size={30} />
              <div className="text-[15px] font-semibold">{t("reading")}</div>
              <p className="max-w-sm text-xs text-muted">{t("readingHint")}</p>
            </>
          ) : (
            <>
              <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[linear-gradient(135deg,#ff5c9d,#b3124f)] text-white shadow-[0_10px_24px_-10px_rgba(224,36,111,.75)]">
                <Icon name="upload" size={26} />
              </span>
              <div className="text-[15px] font-semibold">{t("drop")}</div>
              <p className="max-w-md text-xs text-muted">{t("dropHint")}</p>
              <Button variant="primary" icon="upload" onClick={() => fileRef.current?.click()}>{t("choose")}</Button>
            </>
          )}
          <input ref={fileRef} type="file" hidden accept=".zip,.md,.markdown,.txt,.json,.css,application/zip,text/markdown,application/json,text/css"
            onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
        </div>
      </Modal>
    );
  }

  /* -------------------------------------------------------------------------------- step 2: review */
  const d = draft;
  const fieldRow = (key: string) => {
    const field = d.fields[key];
    if (!field) return null;
    const value = values[key];
    const current = d.current?.[key];
    const label = tb(LABELS[key] ?? key);
    const on = apply.has(key);
    let editor: ReactNode;
    if (key === "language_style" || key === "emoji_style") {
      editor = <span className="text-sm font-medium">{tb(`${key === "language_style" ? "languageStyles" : "emojiStyles"}.${String(value)}`)}</span>;
    } else if (key === "photo_style") {
      editor = <CameraPanel kind="all" value={value as Shot} onChange={(shot) => setValue(key, shot)} label={t("photoStyle")} />;
    } else if (LONG.has(key)) {
      editor = <Textarea rows={Math.min(6, Math.max(2, String(value ?? "").split("\n").length + 1))} className="bidi text-[13px]" value={String(value ?? "")} onChange={(e) => setValue(key, e.target.value)} />;
    } else {
      editor = <Input className="bidi h-9 text-[13px]" value={String(value ?? "")} onChange={(e) => setValue(key, e.target.value)} />;
    }
    return (
      <div key={key} className={cx("flex gap-3 rounded-xl px-2 py-2 transition", on ? "" : "opacity-55")}>
        <Check checked={on} onChange={(v) => setApplied(key, v)} label={label} />
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-1.5">
            <span className="text-[12.5px] font-semibold text-text-2">{label}</span>
            <SourceBadge source={field.source} />
          </div>
          {editor}
          {d.current && !empty(current) && JSON.stringify(current) !== JSON.stringify(value) && typeof current === "string" && (
            <p className="bidi mt-1 line-clamp-1 text-[11.5px] text-muted">{t("current", { value: current })}</p>
          )}
        </div>
      </div>
    );
  };
  const present = (keys: string[]) => keys.filter((k) => d.fields[k]);
  const bulk = (keys: string[]) => (
    <>
      <Button size="sm" variant="ghost" onClick={() => setApply((s) => new Set([...s, ...keys]))}>{t("selectAll")}</Button>
      <Button size="sm" variant="ghost" onClick={() => setApply((s) => new Set([...s].filter((k) => !keys.includes(k))))}>{t("selectNone")}</Button>
    </>
  );
  const primary = isHex(values.color_primary) ? values.color_primary : null;
  const onPrimary = isHex(values.color_text) ? values.color_text : null;
  const ratio = primary && onPrimary ? contrast(onPrimary, primary) : null;
  const headingCss = values.font_heading ?? values.font_family;
  const bodyCss = values.font_family ?? values.font_heading;
  const nothing = !Object.keys(d.fields).length && !d.logos.length && !d.fonts.length;
  const selectedCount = apply.size + (logo ? 1 : 0) + (logoDark ? 1 : 0) + fonts.size + imagery.size + keepLogos.size;

  return (
    <Modal open onClose={onClose} size="xl" title={title}
      footer={<>
        <Button variant="ghost" icon="undo" className="me-auto" onClick={() => setDraft(null)}>{t("back")}</Button>
        <span className="text-xs text-muted">{t("selected", { count: selectedCount })}</span>
        <Button onClick={onClose}>{tb("cancel")}</Button>
        <Button variant="primary" icon="check" loading={commit.isPending} disabled={nothing} onClick={() => commit.mutate()}>{t("submit")}</Button>
      </>}>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex min-w-0 flex-col gap-4">
          {/* what the file holds */}
          <div className="flex flex-wrap items-center gap-2 rounded-2xl bg-ink px-4 py-3 text-white">
            <Icon name={d.kind === "zip" ? "inventory_2" : "description"} size={20} />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold" dir="ltr">{d.filename}</div>
              <div className="text-xs text-white/70">{t("summary", { colours: d.tokens.colours, fonts: d.fonts.length, logos: d.logos.length, images: d.imagery.length, docs: d.docs.length })}</div>
            </div>
            {d.book_source && (
              <span className="inline-flex items-center gap-1 rounded-full bg-white/15 px-2.5 py-1 text-[11.5px] font-semibold">
                <Icon name={d.book_source === "ai" ? "auto_awesome" : "menu_book"} size={13} />{t(d.book_source === "ai" ? "bookAi" : "bookHeadings")}
              </span>
            )}
          </div>

          {nothing && <p className="rounded-2xl bg-warn-bg p-4 text-sm text-warn">{t("nothing")}</p>}

          {d.warnings.length > 0 && (
            <div className="rounded-2xl bg-warn-bg p-3">
              <div className="mb-1.5 flex items-center gap-1.5 text-[13px] font-semibold text-warn"><Icon name="warning" size={15} />{t("warnings")}</div>
              <ul className="flex flex-col gap-1 ps-5 text-[12.5px] text-text-2">
                {d.warnings.map((w, i) => (
                  <li key={i} className="list-disc">
                    {w.message}
                    {!!w.files?.length && (
                      <span className="mt-1 flex flex-wrap gap-1" aria-label={t("missingFiles")}>
                        {w.files.map((f) => (
                          <code key={f} dir="ltr" className="rounded-md bg-white/80 px-1.5 py-px text-[11px] text-text-2 ring-1 ring-line">{f}</code>
                        ))}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {present(IDENTITY).length > 0 && (
            <Section icon="storefront" title={t("sections.identity")} actions={bulk(present(IDENTITY))}>{present(IDENTITY).map(fieldRow)}</Section>
          )}

          {present([...COLOR_ROLES]).length > 0 && (
            <Section icon="palette" title={t("sections.colours")} actions={bulk(present([...COLOR_ROLES]))}>
              <div className="mb-2 flex overflow-hidden rounded-xl ring-1 ring-line" dir="ltr">
                {COLOR_ROLES.filter((k) => isHex(values[k])).map((k) => <span key={k} title={String(values[k])} className="h-10 flex-1" style={{ background: String(values[k]) }} />)}
              </div>
              {COLOR_ROLES.filter((k) => d.fields[k]).map((key) => {
                const on = apply.has(key);
                const value = String(values[key] ?? "");
                const field = d.fields[key];
                return (
                  <div key={key} className={cx("flex items-center gap-3 rounded-xl px-2 py-1.5", !on && "opacity-55")}>
                    <Check checked={on} onChange={(v) => setApplied(key, v)} label={tb(LABELS[key])} />
                    <span className="h-8 w-8 shrink-0 rounded-lg ring-1 ring-black/10" style={{ background: value }} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-[12.5px] font-semibold text-text-2">{tb(LABELS[key])}</span>
                        <SourceBadge source={field.source} />
                      </div>
                      {field.token && <div className="truncate text-[11px] text-muted" dir="ltr">{t("roleToken", { name: field.token })}</div>}
                    </div>
                    <div className="w-[200px] shrink-0"><Select className="h-9 font-mono text-[12px]" dir="ltr" value={value} onChange={(e) => setValue(key, e.target.value)} aria-label={tb(LABELS[key])}>
                      {!d.colours.some((c) => c.value === value) && <option value={value}>{value}</option>}
                      {d.colours.map((c) => <option key={c.name} value={c.value}>{c.value} · {c.name}</option>)}
                    </Select></div>
                  </div>
                );
              })}
              {ratio !== null && (
                <div className="mt-1 flex items-center gap-2 ps-2">
                  <span className="rounded-lg px-2.5 py-1 text-[13px] font-bold" style={{ background: primary!, color: onPrimary! }}>Aa أب</span>
                  <Badge tone={ratio >= 4.5 ? "ok" : "warn"}>{t("contrast", { ratio: ratio.toFixed(1) })}</Badge>
                </div>
              )}
            </Section>
          )}

          {(d.fields.font_heading || d.fields.font_family || d.fonts.length > 0) && (
            <Section icon="text_fields" title={t("sections.fonts")}>
              <div className="grid gap-2 sm:grid-cols-2">
                {(["font_heading", "font_family"] as const).filter((k) => d.fields[k]).map((key) => {
                  const on = apply.has(key);
                  const css = key === "font_heading" ? headingCss : bodyCss;
                  return (
                    <div key={key} className={cx("flex gap-3 rounded-xl bg-white/70 p-3 ring-1 ring-line", !on && "opacity-55")}>
                      <Check checked={on} onChange={(v) => setApplied(key, v)} label={tb(LABELS[key])} />
                      <div className="min-w-0 flex-1">
                        <div className="mb-1 flex flex-wrap items-center gap-1.5">
                          <span className="text-[12.5px] font-semibold text-text-2">{tb(LABELS[key])}</span>
                          <SourceBadge source={d.fields[key].source} />
                        </div>
                        <div className="truncate text-xs text-muted" dir="ltr">{familyOf(values[key])}</div>
                        <p className={cx("mt-2 truncate leading-snug", key === "font_heading" ? "text-[22px] font-medium" : "text-[15px]")} dir="ltr" style={{ fontFamily: fontStack(css) }}>{t("sampleEn")}</p>
                        <p className={cx("truncate leading-snug", key === "font_heading" ? "text-[22px] font-medium" : "text-[15px]")} dir="rtl" style={{ fontFamily: fontStack(css) }}>{t("sampleAr")}</p>
                      </div>
                    </div>
                  );
                })}
              </div>
              {d.fonts.length > 0 && (
                <>
                  <div className="mt-2 flex items-center gap-2">
                    <span className="text-[12.5px] font-semibold text-text-2">{t("fontFiles")}</span>
                    <span className="text-xs text-muted">{fonts.size}/{d.fonts.filter((f) => f.loadable).length}</span>
                    <span className="ms-auto flex">
                      <Button size="sm" variant="ghost" onClick={() => setFonts(new Set(d.fonts.filter((f) => f.loadable).map((f) => f.key)))}>{t("selectAll")}</Button>
                      <Button size="sm" variant="ghost" onClick={() => setFonts(new Set())}>{t("selectNone")}</Button>
                    </span>
                  </div>
                  <ul className="grid gap-1.5 sm:grid-cols-2">
                    {d.fonts.map((f) => (
                      <li key={f.key} className={cx("flex items-center gap-2 rounded-xl bg-white/70 px-2.5 py-2 ring-1 ring-line", !fonts.has(f.key) && "opacity-60")}>
                        <Check checked={fonts.has(f.key)} onChange={(v) => f.loadable && setFonts((s) => toggle(s, f.key, v))} label={f.name} />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[13px]" dir="ltr" style={{ fontFamily: f.loadable ? `"bk-${f.family}"` : undefined, fontWeight: f.weight, fontStyle: f.style }}>{f.family} · أبجد</div>
                          <div className="flex flex-wrap items-center gap-1 text-[11px] text-muted">
                            <span>{t("weight", { weight: f.weight })}</span>·<span className="uppercase">{f.format}</span>
                            <Badge tone={f.role === "other" ? "neutral" : "ink"} className="!py-0">{t(`fontRoles.${f.role}`)}</Badge>
                            {!f.loadable ? <Badge tone="bad" className="!py-0">{t("unreadable")}</Badge>
                              : f.has_arabic ? <Badge tone="ok" className="!py-0">{t("arabicYes")}</Badge>
                              : <Badge tone={d.arabic_needed ? "warn" : "neutral"} className="!py-0">{t("arabicNo")}</Badge>}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </Section>
          )}

          <Section icon="branding" title={t("sections.logos")}>
            {!d.logos.length ? <p className="text-sm text-muted">{t("noLogo")}</p> : (
              <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
                {d.logos.map((l) => {
                  const darkTile = l.variant === "dark";
                  return (
                    <div key={l.key} className={cx("flex flex-col overflow-hidden rounded-2xl ring-1 transition", logo === l.key || logoDark === l.key ? "ring-2 ring-ink" : "ring-line")}>
                      <div className={cx("flex h-24 items-center justify-center p-3", darkTile ? "bg-[#111]" : "bg-[repeating-conic-gradient(#f4f4f5_0%_25%,#fff_0%_50%)] bg-[length:16px_16px]")}>
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={fileUrl(d.import_id, l.key)} alt={l.name} className="max-h-full max-w-full object-contain" />
                      </div>
                      <div className="flex flex-col gap-1.5 bg-white/80 p-2.5">
                        <div className="flex min-w-0 items-center gap-1">
                          <span className="truncate text-[12px] font-medium" dir="ltr" title={l.name}>{l.name}</span>
                          {l.mimetype === "image/svg+xml" && <span title={t("vectorHint")} className="shrink-0"><Badge tone="ok">SVG</Badge></span>}
                        </div>
                        <span className="text-[11px] text-muted">{t(`variants.${l.variant}`)}</span>
                        <div className="flex flex-wrap gap-1">
                          <button type="button" onClick={() => setLogo(logo === l.key ? null : l.key)} aria-pressed={logo === l.key}
                            className={cx("rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 transition", logo === l.key ? "bg-ink text-white ring-ink" : "ring-line hover:ring-ink")}>
                            {t("logoMain")}
                          </button>
                          <button type="button" onClick={() => setLogoDark(logoDark === l.key ? null : l.key)} aria-pressed={logoDark === l.key}
                            className={cx("inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 transition", logoDark === l.key ? "bg-ink text-white ring-ink" : "ring-line hover:ring-ink")}>
                            <Icon name="dark_mode" size={11} />{t("logoDark")}
                          </button>
                        </div>
                        {logo !== l.key && logoDark !== l.key && (
                          <label className="flex items-center gap-1.5 text-[11px] text-muted">
                            <Check checked={keepLogos.has(l.key)} onChange={(v) => setKeepLogos((s) => toggle(s, l.key, v))} label={t("logoKeep")} />{t("logoKeep")}
                          </label>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Section>

          {present(VOICE).length > 0 && (
            <Section icon="campaign" title={t("sections.voice")} actions={bulk(present(VOICE))}>{present(VOICE).map(fieldRow)}</Section>
          )}
          {present(VISUAL).length > 0 && (
            <Section icon="photo_camera" title={t("sections.visual")} actions={bulk(present(VISUAL))}>{present(VISUAL).map(fieldRow)}</Section>
          )}

          {d.imagery.length > 0 && (
            <Section icon="photo_library" title={t("sections.imagery")} count={<span className="text-xs text-muted">{imagery.size}/{d.imagery.length}</span>}>
              <p className="mb-1 text-xs text-muted">{t("imageryHint")}</p>
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                {d.imagery.map((img) => {
                  const on = imagery.has(img.key);
                  return (
                    <button key={img.key} type="button" onClick={() => setImagery((s) => toggle(s, img.key, !on))} aria-pressed={on}
                      className={cx("group relative aspect-[4/3] overflow-hidden rounded-xl ring-1 transition", on ? "ring-2 ring-ink" : "ring-line opacity-70 hover:opacity-100")}>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={fileUrl(d.import_id, img.key)} alt={img.name} loading="lazy" className="h-full w-full object-cover" />
                      <span className="absolute inset-x-0 bottom-0 truncate bg-black/55 px-1.5 py-0.5 text-start text-[10.5px] text-white" dir="ltr">{img.group ? `${img.group} / ` : ""}{img.name}</span>
                      <span className={cx("absolute end-1.5 top-1.5 flex h-5 w-5 items-center justify-center rounded-md", on ? "bg-ink text-white" : "bg-white/85 ring-1 ring-line")}>
                        {on && <Icon name="check" size={13} />}
                      </span>
                    </button>
                  );
                })}
              </div>
            </Section>
          )}

          {(d.tokens.spacing + d.tokens.radius + d.tokens.shadow + d.components) > 0 && (
            <p className="flex items-start gap-1.5 px-1 text-xs text-muted"><Icon name="info" size={14} className="mt-px shrink-0" />
              {t("tokensMore", { spacing: d.tokens.spacing, radius: d.tokens.radius, shadow: d.tokens.shadow, components: d.components })}</p>
          )}
        </div>

        {/* target and brand health */}
        <aside className="order-first lg:order-none">
          <div className="sticky top-0 flex flex-col gap-4">
            <div className="rounded-2xl bg-white/70 p-4 ring-1 ring-line">
              <div className="mb-2 text-[13px] font-semibold text-text-2">{t("target")}</div>
              <div role="radiogroup" className="grid gap-1 rounded-2xl bg-track p-1">
                {(["new", "update"] as const).map((mode) => {
                  const active = mode === "new" ? target === "new" : target !== "new";
                  const disabled = mode === "update" && !kits.length;
                  return (
                    <button key={mode} type="button" role="radio" aria-checked={active} disabled={disabled}
                      onClick={() => setTarget(mode === "new" ? "new" : (kitId ?? kits[0]?.id ?? "new"))}
                      className={cx("flex items-center gap-2 rounded-xl px-3 py-2 text-start text-[13px] font-semibold transition disabled:opacity-40",
                        active ? "bg-white text-text shadow-[0_1px_3px_rgba(0,0,0,.12)]" : "text-text-2 hover:text-text")}>
                      <Icon name={mode === "new" ? "add_circle" : "sync_alt"} size={15} />{t(mode === "new" ? "targetNew" : "targetUpdate")}
                    </button>
                  );
                })}
              </div>
              {target !== "new" && (
                <Select className="mt-2" value={String(target)} onChange={(e) => setTarget(Number(e.target.value))} aria-label={t("kit")}>
                  {kits.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
                </Select>
              )}
              <div className="mt-3"><Switch checked={makeDefault} onChange={setMakeDefault} label={t("makeDefault")} /></div>
            </div>
            <div className="rounded-2xl bg-white/70 p-4 ring-1 ring-line">
              <HealthSummary report={d.completeness} compact title={t("healthAfter")} />
            </div>
          </div>
        </aside>
      </div>
    </Modal>
  );
}
