"use client";
/** Settings › Brand kits: logo, colours, font, tone of voice, rules, hashtags, visual style and voice — used by AI
 * writing, image/video prompts, templates and production. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { Icon } from "@/components/icon";
import { Badge, Button, Card, EmptyState, Field, IconButton, Input, Modal, SectionTitle, Select, Spinner, Switch, Textarea, cx, toast } from "@/components/ui";
import { ApiError, api, mediaUrl } from "@/lib/api";
import { useSession } from "@/lib/session";

type BrandKit = {
  id: number; name: string; logo_media_id: number | null; logo_url: string | null; color_primary: string;
  color_secondary: string; color_text: string; font_family: string; tagline: string | null; tone: string | null;
  guidelines: string | null; hashtags: string | null; visual_style: string | null; voice: string | null;
  is_default: boolean; active: boolean;
};
type Form = Omit<BrandKit, "id" | "logo_url">;

const EMPTY: Form = {
  name: "", logo_media_id: null, color_primary: "#111111", color_secondary: "#71717a", color_text: "#ffffff",
  font_family: "system-ui", tagline: "", tone: "", guidelines: "", hashtags: "", visual_style: "", voice: "",
  is_default: false, active: true,
};
const onError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : String(err));

function fontLabel(font: string) {
  if (font === "system-ui") return "System";
  return font.split(",")[0].replace(/'/g, "");
}

function KitPreview({ kit, small = false }: { kit: Form; small?: boolean }) {
  if (small) {
    return (
      <div className="flex aspect-[4/5] w-full flex-col items-center justify-center gap-1.5 overflow-hidden rounded-xl p-2 shadow-[var(--shadow)]"
        style={{ background: `linear-gradient(150deg, ${kit.color_primary}, ${kit.color_secondary})`, color: kit.color_text, fontFamily: kit.font_family }}>
        {kit.logo_media_id ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={mediaUrl(kit.logo_media_id)} alt="" className="h-9 w-9 rounded-lg bg-white/90 object-contain p-1" />
        ) : <span className="text-xl font-bold">Aa</span>}
      </div>
    );
  }
  return (
    <div className="relative flex aspect-[4/5] w-full flex-col justify-between overflow-hidden rounded-2xl p-4 shadow-[var(--shadow)]"
      style={{ background: `linear-gradient(150deg, ${kit.color_primary}, ${kit.color_secondary})`, color: kit.color_text, fontFamily: kit.font_family }}>
      <div className="flex items-center gap-2">
        {kit.logo_media_id ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={mediaUrl(kit.logo_media_id)} alt="" className="h-9 w-9 rounded-lg bg-white/90 object-contain p-1" />
        ) : <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/20"><Icon name="branding" size={18} /></span>}
        <span className="truncate text-sm font-semibold">{kit.name || "—"}</span>
      </div>
      <div>
        <div className="bidi text-lg font-bold leading-snug">{kit.tagline || "Aa"}</div>
        {kit.hashtags && <div className="bidi mt-1 truncate text-xs opacity-80">{kit.hashtags}</div>}
      </div>
    </div>
  );
}

function ColorField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <Field label={label}>
      <div className="flex items-center gap-2">
        <input type="color" value={/^#[0-9a-f]{6}$/i.test(value) ? value : "#000000"} onChange={(e) => onChange(e.target.value)}
          className="h-10 w-12 shrink-0 cursor-pointer rounded-xl border border-line bg-white/70 p-1" aria-label={label} />
        <Input dir="ltr" value={value} maxLength={9} onChange={(e) => onChange(e.target.value)} className="font-mono" />
      </div>
    </Field>
  );
}

function KitDialog({ kit, onClose }: { kit: BrandKit | null; onClose: () => void }) {
  const t = useTranslations("ai.brand");
  const qc = useQueryClient();
  const [form, setForm] = useState<Form>(() => (kit ? { ...EMPTY, ...kit } : EMPTY));
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));
  const options = useQuery({ queryKey: ["brand-kits", "options"], queryFn: () => api.get<{ fonts: string[] }>("/brand-kits/options"), staleTime: Infinity });

  const save = useMutation({
    mutationFn: () => {
      const body = { ...form, tagline: form.tagline || null, tone: form.tone || null, guidelines: form.guidelines || null,
        hashtags: form.hashtags || null, visual_style: form.visual_style || null, voice: form.voice || null };
      return kit ? api.patch(`/brand-kits/${kit.id}`, body) : api.post("/brand-kits", body);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["brand-kits"] }); toast.success(t("saved")); onClose(); },
    onError,
  });
  const upload = async (file: File) => {
    setUploading(true);
    try {
      const media = await api.upload<{ id: number }>("/media", file);
      set({ logo_media_id: media.id });
    } catch (err) {
      onError(err);
    } finally {
      setUploading(false);
    }
  };

  return (
    <Modal open onClose={onClose} size="xl" title={kit ? kit.name : t("new")}
      footer={<><Button onClick={onClose}>{t("cancel")}</Button><Button variant="primary" loading={save.isPending} disabled={!form.name.trim()} onClick={() => save.mutate()}>{t("save")}</Button></>}>
      <div className="grid gap-6 md:grid-cols-[1fr_220px]">
        <div className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("name")}><Input value={form.name} onChange={(e) => set({ name: e.target.value })} /></Field>
            <Field label={t("tagline")}><Input className="bidi" value={form.tagline ?? ""} onChange={(e) => set({ tagline: e.target.value })} /></Field>
          </div>
          <Field label={t("logo")}>
            <div className="flex items-center gap-3">
              {form.logo_media_id ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={mediaUrl(form.logo_media_id)} alt="" className="h-14 w-14 rounded-xl bg-white object-contain p-1 ring-1 ring-line" />
              ) : <span className="flex h-14 w-14 items-center justify-center rounded-xl bg-fill-2 text-muted"><Icon name="image" size={22} /></span>}
              <Button size="sm" icon="upload" loading={uploading} onClick={() => fileRef.current?.click()}>{form.logo_media_id ? t("changeLogo") : t("uploadLogo")}</Button>
              {form.logo_media_id && <Button size="sm" variant="ghost" onClick={() => set({ logo_media_id: null })}>{t("removeLogo")}</Button>}
              <input ref={fileRef} type="file" accept="image/*" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
            </div>
          </Field>
          <div className="grid gap-4 sm:grid-cols-3">
            <ColorField label={t("colorPrimary")} value={form.color_primary} onChange={(v) => set({ color_primary: v })} />
            <ColorField label={t("colorSecondary")} value={form.color_secondary} onChange={(v) => set({ color_secondary: v })} />
            <ColorField label={t("colorText")} value={form.color_text} onChange={(v) => set({ color_text: v })} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("font")}>
              <Select value={form.font_family} onChange={(e) => set({ font_family: e.target.value })}>
                {(options.data?.fonts ?? [form.font_family]).map((f) => <option key={f} value={f}>{fontLabel(f)}</option>)}
              </Select>
            </Field>
            <Field label={t("voice")} hint={t("voiceHint")}><Input dir="ltr" value={form.voice ?? ""} onChange={(e) => set({ voice: e.target.value })} /></Field>
          </div>
          <Field label={t("tone")} hint={t("toneHint")}><Textarea rows={2} value={form.tone ?? ""} onChange={(e) => set({ tone: e.target.value })} /></Field>
          <Field label={t("guidelines")} hint={t("guidelinesHint")}><Textarea rows={3} value={form.guidelines ?? ""} onChange={(e) => set({ guidelines: e.target.value })} /></Field>
          <Field label={t("hashtags")}><Input className="bidi" value={form.hashtags ?? ""} onChange={(e) => set({ hashtags: e.target.value })} placeholder="#brand #city" /></Field>
          <Field label={t("visualStyle")} hint={t("visualStyleHint")}><Textarea rows={2} value={form.visual_style ?? ""} onChange={(e) => set({ visual_style: e.target.value })} /></Field>
          <div className="flex flex-wrap gap-5">
            <Switch checked={form.is_default} onChange={(v) => set({ is_default: v })} label={t("default")} />
            <Switch checked={form.active} onChange={(v) => set({ active: v })} label={t("active")} />
          </div>
        </div>
        <div className="order-first md:order-none">
          <div className="sticky top-0 mx-auto max-w-[220px]">
            <div className="mb-2 text-[13px] font-medium text-text-2">{t("preview")}</div>
            <KitPreview kit={form} />
          </div>
        </div>
      </div>
    </Modal>
  );
}

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
            action={isAdmin && <Button variant="primary" icon="add" onClick={() => setEditing("new")}>{t("new")}</Button>} />
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
                  <div className="mt-2 flex items-center gap-1">
                    {[kit.color_primary, kit.color_secondary, kit.color_text].map((c, i) => (
                      <span key={i} title={c} className="h-5 w-5 rounded-full ring-1 ring-line" style={{ background: c }} />
                    ))}
                    <span className="ms-1 truncate text-xs text-muted" style={{ fontFamily: kit.font_family }}>{fontLabel(kit.font_family)}</span>
                  </div>
                  {kit.tone && <p className="bidi mt-2 line-clamp-2 text-xs text-muted">{kit.tone}</p>}
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
