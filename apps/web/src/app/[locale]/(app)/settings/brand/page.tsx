"use client";
/** Settings › Brand kits: the full identity of a brand — logo and colours (read from the logo), heading and text
 * fonts, who the brand is and for whom, personality, language, emojis, rules, banned words and example posts —
 * drafted with AI or filled by hand. Used by AI writing, image/video prompts, templates and production. */
import "@fontsource/ibm-plex-sans-arabic/400.css";
import "@fontsource/ibm-plex-sans-arabic/700.css";
import "@fontsource/cairo/400.css";
import "@fontsource/cairo/700.css";
import "@fontsource/tajawal/400.css";
import "@fontsource/tajawal/700.css";
import "@fontsource/almarai/400.css";
import "@fontsource/almarai/700.css";
import "@fontsource/readex-pro/400.css";
import "@fontsource/readex-pro/700.css";
import "@fontsource/alexandria/400.css";
import "@fontsource/alexandria/700.css";
import "@fontsource/noto-kufi-arabic/400.css";
import "@fontsource/noto-kufi-arabic/700.css";
import "@fontsource/changa/400.css";
import "@fontsource/changa/700.css";
import "@fontsource/noto-naskh-arabic/400.css";
import "@fontsource/noto-naskh-arabic/700.css";
import "@fontsource/amiri/400.css";
import "@fontsource/amiri/700.css";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/icon";
import { Badge, Button, Card, EmptyState, Field, IconButton, Input, Modal, SectionTitle, Segmented, Select, Spinner, Switch, Textarea, cx, toast } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { ApiError, api, mediaUrl } from "@/lib/api";
import { contrast, extractPalette, paletteToKit, readableOn } from "@/lib/palette";
import { useSession } from "@/lib/session";

type BrandKit = {
  id: number; name: string; logo_media_id: number | null; logo_url: string | null; color_primary: string;
  color_secondary: string; color_text: string; font_family: string; tagline: string | null; tone: string | null;
  guidelines: string | null; hashtags: string | null; visual_style: string | null; voice: string | null;
  color_accent: string | null; color_background: string | null; font_heading: string | null; description: string | null;
  industry: string | null; audience: string | null; personality: string | null; language_style: string | null;
  emoji_style: string | null; cta: string | null; banned_words: string | null; sample_posts: string | null;
  website: string | null; is_default: boolean; active: boolean;
};
type Form = Omit<BrandKit, "id" | "logo_url">;
type Draft = Partial<Form>;
type Options = { fonts: string[]; language_styles: string[]; emoji_styles: string[] };
type Palette = { colors: string[]; background: string | null };
type Tab = "basics" | "look" | "type" | "voice" | "rules";

const EMPTY: Form = {
  name: "", logo_media_id: null, color_primary: "#111111", color_secondary: "#71717a", color_text: "#ffffff",
  font_family: "system-ui", tagline: "", tone: "", guidelines: "", hashtags: "", visual_style: "", voice: "",
  color_accent: null, color_background: null, font_heading: null, description: "", industry: "", audience: "",
  personality: "", language_style: null, emoji_style: null, cta: "", banned_words: "", sample_posts: "", website: "",
  is_default: false, active: true,
};
const TEXTS = ["tagline", "tone", "guidelines", "hashtags", "visual_style", "voice", "description", "industry", "audience",
  "personality", "cta", "banned_words", "sample_posts", "website"] as const;
const onError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : String(err));
const isHex = (v: string | null | undefined): v is string => !!v && /^#[0-9a-f]{6}$/i.test(v);

function fontLabel(font: string | null | undefined) {
  if (!font || font === "system-ui") return "System";
  return font.split(",")[0].replace(/'/g, "");
}

/* ------------------------------------------------------------------------------------------------ preview */

function KitPreview({ kit, small = false }: { kit: Form; small?: boolean }) {
  const heading = kit.font_heading || kit.font_family;
  const accent = isHex(kit.color_accent) ? kit.color_accent : kit.color_secondary;
  const logo = kit.logo_media_id ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={mediaUrl(kit.logo_media_id)} alt="" className={cx("rounded-lg bg-white/90 object-contain p-1", small ? "h-9 w-9" : "h-10 w-10")} />
  ) : null;
  if (small) {
    return (
      <div className="flex aspect-[4/5] w-full flex-col items-center justify-center gap-1.5 overflow-hidden rounded-xl p-2 shadow-[var(--shadow)]"
        style={{ background: `linear-gradient(150deg, ${kit.color_primary}, ${kit.color_secondary})`, color: kit.color_text, fontFamily: heading }}>
        {logo ?? <span className="text-xl font-bold">Aa</span>}
        {isHex(kit.color_accent) && <span className="h-1.5 w-8 rounded-full" style={{ background: kit.color_accent }} />}
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="relative flex aspect-[4/5] w-full flex-col justify-between overflow-hidden rounded-2xl p-4 shadow-[var(--shadow)]"
        style={{ background: `linear-gradient(150deg, ${kit.color_primary}, ${kit.color_secondary})`, color: kit.color_text, fontFamily: kit.font_family }}>
        <div className="flex items-center gap-2">
          {logo ?? <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-white/20"><Icon name="branding" size={18} /></span>}
          <span className="truncate text-sm font-bold" style={{ fontFamily: heading }}>{kit.name || "—"}</span>
        </div>
        <div>
          <div className="bidi text-[22px] font-bold leading-snug" style={{ fontFamily: heading }}>{kit.tagline || "Aa"}</div>
          {kit.description && <p className="bidi mt-1.5 line-clamp-2 text-[12px] leading-relaxed opacity-85">{kit.description}</p>}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {kit.cta && (
              <span className="bidi rounded-full px-3 py-1 text-[11.5px] font-bold" style={{ background: accent, color: readableOn(accent) }}>{kit.cta}</span>
            )}
            {kit.hashtags && <span className="bidi truncate text-[11px] opacity-80">{kit.hashtags}</span>}
          </div>
        </div>
      </div>
      <div className="flex overflow-hidden rounded-xl ring-1 ring-line" dir="ltr">
        {[kit.color_primary, kit.color_secondary, kit.color_accent, kit.color_background, kit.color_text].filter(isHex).map((c, i) => (
          <span key={i} title={c} className="h-8 flex-1" style={{ background: c }} />
        ))}
      </div>
    </div>
  );
}

function ColorField({ label, value, onChange, optional }: { label: string; value: string | null; onChange: (v: string | null) => void; optional?: boolean }) {
  return (
    <Field label={label}>
      <div className="flex items-center gap-2">
        <input type="color" value={isHex(value) ? value : "#000000"} onChange={(e) => onChange(e.target.value)}
          className="h-10 w-12 shrink-0 cursor-pointer rounded-xl border border-line bg-white/70 p-1" aria-label={label} />
        <Input dir="ltr" value={value ?? ""} maxLength={9} placeholder={optional ? "—" : undefined}
          onChange={(e) => onChange(e.target.value || (optional ? null : ""))} className="font-mono" />
      </div>
    </Field>
  );
}

function FontField({ label, value, fonts, onChange, sample, allowEmpty }: {
  label: string; value: string | null; fonts: string[]; onChange: (v: string | null) => void; sample: string; allowEmpty?: string;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-2xl bg-white/55 p-3 ring-1 ring-line">
      <Field label={label}>
        <Select value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
          {allowEmpty && <option value="">{allowEmpty}</option>}
          {fonts.map((f) => <option key={f} value={f}>{fontLabel(f)}</option>)}
        </Select>
      </Field>
      <p className="bidi truncate text-[22px] font-bold leading-snug" style={{ fontFamily: value || "inherit" }}>{sample}</p>
      <p className="bidi text-sm text-text-2" style={{ fontFamily: value || "inherit" }}>أبجد هوز · Aa Bb 123</p>
    </div>
  );
}

/* ------------------------------------------------------------------------------------------------ dialog */

function KitDialog({ kit, onClose }: { kit: BrandKit | null; onClose: () => void }) {
  const t = useTranslations("ai.brand");
  const qc = useQueryClient();
  const [form, setForm] = useState<Form>(() => (kit ? { ...EMPTY, ...kit } : EMPTY));
  const [tab, setTab] = useState<Tab>("basics");
  const [aiOpen, setAiOpen] = useState(!kit);
  const [uploading, setUploading] = useState(false);
  const [palette, setPalette] = useState<Palette | null>(null);
  const [colorsTouched, setColorsTouched] = useState(!!kit);
  const [personalityDraft, setPersonalityDraft] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));
  const setColor = (patch: Partial<Form>) => { setColorsTouched(true); set(patch); };
  const options = useQuery({ queryKey: ["brand-kits", "options"], queryFn: () => api.get<Options>("/brand-kits/options"), staleTime: Infinity });
  const fonts = options.data?.fonts ?? [form.font_family];
  const presets = t.raw("personalityPresets") as string[];
  const traits = (form.personality ?? "").split(/[,،]/).map((s) => s.trim()).filter(Boolean);

  // An existing logo: read its colours once so they can be offered again.
  useEffect(() => {
    if (!kit?.logo_media_id) return;
    let alive = true;
    extractPalette(mediaUrl(kit.logo_media_id)).then((p) => { if (alive && p.colors.length) setPalette(p); }).catch(() => undefined);
    return () => { alive = false; };
  }, [kit?.logo_media_id]);

  const applyPalette = (p: Palette) => {
    const k = paletteToKit(p.colors, p.background);
    if (!k) return;
    set({ color_primary: k.primary, color_secondary: k.secondary, color_accent: k.accent, color_text: k.text,
      color_background: k.background });
    setColorsTouched(true);
  };

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { ...form };
      for (const key of TEXTS) body[key] = (form[key] ?? "").trim() || null;
      return kit ? api.patch(`/brand-kits/${kit.id}`, body) : api.post("/brand-kits", body);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["brand-kits"] }); toast.success(t("saved")); onClose(); },
    onError,
  });

  const generate = useMutation({
    mutationFn: () => api.post<Draft>("/brand-kits/generate", {
      name: form.name.trim(), description: (form.description ?? "").trim(), industry: form.industry || null,
      audience: form.audience || null, website: form.website || null, language_style: form.language_style,
      palette: palette?.colors ?? [],
    }),
    onSuccess: (draft) => {
      const clean = Object.fromEntries(Object.entries(draft).filter(([, v]) => v !== null && v !== "")) as Draft;
      set(clean);
      setColorsTouched(true);
      setAiOpen(false);
      setTab("look");
      toast.success(t("aiDone"));
    },
    onError: (err) => toast.error(err instanceof ApiError && err.code === "no_ai_provider" ? t("aiNoProvider") : err instanceof ApiError ? err.message : String(err)),
  });

  const upload = async (file: File) => {
    setUploading(true);
    const colors = extractPalette(file).catch(() => null);
    try {
      const media = await api.upload<{ id: number }>("/media", file);
      set({ logo_media_id: media.id });
      const p = await colors;
      if (p?.colors.length) {
        setPalette(p);
        if (!colorsTouched) { applyPalette(p); toast.success(t("colorsFromLogo")); }
      }
    } catch (err) {
      onError(err);
    } finally {
      setUploading(false);
    }
  };

  const toggleTrait = (word: string) => {
    const next = traits.includes(word) ? traits.filter((w) => w !== word) : [...traits, word];
    set({ personality: next.join("، ") });
  };
  const ratio = isHex(form.color_text) && isHex(form.color_primary) ? contrast(form.color_text, form.color_primary) : null;
  const canGenerate = !!form.name.trim() && !!(form.description ?? "").trim();

  const tabs: { value: Tab; label: string; icon: string }[] = [
    { value: "basics", label: t("tabs.basics"), icon: "storefront" },
    { value: "look", label: t("tabs.look"), icon: "palette" },
    { value: "type", label: t("tabs.type"), icon: "text_fields" },
    { value: "voice", label: t("tabs.voice"), icon: "campaign" },
    { value: "rules", label: t("tabs.rules"), icon: "verified_user" },
  ];

  return (
    <Modal open onClose={onClose} size="xl" title={kit ? kit.name : t("new")}
      footer={<><Button onClick={onClose}>{t("cancel")}</Button><Button variant="primary" loading={save.isPending} disabled={!form.name.trim()} onClick={() => save.mutate()}>{t("save")}</Button></>}>
      <div className="grid gap-6 md:grid-cols-[1fr_240px]">
        <div className="flex min-w-0 flex-col gap-4">
          {/* AI draft */}
          <div className="rounded-2xl bg-[linear-gradient(135deg,rgba(124,58,237,.08),rgba(236,72,153,.08))] p-4 ring-1 ring-[rgba(124,58,237,.22)]">
            <button type="button" className="flex w-full items-center gap-2 text-start" onClick={() => setAiOpen((v) => !v)} aria-expanded={aiOpen}>
              <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-ink text-white"><Icon name="wand_stars" size={17} duo /></span>
              <span className="flex-1">
                <span className="block text-sm font-semibold">{t("aiTitle")}</span>
                <span className="block text-xs text-muted">{t("aiSubtitle")}</span>
              </span>
              <Icon name={aiOpen ? "expand_less" : "expand_more"} size={18} className="text-muted" />
            </button>
            {aiOpen && (
              <div className="mt-3 grid gap-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label={t("name")}><Input value={form.name} onChange={(e) => set({ name: e.target.value })} /></Field>
                  <Field label={t("aiLanguage")}>
                    <Select value={form.language_style ?? ""} onChange={(e) => set({ language_style: e.target.value || null })}>
                      <option value="">{t("languageStyles.auto")}</option>
                      {(options.data?.language_styles ?? []).map((v) => <option key={v} value={v}>{t(`languageStyles.${v}`)}</option>)}
                    </Select>
                  </Field>
                </div>
                <Field label={t("aiDescription")}>
                  <Textarea rows={2} className="bidi" value={form.description ?? ""} placeholder={t("aiDescriptionPlaceholder")} onChange={(e) => set({ description: e.target.value })} />
                </Field>
                <Field label={t("aiAudience")}><Input className="bidi" value={form.audience ?? ""} onChange={(e) => set({ audience: e.target.value })} /></Field>
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="primary" icon="auto_awesome" loading={generate.isPending} disabled={!canGenerate} onClick={() => generate.mutate()}>{t("aiGenerate")}</Button>
                  <span className="text-xs text-muted">{palette?.colors.length ? t("aiUsesLogo") : t("aiTipLogo")}</span>
                  {generate.error instanceof ApiError && generate.error.code === "no_ai_provider" && (
                    <Link href="/settings/ai" className="text-xs font-semibold underline">{t("aiProvidersLink")}</Link>
                  )}
                </div>
              </div>
            )}
          </div>

          <div className="max-w-full overflow-x-auto"><Segmented size="sm" value={tab} onChange={setTab} options={tabs} /></div>

          {tab === "basics" && (
            <div className="flex flex-col gap-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={t("name")}><Input value={form.name} onChange={(e) => set({ name: e.target.value })} /></Field>
                <Field label={t("tagline")}><Input className="bidi" value={form.tagline ?? ""} onChange={(e) => set({ tagline: e.target.value })} /></Field>
                <Field label={t("industry")}><Input className="bidi" value={form.industry ?? ""} placeholder={t("industryPlaceholder")} onChange={(e) => set({ industry: e.target.value })} /></Field>
                <Field label={t("website")}><Input dir="ltr" value={form.website ?? ""} placeholder="https://" onChange={(e) => set({ website: e.target.value })} /></Field>
              </div>
              <Field label={t("description")} hint={t("descriptionHint")}><Textarea rows={3} className="bidi" value={form.description ?? ""} onChange={(e) => set({ description: e.target.value })} /></Field>
              <Field label={t("audience")} hint={t("audienceHint")}><Textarea rows={2} className="bidi" value={form.audience ?? ""} onChange={(e) => set({ audience: e.target.value })} /></Field>
            </div>
          )}

          {tab === "look" && (
            <div className="flex flex-col gap-4">
              <Field label={t("logo")}>
                <div className="flex flex-wrap items-center gap-3">
                  {form.logo_media_id ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={mediaUrl(form.logo_media_id)} alt="" className="h-14 w-14 rounded-xl bg-white object-contain p-1 ring-1 ring-line" />
                  ) : <span className="flex h-14 w-14 items-center justify-center rounded-xl bg-fill-2 text-muted"><Icon name="image" size={22} /></span>}
                  <Button size="sm" icon="upload" loading={uploading} onClick={() => fileRef.current?.click()}>{form.logo_media_id ? t("changeLogo") : t("uploadLogo")}</Button>
                  {form.logo_media_id && <Button size="sm" variant="ghost" onClick={() => set({ logo_media_id: null })}>{t("removeLogo")}</Button>}
                  <input ref={fileRef} type="file" accept="image/*" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
                </div>
              </Field>
              {palette && palette.colors.length > 0 && (
                <div className="rounded-2xl bg-white/55 p-3 ring-1 ring-line">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <span className="text-[13px] font-medium text-text-2">{t("logoColors")}</span>
                    <span className="text-xs text-muted">{t("logoColorsHint")}</span>
                    <Button size="sm" variant="ghost" icon="palette" className="ms-auto" onClick={() => applyPalette(palette)}>{t("applyLogoColors")}</Button>
                  </div>
                  <div className="flex flex-wrap gap-2" dir="ltr">
                    {palette.colors.map((c) => (
                      <button key={c} type="button" title={c} onClick={() => setColor({ color_primary: c, color_text: readableOn(c) })}
                        className={cx("flex items-center gap-1.5 rounded-full bg-white py-1 pe-2.5 ps-1 text-xs font-mono ring-1 ring-line transition hover:ring-ink",
                          form.color_primary === c && "ring-2 ring-ink")}>
                        <span className="h-5 w-5 rounded-full ring-1 ring-black/10" style={{ background: c }} />{c}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                <ColorField label={t("colorPrimary")} value={form.color_primary} onChange={(v) => setColor({ color_primary: v ?? "" })} />
                <ColorField label={t("colorSecondary")} value={form.color_secondary} onChange={(v) => setColor({ color_secondary: v ?? "" })} />
                <ColorField label={t("colorAccent")} value={form.color_accent} optional onChange={(v) => setColor({ color_accent: v })} />
                <ColorField label={t("colorText")} value={form.color_text} onChange={(v) => setColor({ color_text: v ?? "" })} />
                <ColorField label={t("colorBackground")} value={form.color_background} optional onChange={(v) => setColor({ color_background: v })} />
              </div>
              {ratio !== null && (
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <Badge tone={ratio >= 4.5 ? "ok" : "warn"}>{t(ratio >= 4.5 ? "contrastOk" : "contrastLow", { ratio: ratio.toFixed(1) })}</Badge>
                  {ratio < 4.5 && <Button size="sm" variant="ghost" onClick={() => setColor({ color_text: readableOn(form.color_primary) })}>{t("fixContrast")}</Button>}
                </div>
              )}
              <Field label={t("visualStyle")} hint={t("visualStyleHint")}><Textarea rows={2} className="bidi" value={form.visual_style ?? ""} onChange={(e) => set({ visual_style: e.target.value })} /></Field>
            </div>
          )}

          {tab === "type" && (
            <div className="grid gap-4 sm:grid-cols-2">
              <FontField label={t("fontHeading")} value={form.font_heading} fonts={fonts} allowEmpty={t("sameAsText")}
                sample={form.tagline || form.name || t("fontSample")} onChange={(v) => set({ font_heading: v })} />
              <FontField label={t("fontBody")} value={form.font_family} fonts={fonts}
                sample={t("fontSample")} onChange={(v) => set({ font_family: v || "system-ui" })} />
            </div>
          )}

          {tab === "voice" && (
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-2">
                <span className="text-[13px] font-medium text-text-2">{t("personality")}</span>
                <div className="flex flex-wrap gap-1.5">
                  {[...presets, ...traits.filter((w) => !presets.includes(w))].map((w) => (
                    <button key={w} type="button" onClick={() => toggleTrait(w)} aria-pressed={traits.includes(w)}
                      className={cx("rounded-full px-3 py-1.5 text-[13px] ring-1 transition", traits.includes(w) ? "bg-ink text-white ring-ink" : "bg-white/70 ring-line hover:ring-ink")}>
                      {w}
                    </button>
                  ))}
                  <form className="flex" onSubmit={(e) => { e.preventDefault(); const w = personalityDraft.trim(); if (w && !traits.includes(w)) toggleTrait(w); setPersonalityDraft(""); }}>
                    <Input className="h-8 w-32 rounded-full text-[13px]" value={personalityDraft} placeholder={t("personalityAdd")} onChange={(e) => setPersonalityDraft(e.target.value)} />
                  </form>
                </div>
                <span className="text-xs text-muted">{t("personalityHint")}</span>
              </div>
              <Field label={t("tone")} hint={t("toneHint")}><Textarea rows={2} className="bidi" value={form.tone ?? ""} onChange={(e) => set({ tone: e.target.value })} /></Field>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={t("languageStyle")}>
                  <Select value={form.language_style ?? ""} onChange={(e) => set({ language_style: e.target.value || null })}>
                    <option value="">{t("languageStyles.auto")}</option>
                    {(options.data?.language_styles ?? []).map((v) => <option key={v} value={v}>{t(`languageStyles.${v}`)}</option>)}
                  </Select>
                </Field>
                <div className="flex flex-col gap-1.5">
                  <span className="text-[13px] font-medium text-text-2">{t("emojiStyle")}</span>
                  <Segmented size="sm" value={form.emoji_style ?? ""} onChange={(v) => set({ emoji_style: v || null })}
                    options={[{ value: "", label: t("emojiStyles.auto") }, ...(options.data?.emoji_styles ?? []).map((v) => ({ value: v, label: t(`emojiStyles.${v}`) }))]} />
                </div>
                <Field label={t("cta")}><Input className="bidi" value={form.cta ?? ""} placeholder={t("ctaPlaceholder")} onChange={(e) => set({ cta: e.target.value })} /></Field>
                <Field label={t("voice")} hint={t("voiceHint")}><Input dir="ltr" value={form.voice ?? ""} onChange={(e) => set({ voice: e.target.value })} /></Field>
              </div>
            </div>
          )}

          {tab === "rules" && (
            <div className="flex flex-col gap-4">
              <Field label={t("guidelines")} hint={t("guidelinesHint")}><Textarea rows={4} className="bidi" value={form.guidelines ?? ""} placeholder={t("guidelinesPlaceholder")} onChange={(e) => set({ guidelines: e.target.value })} /></Field>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={t("bannedWords")} hint={t("bannedWordsHint")}><Input className="bidi" value={form.banned_words ?? ""} onChange={(e) => set({ banned_words: e.target.value })} /></Field>
                <Field label={t("hashtags")}><Input className="bidi" value={form.hashtags ?? ""} onChange={(e) => set({ hashtags: e.target.value })} placeholder="#brand #city" /></Field>
              </div>
              <Field label={t("samplePosts")} hint={t("samplePostsHint")}><Textarea rows={5} className="bidi" value={form.sample_posts ?? ""} onChange={(e) => set({ sample_posts: e.target.value })} /></Field>
            </div>
          )}

          <div className="flex flex-wrap gap-5 border-t border-line pt-4">
            <Switch checked={form.is_default} onChange={(v) => set({ is_default: v })} label={t("default")} />
            <Switch checked={form.active} onChange={(v) => set({ active: v })} label={t("active")} />
          </div>
        </div>
        <div className="order-first md:order-none">
          <div className="sticky top-0 mx-auto max-w-[240px]">
            <div className="mb-2 text-[13px] font-medium text-text-2">{t("preview")}</div>
            <KitPreview kit={form} />
          </div>
        </div>
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------------------------------------------------ page */

export default function BrandKitsPage() {
  const t = useTranslations("ai.brand");
  const qc = useQueryClient();
  const isAdmin = useSession((s) => s.can("admin"));
  const kits = useQuery({ queryKey: ["brand-kits"], queryFn: () => api.get<BrandKit[]>("/brand-kits") });
  const [editing, setEditing] = useState<BrandKit | null | "new">(null);
  const [toDelete, setToDelete] = useState<BrandKit | null>(null);
  const makeDefault = useMutation({ mutationFn: (id: number) => api.post(`/brand-kits/${id}/default`), onSuccess: () => qc.invalidateQueries({ queryKey: ["brand-kits"] }), onError });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/brand-kits/${id}`),
    onSuccess: () => { setToDelete(null); qc.invalidateQueries({ queryKey: ["brand-kits"] }); }, onError,
  });

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <SectionTitle icon="branding" actions={isAdmin && <Button variant="primary" size="sm" icon="add" onClick={() => setEditing("new")}>{t("new")}</Button>}>
          {t("title")}
        </SectionTitle>
        <p className="-mt-1 mb-4 text-sm text-muted">{t("subtitle")}</p>
        {kits.isLoading ? <div className="py-8 text-center"><Spinner /></div> : !kits.data?.length ? (
          <EmptyState icon="palette" title={t("emptyTitle")} text={t("emptyText")}
            action={isAdmin && <Button variant="primary" icon="wand_stars" onClick={() => setEditing("new")}>{t("newWithAi")}</Button>} />
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {kits.data.map((kit) => (
              <div key={kit.id} className={cx("flex gap-3 rounded-2xl bg-white/55 p-3 ring-1 ring-line", !kit.active && "opacity-60")}>
                <div className="w-20 shrink-0"><KitPreview kit={kit} small /></div>
                <div className="flex min-w-0 flex-1 flex-col">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="truncate font-semibold">{kit.name}</span>
                    {kit.is_default && <Badge tone="ink">{t("default")}</Badge>}
                    {!kit.active && <Badge>{t("inactive")}</Badge>}
                  </div>
                  {kit.industry && <span className="bidi mt-0.5 truncate text-xs text-muted">{kit.industry}</span>}
                  <div className="mt-2 flex items-center gap-1" dir="ltr">
                    {[kit.color_primary, kit.color_secondary, kit.color_accent, kit.color_text].filter(isHex).map((c, i) => (
                      <span key={i} title={c} className="h-5 w-5 rounded-full ring-1 ring-line" style={{ background: c }} />
                    ))}
                    <span className="ms-1 truncate text-xs text-muted" style={{ fontFamily: kit.font_heading || kit.font_family }}>{fontLabel(kit.font_heading || kit.font_family)}</span>
                  </div>
                  {(kit.personality || kit.tone) && <p className="bidi mt-2 line-clamp-2 text-xs text-muted">{kit.personality || kit.tone}</p>}
                  {isAdmin && (
                    <div className="mt-auto flex items-center pt-2">
                      {!kit.is_default && kit.active && <Button size="sm" variant="ghost" icon="verified" onClick={() => makeDefault.mutate(kit.id)}>{t("makeDefault")}</Button>}
                      <span className="ms-auto flex">
                        <IconButton icon="edit_square" label={t("edit")} onClick={() => setEditing(kit)} />
                        <IconButton icon="delete" label={t("delete")} onClick={() => setToDelete(kit)} />
                      </span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
      <Card className="text-sm text-muted">
        <SectionTitle icon="lightbulb">{t("usedForTitle")}</SectionTitle>
        <p>{t("usedFor")}</p>
      </Card>
      {editing && <KitDialog kit={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      <Modal open={!!toDelete} onClose={() => setToDelete(null)} title={t("deleteTitle")} size="sm"
        footer={<><Button onClick={() => setToDelete(null)}>{t("cancel")}</Button><Button variant="danger" loading={remove.isPending} onClick={() => toDelete && remove.mutate(toDelete.id)}>{t("delete")}</Button></>}>
        <p className="text-sm text-text-2">{t("deleteText", { name: toDelete?.name ?? "" })}</p>
      </Modal>
    </div>
  );
}
