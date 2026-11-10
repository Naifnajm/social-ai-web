"use client";
/**
 * "Create with AI" dialog: image, video, voice-over, sound effect or music, with prompt, style, aspect, duration,
 * model picker (price + estimate + wallet), live progress for videos and a preview. Returns the created media file.
 *
 *   <AiMediaDialog open={open} onClose={() => setOpen(false)} kinds={["image", "video"]}
 *     initialPrompt={caption} inputMediaIds={[photoId]} onCreated={(media, job) => attach(media.id)} />
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ApiError, api, mediaUrl } from "@/lib/api";
import { ASPECTS, type Aspect, type AudioMode, type Estimate, type JobMedia, type MediaJob, type MediaKind, STYLES, money, useAiStatus } from "@/lib/ai";
import { Icon } from "./icon";
import { ModelPicker } from "./model-picker";
import { Badge, Button, Field, Input, Modal, Segmented, Select, Textarea, cx, toast } from "./ui";

type BrandKitLite = { id: number; name: string; is_default: boolean; active: boolean };

type Props = {
  open: boolean;
  onClose: () => void;
  onCreated?: (media: JobMedia, job: MediaJob) => void;
  kinds?: MediaKind[];
  initialKind?: MediaKind;
  initialPrompt?: string;
  initialAspect?: Aspect;
  inputMediaIds?: number[];
  title?: string;
};

const VIDEO_SECONDS = [4, 5, 8, 10, 12];
const SOUND_SECONDS = [5, 10, 20, 30, 60];

export function AiMediaDialog({ open, onClose, onCreated, kinds = ["image", "video", "audio"], initialKind, initialPrompt = "",
  initialAspect = "1:1", inputMediaIds = [], title }: Props) {
  const t = useTranslations("ai.media");
  const qc = useQueryClient();
  const status = useAiStatus();
  const [kind, setKind] = useState<MediaKind>(initialKind && kinds.includes(initialKind) ? initialKind : kinds[0]);
  const [prompt, setPrompt] = useState(initialPrompt);
  const [style, setStyle] = useState<string | null>(null);
  const [aspect, setAspect] = useState<Aspect>(initialAspect);
  const [seconds, setSeconds] = useState(8);
  const [audioMode, setAudioMode] = useState<AudioMode>("speech");
  const [voice, setVoice] = useState("");
  const [modelId, setModelId] = useState<number | null>(null);
  const [refs, setRefs] = useState<number[]>(inputMediaIds);
  const [pickedKit, setBrandKitId] = useState<number | null | undefined>(undefined); // undefined = default kit
  const [notEnough, setNotEnough] = useState(false);
  const [job, setJob] = useState<MediaJob | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // reset when re-opened with new inputs
  const [lastOpen, setLastOpen] = useState(open);
  if (open !== lastOpen) {
    setLastOpen(open);
    if (open) {
      setPrompt(initialPrompt);
      setRefs(inputMediaIds);
      setJob(null);
    }
  }

  const kits = useQuery({ queryKey: ["brand-kits", "active"], queryFn: () => api.get<BrandKitLite[]>("/brand-kits", { active_only: true }), enabled: open, staleTime: 60_000 });
  const brandKitId = pickedKit === undefined ? kits.data?.find((k) => k.is_default)?.id ?? null : pickedKit;

  const effectiveSeconds = kind === "video" ? seconds : kind === "audio" && audioMode !== "speech" ? seconds : 0;
  const onEstimate = useCallback((_e: Estimate | undefined, over: boolean) => setNotEnough(over), []);

  const start = useMutation({
    mutationFn: () => api.post<MediaJob>("/ai/media", {
      kind, prompt, model_id: modelId, aspect, style: kind === "audio" ? null : style, seconds: effectiveSeconds || 8,
      audio_mode: kind === "audio" ? audioMode : "speech", voice: voice.trim() || null,
      input_media_ids: kind === "audio" ? [] : refs, brand_kit_id: brandKitId,
    }),
    onSuccess: (result) => {
      setJob(result);
      qc.invalidateQueries({ queryKey: ["ai"] });
      if (result.state === "failed") toast.error(result.error || t("failed"));
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });

  const improve = useMutation({
    mutationFn: () => api.post<{ prompt: string }>("/ai/suggest-visual", { kind: kind === "video" ? "video" : "image", text: prompt, brand_kit_id: brandKitId }),
    onSuccess: (r) => setPrompt(r.prompt),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });

  // live progress while the provider is working
  const running = job?.state === "running";
  const jobId = job?.id;
  useEffect(() => {
    if (!running || !jobId) return;
    const timer = setInterval(async () => {
      try {
        const [fresh] = await api.post<MediaJob[]>("/ai/jobs/check", { ids: [jobId] });
        if (fresh) setJob(fresh);
      } catch {
        /* keep polling */
      }
    }, 4000);
    return () => clearInterval(timer);
  }, [running, jobId]);

  const upload = async (file: File) => {
    setUploading(true);
    try {
      const media = await api.upload<{ id: number }>("/media", file);
      setRefs((r) => [...r, media.id].slice(-3));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  };

  const use = () => {
    if (job?.media) {
      onCreated?.(job.media, job);
      onClose();
    }
  };

  const busy = start.isPending || running;
  const footer = job?.state === "done" ? (
    <>
      <Button icon="refresh" onClick={() => setJob(null)}>{t("again")}</Button>
      <Button variant="primary" icon="check" onClick={use}>{onCreated ? t("use") : t("close")}</Button>
    </>
  ) : (
    <>
      <span className="me-auto text-xs text-muted">{running ? t("keepWorking") : ""}</span>
      <Button onClick={onClose}>{running ? t("hide") : t("cancel")}</Button>
      {job?.state === "failed" ? (
        <Button variant="primary" icon="refresh" loading={start.isPending} onClick={() => start.mutate()}>{t("retry")}</Button>
      ) : (
        <Button variant="primary" icon="auto_awesome" loading={busy} disabled={!prompt.trim() || notEnough} onClick={() => start.mutate()}>
          {t("generate")}
        </Button>
      )}
    </>
  );

  if (!open || typeof document === "undefined") return null;
  // portal: a parent with backdrop-filter (.glass cards) would otherwise trap the fixed overlay
  return createPortal(
    <Modal open={open} onClose={onClose} title={title || t("title")} size="lg" footer={footer}>
      {job && job.state !== "failed" ? (
        <JobView job={job} />
      ) : (
        <div className="flex flex-col gap-4">
          {job?.state === "failed" && (
            <div className="flex items-start gap-2 rounded-2xl bg-bad-bg px-3 py-2.5 text-sm text-bad">
              <Icon name="error" size={18} className="mt-0.5" /> <span className="bidi">{job.error || t("failed")}</span>
            </div>
          )}
          {kinds.length > 1 && (
            <Segmented value={kind} onChange={(k) => { setKind(k); setModelId(null); }} className="self-start"
              options={kinds.map((k) => ({ value: k, label: t(`kinds.${k}`), icon: k === "image" ? "image" : k === "video" ? "movie" : "graphic_eq" }))} />
          )}
          {kind === "audio" && (
            <Segmented size="sm" value={audioMode} onChange={(m) => { setAudioMode(m); setSeconds(m === "music" ? 30 : 10); }} className="self-start"
              options={(["speech", "sfx", "music"] as AudioMode[]).map((m) => ({ value: m, label: t(`audioModes.${m}`) }))} />
          )}

          <Field label={kind === "audio" && audioMode === "speech" ? t("textToSpeak") : t("prompt")}>
            <Textarea rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder={t(`placeholders.${kind === "audio" ? audioMode : kind}`)} />
          </Field>
          {kind !== "audio" && status.data?.text && (
            <Button size="sm" variant="ghost" icon="wand_stars" className="-mt-2 self-start" loading={improve.isPending}
              disabled={!prompt.trim()} onClick={() => improve.mutate()}>{t("improve")}</Button>
          )}

          {kind === "image" && (
            <Field label={t("style")}>
              <div className="flex flex-wrap gap-1.5">
                {[null, ...STYLES].map((s) => (
                  <button key={s ?? "none"} type="button" onClick={() => setStyle(s)}
                    className={cx("h-8 rounded-full px-3 text-[13px] font-medium transition", style === s ? "bg-ink text-white" : "bg-fill-2 text-text-2 hover:text-text")}>
                    {t(`styles.${s ?? "none"}`)}
                  </button>
                ))}
              </div>
            </Field>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            {kind !== "audio" && (
              <Field label={t("aspect")}>
                <Segmented size="sm" value={aspect} onChange={setAspect} className="w-fit"
                  options={ASPECTS.map((a) => ({ value: a, label: <span dir="ltr">{a}</span> }))} />
              </Field>
            )}
            {(kind === "video" || (kind === "audio" && audioMode !== "speech")) && (
              <Field label={t("duration")}>
                <Segmented size="sm" value={seconds} onChange={setSeconds} className="w-fit"
                  options={(kind === "video" ? VIDEO_SECONDS : SOUND_SECONDS).map((s) => ({ value: s, label: t("seconds", { s }) }))} />
              </Field>
            )}
            {kind === "audio" && audioMode === "speech" && (
              <Field label={t("voice")} hint={t("voiceHint")}>
                <Input dir="ltr" value={voice} onChange={(e) => setVoice(e.target.value)} placeholder="alloy · 21m00Tcm4TlvDq8ikWAM" />
              </Field>
            )}
            {!!kits.data?.length && (
              <Field label={t("brandKit")}>
                <Select value={brandKitId ?? ""} onChange={(e) => setBrandKitId(e.target.value ? Number(e.target.value) : null)}>
                  <option value="">{t("noBrand")}</option>
                  {kits.data.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
                </Select>
              </Field>
            )}
          </div>

          {kind !== "audio" && (
            <Field label={kind === "video" ? t("animateImage") : t("references")} hint={kind === "video" ? t("animateHint") : t("referencesHint")}>
              <div className="flex flex-wrap items-center gap-2">
                {refs.map((id) => (
                  <span key={id} className="relative">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={mediaUrl(id)} alt="" className="h-16 w-16 rounded-xl object-cover ring-1 ring-line" />
                    <button type="button" aria-label={t("remove")} onClick={() => setRefs((r) => r.filter((x) => x !== id))}
                      className="absolute -end-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-ink text-white">
                      <Icon name="close" size={12} />
                    </button>
                  </span>
                ))}
                {refs.length < (kind === "video" ? 1 : 3) && (
                  <button type="button" onClick={() => fileRef.current?.click()} disabled={uploading}
                    className="flex h-16 w-16 items-center justify-center rounded-xl border border-dashed border-line-strong text-muted transition hover:bg-fill">
                    <Icon name={uploading ? "progress_activity" : "add_photo"} spin={uploading} size={20} />
                  </button>
                )}
                <input ref={fileRef} type="file" accept="image/*" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
              </div>
            </Field>
          )}

          <ModelPicker capability={kind} value={modelId} onChange={setModelId} label={t("model")} prompt={prompt}
            seconds={effectiveSeconds} audioMode={kind === "audio" ? audioMode : "speech"} onEstimate={onEstimate} />
        </div>
      )}
    </Modal>,
    document.body,
  );
}

function JobView({ job }: { job: MediaJob }) {
  const t = useTranslations("ai.media");
  const media = job.media;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge tone={job.state === "done" ? "ok" : "neutral"}>{t(`states.${job.state}`)}</Badge>
        {job.provider && <span className="text-muted">{job.provider}{job.model_name ? ` · ${job.model_name}` : ""}</span>}
        {job.state === "done" && <span className="ms-auto text-xs text-muted" dir="ltr">{money(job.cost, true)}</span>}
      </div>
      {job.notice && <div className="rounded-xl bg-warn-bg px-3 py-2 text-[13px] text-warn">{job.notice}</div>}
      {job.state === "running" ? (
        <div className="flex aspect-video flex-col items-center justify-center gap-4 rounded-2xl bg-fill">
          <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-ink text-white">
            <Icon name="auto_awesome" size={26} duo className="animate-pulse" />
          </span>
          <div className="text-sm font-medium">{t(`creating.${job.kind}`)}</div>
          <div className="h-1.5 w-56 overflow-hidden rounded-full bg-track">
            <div className={cx("h-full rounded-full bg-ink transition-all", !job.progress && "w-1/3 animate-pulse")} style={job.progress ? { width: `${Math.max(job.progress, 6)}%` } : undefined} />
          </div>
          <div className="text-xs text-muted">{job.progress ? `${job.progress}%` : t("waiting")}</div>
        </div>
      ) : media ? (
        <div className="flex justify-center rounded-2xl bg-fill p-2">
          {media.mimetype.startsWith("image/") ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={media.url} alt={job.title} className="max-h-[52vh] rounded-xl object-contain" />
          ) : media.mimetype.startsWith("video/") ? (
            <video src={media.url} controls autoPlay muted loop playsInline className="max-h-[52vh] rounded-xl" />
          ) : (
            <div className="flex w-full flex-col items-center gap-3 py-6">
              <Icon name={job.audio_mode === "music" ? "music_note" : "graphic_eq"} size={32} className="text-text-2" />
              <audio src={media.url} controls className="w-full max-w-md" />
            </div>
          )}
        </div>
      ) : null}
      <p className="bidi line-clamp-3 text-[13px] text-muted">{job.prompt}</p>
    </div>
  );
}

/** Small button that opens the dialog — convenient for composers. */
export function AiMediaButton(props: Omit<Props, "open" | "onClose"> & { label?: string; size?: "sm" | "md" }) {
  const t = useTranslations("ai.media");
  const [open, setOpen] = useState(false);
  const { label, size = "sm", ...rest } = props;
  return (
    <>
      <Button size={size} icon="auto_awesome" className="shrink-0 whitespace-nowrap" onClick={() => setOpen(true)}>{label || t("button")}</Button>
      <AiMediaDialog {...rest} open={open} onClose={() => setOpen(false)} />
    </>
  );
}

