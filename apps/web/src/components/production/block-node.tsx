"use client";
/**
 * One block on the canvas: glass card with header, meta pills, typed input ports, preview, versions and run.
 * Below COMPACT_ZOOM it is drawn as a compact card (icon, name, state, thumbnail) that stays readable and is cheap.
 * Each block reads its own slice of the canvas store, so a poll re-renders only the blocks that changed.
 */
import { Handle, type Node, type NodeProps, Position, useConnection, useStore } from "@xyflow/react";
import { useTranslations } from "next-intl";
import { type CSSProperties, memo } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import { cx } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { credits as creditsText } from "@/lib/ai";
import { useSession } from "@/lib/session";
import { COMPACT_ZOOM, GENERATIVE, KIND_META, NODE_W, isRunning, typeColor, usd } from "./meta";
import { canLink, useCanvasStore } from "./store";
import type { BlockNode as Block, OutputItem, Port } from "./types";

export type BlockFlowNode = Node<{ block: Block }, "block">;

const WAVE = [8, 14, 22, 30, 18, 26, 34, 20, 12, 24, 32, 16, 10, 22, 28, 14, 8, 18, 26, 12];
const EMPTY_COUNTS: Record<string, number> = {};
const NO_PORTS: Port[] = [];

/** Dev only: counts block renders (window.__blockRenders) to check that polls re-render only what changed. */
function countRender() {
  if (process.env.NODE_ENV !== "production" && typeof window !== "undefined") {
    const w = window as unknown as { __blockRenders?: number };
    w.__blockRenders = (w.__blockRenders || 0) + 1;
  }
}

export function StateIcon({ state, size = 17 }: { state: string; size?: number }) {
  const t = useTranslations("production.states");
  const label = t(state);
  if (state === "done") return <span role="img" aria-label={label} title={label} className="flex"><Icon name="check_circle" size={size} className="text-[#34c759]" /></span>;
  if (state === "failed") return <span role="img" aria-label={label} title={label} className="flex"><Icon name="error" size={size} className="text-bad" /></span>;
  if (state === "waiting") return <span role="img" aria-label={label} title={label} className="flex"><Icon name="schedule" size={size} className="text-warn" /></span>;
  if (isRunning(state)) return <span role="img" aria-label={label} title={label} className="flex"><Icon name="progress_activity" size={size - 1} spin className="text-muted" /></span>;
  return null;
}

/** Price of a block for the card: what it cost (done) or what a run would cost, in AI credits when they pay for it. */
export function useBlockPrice(block: Block) {
  const t = useTranslations("production");
  const perUsd = useCanvasStore((s) => s.creditsPerUsd);
  const inCredits = block.estimate?.credits != null && !!perUsd;
  if (block.cost > 0) {
    return { spent: true, text: inCredits ? t("creditsAmount", { amount: creditsText(block.cost * perUsd!) }) : usd(block.cost) };
  }
  if (block.estimate?.credits != null && block.estimate.credits > 0) return { spent: false, text: t("approxCredits", { amount: creditsText(block.estimate.credits) }) };
  if (block.estimate && block.estimate.cost > 0) return { spent: false, text: `≈ ${usd(block.estimate.cost)}` };
  return null;
}

function ExpandButton({ onClick }: { onClick: () => void }) {
  const t = useTranslations("production");
  return (
    <button type="button" onClick={onClick} aria-label={t("lightbox.open")} title={t("lightbox.open")}
      className="nodrag absolute end-2 top-2 flex h-7 w-7 items-center justify-center rounded-full bg-black/55 text-white opacity-0 backdrop-blur-md transition-opacity duration-150 hover:bg-black/75 focus-visible:opacity-100 group-hover/preview:opacity-100">
      <Icon name="crop_free" size={14} />
    </button>
  );
}

function Preview({ block }: { block: Block }) {
  const t = useTranslations("production");
  const ui = useCanvasStore((s) => s.ui);
  const media = block.output;
  const open = () => ui.openLightbox(block.id);
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
      <div className="group/preview relative mx-3 mt-1 overflow-hidden rounded-2xl bg-black/5">
        <button type="button" onClick={open} className="nodrag block w-full cursor-zoom-in" aria-label={t("lightbox.open")}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={media.url} alt="" loading="lazy" decoding="async" className="block max-h-[260px] w-full object-cover" draggable={false} />
        </button>
      </div>
    );
  }
  if (media?.kind === "video") {
    return (
      <div className="group/preview relative mx-3 mt-1 overflow-hidden rounded-2xl bg-black">
        <video src={media.url} className="nodrag block max-h-[260px] w-full object-cover" muted loop playsInline controls preload="metadata" />
        <ExpandButton onClick={open} />
      </div>
    );
  }
  if (media?.kind === "audio") {
    return (
      <div className="group/preview relative mx-3 mt-1 rounded-2xl bg-fill px-3 pb-2 pt-3">
        <div className="flex h-10 items-center justify-center gap-[3px]" aria-hidden>
          {WAVE.map((h, i) => <span key={i} className="w-1 rounded-full bg-ink/70" style={{ height: h }} />)}
        </div>
        <audio src={media.url} controls className="nodrag mt-2 h-8 w-full" preload="none" />
        <ExpandButton onClick={open} />
      </div>
    );
  }
  const text = block.kind === "text" ? block.output_text || block.text_value : block.output_text;
  if (text) {
    return (
      <div className="group/preview relative mx-3 mt-1">
        <div className="bidi nowheel max-h-[170px] overflow-auto whitespace-pre-wrap rounded-2xl bg-white/60 px-3 py-2.5 text-[12.5px] leading-relaxed" dir="auto">{text}</div>
        {block.kind !== "text" && <ExpandButton onClick={open} />}
      </div>
    );
  }
  const hint = block.kind === "upload" ? t("hints.upload") : block.kind === "design" ? t("hints.design") : block.kind === "text" ? t("hints.text") : t("hints.empty");
  const action = block.kind === "upload" ? () => ui.pickFile(block.id) : block.kind === "design" ? () => ui.openDesign(block.id) : block.kind === "text" ? () => ui.select([block.id]) : undefined;
  return (
    <button type="button" onClick={action} disabled={!action}
      className={cx("nodrag mx-3 mt-1 flex min-h-[110px] w-[calc(100%-24px)] flex-col items-center justify-center gap-1.5 rounded-2xl border-[1.5px] border-dashed border-black/15 px-4 py-4 text-center text-xs text-muted transition-colors duration-150", action && "hover:border-black/30 hover:bg-white/50")}>
      <Icon name={KIND_META[block.kind]?.icon || "add"} size={24} className="opacity-50" />
      {hint}
    </button>
  );
}

function AccountsRow({ ids }: { ids: number[] }) {
  const all = useCanvasStore((s) => s.graph?.accounts);
  const accounts = (all || []).filter((a) => ids.includes(a.id));
  if (!accounts.length) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {accounts.slice(0, 6).map((a) => <PlatformBadge key={a.id} platform={a.platform} size={20} />)}
    </div>
  );
}

function Versions({ block }: { block: Block }) {
  const t = useTranslations("production");
  const ui = useCanvasStore((s) => s.ui);
  const current = block.outputs.filter((o) => o.run === block.run_no);
  const items: OutputItem[] = (current.length > 1 ? current : block.outputs).slice(0, 6);
  if (items.length < 2) return null;
  return (
    <div className="nodrag flex gap-1 px-3 pt-2">
      {items.map((o, index) => (
        <button key={o.id} type="button" onClick={() => ui.openLightbox(block.id, o.id)}
          className={cx("h-9 w-9 overflow-hidden rounded-lg border-2 bg-fill-2 text-[10px] font-bold text-muted transition-colors duration-150", o.selected ? "border-ink text-ink" : "border-transparent hover:border-black/20")}
          title={t("lightbox.version", { n: index + 1 })} aria-label={t("lightbox.version", { n: index + 1 })} aria-pressed={o.selected}>
          {o.media?.kind === "image" ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={o.media.url} alt="" loading="lazy" className="h-full w-full object-cover" draggable={false} />
          ) : (o.aspect || index + 1)}
        </button>
      ))}
    </div>
  );
}

type HandleStatus = "valid" | "invalid" | null;

/** While a link is dragged, ports that would accept it light up and the others fade. */
function useHandleStatus(nodeId: number, handleType: "source" | "target", port?: string): HandleStatus {
  return useConnection((c) => {
    if (!c.inProgress) return null;
    const fromId = Number(c.fromNode.id);
    if (fromId === nodeId) return c.fromHandle.type === handleType && c.fromHandle.id === (port ?? "out") ? null : "invalid";
    if (c.fromHandle.type === handleType) return "invalid";
    return (handleType === "target" ? canLink(fromId, nodeId, port) : canLink(nodeId, fromId, c.fromHandle.id)) ? "valid" : "invalid";
  });
}

const statusClass = (status: HandleStatus) => cx("transition-[opacity,transform,box-shadow] duration-150",
  status === "invalid" && "opacity-25",
  status === "valid" && "!scale-125 !shadow-[0_0_0_3px_rgba(22,163,74,.35),0_0_0_1px_#16a34a]");

function OutHandle({ block, readOnly, compact }: { block: Block; readOnly: boolean; compact?: boolean }) {
  const t = useTranslations("production");
  const status = useHandleStatus(block.id, "source");
  return (
    <Handle type="source" position={Position.Right} id="out" isConnectable={!readOnly} title={t("handles.out")} aria-label={t("handles.out")}
      className={cx("!border-0 !bg-white !shadow-[0_0_0_1px_rgba(0,0,0,.14),0_1px_3px_rgba(0,0,0,.15)]", compact ? "!h-6 !w-6" : "!h-4 !w-4", statusClass(status))}
      style={{ right: compact ? -12 : -8 }}>
      <span className={cx("pointer-events-none absolute rounded-full", compact ? "inset-[5px]" : "inset-[3px]")} style={{ background: typeColor(block.out_type) }} />
    </Handle>
  );
}

function PortHandle({ nodeId, port, readOnly, style, compact }: { nodeId: number; port: Port; readOnly: boolean; style?: CSSProperties; compact?: boolean }) {
  const status = useHandleStatus(nodeId, "target", port.key);
  const colors = port.accepts.map(typeColor);
  return (
    <Handle type="target" position={Position.Left} id={port.key} isConnectable={!readOnly} title={port.label}
      className={cx("!border-0 !bg-white !shadow-[0_0_0_1px_rgba(0,0,0,.14),0_1px_3px_rgba(0,0,0,.12)]", compact ? "!h-5 !w-5" : "!h-3.5 !w-3.5", statusClass(status))}
      style={{ left: compact ? -10 : -7, ...style }}>
      <span className={cx("pointer-events-none absolute rounded-full", compact ? "inset-[4px]" : "inset-[3px]")}
        style={{ background: colors.length > 1 ? `conic-gradient(${colors.map((c, i) => `${c} ${(i * 100) / colors.length}% ${((i + 1) * 100) / colors.length}%`).join(",")})` : colors[0] }} />
    </Handle>
  );
}

function cardShadow(selected: boolean, state: string, highlighted: boolean) {
  if (highlighted) return "shadow-[0_0_0_2.5px_var(--warn),0_0_0_9px_color-mix(in_srgb,var(--warn)_22%,transparent),0_12px_30px_-12px_rgba(0,0,0,.18)]";
  if (selected) return "shadow-[0_0_0_1.5px_#0a0a0a,0_20px_44px_-14px_rgba(0,0,0,.3)]";
  if (state === "failed") return "shadow-[0_0_0_1.5px_rgba(217,45,32,.45),0_12px_30px_-12px_rgba(217,45,32,.2)]";
  if (state === "waiting") return "shadow-[0_0_0_2px_var(--warn),0_12px_30px_-12px_rgba(0,0,0,.18)]";
  if (isRunning(state)) return "shadow-[0_0_0_4px_color-mix(in_srgb,var(--kind)_20%,transparent),0_12px_30px_-12px_rgba(0,0,0,.18)]";
  return "shadow-[0_0_0_1px_rgba(0,0,0,.06),inset_0_1px_0_rgba(255,255,255,.7),0_12px_30px_-12px_rgba(0,0,0,.18)]";
}

function BlockNodeView({ data, selected }: NodeProps<BlockFlowNode>) {
  countRender();
  const block = data.block;
  const compact = useStore((s) => s.transform[2] < COMPACT_ZOOM);
  const ports = useCanvasStore((s) => s.kinds.get(block.kind)?.ports ?? NO_PORTS);
  const counts = useCanvasStore((s) => s.portCounts.get(block.id) ?? EMPTY_COUNTS);
  const readOnly = useCanvasStore((s) => s.readOnly);
  const highlighted = useCanvasStore((s) => s.highlight.includes(block.id));
  return compact
    ? <CompactCard block={block} ports={ports} readOnly={readOnly} selected={!!selected} highlighted={highlighted} />
    : <FullCard block={block} ports={ports} counts={counts} readOnly={readOnly} selected={!!selected} highlighted={highlighted} />;
}

function FullCard({ block, ports, counts, readOnly, selected, highlighted }: {
  block: Block; ports: Port[]; counts: Record<string, number>; readOnly: boolean; selected: boolean; highlighted: boolean;
}) {
  const t = useTranslations("production");
  const ui = useCanvasStore((s) => s.ui);
  const meta = KIND_META[block.kind] || KIND_META.text;
  const generative = GENERATIVE.includes(block.kind);
  const running = isRunning(block.state);
  const canRun = !readOnly && block.kind !== "text";
  const price = useBlockPrice(block);

  return (
    <div
      style={{ width: NODE_W, ["--kind" as string]: meta.color }}
      className={cx(
        // no backdrop blur: 40+ blurred cards cost a lot while panning; a nearly opaque card looks the same
        "block-card group relative rounded-[22px] border border-white/70 pb-3 transition-[background-color,box-shadow] duration-200",
        selected ? "bg-white" : "bg-white/[.92] hover:bg-white",
        cardShadow(selected, block.state, highlighted),
      )}
    >
      {/* header */}
      <div className="relative flex h-11 items-center gap-2 px-3.5">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg"
          style={{ color: `color-mix(in srgb, ${meta.color} 82%, #000)`, background: `color-mix(in srgb, ${meta.color} 13%, #fff)` }}>
          <Icon name={meta.icon} size={15} />
        </span>
        <span className="bidi min-w-0 flex-1 truncate text-[13.5px] font-semibold tracking-tight" dir="auto" title={block.name}>{block.name}</span>
        <StateIcon state={block.state} />
        {block.out_type && <OutHandle block={block} readOnly={readOnly} />}
      </div>

      {/* meta pills */}
      {(generative || price || ["reframe", "merge", "design"].includes(block.kind)) && (
        <div className="flex h-7 items-center gap-1 overflow-hidden px-3.5">
          {generative && (
            <span className="max-w-[130px] truncate rounded-full bg-white/90 px-2 py-px font-mono text-[10.5px] text-ink shadow-[inset_0_0_0_1px_var(--line)]">
              {block.model_label || t("defaultModel")}
            </span>
          )}
          {["image", "video", "merge", "design"].includes(block.kind) && <span className="rounded-full bg-fill-2 px-2 py-px text-[10.5px] text-muted">{block.aspect}</span>}
          {block.kind === "reframe" && <span className="rounded-full bg-fill-2 px-2 py-px text-[10.5px] text-muted">{block.formats.join(" · ")}</span>}
          {block.variations > 1 && <span className="rounded-full bg-fill-2 px-2 py-px text-[10.5px] text-muted">×{block.variations}</span>}
          {price && (
            <span className={cx("whitespace-nowrap rounded-full px-2 py-px text-[10.5px] tabular-nums", price.spent ? "bg-ok-bg text-ok" : "bg-fill-2 text-ink")}
              title={price.spent ? t("spent") : t("estimateHint")}>{price.text}</span>
          )}
        </div>
      )}

      {/* typed input ports */}
      {!!ports.length && (
        <div className="pb-1">
          {ports.map((port) => (
            <div key={port.key} className="relative flex h-7 items-center gap-1.5 px-3.5 text-[11.5px] text-muted hover:bg-fill">
              <PortHandle nodeId={block.id} port={port} readOnly={readOnly} />
              <span className="bidi flex-1 truncate" dir="auto">{port.label}</span>
              {!!counts[port.key] && <span className="min-w-[18px] rounded-full bg-fill-2 px-1.5 text-center text-[10px] text-ink">{counts[port.key]}</span>}
            </div>
          ))}
        </div>
      )}

      <Preview block={block} />
      <Versions block={block} />

      {block.prompt && generative && !block.output && !block.output_text && (
        <p className="bidi mx-3.5 mt-2 line-clamp-3 text-[11.5px] leading-snug text-muted" dir="auto">{block.prompt}</p>
      )}
      {block.error && <ErrorText text={block.error} />}
      {!block.error && block.notice && <p className="bidi mx-3 mt-2 rounded-[10px] bg-warn-bg px-2.5 py-1.5 text-[11.5px] text-warn" dir="auto">{block.notice}</p>}

      {canRun && (
        <div className="flex items-center justify-end gap-1.5 px-3 pt-2.5">
          {block.kind === "design" && (
            <button type="button" className="nodrag h-7 rounded-full bg-fill-2 px-3 text-[12px] font-medium transition-colors duration-150 hover:bg-black/10" onClick={() => ui.openDesign(block.id)}>
              {t("openEditor")}
            </button>
          )}
          <RunButton block={block} onRun={(force) => ui.run([block.id], { force, downstream: true })} />
        </div>
      )}

      {running && (
        <div className="absolute inset-x-5 bottom-1.5 h-[3px] overflow-hidden rounded-full bg-fill-2" role="progressbar" aria-valuenow={block.progress || 0} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-full rounded-full bg-ink transition-[width] duration-700" style={{ width: `${Math.max(8, block.progress || 0)}%` }} />
        </div>
      )}
    </div>
  );
}

/** Error of a block; a mention of the settings becomes a link to the AI providers. */
export function ErrorText({ text, className }: { text: string; className?: string }) {
  const t = useTranslations("production");
  const admin = useSession((s) => s.can("admin"));
  const settings = admin && /settings|إعدادات|instellingen|einstellungen|paramètres|réglages/i.test(text);
  return (
    <p className={cx("bidi mx-3 mt-2 rounded-[10px] bg-bad-bg px-2.5 py-1.5 text-[11.5px] text-bad", className)} dir="auto">
      {text}
      {settings && (
        <Link href="/settings/ai" className="nodrag ms-1.5 inline-flex items-center gap-0.5 font-semibold underline underline-offset-2">
          {t("openSettings")}
        </Link>
      )}
    </p>
  );
}

/** The card drawn when zoomed out: big type, state as text, one thumbnail. Ports keep their handles for the links. */
function CompactCard({ block, ports, readOnly, selected, highlighted }: { block: Block; ports: Port[]; readOnly: boolean; selected: boolean; highlighted: boolean }) {
  const t = useTranslations("production");
  const meta = KIND_META[block.kind] || KIND_META.text;
  const media = block.output;
  const height = Math.max(120, 36 + ports.length * 26);
  const text = block.kind === "text" ? block.output_text || block.text_value : block.output_text;
  return (
    <div style={{ width: NODE_W, height, ["--kind" as string]: meta.color }}
      className={cx("block-card relative flex items-center gap-3.5 rounded-[26px] border border-white/70 px-4 transition-[background-color,box-shadow] duration-200",
        selected ? "bg-white" : "bg-white/90", cardShadow(selected, block.state, highlighted))}>
      {ports.map((port, i) => (
        <PortHandle key={port.key} nodeId={block.id} port={port} readOnly={readOnly} compact
          style={{ top: height / 2 + (i - (ports.length - 1) / 2) * 26 }} />
      ))}
      <span className="relative flex h-[72px] w-[72px] shrink-0 items-center justify-center overflow-hidden rounded-2xl"
        style={{ color: `color-mix(in srgb, ${meta.color} 82%, #000)`, background: `color-mix(in srgb, ${meta.color} 13%, #fff)` }}>
        {media?.kind === "image" ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={media.url} alt="" loading="lazy" decoding="async" className="h-full w-full object-cover" draggable={false} />
        ) : (
          <Icon name={media?.kind === "video" ? "movie" : media?.kind === "audio" ? "graphic_eq" : meta.icon} size={34} />
        )}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="bidi line-clamp-2 text-[22px] font-semibold leading-tight tracking-tight" dir="auto">{block.name}</span>
        <span className={cx("flex items-center gap-1.5 text-[16px] font-medium",
          block.state === "failed" ? "text-bad" : block.state === "done" ? "text-ok" : block.state === "waiting" ? "text-warn" : "text-muted")}>
          <StateIcon state={block.state} size={18} />
          <span className="truncate">{block.state === "idle" && text ? t(`kinds.${block.kind}`) : t(`states.${block.state}`)}</span>
        </span>
      </span>
      {block.out_type && <OutHandle block={block} readOnly={readOnly} compact />}
      {isRunning(block.state) && (
        <div className="absolute inset-x-6 bottom-2 h-1.5 overflow-hidden rounded-full bg-fill-2">
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
    <button type="button" disabled={running} onClick={() => onRun(again)} title={`${again ? t("regenerate") : t("runFromHere")} · Ctrl+Enter`}
      className="nodrag inline-flex h-7 items-center gap-1 rounded-full bg-ink px-3 text-[12px] font-medium text-white shadow-[0_6px_14px_-6px_rgba(0,0,0,.5)] transition hover:-translate-y-px disabled:opacity-40">
      <Icon name={running ? "progress_activity" : again ? "refresh" : "play_arrow"} spin={running} size={14} />
      {running ? t("running") : again ? t("regenerate") : t("run")}
    </button>
  );
}

export const BlockNodeComponent = memo(BlockNodeView);
