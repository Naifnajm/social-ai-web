"use client";
/** Brand template editor: frame upload, live preview with draggable photo/text boxes, text & logo options. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/icon";
import { ColorInput, CornerPicker, NumberBox, Range, Section } from "@/components/templates/controls";
import { type Box, FrameStage, StageLegend } from "@/components/templates/frame-stage";
import {
  type BrandKitBrief, CATEGORIES, type Detection, FORMATS, type MediaItem, type Template, type TemplateForm,
  type TemplateFormat, type TemplateSet, formatInfo,
} from "@/components/templates/types";
import { Button, Card, EmptyState, Field, IconButton, Input, Modal, Segmented, Select, Spinner, Switch, cx, toast } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";

const DEFAULTS: TemplateForm = {
  name: "", set_id: null, brand_kit_id: null, category: "other", format: "post_4x5", frame_media_id: null,
  background_color: null, box_x: 5, box_y: 5, box_w: 90, box_h: 72, photo_fit: "cover",
  text_enabled: false, text_x: 6, text_y: 80, text_w: 88, text_h: 14, text_size: 64, text_color: "#ffffff",
  text_bg_color: null, text_align: "auto", text_bold: true, text_max_lines: 2, text_default: "",
  logo_enabled: false, logo_position: "top_right", logo_size: 16,
};
const FORM_KEYS = Object.keys(DEFAULTS) as (keyof TemplateForm)[];
const pick = (t: Template): TemplateForm =>
  Object.fromEntries(FORM_KEYS.map((k) => [k, t[k] ?? DEFAULTS[k]])) as TemplateForm;

export default function TemplateEditorPage() {
  return (
    <Suspense fallback={<div className="flex justify-center py-20"><Spinner size={26} /></div>}>
      <Editor />
    </Suspense>
  );
}

function Editor() {
  const t = useTranslations("templates");
  const { id } = useParams<{ id: string }>();
  const search = useSearchParams();
  const isNew = id === "new";
  const templateId = isNew ? null : Number(id);
  const router = useRouter();
  const qc = useQueryClient();
  const canEdit = useSession((s) => s.can("editor"));

  const template = useQuery({ queryKey: ["template", templateId], queryFn: () => api.get<Template>(`/templates/${templateId}`), enabled: !!templateId });
  const sets = useQuery({ queryKey: ["template-sets"], queryFn: () => api.get<TemplateSet[]>("/templates/sets") });
  const kits = useQuery({ queryKey: ["template-brand-kits"], queryFn: () => api.get<BrandKitBrief[]>("/templates/brand-kits") });

  const [form, setForm] = useState<TemplateForm | null>(() => isNew ? {
    ...DEFAULTS,
    set_id: Number(search.get("set")) || null,
    format: (search.get("format") as TemplateFormat) || "post_4x5",
  } : null);
  const [dirty, setDirty] = useState(false);
  const [hasWindow, setHasWindow] = useState(true);
  const [loadedId, setLoadedId] = useState<number | null>(null);
  if (template.data && loadedId !== template.data.id) {
    setLoadedId(template.data.id);
    setForm(pick(template.data));
    setHasWindow(template.data.frame_has_window);
    setDirty(false);
  }

  const update = useCallback((values: Partial<TemplateForm>) => {
    setForm((f) => (f ? { ...f, ...values } : f));
    setDirty(true);
  }, []);

  // ------------------------------------------------------------ live preview (debounced)
  const [previewSrc, setPreviewSrc] = useState<string | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [sampleText, setSampleText] = useState("");
  const [samplePhoto, setSamplePhoto] = useState<number | null>(null);
  const seq = useRef(0);
  const payload = useMemo(() => form && JSON.stringify({ ...form, text: sampleText || undefined, media_id: samplePhoto || undefined }), [form, sampleText, samplePhoto]);
  useEffect(() => {
    if (!payload) return;
    const mine = ++seq.current;
    const timer = setTimeout(async () => {
      setPreviewBusy(true);
      try {
        const blob = await api.post<Blob>("/templates/render-preview", JSON.parse(payload));
        if (mine !== seq.current) return;
        const url = URL.createObjectURL(blob);
        setPreviewSrc((old) => {
          if (old?.startsWith("blob:")) URL.revokeObjectURL(old);
          return url;
        });
      } catch {
        /* keep the last preview */
      } finally {
        if (mine === seq.current) setPreviewBusy(false);
      }
    }, 280);
    return () => clearTimeout(timer);
  }, [payload]);

  // ------------------------------------------------------------ frame upload
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const uploadFrame = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    try {
      const res = await api.upload<{ media: MediaItem; detection: Detection }>("/templates/frames", file);
      const d = res.detection;
      update({ frame_media_id: res.media.id, box_x: d.box_x, box_y: d.box_y, box_w: d.box_w, box_h: d.box_h, format: d.format });
      setHasWindow(d.frame_has_window);
      if (!form?.name) update({ name: file.name.replace(/\.[^.]+$/, "").slice(0, 80) });
      toast.success(d.frame_has_window ? t("editor.windowFound") : t("editor.noWindow"));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  };

  const detect = useMutation({
    mutationFn: () => api.post<Template>(`/templates/${templateId}/detect`),
    onSuccess: (data) => {
      update({ box_x: data.box_x, box_y: data.box_y, box_w: data.box_w, box_h: data.box_h });
      toast.success(t("editor.windowFound"));
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });

  // ------------------------------------------------------------ save / delete / duplicate
  const save = useMutation({
    mutationFn: () => {
      const body = { ...form!, name: form!.name.trim() || t("editor.untitled") };
      return isNew ? api.post<Template>("/templates", body) : api.patch<Template>(`/templates/${templateId}`, body);
    },
    onSuccess: (data) => {
      setDirty(false);
      toast.success(t("saved"));
      qc.invalidateQueries({ queryKey: ["template-sets"] });
      qc.invalidateQueries({ queryKey: ["templates"] });
      qc.setQueryData(["template", data.id], data);
      if (isNew) router.replace(`/templates/${data.id}`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
  const [confirmDelete, setConfirmDelete] = useState(false);
  const remove = useMutation({
    mutationFn: () => api.delete(`/templates/${templateId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["template-sets"] });
      qc.invalidateQueries({ queryKey: ["templates"] });
      router.replace("/settings/templates");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
  const duplicate = useMutation({
    mutationFn: () => api.post<Template>(`/templates/${templateId}/duplicate`),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["template-sets"] });
      router.push(`/templates/${data.id}`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });

  const onBox = useCallback((kind: "photo" | "text", b: Box) => {
    if (kind === "photo") update({ box_x: b.x, box_y: b.y, box_w: b.w, box_h: b.h });
    else update({ text_x: b.x, text_y: b.y, text_w: b.w, text_h: b.h });
  }, [update]);

  if (template.isError) {
    return <EmptyState icon="photo_frame" title={t("editor.notFound")} action={<Link href="/settings/templates"><Button>{t("backToTemplates")}</Button></Link>} />;
  }
  if (!form) return <div className="flex justify-center py-20"><Spinner size={26} /></div>;

  const info = formatInfo(form.format);
  const kitOptions = kits.data ?? [];
  const cornerLabels = Object.fromEntries((["top_left", "top_right", "bottom_left", "bottom_right"] as const).map((c) => [c, t(`corners.${c}`)]));

  return (
    <div className="pt-2">
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <Link href="/settings/templates" className="inline-flex h-10 w-10 items-center justify-center rounded-full text-text-2 hover:bg-fill-2" aria-label={t("backToTemplates")}>
          <Icon name="arrow_back" size={20} className="rtl:rotate-180" />
        </Link>
        <div className="min-w-0 flex-1">
          <input value={form.name} onChange={(e) => update({ name: e.target.value })} placeholder={t("editor.namePlaceholder")} disabled={!canEdit}
            className="bidi w-full truncate bg-transparent text-2xl font-bold tracking-tight outline-none placeholder:text-faint" />
          <p className="text-sm text-muted">{info.aspect} · {info.w}×{info.h}{template.data ? ` · ${t("usedTimes", { count: template.data.usage_count })}` : ""}</p>
        </div>
        {canEdit && (
          <div className="flex flex-wrap items-center gap-2">
            {!isNew && <IconButton icon="content_copy" label={t("duplicate")} onClick={() => duplicate.mutate()} />}
            {!isNew && <IconButton icon="delete" label={t("delete")} onClick={() => setConfirmDelete(true)} />}
            <Button variant="primary" icon="save" loading={save.isPending} disabled={!dirty && !isNew} onClick={() => save.mutate()}>
              {isNew ? t("editor.create") : t("save")}
            </Button>
          </div>
        )}
      </header>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_400px]">
        {/* ------------------------------------------------ canvas */}
        <Card className="flex flex-col items-center gap-4 lg:sticky lg:top-16 lg:self-start">
          <div className="w-full" style={{ maxWidth: info.h > info.w ? `${Math.round(560 * info.w / info.h)}px` : "640px" }}>
            <FrameStage ratio={info.w / info.h} src={previewSrc} loading={previewBusy}
              photo={{ x: form.box_x, y: form.box_y, w: form.box_w, h: form.box_h }}
              text={form.text_enabled ? { x: form.text_x, y: form.text_y, w: form.text_w, h: form.text_h } : null}
              onChange={onBox} readOnly={!canEdit} emptyLabel={t("editor.uploadFrame")} />
          </div>
          <StageLegend text={form.text_enabled} />
          <p className="-mt-2 max-w-md text-center text-xs text-muted">{t("editor.stageHint")}</p>
          <div className="grid w-full max-w-lg gap-3 sm:grid-cols-2">
            <Field label={t("editor.sampleText")}>
              <Input value={sampleText} onChange={(e) => setSampleText(e.target.value)} placeholder={form.text_default || t("editor.sampleTextPlaceholder")} className="bidi" />
            </Field>
            <Field label={t("editor.samplePhoto")}>
              <SamplePhotoPicker value={samplePhoto} onChange={setSamplePhoto} />
            </Field>
          </div>
        </Card>

        {/* ------------------------------------------------ settings */}
        <Card className="flex flex-col gap-5">
          <Section icon="photo_frame" title={t("editor.frame")}>
            <input ref={fileInput} type="file" accept="image/png,image/webp" className="hidden"
              onChange={(e) => { uploadFrame(e.target.files?.[0]); e.target.value = ""; }} />
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); uploadFrame(e.dataTransfer.files?.[0]); }}
              className="flex items-center gap-3 rounded-2xl border border-dashed border-black/15 bg-white/50 p-3">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-fill-2">
                {uploading ? <Spinner size={18} /> : <Icon name={form.frame_media_id ? "check_circle" : "upload"} size={20} className={form.frame_media_id ? "text-ok" : "text-text-2"} />}
              </span>
              <div className="min-w-0 flex-1 text-sm">
                <div className="font-medium">{form.frame_media_id ? t("editor.frameReady") : t("editor.frameMissing")}</div>
                <div className="text-xs text-muted">{t("editor.frameHint")}</div>
              </div>
              {canEdit && <Button size="sm" onClick={() => fileInput.current?.click()}>{form.frame_media_id ? t("editor.replace") : t("editor.upload")}</Button>}
            </div>
            {form.frame_media_id && !hasWindow && (
              <p className="flex items-start gap-1.5 rounded-xl bg-warn-bg px-3 py-2 text-xs text-warn"><Icon name="info" size={14} className="mt-0.5" />{t("editor.noWindow")}</p>
            )}
            <Field label={t("editor.format")}>
              <Segmented value={form.format} onChange={(v) => update({ format: v })} size="sm" className="w-full justify-between"
                options={FORMATS.map((f) => ({ value: f.value, label: <span dir="ltr">{f.aspect}</span> }))} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("editor.set")}>
                <Select value={form.set_id ?? ""} onChange={(e) => update({ set_id: e.target.value ? Number(e.target.value) : null })}>
                  <option value="">{t("editor.noSet")}</option>
                  {sets.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </Select>
              </Field>
              <Field label={t("category")}>
                <Select value={form.category} onChange={(e) => update({ category: e.target.value })}>
                  {CATEGORIES.map((c) => <option key={c} value={c}>{t(`categories.${c}`)}</option>)}
                </Select>
              </Field>
            </div>
          </Section>

          <Section icon="image" title={t("editor.photo")}
            aside={!isNew && form.frame_media_id ? <Button size="sm" variant="ghost" icon="aspect_ratio" loading={detect.isPending} onClick={() => detect.mutate()}>{t("editor.detect")}</Button> : null}>
            <Segmented value={form.photo_fit} onChange={(v) => update({ photo_fit: v })} size="sm" className="self-start"
              options={[{ value: "cover", label: t("editor.fitCover") }, { value: "contain", label: t("editor.fitContain") }]} />
            <div className="grid grid-cols-4 gap-2">
              <NumberBox label={t("editor.left")} value={form.box_x} onChange={(v) => update({ box_x: v })} />
              <NumberBox label={t("editor.top")} value={form.box_y} onChange={(v) => update({ box_y: v })} />
              <NumberBox label={t("editor.width")} value={form.box_w} onChange={(v) => update({ box_w: Math.max(1, v) })} />
              <NumberBox label={t("editor.height")} value={form.box_h} onChange={(v) => update({ box_h: Math.max(1, v) })} />
            </div>
            <Field label={t("editor.background")} hint={t("editor.backgroundHint")}>
              <ColorInput value={form.background_color} onChange={(v) => update({ background_color: v })} placeholder={t("editor.fromBrandKit")} allowEmpty />
            </Field>
          </Section>

          <Section icon="text_fields" title={t("editor.text")}
            aside={<Switch checked={form.text_enabled} onChange={(v) => update({ text_enabled: v })} />}>
            {form.text_enabled ? (
              <>
                <Field label={t("editor.textDefault")} hint={t("editor.textDefaultHint")}>
                  <Input value={form.text_default ?? ""} onChange={(e) => update({ text_default: e.target.value })} placeholder={t("editor.sampleTextPlaceholder")} className="bidi" maxLength={200} />
                </Field>
                <Field label={t("editor.textSize")}>
                  <Range value={form.text_size} onChange={(v) => update({ text_size: v })} min={20} max={200} suffix="px" />
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label={t("editor.textColor")}>
                    <ColorInput value={form.text_color} onChange={(v) => update({ text_color: v || "#ffffff" })} />
                  </Field>
                  <Field label={t("editor.textBackground")}>
                    <ColorInput value={form.text_bg_color} onChange={(v) => update({ text_bg_color: v })} placeholder={t("editor.none")} allowEmpty />
                  </Field>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <Segmented value={form.text_align} onChange={(v) => update({ text_align: v })} size="sm"
                    options={[
                      { value: "auto", label: t("editor.alignAuto") },
                      { value: "left", label: "", icon: "format_align_left" },
                      { value: "center", label: "", icon: "format_align_center" },
                      { value: "right", label: "", icon: "format_align_right" },
                    ]} />
                  <Switch checked={form.text_bold} onChange={(v) => update({ text_bold: v })} label={t("editor.bold")} />
                </div>
                <Field label={t("editor.maxLines")}>
                  <Segmented value={form.text_max_lines} onChange={(v) => update({ text_max_lines: v })} size="sm" className="self-start"
                    options={[1, 2, 3, 4].map((n) => ({ value: n, label: String(n) }))} />
                </Field>
              </>
            ) : <p className="text-xs text-muted">{t("editor.textOffHint")}</p>}
          </Section>

          <Section icon="branding" title={t("editor.logo")}
            aside={<Switch checked={form.logo_enabled} onChange={(v) => update({ logo_enabled: v })} />}>
            <Field label={t("editor.brandKit")}>
              <Select value={form.brand_kit_id ?? ""} onChange={(e) => update({ brand_kit_id: e.target.value ? Number(e.target.value) : null })}>
                <option value="">{t("editor.defaultKit")}</option>
                {kitOptions.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
              </Select>
            </Field>
            {form.logo_enabled && (
              <div className="flex items-start gap-4">
                <CornerPicker value={form.logo_position} onChange={(v) => update({ logo_position: v })} labels={cornerLabels} />
                <Field label={t("editor.logoSize")} className="min-w-0 flex-1">
                  <Range value={form.logo_size} onChange={(v) => update({ logo_size: v })} min={5} max={40} suffix="%" />
                </Field>
              </div>
            )}
            {form.logo_enabled && !kitOptions.some((k) => k.logo_media_id) && (
              <p className="text-xs text-muted">{t("editor.noLogo")}</p>
            )}
          </Section>
        </Card>
      </div>

      <Modal open={confirmDelete} onClose={() => setConfirmDelete(false)} title={t("deleteTemplateTitle")} size="sm"
        footer={<><Button onClick={() => setConfirmDelete(false)}>{t("cancel")}</Button><Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate()}>{t("delete")}</Button></>}>
        <p className="text-sm text-text-2">{t("deleteTemplateText")}</p>
      </Modal>
    </div>
  );
}

function SamplePhotoPicker({ value, onChange }: { value: number | null; onChange: (id: number | null) => void }) {
  const t = useTranslations("templates");
  const [open, setOpen] = useState(false);
  const media = useQuery({ queryKey: ["media", "image"], queryFn: () => api.get<MediaItem[]>("/media", { kind: "image", limit: 60 }), enabled: open });
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}
        className="flex h-10 w-full items-center gap-2 rounded-xl border border-line bg-white/70 px-2 text-start text-sm">
        {value ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={`/api/media/${value}/file`} alt="" className="h-7 w-7 rounded-md object-cover" />
        ) : <Icon name="image" size={18} className="text-muted" />}
        <span className="flex-1 truncate text-text-2">{value ? t("editor.yourPhoto") : t("editor.samplePhotoDefault")}</span>
        {value && <span role="button" tabIndex={0} onClick={(e) => { e.stopPropagation(); onChange(null); }} className="rounded-full p-1 text-muted hover:bg-fill-2"><Icon name="close" size={14} /></span>}
      </button>
      <Modal open={open} onClose={() => setOpen(false)} title={t("editor.samplePhoto")} size="lg">
        {media.isLoading ? <div className="flex justify-center py-10"><Spinner /></div> : (
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
            {media.data?.filter((m) => m.source !== "template").map((m) => (
              <button key={m.id} onClick={() => { onChange(m.id); setOpen(false); }}
                className={cx("aspect-square overflow-hidden rounded-xl ring-2 transition", value === m.id ? "ring-ink" : "ring-transparent hover:ring-black/15")}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={m.thumb_url} alt="" className="h-full w-full object-cover" />
              </button>
            ))}
            {!media.data?.length && <p className="col-span-full py-6 text-center text-sm text-muted">{t("noPhotos")}</p>}
          </div>
        )}
      </Modal>
    </>
  );
}
