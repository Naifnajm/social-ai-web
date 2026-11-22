"use client";
/** "New production": before a production pipeline board is made, pick the video model (and the idea, and for the
 * quick pipeline whether an ElevenLabs voice-over replaces the clip's own sound). */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { AiProviderLogo } from "@/components/ai-brand";
import { Icon } from "@/components/icon";
import { Badge, Button, EmptyState, Field, Modal, Spinner, Switch, Textarea, cx, toast } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { credits, money } from "@/lib/ai";
import { useSession } from "@/lib/session";
import type { BoardCard, BoardTemplate, VideoModelOption } from "./types";

const MAX_TEXT = 2000;
/** clip length the pipelines' video block uses, so the price shown matches what the board will cost */
const SECONDS = { i2v: 8, t2v: 10 } as const;

export function NewProductionDialog({ template, onClose }: { template: BoardTemplate; onClose: () => void }) {
  const t = useTranslations("production.newProduction");
  const router = useRouter();
  const isAdmin = useSession((s) => s.can("admin"));
  const mode = template.video_mode ?? "t2v";
  const seconds = SECONDS[mode];
  const models = useQuery({
    queryKey: ["ai", "video-models", mode, seconds],
    queryFn: () => api.get<{ models: VideoModelOption[] }>(`/ai/video-models?mode=${mode}&seconds=${seconds}`),
  });
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<number | null>(null);
  const [voiceOver, setVoiceOver] = useState(false);
  const list = models.data?.models ?? [];
  const selected = picked ?? (list.find((m) => m.recommended) ?? list[0])?.id ?? null;
  const quick = template.key === "pipeline_quick";

  const create = useMutation({
    mutationFn: () => api.post<BoardCard>("/production/boards", {
      template: template.key, video_model_id: selected, text: text.trim() || null, voice_over: quick && voiceOver,
    }),
    onSuccess: (board) => router.push(`/production/${board.id}`),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });

  return (
    <Modal open onClose={onClose} title={t("title")} size="lg"
      footer={<>
        <Button variant="ghost" onClick={onClose}>{t("cancel")}</Button>
        <Button variant="primary" icon="add" loading={create.isPending} disabled={models.isLoading || (list.length > 0 && !selected)} onClick={() => create.mutate()}>{t("create")}</Button>
      </>}>
      <div className="flex flex-col gap-5">
        <div className="flex items-center gap-3 rounded-2xl bg-white/55 p-3 ring-1 ring-line">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-b from-[#3a3a3c] to-[#0a0a0a] text-white">
            <Icon name={template.icon} size={18} />
          </span>
          <div className="min-w-0">
            <div className="text-sm font-semibold">{template.name}</div>
            <div className="text-xs leading-snug text-muted">{template.description}</div>
          </div>
        </div>

        <Field label={t("about")} hint={t("aboutHint", { count: text.length, max: MAX_TEXT })}>
          <Textarea rows={3} maxLength={MAX_TEXT} dir="auto" value={text} placeholder={t("aboutPlaceholder")}
            onChange={(e) => setText(e.target.value)} />
        </Field>

        <div className="flex flex-col gap-2">
          <span className="text-[13px] font-medium text-text-2">{t("videoModel")}</span>
          {models.isLoading ? (
            <div className="py-6 text-center"><Spinner /></div>
          ) : !list.length ? (
            <div className="rounded-2xl bg-white/55 ring-1 ring-line">
              <EmptyState icon="movie" title={t("noModels")} text={t("noModelsText")}
                action={isAdmin && <Link href="/settings/ai" className="inline-flex h-8 items-center rounded-full bg-ink px-3.5 text-[13px] font-semibold text-white hover:bg-ink-2">{t("addProvider")}</Link>} />
            </div>
          ) : (
            <div role="radiogroup" aria-label={t("videoModel")} className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {list.map((m) => {
                const active = m.id === selected;
                return (
                  <button key={m.id} type="button" role="radio" aria-checked={active} onClick={() => setPicked(m.id)}
                    className={cx("flex items-start gap-3 rounded-2xl p-3 text-start transition",
                      active ? "bg-white shadow-[var(--shadow-lift)] ring-2 ring-ink" : "bg-white/55 ring-1 ring-line hover:bg-white/85")}>
                    <AiProviderLogo type={m.provider_type} label={m.provider} size={32} />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className="text-sm font-semibold leading-snug" dir="auto">{m.label}</span>
                        {m.recommended && <Badge tone="ink">{t("recommended")}</Badge>}
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-muted" dir="auto">{m.provider}</span>
                      <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        <span className="whitespace-nowrap text-xs font-medium text-text-2" title={m.credits != null ? money(m.cost) : undefined}>
                          {m.credits != null ? t("costCredits", { amount: credits(m.credits), seconds }) : t("cost", { amount: money(m.cost), seconds })}
                        </span>
                        {m.audio && <Badge className="whitespace-nowrap"><Icon name="graphic_eq" size={12} />{t("ownSound")}</Badge>}
                      </span>
                      {m.eu_limited && (
                        <span className="mt-1.5 flex items-center gap-1 text-xs text-warn">
                          <Icon name="warning" size={13} />{t("euLimited")}
                        </span>
                      )}
                    </span>
                    {active ? <Icon name="check_circle" size={18} className="shrink-0 text-ink" /> : <span className="h-[18px] w-[18px] shrink-0 rounded-full ring-[1.5px] ring-inset ring-black/20" />}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {quick && (
          <div className="rounded-2xl bg-white/55 p-3.5 ring-1 ring-line">
            <Switch checked={voiceOver} onChange={setVoiceOver} label={<span className="font-medium">{t("voiceOver")}</span>} />
            <p className="mt-1.5 ps-[50px] text-xs text-muted">{t("voiceOverHint")}</p>
          </div>
        )}
      </div>
    </Modal>
  );
}
