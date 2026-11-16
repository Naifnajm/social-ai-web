"use client";
/** Right-hand panel: the settings, approval, publishing and results history of the selected block. */
import { useTranslations } from "next-intl";
import { type ReactNode, useState } from "react";
import { CameraPanel } from "@/components/camera-panel";
import { Icon, PlatformBadge } from "@/components/icon";
import { Button, Field, IconButton, Input, Segmented, Select, Textarea, cx, toast } from "@/components/ui";
import { useRouter } from "@/i18n/navigation";
import { credits as creditsText } from "@/lib/ai";
import { ErrorText, StateIcon } from "./block-node";
import { useCanvas } from "./canvas-context";
import { useOutputCost } from "./lightbox";
import { ModelPicker } from "./model-picker";
import { CAPABILITY, FORMATS, GENERATIVE, KIND_META, aspectBox, isRunning, usd } from "./meta";
import { ApprovalActions } from "./approval-actions";
import { pushUndo, updateNode, useCanvasStore } from "./store";
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
  const [shown, setShown] = useState(value);
  if (shown !== value) { // changed elsewhere (undo / redo, another person)
    setShown(value);
    setDraft(value);
  }
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
  const { graph, actions, readOnly, ui } = useCanvas();
  const meta = KIND_META[node.kind] || KIND_META.text;
  const update = (values: Record<string, unknown>) => updateNode(node.id, values);
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
        <StateIcon state={node.state} />
        <IconButton icon="close" label={t("close")} onClick={onClose} />
      </header>
      {(node.error || node.notice) && (
        <div className="border-b border-line pb-2.5">
          {node.error ? <ErrorText text={node.error} /> : <p className="bidi mx-3 mt-2 rounded-[10px] bg-warn-bg px-2.5 py-1.5 text-[11.5px] text-warn" dir="auto">{node.notice}</p>}
        </div>
      )}

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
            {(node.kind === "image" || node.kind === "video") && (
              <CameraPanel kind={node.kind} value={node.shot} disabled={readOnly} onChange={(shot) => update({ shot })} />
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
            <Button variant="primary" icon="brush" disabled={readOnly} onClick={() => ui.openDesign(node.id)}>{t("openEditor")}</Button>
          </Section>
        )}

        {node.kind === "upload" && (
          <Section>
            <Button icon="upload" disabled={readOnly} onClick={() => ui.pickFile(node.id)}>{node.output ? t("replaceFile") : t("chooseFile")}</Button>
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

        <Inputs node={node} />
        {node.outputs.length > 0 && <History node={node} />}
      </div>

      {!readOnly && node.kind !== "text" && (
        <footer className="flex flex-col gap-2 border-t border-line px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="primary" size="sm" icon={running ? undefined : "fast_forward"} loading={running} title={`${t("runFromHere")} · Ctrl+Enter`}
              onClick={() => ui.run([node.id], { downstream: true })}>
              {t("runFromHere")}
            </Button>
            <Button size="sm" icon="play_arrow" disabled={running} onClick={() => ui.run([node.id], { downstream: false })} title={t("runOnlyHint")}>
              {t("menu.runOnly")}
            </Button>
            {GENERATIVE.includes(node.kind) && node.state === "done" && (
              <Button size="sm" variant="ghost" icon="refresh" disabled={running} onClick={() => ui.run([node.id], { force: true, downstream: false })}>{t("regenerate")}</Button>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {(node.output || node.output_text || node.post_id) && (
              <Button size="sm" variant="ghost" icon="open_in_new" onClick={sendToStudio}>{node.kind === "post" ? t("openPost") : t("sendToStudio")}</Button>
            )}
            <EstimateLine node={node} />
          </div>
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

/** Price of one run of the block: AI credits and dollars when credits pay for it. */
function EstimateLine({ node }: { node: BlockNode }) {
  const t = useTranslations("production");
  const est = node.estimate;
  if (!est || !(est.cost > 0)) return null;
  return (
    <span className="ms-auto text-end text-xs tabular-nums text-muted" title={t("estimateHint")}>
      {est.credits != null ? <><span className="font-medium text-ink">{t("approxCredits", { amount: creditsText(est.credits) })}</span> · {usd(est.cost)}</> : `≈ ${usd(est.cost)}`}
    </span>
  );
}

/** The links into this block (also reachable by keyboard and screen readers), each can be removed. */
function Inputs({ node }: { node: BlockNode }) {
  const t = useTranslations("production");
  const { graph, actions, readOnly } = useCanvas();
  const ports = useCanvasStore((s) => s.kinds.get(node.kind)?.ports);
  const links = graph.edges.filter((e) => e.target === node.id);
  if (!ports?.length) return null;
  const unlink = async (edgeId: number) => {
    const removed = await actions.archive([], [edgeId]).catch(() => null);
    if (removed?.edge_ids.length) pushUndo({ type: "archive", ...removed });
  };
  return (
    <Section title={t("inspector.inputs")}>
      {links.length ? (
        <ul className="flex flex-col gap-1">
          {links.map((e) => {
            const source = graph.nodes.find((n) => n.id === e.source);
            const port = ports.find((p) => p.key === e.port);
            return (
              <li key={e.id} className="flex items-center gap-2 rounded-xl bg-white/60 px-2.5 py-1.5 text-[13px] ring-1 ring-line">
                <Icon name={(source && KIND_META[source.kind]?.icon) || "link"} size={15} className="text-text-2" />
                <span className="bidi min-w-0 flex-1 truncate" dir="auto">{source?.name}</span>
                <span className="shrink-0 text-xs text-muted">→ {port?.label || e.port}</span>
                {!readOnly && (
                  <button type="button" onClick={() => unlink(e.id)} aria-label={t("inspector.unlink", { name: source?.name || "" })} title={t("inspector.unlink", { name: source?.name || "" })}
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-muted hover:bg-fill-2 hover:text-ink">
                    <Icon name="link_off" size={14} />
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      ) : <p className="text-xs text-muted">{t("inspector.noInputs")}</p>}
    </Section>
  );
}

function History({ node }: { node: BlockNode }) {
  const t = useTranslations("production");
  const { ui } = useCanvas();
  const costOf = useOutputCost();
  const runs = new Map<number, OutputItem[]>();
  for (const o of node.outputs) runs.set(o.run, [...(runs.get(o.run) || []), o]);
  return (
    <Section title={t("inspector.history")}>
      {[...runs.entries()].map(([run, items]) => (
        <div key={run} className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2 text-[11px] text-muted">
            <span className="font-semibold text-ink">{t("inspector.runNo", { n: run })}</span>
            {items[0].model && <span className="font-mono" dir="ltr">{items[0].model}</span>}
            {costOf(items.reduce((s, o) => s + o.cost, 0), node) && <span className="tabular-nums">{costOf(items.reduce((s, o) => s + o.cost, 0), node)}</span>}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {items.map((o) => (
              <button key={o.id} type="button" onClick={() => ui.openLightbox(node.id, o.id)} aria-pressed={o.selected}
                title={[o.selected ? t("lightbox.inUse") : null, costOf(o.cost, node)].filter(Boolean).join(" · ") || undefined}
                className={cx("overflow-hidden rounded-xl border-2 bg-fill-2 text-[11px] font-semibold text-muted transition-colors duration-150", o.selected ? "border-ink" : "border-transparent hover:border-black/20",
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
