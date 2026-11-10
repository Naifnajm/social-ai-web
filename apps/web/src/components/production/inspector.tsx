"use client";
/** Right-hand panel: the settings, approval, publishing and results history of the selected block. */
import { useTranslations } from "next-intl";
import { type ReactNode, useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import { Button, Field, IconButton, Input, Segmented, Select, Textarea, cx, toast } from "@/components/ui";
import { useRouter } from "@/i18n/navigation";
import { useCanvas } from "./canvas-context";
import { ModelPicker } from "./model-picker";
import { CAPABILITY, FORMATS, GENERATIVE, KIND_META, aspectBox, isRunning, usd } from "./meta";
import { ApprovalActions } from "./approval-actions";
import type { BlockNode, OutputItem } from "./types";

function Section({ title, children }: { title?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 border-t border-line px-4 py-4 first:border-t-0">
      {title && <h4 className="text-[12px] font-semibold uppercase tracking-wide text-muted">{title}</h4>}
      {children}
    </section>
  );
}

/** A text field saved when it loses focus. */
function DraftText({ value, onSave, rows, placeholder, disabled, multiline = true }: {
  value: string; onSave: (v: string) => void; rows?: number; placeholder?: string; disabled?: boolean; multiline?: boolean;
}) {
  const [draft, setDraft] = useState(value);
  const save = () => draft !== value && onSave(draft);
  return multiline ? (
    <Textarea rows={rows || 4} value={draft} placeholder={placeholder} disabled={disabled} dir="auto"
      onChange={(e) => setDraft(e.target.value)} onBlur={save} />
  ) : (
    <Input value={draft} placeholder={placeholder} disabled={disabled} dir="auto" onChange={(e) => setDraft(e.target.value)} onBlur={save}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
  );
}

export function Inspector({ node, onClose }: { node: BlockNode; onClose: () => void }) {
  const t = useTranslations("production");
  const router = useRouter();
  const { graph, actions, readOnly, runNode, openDesign, pickFile } = useCanvas();
  const meta = KIND_META[node.kind] || KIND_META.text;
  const update = (values: Record<string, unknown>) => !readOnly && actions.updateNode(node.id, values).catch(() => undefined);
  const capability = CAPABILITY[node.kind];
  const running = isRunning(node.state);

  const sendToStudio = async () => {
    const { post_id } = await actions.sendToStudio(node.id);
    toast.success(t("sentToStudio"));
    router.push(`/studio?post=${post_id}`);
  };

  return (
    <aside className="glass-strong pop-in flex max-h-full w-full flex-col overflow-hidden rounded-[22px] !bg-white/90">
      <header className="flex items-center gap-2 border-b border-line px-4 py-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl text-white" style={{ background: meta.color }}>
          <Icon name={meta.icon} size={17} />
        </span>
        <div className="min-w-0 flex-1">
          <DraftText key={`name-${node.id}`} multiline={false} value={node.name} disabled={readOnly} onSave={(name) => update({ name })} />
        </div>
        <IconButton icon="close" label={t("close")} onClick={onClose} />
      </header>

      <div className="flex-1 overflow-y-auto">
        {node.kind === "text" && (
          <Section>
            <Field label={t("inspector.text")} hint={t("inspector.variablesHint")}>
              <DraftText key={`text-${node.id}`} rows={7} value={node.text_value} disabled={readOnly} onSave={(text_value) => update({ text_value })} />
            </Field>
          </Section>
        )}

        {GENERATIVE.includes(node.kind) && (
          <Section>
            <Field label={node.kind === "audio" && node.audio_mode === "speech" ? t("inspector.script") : t("inspector.prompt")}
              hint={node.kind === "audio" && node.audio_mode === "speech" ? t("inspector.scriptHint") : t("inspector.promptHint")}>
              <DraftText key={`prompt-${node.id}`} rows={5} value={node.prompt} disabled={readOnly} onSave={(prompt) => update({ prompt })} />
            </Field>
            <Field label={t("inspector.model")}>
              <ModelPicker capability={capability} value={node.model_id} fallback={graph.pickers[capability] || []}
                estimate={node.estimate} disabled={readOnly} onChange={(model_id) => update({ model_id })} />
            </Field>
          </Section>
        )}

        {["image", "video", "merge", "design"].includes(node.kind) && (
          <Section title={t("inspector.format")}>
            <AspectPicker value={node.aspect} disabled={readOnly} onChange={(aspect) => update({ aspect })} />
            {node.kind === "image" && (
              <Field label={t("inspector.style")}>
                <Select value={node.style || ""} disabled={readOnly} onChange={(e) => update({ style: e.target.value || null })}>
                  <option value="">{t("inspector.noStyle")}</option>
                  {graph.styles.map((s) => <option key={s} value={s}>{t(`styles.${s}`)}</option>)}
                </Select>
              </Field>
            )}
          </Section>
        )}

        {node.kind === "audio" && (
          <Section title={t("inspector.sound")}>
            <Segmented size="sm" value={node.audio_mode} onChange={(audio_mode) => update({ audio_mode })}
              options={graph.audio_modes.map((m) => ({ value: m, label: t(`audioModes.${m}`) }))} />
          </Section>
        )}

        {(node.kind === "video" || (node.kind === "audio" && node.audio_mode !== "speech")) && (
          <Section>
            <Field label={t("inspector.seconds")}>
              <Segmented size="sm" value={node.seconds} onChange={(seconds) => update({ seconds })}
                options={(node.kind === "video" ? [4, 5, 8, 10] : [5, 10, 20, 30]).map((s) => ({ value: s, label: `${s}s` }))} />
            </Field>
          </Section>
        )}

        {GENERATIVE.includes(node.kind) && (
          <Section>
            <Field label={t("inspector.variations")} hint={t("inspector.variationsHint")}>
              <Segmented size="sm" value={node.variations} onChange={(variations) => update({ variations })}
                options={[1, 2, 3, 4].map((v) => ({ value: v, label: `×${v}` }))} />
            </Field>
          </Section>
        )}

        {node.kind === "design" && (
          <Section>
            <Button variant="primary" icon="brush" disabled={readOnly} onClick={() => openDesign(node.id)}>{t("openEditor")}</Button>
          </Section>
        )}

        {node.kind === "upload" && (
          <Section>
            <Button icon="upload" disabled={readOnly} onClick={() => pickFile(node.id)}>{node.output ? t("replaceFile") : t("chooseFile")}</Button>
            {node.output && <span className="bidi truncate text-xs text-muted" dir="auto">{node.output.filename}</span>}
          </Section>
        )}

        {node.kind === "reframe" && (
          <Section title={t("inspector.formats")}>
            <div className="grid grid-cols-4 gap-1.5">
              {FORMATS.map((f) => {
                const active = node.formats.includes(f);
                const box = aspectBox(f, 28);
                return (
                  <button key={f} type="button" disabled={readOnly}
                    onClick={() => update({ formats: active ? node.formats.filter((x) => x !== f) : [...node.formats, f] })}
                    className={cx("flex flex-col items-center gap-1.5 rounded-xl border px-1 pb-2 pt-2.5 text-xs", active ? "border-ink font-semibold text-ink" : "border-line bg-white/60 text-muted")}>
                    <span className={cx("rounded", active ? "bg-ink" : "bg-black/20")} style={box} />
                    <span dir="ltr">{f}</span>
                  </button>
                );
              })}
            </div>
            <Segmented size="sm" value={node.fit_mode} onChange={(fit_mode) => update({ fit_mode })}
              options={[{ value: "blur", label: t("fit.blur") }, { value: "crop", label: t("fit.crop") }]} />
          </Section>
        )}

        {node.kind === "captions" && (
          <Section title={t("inspector.captions")}>
            {!graph.subtitles && <p className="rounded-xl bg-warn-bg px-3 py-2 text-xs text-warn">{t("inspector.noSubtitles")}</p>}
            <Field label={t("inspector.position")}>
              <Segmented size="sm" value={node.caption_position} onChange={(caption_position) => update({ caption_position })}
                options={["top", "center", "bottom"].map((p) => ({ value: p, label: t(`captionPositions.${p}`) }))} />
            </Field>
            <Field label={t("inspector.size")}>
              <Segmented size="sm" value={node.caption_size} onChange={(caption_size) => update({ caption_size })}
                options={["s", "m", "l"].map((s) => ({ value: s, label: t(`captionSizes.${s}`) }))} />
            </Field>
            <Field label={t("inspector.language")} hint={t("inspector.languageHint")}>
              <DraftText key={`lang-${node.id}`} multiline={false} value={node.caption_language} disabled={readOnly}
                placeholder="ar, en…" onSave={(caption_language) => update({ caption_language })} />
            </Field>
          </Section>
        )}

        {node.kind === "template" && (
          <Section title={t("inspector.template")}>
            {graph.brand_templates.length ? (
              <Select value={node.template_ref || ""} disabled={readOnly} onChange={(e) => update({ template_ref: e.target.value || null })}>
                <option value="">{t("inspector.chooseTemplate")}</option>
                {graph.brand_templates.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </Select>
            ) : (
              <p className="text-xs text-muted">{t("inspector.noTemplates")}</p>
            )}
            <Field label={t("inspector.templateText")}>
              <DraftText key={`tt-${node.id}`} rows={2} value={node.text_value} disabled={readOnly} onSave={(text_value) => update({ text_value })} />
            </Field>
          </Section>
        )}

        {node.kind === "approval" && (
          <Section title={t("inspector.approval")}>
            <Field label={t("inspector.approver")} hint={t("inspector.approverHint")}>
              <Select value={node.approver_id ?? ""} disabled={readOnly} onChange={(e) => update({ approver_id: e.target.value ? Number(e.target.value) : null })}>
                <option value="">{t("inspector.boardOwner")}</option>
                {graph.members.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </Select>
            </Field>
            <ApprovalActions node={node} />
          </Section>
        )}

        {node.kind === "post" && <PostSettings node={node} update={update} />}

        {node.outputs.length > 0 && <History node={node} />}
      </div>

      {!readOnly && node.kind !== "text" && (
        <footer className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-3">
          <Button variant="primary" size="sm" icon={running ? undefined : "play_arrow"} loading={running} onClick={() => runNode(node.id)}>
            {t("runFromHere")}
          </Button>
          {GENERATIVE.includes(node.kind) && node.state === "done" && (
            <Button size="sm" icon="refresh" disabled={running} onClick={() => runNode(node.id, true)}>{t("regenerate")}</Button>
          )}
          {(node.output || node.output_text || node.post_id) && (
            <Button size="sm" variant="ghost" icon="open_in_new" onClick={sendToStudio}>{node.kind === "post" ? t("openPost") : t("sendToStudio")}</Button>
          )}
          {node.estimate && node.estimate.cost > 0 && <span className="ms-auto text-xs tabular-nums text-muted">≈ {usd(node.estimate.cost)}</span>}
        </footer>
      )}
    </aside>
  );
}

function AspectPicker({ value, onChange, disabled }: { value: string; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <div className="grid grid-cols-4 gap-1.5">
      {FORMATS.map((f) => (
        <button key={f} type="button" disabled={disabled} onClick={() => onChange(f)}
          className={cx("flex flex-col items-center gap-1.5 rounded-xl border px-1 pb-2 pt-2.5 text-xs", f === value ? "border-ink font-semibold text-ink" : "border-line bg-white/60 text-muted")}>
          <span className={cx("rounded", f === value ? "bg-ink" : "bg-black/20")} style={aspectBox(f, 28)} />
          <span dir="ltr">{f}</span>
        </button>
      ))}
    </div>
  );
}

function PostSettings({ node, update }: { node: BlockNode; update: (v: Record<string, unknown>) => void }) {
  const t = useTranslations("production");
  const { graph, readOnly } = useCanvas();
  const toggle = (id: number) => update({ account_ids: node.account_ids.includes(id) ? node.account_ids.filter((x) => x !== id) : [...node.account_ids, id] });
  const local = node.publish_at ? new Date(node.publish_at) : null;
  const localValue = local ? new Date(local.getTime() - local.getTimezoneOffset() * 60000).toISOString().slice(0, 16) : "";
  return (
    <Section title={t("inspector.publishOn")}>
      {graph.accounts.length ? (
        <div className="grid max-h-56 gap-1.5 overflow-y-auto">
          {graph.accounts.map((a) => {
            const active = node.account_ids.includes(a.id);
            return (
              <button key={a.id} type="button" disabled={readOnly} onClick={() => toggle(a.id)}
                className={cx("flex items-center gap-2 rounded-xl border px-2.5 py-1.5 text-start text-[13px]", active ? "border-ink shadow-[inset_0_0_0_1px_#0a0a0a]" : "border-line bg-white/60")}>
                <PlatformBadge platform={a.platform} size={22} />
                <span className="bidi flex-1 truncate" dir="auto">{a.name}</span>
                {active && <Icon name="check" size={15} />}
              </button>
            );
          })}
        </div>
      ) : (
        <p className="text-xs text-muted">{t("inspector.noAccounts")}</p>
      )}
      <Field label={t("inspector.publishMode")}>
        <Select value={node.publish_mode} disabled={readOnly} onChange={(e) => update({ publish_mode: e.target.value })}>
          {graph.publish_modes.map((m) => <option key={m} value={m}>{t(`publishModes.${m}`)}</option>)}
        </Select>
      </Field>
      {node.publish_mode === "at" && (
        <Field label={t("inspector.publishAt")}>
          <Input type="datetime-local" dir="ltr" value={localValue} disabled={readOnly}
            onChange={(e) => e.target.value && update({ publish_at: new Date(e.target.value).toISOString() })} />
        </Field>
      )}
      {node.post_state && <p className="text-xs text-muted">{t("inspector.linkedPost", { state: t(`postStates.${node.post_state}`) })}</p>}
    </Section>
  );
}

function History({ node }: { node: BlockNode }) {
  const t = useTranslations("production");
  const { actions, readOnly } = useCanvas();
  const runs = new Map<number, OutputItem[]>();
  for (const o of node.outputs) runs.set(o.run, [...(runs.get(o.run) || []), o]);
  return (
    <Section title={t("inspector.history")}>
      {[...runs.entries()].map(([run, items]) => (
        <div key={run} className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2 text-[11px] text-muted">
            <span className="font-semibold text-ink">{t("inspector.runNo", { n: run })}</span>
            {items[0].model && <span className="font-mono" dir="ltr">{items[0].model}</span>}
            {items.reduce((s, o) => s + o.cost, 0) > 0 && <span className="tabular-nums">{usd(items.reduce((s, o) => s + o.cost, 0))}</span>}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {items.map((o) => (
              <button key={o.id} type="button" disabled={readOnly} onClick={() => actions.selectOutput(node.id, o.id)}
                className={cx("overflow-hidden rounded-xl border-2 bg-fill-2 text-[11px] font-semibold text-muted", o.selected ? "border-ink" : "border-transparent",
                  o.media ? "h-14 w-14" : "w-full px-2.5 py-1.5 text-start font-normal")}>
                {o.media?.kind === "image" ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={o.media.url} alt="" className="h-full w-full object-cover" />
                ) : o.media ? (
                  <span className="flex h-full w-full flex-col items-center justify-center gap-0.5">
                    <Icon name={o.media.kind === "video" ? "movie" : "graphic_eq"} size={16} />{o.aspect}
                  </span>
                ) : (
                  <span className="bidi line-clamp-3 text-xs text-text" dir="auto">{o.text}</span>
                )}
              </button>
            ))}
          </div>
        </div>
      ))}
    </Section>
  );
}
