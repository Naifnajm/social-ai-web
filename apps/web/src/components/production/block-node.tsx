"use client";
/** One block on the canvas: glass card with header, meta pills, typed input ports, preview, versions and run. */
import { Handle, type Node, type NodeProps, Position } from "@xyflow/react";
import { useTranslations } from "next-intl";
import { memo, useMemo } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import { cx } from "@/components/ui";
import { useCanvas } from "./canvas-context";
import { GENERATIVE, KIND_META, NODE_W, isRunning, typeColor, usd } from "./meta";
import type { BlockNode as Block, OutputItem } from "./types";

export type BlockFlowNode = Node<{ block: Block }, "block">;

const WAVE = [8, 14, 22, 30, 18, 26, 34, 20, 12, 24, 32, 16, 10, 22, 28, 14, 8, 18, 26, 12];

function StateIcon({ state }: { state: string }) {
  if (state === "done") return <Icon name="check_circle" size={17} className="text-[#34c759]" />;
  if (state === "failed") return <Icon name="error" size={17} className="text-bad" />;
  if (state === "waiting") return <Icon name="schedule" size={17} className="text-warn" />;
  if (isRunning(state)) return <Icon name="progress_activity" size={16} spin className="text-muted" />;
  return null;
}

function Preview({ block }: { block: Block }) {
  const t = useTranslations("production");
  const { pickFile, openDesign } = useCanvas();
  const media = block.output;
  if (block.kind === "approval") {
    const tone = block.approval_state === "approved" ? "text-ok" : block.approval_state === "rejected" ? "text-bad" : "text-warn";
    return (
      <div className={cx("mx-3 mt-1 rounded-2xl px-3 py-3 text-[13px]", block.state === "waiting" ? "bg-warn-bg" : "bg-fill")}>
        <div className={cx("flex items-center gap-1.5 font-semibold", block.approval_state ? tone : "text-muted")}>
          <Icon name={block.approval_state === "approved" ? "verified" : block.approval_state === "rejected" ? "block" : "verified_user"} size={16} />
          {t(`approval.${block.approval_state || "none"}`)}
        </div>
        {block.approver_name && <div className="mt-1 text-xs text-muted">{t("approval.by", { name: block.approver_name })}</div>}
        {block.approval_comment && <div className="bidi mt-1 text-xs text-text-2" dir="auto">“{block.approval_comment}”</div>}
      </div>
    );
  }
  if (block.kind === "post") {
    return (
      <div className="mx-3 mt-1 flex min-h-[64px] flex-col justify-center gap-1 rounded-2xl bg-fill px-3 py-3 text-[13px]">
        <div className="flex items-center gap-1.5 font-semibold">
          <Icon name={block.post_id ? "outbox" : "send"} size={16} />
          {block.post_id ? t(`postStates.${block.post_state || "draft"}`) : t(`publishModes.${block.publish_mode}`)}
        </div>
        <AccountsRow ids={block.account_ids} />
      </div>
    );
  }
  if (media?.kind === "image") {
    return (
      <div className="mx-3 mt-1 overflow-hidden rounded-2xl bg-black/5">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={media.url} alt="" className="block max-h-[260px] w-full object-cover" draggable={false} />
      </div>
    );
  }
  if (media?.kind === "video") {
    return (
      <div className="mx-3 mt-1 overflow-hidden rounded-2xl bg-black">
        <video src={media.url} className="nodrag block max-h-[260px] w-full object-cover" muted loop playsInline controls preload="metadata" />
      </div>
    );
  }
  if (media?.kind === "audio") {
    return (
      <div className="mx-3 mt-1 rounded-2xl bg-fill px-3 pb-2 pt-3">
        <div className="flex h-10 items-center justify-center gap-[3px]" aria-hidden>
          {WAVE.map((h, i) => <span key={i} className="w-1 rounded-full bg-ink/70" style={{ height: h }} />)}
        </div>
        <audio src={media.url} controls className="nodrag mt-2 h-8 w-full" preload="none" />
      </div>
    );
  }
  const text = block.kind === "text" ? block.output_text || block.text_value : block.output_text;
  if (text) {
    return <div className="bidi nowheel mx-3 mt-1 max-h-[170px] overflow-auto whitespace-pre-wrap rounded-2xl bg-white/60 px-3 py-2.5 text-[12.5px] leading-relaxed" dir="auto">{text}</div>;
  }
  const hint = block.kind === "upload" ? t("hints.upload") : block.kind === "design" ? t("hints.design") : block.kind === "text" ? t("hints.text") : t("hints.empty");
  const action = block.kind === "upload" ? () => pickFile(block.id) : block.kind === "design" ? () => openDesign(block.id) : undefined;
  return (
    <button type="button" onClick={action} disabled={!action}
      className={cx("nodrag mx-3 mt-1 flex min-h-[110px] w-[calc(100%-24px)] flex-col items-center justify-center gap-1.5 rounded-2xl border-[1.5px] border-dashed border-black/15 px-4 py-4 text-center text-xs text-muted", action && "hover:border-black/30 hover:bg-white/50")}>
      <Icon name={KIND_META[block.kind]?.icon || "add"} size={24} className="opacity-50" />
      {hint}
    </button>
  );
}

function AccountsRow({ ids }: { ids: number[] }) {
  const { graph } = useCanvas();
  const accounts = graph.accounts.filter((a) => ids.includes(a.id));
  if (!accounts.length) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {accounts.slice(0, 6).map((a) => <PlatformBadge key={a.id} platform={a.platform} size={20} />)}
    </div>
  );
}

function Versions({ block }: { block: Block }) {
  const { actions, readOnly } = useCanvas();
  const current = block.outputs.filter((o) => o.run === block.run_no);
  const items: OutputItem[] = (current.length > 1 ? current : block.outputs).slice(0, 6);
  if (items.length < 2) return null;
  return (
    <div className="nodrag flex gap-1 px-3 pt-2">
      {items.map((o, index) => (
        <button key={o.id} type="button" disabled={readOnly} onClick={() => actions.selectOutput(block.id, o.id)}
          className={cx("h-9 w-9 overflow-hidden rounded-lg border-2 bg-fill-2 text-[10px] font-bold text-muted", o.selected ? "border-ink text-ink" : "border-transparent")}
          title={o.aspect || `#${index + 1}`}>
          {o.media?.kind === "image" ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={o.media.url} alt="" className="h-full w-full object-cover" draggable={false} />
          ) : (o.aspect || index + 1)}
        </button>
      ))}
    </div>
  );
}

function BlockNodeView({ data, selected }: NodeProps<BlockFlowNode>) {
  const block = data.block;
  const t = useTranslations("production");
  const { graph, runNode, readOnly, openDesign } = useCanvas();
  const kind = useMemo(() => graph.kinds.find((k) => k.key === block.kind), [graph.kinds, block.kind]);
  const meta = KIND_META[block.kind] || KIND_META.text;
  const counts = useMemo(() => {
    const result: Record<string, number> = {};
    for (const e of graph.edges) if (e.target === block.id) result[e.port] = (result[e.port] || 0) + 1;
    return result;
  }, [graph.edges, block.id]);
  const generative = GENERATIVE.includes(block.kind);
  const running = isRunning(block.state);
  const outColor = typeColor(block.out_type);
  const canRun = !readOnly && block.kind !== "text";

  return (
    <div
      style={{ width: NODE_W, ["--kind" as string]: meta.color }}
      className={cx(
        "group relative rounded-[22px] border border-white/70 pb-3 backdrop-blur-xl transition",
        selected ? "bg-white/95" : "bg-white/75 hover:bg-white/85",
        selected ? "shadow-[0_0_0_1.5px_#0a0a0a,0_20px_44px_-14px_rgba(0,0,0,.3)]"
          : block.state === "failed" ? "shadow-[0_0_0_1.5px_rgba(217,45,32,.45),0_12px_30px_-12px_rgba(217,45,32,.2)]"
          : block.state === "waiting" ? "shadow-[0_0_0_2px_var(--warn),0_12px_30px_-12px_rgba(0,0,0,.18)]"
          : running ? "shadow-[0_0_0_4px_color-mix(in_srgb,var(--kind)_20%,transparent),0_12px_30px_-12px_rgba(0,0,0,.18)]"
          : "shadow-[0_0_0_1px_rgba(0,0,0,.06),inset_0_1px_0_rgba(255,255,255,.7),0_12px_30px_-12px_rgba(0,0,0,.18)]",
      )}
    >
      {/* header */}
      <div className="relative flex h-11 items-center gap-2 px-3.5">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg"
          style={{ color: `color-mix(in srgb, ${meta.color} 82%, #000)`, background: `color-mix(in srgb, ${meta.color} 13%, #fff)` }}>
          <Icon name={meta.icon} size={15} />
        </span>
        <span className="bidi min-w-0 flex-1 truncate text-[13.5px] font-semibold tracking-tight" dir="auto">{block.name}</span>
        <StateIcon state={block.state} />
        {block.out_type && (
          <Handle type="source" position={Position.Right} id="out" isConnectable={!readOnly}
            className="!h-4 !w-4 !border-0 !bg-white !shadow-[0_0_0_1px_rgba(0,0,0,.14),0_1px_3px_rgba(0,0,0,.15)]"
            style={{ right: -8 }}>
            <span className="pointer-events-none absolute inset-[3px] rounded-full" style={{ background: outColor }} />
          </Handle>
        )}
      </div>

      {/* meta pills */}
      {(generative || block.cost > 0 || ["reframe", "merge", "design"].includes(block.kind)) && (
        <div className="flex h-7 items-center gap-1 overflow-hidden px-3.5">
          {generative && (
            <span className="max-w-[130px] truncate rounded-full bg-white/90 px-2 py-px font-mono text-[10.5px] text-ink shadow-[inset_0_0_0_1px_var(--line)]">
              {block.model_label || t("defaultModel")}
            </span>
          )}
          {["image", "video", "merge", "design"].includes(block.kind) && <span className="rounded-full bg-fill-2 px-2 py-px text-[10.5px] text-muted">{block.aspect}</span>}
          {block.kind === "reframe" && <span className="rounded-full bg-fill-2 px-2 py-px text-[10.5px] text-muted">{block.formats.join(" · ")}</span>}
          {block.variations > 1 && <span className="rounded-full bg-fill-2 px-2 py-px text-[10.5px] text-muted">×{block.variations}</span>}
          {block.cost > 0 ? (
            <span className="rounded-full bg-ok-bg px-2 py-px text-[10.5px] tabular-nums text-ok">{usd(block.cost)}</span>
          ) : block.estimate && block.estimate.cost > 0 ? (
            <span className="rounded-full bg-fill-2 px-2 py-px text-[10.5px] tabular-nums text-ink">≈ {usd(block.estimate.cost)}</span>
          ) : null}
        </div>
      )}

      {/* typed input ports */}
      {!!kind?.ports.length && (
        <div className="pb-1">
          {kind.ports.map((port) => {
            const colors = port.accepts.map(typeColor);
            return (
              <div key={port.key} className="relative flex h-7 items-center gap-1.5 px-3.5 text-[11.5px] text-muted hover:bg-fill">
                <Handle type="target" position={Position.Left} id={port.key} isConnectable={!readOnly}
                  className="!h-3.5 !w-3.5 !border-0 !bg-white !shadow-[0_0_0_1px_rgba(0,0,0,.14),0_1px_3px_rgba(0,0,0,.12)]"
                  style={{ left: -7 }}>
                  <span className="pointer-events-none absolute inset-[3px] rounded-full"
                    style={{ background: colors.length > 1 ? `conic-gradient(${colors.map((c, i) => `${c} ${(i * 100) / colors.length}% ${((i + 1) * 100) / colors.length}%`).join(",")})` : colors[0] }} />
                </Handle>
                <span className="bidi flex-1 truncate" dir="auto">{port.label}</span>
                {!!counts[port.key] && <span className="min-w-[18px] rounded-full bg-fill-2 px-1.5 text-center text-[10px] text-ink">{counts[port.key]}</span>}
              </div>
            );
          })}
        </div>
      )}

      <Preview block={block} />
      <Versions block={block} />

      {block.prompt && generative && !block.output && !block.output_text && (
        <p className="bidi mx-3.5 mt-2 line-clamp-3 text-[11.5px] leading-snug text-muted" dir="auto">{block.prompt}</p>
      )}
      {block.error && <p className="bidi mx-3 mt-2 rounded-[10px] bg-bad-bg px-2.5 py-1.5 text-[11.5px] text-bad" dir="auto">{block.error}</p>}
      {!block.error && block.notice && <p className="bidi mx-3 mt-2 rounded-[10px] bg-warn-bg px-2.5 py-1.5 text-[11.5px] text-warn" dir="auto">{block.notice}</p>}

      {canRun && (
        <div className="flex items-center justify-end gap-1.5 px-3 pt-2.5">
          {block.kind === "design" && (
            <button type="button" className="nodrag h-7 rounded-full bg-fill-2 px-3 text-[12px] font-medium hover:bg-black/10" onClick={() => openDesign(block.id)}>
              {t("openEditor")}
            </button>
          )}
          <RunButton block={block} onRun={(force) => runNode(block.id, force)} />
        </div>
      )}

      {running && (
        <div className="absolute inset-x-5 bottom-1.5 h-[3px] overflow-hidden rounded-full bg-fill-2">
          <div className="h-full rounded-full bg-ink transition-[width] duration-700" style={{ width: `${Math.max(8, block.progress || 0)}%` }} />
        </div>
      )}
    </div>
  );
}

function RunButton({ block, onRun }: { block: Block; onRun: (force: boolean) => void }) {
  const t = useTranslations("production");
  const running = isRunning(block.state);
  const again = block.fresh && GENERATIVE.includes(block.kind);
  return (
    <button type="button" disabled={running} onClick={() => onRun(again)}
      className="nodrag inline-flex h-7 items-center gap-1 rounded-full bg-ink px-3 text-[12px] font-medium text-white shadow-[0_6px_14px_-6px_rgba(0,0,0,.5)] transition hover:-translate-y-px disabled:opacity-40">
      <Icon name={running ? "progress_activity" : again ? "refresh" : "play_arrow"} spin={running} size={14} />
      {running ? t("running") : again ? t("regenerate") : t("run")}
    </button>
  );
}

export const BlockNodeComponent = memo(BlockNodeView);
