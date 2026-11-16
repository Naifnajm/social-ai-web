"use client";
/**
 * Production canvas (React Flow): typed blocks and links, groups, undo/redo, copy/paste, keyboard shortcuts,
 * file drop, inspector, variables & batch versions, brand kit, run preflight with cost (and AI credits), stop,
 * run progress and summary, context menus, search, tidy up, lightbox, design editor.
 * The page is RTL in Arabic, but the flow itself stays left-to-right (inputs on the left, output on the right);
 * the floating chrome (top bar, inspector, toolbar) mirrors.
 */
import "@xyflow/react/dist/style.css";
import {
  Background, BackgroundVariant, type Connection, ControlButton, Controls, type EdgeChange, type FinalConnectionState,
  type FitViewOptions, MiniMap, type Node, type NodeChange, ReactFlow, ReactFlowProvider, applyNodeChanges, useReactFlow,
} from "@xyflow/react";
import { useTranslations } from "next-intl";
import { type DragEvent, type MouseEvent as ReactMouseEvent, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/icon";
import { Button, EmptyState, Modal, Spinner, cx, toast } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { useCredits } from "@/lib/billing";
import { useSession } from "@/lib/session";
import { BlockNodeComponent, type BlockFlowNode } from "./block-node";
import { DesignEditor, type DesignState } from "./design-editor";
import { ConnectionLine, GroupFrame, type GroupFlowNode, TypedEdge, type TypedFlowEdge } from "./flow-parts";
import { Inspector } from "./inspector";
import { Lightbox } from "./lightbox";
import { CONFIRM_FROM_USD, GRID, KIND_META, NODE_W, TOOLBAR_KINDS, compatibleKinds, isRunning, tidyLayout } from "./meta";
import {
  ContextMenu, KindList, KindPopover, MOD, type MenuItem, type Preflight, PreflightDialog, type RunResult, RunSummary, SearchPalette, ShortcutsSheet,
} from "./overlays";
import {
  type CanvasUi, type RunMode, bindUi, groupNodes, pushUndo, redo, resetCanvas, setCanvasMeta, syncGraph, undo, canLink, useCanvasStore,
} from "./store";
import { TopBar } from "./top-bar";
import { Toolbar } from "./toolbar";
import type { BlockGroup, BlockNode, Graph } from "./types";
import { errorText, useBoard } from "./use-board";

type FlowNode = BlockFlowNode | GroupFlowNode;
type Clip = { ids: number[]; origin?: { x: number; y: number } };
type Menu = { x: number; y: number; flow: { x: number; y: number }; nodeId?: number };
type LinkPicker = { x: number; y: number; flow: { x: number; y: number }; fromId: number; handleType: "source" | "target"; port: string | null };

const CLIPBOARD_KEY = "production.clipboard";
const TIP_KEY = "production.tip.link";
// defined once, outside the component: new objects on each render make React Flow re-create every node
const nodeTypes = { block: BlockNodeComponent, "group-frame": GroupFrame };
const edgeTypes = { typed: TypedEdge };
const FRAME_PAD = 28;
const FRAME_HEAD = 46;
const TOP_BAR = 76;
const INSPECTOR_W = 362;
const LONG_RUN_MS = 20_000;

function readClipboard(): Clip {
  try {
    const data = JSON.parse(window.localStorage.getItem(CLIPBOARD_KEY) || "null");
    return Array.isArray(data?.ids) ? { ids: data.ids, origin: data.origin } : { ids: [] };
  } catch {
    return { ids: [] };
  }
}

function writeClipboard(clip: Clip) {
  try {
    window.localStorage.setItem(CLIPBOARD_KEY, JSON.stringify({ ...clip, at: Date.now() }));
    return true;
  } catch {
    return false;
  }
}

function readFlag(key: string) {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function writeFlag(key: string) {
  try {
    window.localStorage.setItem(key, "1");
  } catch {
    /* storage unavailable: the tip shows again next time */
  }
}

/** Edges of the last render: an unchanged link keeps its object, so React Flow skips it (one canvas at a time). */
let edgeCache = new Map<string, TypedFlowEdge>();

function buildEdges(graph: Graph | undefined, blocksById: Map<number, BlockNode>, selectedEdges: string[],
  t: (key: string, values?: Record<string, string>) => string): TypedFlowEdge[] {
  const kinds = new Map((graph?.kinds || []).map((k) => [k.key, k]));
  const next = (graph?.edges || []).map((e) => {
    const id = String(e.id);
    const source = blocksById.get(e.source);
    const target = blocksById.get(e.target);
    const port = target ? kinds.get(target.kind)?.ports.find((p) => p.key === e.port)?.label || e.port : e.port;
    const running = isRunning(target?.state || "");
    const selected = selectedEdges.includes(id);
    const ariaLabel = t("a11y.link", { from: source?.name || "", to: target?.name || "", port });
    const old = edgeCache.get(id);
    if (old && old.selected === selected && old.data?.running === running && old.data?.type === e.type && old.ariaLabel === ariaLabel
      && old.targetHandle === e.port && old.source === String(e.source) && old.target === String(e.target)) return old;
    return { id, source: String(e.source), target: String(e.target), sourceHandle: "out", targetHandle: e.port, type: "typed" as const,
      data: { type: e.type, running }, selected, ariaLabel };
  });
  edgeCache = new Map(next.map((e) => [e.id, e]));
  return next;
}

const isRtl = () => typeof document !== "undefined" && document.documentElement.dir === "rtl";

/** Room taken by the floating chrome, so fitting and centring keep blocks visible. */
function chromePadding(inspector: boolean): FitViewOptions["padding"] {
  if (typeof window === "undefined") return 0.2;
  const wide = window.innerWidth >= 1024;
  const side = inspector && wide ? INSPECTOR_W + 24 : 32;
  const rtl = isRtl();
  return { top: `${TOP_BAR + 24}px`, bottom: `${window.innerWidth < 768 ? 96 : 124}px`, left: `${rtl ? side : 32}px`, right: `${rtl ? 32 : side}px` };
}

/** Builds the React Flow block nodes from the graph; an unchanged block keeps its node object (no re-render). */
function buildBlocks(graph: Graph, previous: BlockFlowNode[], label: (b: BlockNode) => string): BlockFlowNode[] {
  const prev = new Map(previous.map((n) => [n.id, n]));
  return graph.nodes.map((block) => {
    const id = String(block.id);
    const old = prev.get(id);
    if (old && old.data.block === block && (old.dragging || (old.position.x === block.x && old.position.y === block.y))) return old;
    return {
      id,
      type: "block" as const,
      position: old?.dragging ? old.position : { x: block.x, y: block.y },
      data: { block },
      selected: old?.selected,
      measured: old?.measured,
      dragging: old?.dragging,
      zIndex: 1,
      ariaLabel: label(block),
    };
  });
}

function groupFrames(groups: BlockGroup[], blocks: BlockFlowNode[]): GroupFlowNode[] {
  const byId = new Map(blocks.map((n) => [n.data.block.id, n]));
  const frames: GroupFlowNode[] = [];
  for (const group of groups) {
    const members = group.nodes.map((id) => byId.get(id)).filter(Boolean) as BlockFlowNode[];
    if (!members.length) continue;
    const minX = Math.min(...members.map((n) => n.position.x)) - FRAME_PAD;
    const minY = Math.min(...members.map((n) => n.position.y)) - FRAME_PAD - FRAME_HEAD;
    const maxX = Math.max(...members.map((n) => n.position.x + (n.measured?.width || NODE_W))) + FRAME_PAD;
    const maxY = Math.max(...members.map((n) => n.position.y + (n.measured?.height || 320))) + FRAME_PAD;
    const data = { groupId: group.id, name: group.name, color: group.color, width: maxX - minX, height: maxY - minY };
    frames.push({ id: `group-${group.id}`, type: "group-frame", position: { x: minX, y: minY }, data, zIndex: 0, selectable: false, focusable: false,
      dragHandle: ".group-handle", style: { pointerEvents: "none" } });
  }
  return frames;
}

export function ProductionCanvas({ boardId }: { boardId: number }) {
  return (
    <ReactFlowProvider>
      <CanvasInner boardId={boardId} />
    </ReactFlowProvider>
  );
}

function CanvasInner({ boardId }: { boardId: number }) {
  const t = useTranslations("production");
  const { can } = useSession();
  const readOnly = !can("editor");
  const { query, graph, actions } = useBoard(boardId);
  const flow = useReactFlow();
  const wrapper = useRef<HTMLDivElement>(null);
  const inspectorBox = useRef<HTMLDivElement>(null);
  const fileInputId = useId();
  const [uploadTarget, setUploadTarget] = useState<number | null>(null);
  const viewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dragStart = useRef<Record<number, [number, number]>>({});
  const pointer = useRef<{ x: number; y: number } | null>(null);
  const lastEscape = useRef(0);

  const [rfNodes, setRfNodes] = useState<BlockFlowNode[]>([]);
  const [synced, setSynced] = useState<Graph["nodes"] | null>(null);
  const [selectedEdges, setSelectedEdges] = useState<string[]>([]);
  const [designNodeId, setDesignNodeId] = useState<number | null>(null);
  const [dropping, setDropping] = useState(false);
  const [smallScreen, setSmallScreen] = useState(() => typeof window !== "undefined" && window.innerWidth < 768);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [linkPicker, setLinkPicker] = useState<LinkPicker | null>(null);
  const [addAt, setAddAt] = useState<Menu | null>(null);
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [checking, setChecking] = useState(false);
  const [summary, setSummary] = useState<RunResult | null>(null);
  const [announce, setAnnounce] = useState("");
  const [lightbox, setLightbox] = useState<{ nodeId: number; outputId?: number | null } | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [addSheet, setAddSheet] = useState(false);
  const [tipHidden, setTipHidden] = useState(true);
  const [tidying, setTidying] = useState(false);
  const storeReady = useCanvasStore((s) => s.graph !== null && s.actions !== null);
  const canUndo = useCanvasStore((s) => s.undoStack.length > 0);
  const canRedo = useCanvasStore((s) => s.redoStack.length > 0);

  // one store per open board (layout effects: ready before the first paint)
  useLayoutEffect(() => {
    resetCanvas(actions, readOnly);
    // only when another board opens
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boardId]);
  useLayoutEffect(() => setCanvasMeta({ actions, readOnly }), [actions, readOnly]);
  useLayoutEffect(() => {
    if (graph) syncGraph(graph);
  }, [graph]);

  // AI credits: shown instead of dollars when the board runs on the platform's AI
  const usesCredits = !!graph && (graph.run_all.credits != null || graph.nodes.some((n) => n.estimate?.credits != null));
  const credits = useCredits(usesCredits && !readOnly);
  const perUsd = usesCredits ? credits.data?.credits_per_usd ?? null : null;
  useEffect(() => setCanvasMeta({ creditsPerUsd: perUsd }), [perUsd]);

  const blockLabel = useCallback((b: BlockNode) => t("a11y.block", { name: b.name, kind: t(`kinds.${b.kind}`), state: t(`states.${b.state}`) }), [t]);

  // keep the React Flow nodes in step with the server graph (adjusting state while rendering, no effect)
  if (graph && synced !== graph.nodes) {
    setSynced(graph.nodes);
    setRfNodes((prev) => buildBlocks(graph, prev, blockLabel));
  }

  useEffect(() => {
    const onResize = () => setSmallScreen(window.innerWidth < 768);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const blocksById = useMemo(() => new Map((graph?.nodes || []).map((n) => [n.id, n])), [graph?.nodes]);
  const selectedIds = useMemo(() => rfNodes.filter((n) => n.selected).map((n) => Number(n.id)), [rfNodes]);
  const selectedBlock = selectedIds.length === 1 ? blocksById.get(selectedIds[0]) || null : null;
  const frames = useMemo(() => groupFrames(graph?.groups || [], rfNodes), [graph?.groups, rfNodes]);
  const displayNodes = useMemo<FlowNode[]>(() => [...frames, ...rfNodes], [frames, rfNodes]);
  const edges = useMemo(() => buildEdges(graph, blocksById, selectedEdges, t), [graph, blocksById, selectedEdges, t]);

  const select = useCallback((ids: number[]) => {
    setRfNodes((nodes) => nodes.map((n) => {
      const selected = ids.includes(Number(n.id));
      return !!n.selected === selected ? n : { ...n, selected };
    }));
    setSelectedEdges([]);
  }, []);

  // ------------------------------------------------------------------ viewport helpers
  const fitTo = useCallback((ids?: number[], inspector = false) => {
    flow.fitView({ nodes: ids?.map((id) => ({ id: String(id) })), padding: chromePadding(inspector), duration: 250, maxZoom: 1, minZoom: ids?.length === 1 ? 0.6 : 0.15 });
  }, [flow]);

  const focusBlock = useCallback((id: number) => {
    select([id]);
    fitTo([id], true);
  }, [select, fitTo]);

  // when a block is selected, move it out from under the inspector (side panel, or bottom sheet on phones)
  const lastPanned = useRef<number | null>(null);
  useEffect(() => {
    const id = selectedBlock?.id ?? null;
    if (id === lastPanned.current) return;
    lastPanned.current = id;
    if (id == null) return;
    const frame = requestAnimationFrame(() => {
      const node = flow.getInternalNode(String(id));
      if (!node) return;
      const { x: vx, y: vy, zoom } = flow.getViewport();
      const w = (node.measured.width || NODE_W) * zoom;
      const h = (node.measured.height || 300) * zoom;
      const left = node.internals.positionAbsolute.x * zoom + vx;
      const top = node.internals.positionAbsolute.y * zoom + vy;
      const W = window.innerWidth;
      const H = window.innerHeight;
      let dx = 0;
      let dy = 0;
      if (W >= 1024) {
        if (isRtl()) {
          if (left < INSPECTOR_W + 16) dx = INSPECTOR_W + 32 - left;
        } else if (left + w > W - INSPECTOR_W - 16) {
          dx = W - INSPECTOR_W - 32 - (left + w);
        }
        if (dx && left + dx < 16 && !isRtl()) dx = 16 - left;
      } else {
        const sheet = inspectorBox.current?.getBoundingClientRect().top ?? H * 0.38;
        const room = sheet - TOP_BAR - 12;
        if (top < TOP_BAR || top + Math.min(h, room) > sheet - 8) dy = TOP_BAR + 12 - top;
        if (left < 8 || left + w > W - 8) dx = (W - w) / 2 - left;
      }
      if (dx || dy) flow.setViewport({ x: vx + dx, y: vy + dy, zoom }, { duration: 200 });
    });
    return () => cancelAnimationFrame(frame);
  }, [selectedBlock?.id, flow]);

  // ------------------------------------------------------------------ changes from React Flow
  const onNodesChange = useCallback((changes: NodeChange<FlowNode>[]) => {
    const blockChanges: NodeChange<BlockFlowNode>[] = [];
    for (const change of changes) {
      const id = "id" in change ? change.id : "";
      if (id.startsWith("group-")) {
        if (change.type === "position" && change.position) {
          const frame = frames.find((f) => f.id === id);
          const group = graph?.groups.find((g) => `group-${g.id}` === id);
          if (!frame || !group) continue;
          const dx = change.position.x - frame.position.x;
          const dy = change.position.y - frame.position.y;
          for (const member of group.nodes) {
            const node = rfNodes.find((n) => n.id === String(member));
            if (node) blockChanges.push({ type: "position", id: node.id, position: { x: node.position.x + dx, y: node.position.y + dy }, dragging: change.dragging });
          }
        }
        continue;
      }
      if (readOnly && change.type === "position") continue;
      blockChanges.push(change as NodeChange<BlockFlowNode>);
    }
    if (blockChanges.length) setRfNodes((nodes) => applyNodeChanges(blockChanges, nodes));
  }, [frames, graph?.groups, rfNodes, readOnly]);

  const onEdgesChange = useCallback((changes: EdgeChange<TypedFlowEdge>[]) => {
    setSelectedEdges((current) => {
      let next = [...current];
      for (const change of changes) {
        if (change.type === "select") next = change.selected ? [...new Set([...next, change.id])] : next.filter((id) => id !== change.id);
      }
      return next;
    });
  }, []);

  const membersOf = useCallback((node: Node) => {
    if (node.type !== "group-frame") return [Number(node.id)];
    return graph?.groups.find((g) => `group-${g.id}` === node.id)?.nodes || [];
  }, [graph?.groups]);

  const onNodeDragStart = useCallback((_e: unknown, node: Node, nodes: Node[]) => {
    const ids = new Set([...nodes.flatMap(membersOf), ...membersOf(node)]);
    dragStart.current = Object.fromEntries([...ids].map((id) => {
      const block = blocksById.get(id);
      return [id, [block?.x || 0, block?.y || 0]];
    }));
  }, [membersOf, blocksById]);

  const onNodeDragStop = useCallback(() => {
    const after: Record<number, [number, number]> = {};
    const before = dragStart.current;
    for (const id of Object.keys(before).map(Number)) {
      const node = rfNodes.find((n) => n.id === String(id));
      if (node) after[id] = [Math.round(node.position.x), Math.round(node.position.y)];
    }
    dragStart.current = {};
    if (!Object.keys(after).length) return;
    const moved = Object.keys(after).some((id) => after[Number(id)][0] !== before[Number(id)][0] || after[Number(id)][1] !== before[Number(id)][1]);
    if (!moved) return;
    actions.savePositions(after);
    pushUndo({ type: "move", before, after });
  }, [rfNodes, actions]);

  // ------------------------------------------------------------------ links
  const isValidConnection = useCallback((conn: Connection | { source: string; target: string; targetHandle?: string | null }) =>
    canLink(Number(conn.source), Number(conn.target), conn.targetHandle), []);

  const onConnect = useCallback(async (conn: Connection) => {
    try {
      const edge = await actions.connect(Number(conn.source), Number(conn.target), conn.targetHandle);
      pushUndo({ type: "connect", edge_id: edge.id, replaced: edge.replaced });
    } catch {
      /* toast shown */
    }
  }, [actions]);

  // a link dropped on the empty canvas: offer the blocks that fit, made right there and linked
  const onConnectEnd = useCallback((event: MouseEvent | TouchEvent, state: FinalConnectionState) => {
    if (readOnly || state.isValid || state.toNode || !state.fromNode || !state.fromHandle || !graph) return;
    const point = "changedTouches" in event ? event.changedTouches[0] : event;
    if (!point) return;
    setLinkPicker({
      x: point.clientX, y: point.clientY, flow: flow.screenToFlowPosition({ x: point.clientX, y: point.clientY }),
      fromId: Number(state.fromNode.id), handleType: state.fromHandle.type, port: state.fromHandle.id ?? null,
    });
  }, [readOnly, graph, flow]);

  // ------------------------------------------------------------------ add / delete / paste / group
  const centerPosition = useCallback(() => {
    const rect = wrapper.current?.getBoundingClientRect();
    const point = flow.screenToFlowPosition({ x: (rect?.left || 0) + (rect?.width || 800) / 2, y: (rect?.top || 0) + (rect?.height || 600) / 2.4 });
    return { x: Math.round(point.x - NODE_W / 2 + (Math.random() - 0.5) * 60), y: Math.round(point.y - 120 + (Math.random() - 0.5) * 60) };
  }, [flow]);

  const snap = (v: number) => Math.round(v / GRID) * GRID;

  const addBlock = useCallback(async (kind: string, position?: { x: number; y: number }) => {
    if (readOnly) return;
    const { x, y } = position || centerPosition();
    try {
      const node = await actions.addNode(kind, snap(x), snap(y));
      pushUndo({ type: "add", node_ids: [node.id], edge_ids: [] });
      select([node.id]);
      return node;
    } catch {
      return undefined;
    }
  }, [readOnly, centerPosition, actions, select]);

  const addLinked = useCallback(async (kind: string, picker: LinkPicker) => {
    const fromSource = picker.handleType === "source";
    const x = fromSource ? picker.flow.x + 24 : picker.flow.x - NODE_W - 24;
    const y = picker.flow.y - 30;
    try {
      const node = await actions.addNode(kind, snap(x), snap(y));
      const edge = fromSource
        ? await actions.connect(picker.fromId, node.id, null)
        : await actions.connect(node.id, picker.fromId, picker.port);
      pushUndo({ type: "add", node_ids: [node.id], edge_ids: [edge.id], replaced: edge.replaced });
      select([node.id]);
    } catch {
      /* toast shown */
    }
  }, [actions, select]);

  const deleteIds = useCallback(async (nodeIds: number[], edgeIds: number[]) => {
    if (readOnly || (!nodeIds.length && !edgeIds.length)) return;
    const removed = await actions.archive(nodeIds, edgeIds).catch(() => null);
    if (removed && (removed.node_ids.length || removed.edge_ids.length)) pushUndo({ type: "archive", ...removed });
    setSelectedEdges([]);
  }, [readOnly, actions]);
  const deleteSelection = useCallback(() => deleteIds(selectedIds, selectedEdges.map(Number)), [deleteIds, selectedIds, selectedEdges]);

  const copy = useCallback((ids: number[]) => {
    if (!ids.length) return;
    const nodes = ids.map((id) => blocksById.get(id)).filter(Boolean) as BlockNode[];
    const origin = { x: Math.min(...nodes.map((n) => n.x)), y: Math.min(...nodes.map((n) => n.y)) };
    if (writeClipboard({ ids, origin })) toast.info(t("copied", { count: ids.length }));
    else toast.error(t("clipboardUnavailable"));
  }, [blocksById, t]);

  /** Pastes blocks with their top-left corner at `at` (flow position), or next to where they were. */
  const paste = useCallback(async (clip: Clip, at?: { x: number; y: number } | null) => {
    if (readOnly) return;
    if (!clip.ids.length) {
      toast.info(t("nothingToPaste"));
      return;
    }
    const dx = at && clip.origin ? snap(at.x - clip.origin.x) : 40;
    const dy = at && clip.origin ? snap(at.y - clip.origin.y) : 40;
    const result = await actions.paste(clip.ids, dx, dy).catch(() => null);
    if (!result) return;
    pushUndo({ type: "add", node_ids: result.nodes.map((n) => n.id), edge_ids: result.edges.map((e) => e.id) });
    select(result.nodes.map((n) => n.id));
  }, [readOnly, actions, select, t]);

  const pointerFlow = useCallback(() => {
    const p = pointer.current;
    const rect = wrapper.current?.getBoundingClientRect();
    if (!p || !rect || p.x < rect.left || p.y < rect.top || p.x > rect.right || p.y > rect.bottom) return null;
    return flow.screenToFlowPosition(p);
  }, [flow]);

  const duplicate = useCallback((ids: number[]) => {
    const nodes = ids.map((id) => blocksById.get(id)).filter(Boolean) as BlockNode[];
    if (!nodes.length) return;
    const origin = { x: Math.min(...nodes.map((n) => n.x)), y: Math.min(...nodes.map((n) => n.y)) };
    const at = pointerFlow();
    paste({ ids, origin }, at && (Math.abs(at.x - origin.x) > 60 || Math.abs(at.y - origin.y) > 60) ? at : { x: origin.x + 44, y: origin.y + 44 });
  }, [blocksById, pointerFlow, paste]);

  const group = useCallback((ids: number[]) => groupNodes(ids), []);

  // ------------------------------------------------------------------ tidy up
  const tidy = useCallback((ids?: number[]) => {
    if (readOnly || !graph) return;
    const scope = new Set(ids && ids.length > 1 ? ids : graph.nodes.map((n) => n.id));
    const nodes = rfNodes.filter((n) => scope.has(Number(n.id))).map((n) => ({ id: Number(n.id), x: n.position.x, y: n.position.y, height: n.measured?.height || 300 }));
    const after = tidyLayout(nodes, graph.edges);
    const before = Object.fromEntries(nodes.map((n) => [n.id, [Math.round(n.x), Math.round(n.y)] as [number, number]]));
    if (!Object.keys(after).some((id) => after[Number(id)][0] !== before[Number(id)][0] || after[Number(id)][1] !== before[Number(id)][1])) return;
    setTidying(true);
    actions.savePositions(after);
    pushUndo({ type: "move", before, after });
    setTimeout(() => {
      setTidying(false);
      fitTo(scope.size === graph.nodes.length ? undefined : [...scope], !!selectedBlock);
    }, 320);
  }, [readOnly, graph, rfNodes, actions, fitTo, selectedBlock]);

  // ------------------------------------------------------------------ runs: preflight, stop, progress, summary
  const startRun = useCallback(async (nodeIds: number[] | null, mode: RunMode, long: boolean) => {
    if (long && typeof Notification !== "undefined" && Notification.permission === "default") {
      Notification.requestPermission().catch(() => undefined);
    }
    setSummary(null);
    await actions.run(nodeIds, mode).catch(() => undefined);
  }, [actions]);

  const run = useCallback(async (nodeIds: number[] | null, mode: RunMode = {}) => {
    if (readOnly || !graph) return;
    const slow = setTimeout(() => setChecking(true), 300); // no spinner flash for a quick check
    let estimate;
    try {
      estimate = await actions.estimate(nodeIds, mode);
    } catch {
      estimate = null; // the estimate is only a guide: run anyway
    } finally {
      clearTimeout(slow);
      setChecking(false);
    }
    const ids = nodeIds || graph.nodes.map((n) => n.id);
    const long = ids.some((id) => ["video", "audio", "captions", "merge"].includes(blocksById.get(id)?.kind || "")) || ids.length > 4;
    if (!estimate) return startRun(nodeIds, mode, long);
    setCanvasMeta({ highlight: estimate.empty_text || [] });
    if (estimate.missing?.length) {
      setPreflight({ kind: "missing", estimate });
      return;
    }
    const over = estimate.credits != null && estimate.credits_available != null && estimate.credits > estimate.credits_available;
    if (!estimate.empty_text?.length && !over && estimate.cost < CONFIRM_FROM_USD) return startRun(nodeIds, mode, long);
    const label = !nodeIds ? t("preflight.titleAll") : mode.downstream === false ? t("preflight.titleOnly", { count: nodeIds.length }) : t("preflight.titleFrom");
    setPreflight({ kind: "confirm", estimate, label, onRun: () => startRun(nodeIds, mode, long) });
  }, [readOnly, graph, actions, startRun, blocksById, t]);

  const stop = useCallback(() => {
    if (readOnly) return;
    actions.stop().then(() => setAnnounce(t("stopped"))).catch(() => undefined);
  }, [readOnly, actions, t]);

  // follows the run: which blocks belong to it, then a summary (toast, live region, notification when hidden)
  const startedAt = useRef(0);
  useEffect(() => useCanvasStore.subscribe((state, prev) => {
    const g = state.graph;
    if (!g || g === prev.graph) return;
    const active = g.nodes.filter((n) => isRunning(n.state) || n.state === "waiting").map((n) => n.id);
    const ids = state.runIds;
    if (g.busy) {
      if (!ids.length) startedAt.current = Date.now();
      const merged = [...new Set([...ids, ...active])];
      if (merged.length !== ids.length) setCanvasMeta({ runIds: merged });
      return;
    }
    if (!ids.length) return;
    const byId = new Map(g.nodes.map((n) => [n.id, n]));
    const done = ids.filter((id) => byId.get(id)?.state === "done").length;
    const failed = ids.filter((id) => byId.get(id)?.state === "failed");
    const stopped = ids.filter((id) => byId.get(id)?.state === "idle").length;
    setCanvasMeta({ runIds: [] });
    const result = { done, failed, stopped, at: Date.now() };
    setSummary(result);
    const text = [t("summary.done", { count: done }), failed.length ? t("summary.failed", { count: failed.length }) : null].filter(Boolean).join(" · ");
    setAnnounce(text);
    if (document.hidden) {
      const title = document.title.replace(/^\([^)]*\) /, "");
      document.title = `(${failed.length ? "!" : "✓"}) ${title}`;
      const restore = () => {
        if (document.hidden) return;
        document.title = title;
        document.removeEventListener("visibilitychange", restore);
      };
      document.addEventListener("visibilitychange", restore);
      if (Date.now() - startedAt.current > LONG_RUN_MS && typeof Notification !== "undefined" && Notification.permission === "granted") {
        try {
          new Notification(g.board.name, { body: text, tag: `production-${g.board.id}` });
        } catch {
          /* notifications unavailable */
        }
      }
    }
  }), [t]);

  // pointed-at empty text blocks stop glowing once they have text
  useEffect(() => useCanvasStore.subscribe((state, prev) => {
    if (!state.highlight.length || state.blocks === prev.blocks) return;
    const left = state.highlight.filter((id) => state.blocks.get(id)?.kind === "text" && !state.blocks.get(id)?.text_value.trim());
    if (left.length !== state.highlight.length) setCanvasMeta({ highlight: left });
  }), []);

  const showIds = useCallback((ids: number[]) => {
    if (!ids.length) return;
    select(ids);
    fitTo(ids, ids.length === 1);
  }, [select, fitTo]);

  // ------------------------------------------------------------------ files
  const pickFile = useCallback((nodeId: number) => {
    setUploadTarget(nodeId);
    (document.getElementById(fileInputId) as HTMLInputElement | null)?.click();
  }, [fileInputId]);

  const onFile = async (file?: File | null) => {
    const nodeId = uploadTarget;
    if (!file || !nodeId) return;
    try {
      await actions.uploadFile(nodeId, file);
      toast.success(t("uploaded"));
    } catch {
      /* toast shown */
    }
  };

  // stable callbacks for the blocks and panels (through the store)
  const ui = useMemo<CanvasUi>(() => ({
    select, openDesign: setDesignNodeId, pickFile, run, focusBlock,
    openLightbox: (nodeId, outputId) => setLightbox({ nodeId, outputId }),
  }), [select, pickFile, run, focusBlock]);
  useLayoutEffect(() => bindUi(ui), [ui]);

  // ------------------------------------------------------------------ keyboard shortcuts
  const busy = !!graph?.busy;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.closest("input, textarea, select, [contenteditable=true]") || target.closest("[role=dialog]"))) return;
      if (lightbox || searchOpen || helpOpen || preflight) return;
      const mod = e.metaKey || e.ctrlKey;
      const key = e.key.toLowerCase();
      if (key === "delete" || key === "backspace") {
        e.preventDefault();
        deleteSelection();
      } else if (mod && key === "z" && !e.shiftKey) {
        e.preventDefault();
        undo();
      } else if (mod && (key === "y" || (key === "z" && e.shiftKey))) {
        e.preventDefault();
        redo();
      } else if (mod && key === "c" && selectedIds.length) {
        copy(selectedIds);
      } else if (mod && key === "v") {
        paste(readClipboard(), pointerFlow());
      } else if (mod && key === "d" && selectedIds.length) {
        e.preventDefault();
        duplicate(selectedIds);
      } else if (mod && key === "a") {
        e.preventDefault();
        select(rfNodes.map((n) => Number(n.id)));
      } else if (mod && key === "g") {
        e.preventDefault();
        group(selectedIds);
      } else if (mod && key === "enter") {
        e.preventDefault();
        run(selectedIds.length ? selectedIds : null);
      } else if ((mod && key === "k") || (!mod && key === "/")) {
        e.preventDefault();
        setSearchOpen(true);
      } else if (e.key === "?") {
        e.preventDefault();
        setHelpOpen(true);
      } else if (e.shiftKey && e.code === "Digit1") {
        e.preventDefault();
        fitTo(undefined, !!selectedBlock);
      } else if (e.shiftKey && key === "t" && !mod) {
        e.preventDefault();
        tidy(selectedIds);
      } else if (key === "escape") {
        const now = Date.now();
        if (busy && now - lastEscape.current < 700) {
          lastEscape.current = 0;
          stop();
        } else {
          lastEscape.current = now;
          select([]);
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [deleteSelection, paste, copy, duplicate, selectedIds, select, rfNodes, group, run, pointerFlow, fitTo, tidy, stop, busy,
    selectedBlock, lightbox, searchOpen, helpOpen, preflight]);

  // ------------------------------------------------------------------ toolbar drag & file drop
  const onDragOver = (e: DragEvent) => {
    if (readOnly) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    if (!dropping && e.dataTransfer.types.includes("Files")) setDropping(true);
  };
  const onDrop = async (e: DragEvent) => {
    e.preventDefault();
    setDropping(false);
    if (readOnly) return;
    const position = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY });
    const kind = e.dataTransfer.getData("application/production-kind");
    if (kind) {
      addBlock(kind, { x: position.x - NODE_W / 2, y: position.y - 30 });
      return;
    }
    const files = [...e.dataTransfer.files].filter((f) => /^(image|video|audio)\//.test(f.type));
    if (!files.length) return;
    const created: number[] = [];
    for (const [index, file] of files.entries()) {
      try {
        const node = await actions.addNode("upload", snap(position.x - NODE_W / 2 + index * 44), snap(position.y - 40 + index * 44), { name: file.name.slice(0, 160) });
        created.push(node.id);
        await actions.uploadFile(node.id, file);
      } catch {
        /* toast shown */
      }
    }
    if (created.length) {
      pushUndo({ type: "add", node_ids: created, edge_ids: [] });
      select(created);
    }
  };

  const onMoveEnd = useCallback((event: unknown, viewport: { x: number; y: number; zoom: number }) => {
    // only moves made by the person are remembered (not fitView), and not from a phone
    if (readOnly || !event || smallScreen) return;
    if (viewTimer.current) clearTimeout(viewTimer.current);
    viewTimer.current = setTimeout(() => actions.saveView(viewport.zoom, viewport.x, viewport.y), 600);
  }, [actions, readOnly, smallScreen]);

  // ------------------------------------------------------------------ context menus
  const openMenu = useCallback((e: ReactMouseEvent | MouseEvent, nodeId?: number) => {
    e.preventDefault();
    setLinkPicker(null);
    setMenu({ x: e.clientX, y: e.clientY, flow: flow.screenToFlowPosition({ x: e.clientX, y: e.clientY }), nodeId });
  }, [flow]);

  const menuItems = (m: Menu): MenuItem[] => {
    if (m.nodeId != null) {
      const ids = selectedIds.includes(m.nodeId) && selectedIds.length > 1 ? selectedIds : [m.nodeId];
      const block = blocksById.get(m.nodeId);
      const many = ids.length > 1;
      const hasResult = !many && !!block && (!!block.output || !!block.output_text || block.outputs.length > 0) && block.kind !== "text";
      const runnable = ids.some((id) => blocksById.get(id)?.kind !== "text");
      return [
        ...(!readOnly ? [
          { icon: "play_arrow", label: many ? t("menu.runOnlyThese", { count: ids.length }) : t("menu.runOnly"), onClick: () => run(ids, { downstream: false }), disabled: !runnable },
          { icon: "fast_forward", label: t("runFromHere"), shortcut: `${MOD}+Enter`, onClick: () => run(ids, { downstream: true }), disabled: !runnable },
          "-" as const,
        ] : []),
        ...(hasResult ? [{ icon: "crop_free", label: t("menu.openResult"), onClick: () => setLightbox({ nodeId: m.nodeId! }) }] : []),
        ...(!readOnly ? [
          { icon: "content_paste", label: t("duplicate"), shortcut: `${MOD}+D`, onClick: () => duplicate(ids) },
          { icon: "content_copy", label: t("copy"), shortcut: `${MOD}+C`, onClick: () => copy(ids) },
          { icon: "select_group", label: t("group"), shortcut: `${MOD}+G`, onClick: () => group(ids) },
          ...(many ? [{ icon: "account_tree", label: t("menu.tidy"), shortcut: "Shift+T", onClick: () => tidy(ids) }] : []),
          "-" as const,
          { icon: "delete", label: t("delete"), shortcut: "Del", danger: true, onClick: () => deleteIds(ids, []) },
        ] : []),
      ];
    }
    const clip = readOnly ? { ids: [] } : readClipboard();
    return [
      ...(!readOnly ? [
        { icon: "content_paste", label: t("menu.pasteHere"), shortcut: `${MOD}+V`, disabled: !clip.ids.length, onClick: () => paste(clip, m.flow) },
        { icon: "add", label: t("menu.addBlock"), onClick: () => setAddAt(m) },
        "-" as const,
      ] : []),
      { icon: "select_group", label: t("menu.selectAll"), shortcut: `${MOD}+A`, onClick: () => select(rfNodes.map((n) => Number(n.id))) },
      ...(!readOnly ? [{ icon: "account_tree", label: t("menu.tidy"), shortcut: "Shift+T", onClick: () => tidy() }] : []),
      { icon: "zoom_in_map", label: t("menu.fit"), shortcut: "Shift+1", onClick: () => fitTo(undefined, !!selectedBlock) },
      { icon: "search", label: t("search.title"), shortcut: `${MOD}+K`, onClick: () => setSearchOpen(true) },
      { icon: "info", label: t("shortcuts.title"), shortcut: "?", onClick: () => setHelpOpen(true) },
    ];
  };

  // first-run tip: how to link an output to an input
  const nodeCount = graph?.nodes.length || 0;
  const edgeCount = graph?.edges.length || 0;
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reads localStorage once the board is shown
    if (nodeCount >= 2 && edgeCount === 0 && !readOnly) setTipHidden(readFlag(TIP_KEY));
  }, [nodeCount, edgeCount, readOnly]);
  const dismissTip = () => {
    writeFlag(TIP_KEY);
    setTipHidden(true);
  };

  // phones start on the first blocks at a readable zoom; wider screens fit the board (or keep the saved view)
  const loaded = !!graph;
  const initialFit = useMemo<FitViewOptions | undefined>(() => {
    if (!graph) return undefined;
    const first = [...graph.nodes].sort((a, b) => a.x - b.x || a.y - b.y).slice(0, smallScreen ? 2 : graph.nodes.length);
    return { nodes: smallScreen ? first.map((n) => ({ id: String(n.id) })) : undefined, padding: chromePadding(false), maxZoom: 1, minZoom: smallScreen ? 0.55 : 0.15 };
    // only for the first view
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded]);

  const ariaLabels = useMemo(() => ({
    "node.a11yDescription.default": t("a11y.nodeHelp"),
    "node.a11yDescription.keyboardDisabled": t("a11y.nodeHelpKeyboard"),
    "edge.a11yDescription.default": t("a11y.edgeHelp"),
    "controls.ariaLabel": t("a11y.controls"),
    "controls.zoomIn.ariaLabel": t("a11y.zoomIn"),
    "controls.zoomOut.ariaLabel": t("a11y.zoomOut"),
    "controls.fitView.ariaLabel": t("a11y.fitView"),
    "minimap.ariaLabel": t("a11y.minimap"),
    "handle.ariaLabel": t("a11y.handle"),
  }), [t]);

  if (query.isLoading) {
    return <div className="flex h-full items-center justify-center"><Spinner size={28} /></div>;
  }
  if (!graph) {
    return <EmptyState icon="error" title={t("notFound")} text={query.error ? errorText(query.error) : undefined} />;
  }
  if (!storeReady) return null; // the store is filled in a layout effect, before the first paint

  const savedView = graph.board.pan_x || graph.board.pan_y || graph.board.zoom !== 1;
  const designNode = designNodeId ? blocksById.get(designNodeId) : null;
  const designInputs = designNode ? (() => {
    let imageUrl: string | null = null;
    let headline: string | null = null;
    for (const e of graph.edges.filter((x) => x.target === designNode.id)) {
      const src = blocksById.get(e.source);
      if (!src) continue;
      if (e.port === "background" && src.output?.kind === "image") imageUrl = src.output.url;
      if (e.port === "headline" && (src.output_text || src.text_value)) headline = headline || src.output_text || src.text_value;
    }
    return { imageUrl, headline };
  })() : null;
  const empty = !graph.nodes.length;
  const pickerKinds = linkPicker ? (() => {
    const from = blocksById.get(linkPicker.fromId);
    return from ? compatibleKinds(graph.kinds, from, linkPicker.handleType, linkPicker.port) : [];
  })() : [];

  return (
    <div className="relative h-full w-full overflow-hidden">
      <TopBar graph={graph} canUndo={canUndo && !readOnly} canRedo={canRedo && !readOnly} onUndo={undo} onRedo={redo}
        onRunAll={() => run(null)} onStop={stop} checking={checking} compact={smallScreen} />

      <div ref={wrapper} dir="ltr" className={cx("absolute inset-0", dropping && "outline-dashed outline-2 -outline-offset-[12px] outline-black/40", tidying && "production-tidying")}
        onDragOver={onDragOver} onDragLeave={() => setDropping(false)} onDrop={onDrop}
        onPointerMove={(e) => { pointer.current = { x: e.clientX, y: e.clientY }; }}>
        <ReactFlow<FlowNode, TypedFlowEdge>
          nodes={displayNodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeDragStart={onNodeDragStart}
          onNodeDragStop={onNodeDragStop}
          onConnect={onConnect}
          onConnectEnd={onConnectEnd}
          isValidConnection={isValidConnection}
          connectionLineComponent={ConnectionLine}
          onMoveEnd={onMoveEnd}
          onPaneClick={() => { setSelectedEdges([]); setMenu(null); }}
          onPaneContextMenu={(e) => openMenu(e)}
          onNodeContextMenu={(e, node) => node.type === "block" && openMenu(e, Number(node.id))}
          onSelectionContextMenu={(e, nodes) => { const first = nodes.find((n) => n.type === "block"); if (first) openMenu(e, Number(first.id)); }}
          defaultViewport={{ x: graph.board.pan_x || 0, y: graph.board.pan_y || 0, zoom: graph.board.zoom || 1 }}
          fitView={!savedView || smallScreen}
          fitViewOptions={initialFit}
          minZoom={0.15}
          maxZoom={2}
          snapToGrid
          snapGrid={[GRID, GRID]}
          panOnScroll
          zoomActivationKeyCode={["Meta", "Control"]}
          deleteKeyCode={null}
          selectionKeyCode="Shift"
          multiSelectionKeyCode={["Meta", "Control", "Shift"]}
          nodesDraggable={!readOnly}
          nodesConnectable={!readOnly}
          edgesFocusable={false}
          connectionRadius={28}
          ariaLabelConfig={ariaLabels}
          proOptions={{ hideAttribution: true }}
          className="production-flow"
        >
          <Background variant={BackgroundVariant.Dots} gap={GRID} size={1.4} color="rgba(0,0,0,.2)" bgColor="#f2f2f4" />
          {!empty && !selectedBlock && (
            <MiniMap pannable zoomable className="!hidden !rounded-2xl !border !border-white/70 !bg-white/70 !shadow-[0_10px_30px_-10px_rgba(0,0,0,.25)] backdrop-blur-xl md:!block"
              position="bottom-left" nodeBorderRadius={12}
              nodeColor={(n) => (n.type === "block" ? KIND_META[(n as BlockFlowNode).data.block.kind]?.color || "#999" : "transparent")}
              maskColor="rgba(242,242,244,.6)" />
          )}
          <Controls position="bottom-left" showInteractive={false} fitViewOptions={{ padding: chromePadding(!!selectedBlock), duration: 250, maxZoom: 1 }}
            className={cx("!overflow-hidden !rounded-xl !border !border-white/70 !shadow-[0_8px_24px_-10px_rgba(0,0,0,.25)]", empty ? "!mb-4" : "!mb-[150px] max-md:!mb-24")}>
            {!readOnly && !empty && (
              <ControlButton onClick={() => tidy(selectedIds)} title={`${t("menu.tidy")} (Shift+T)`} aria-label={t("menu.tidy")}>
                <Icon name="account_tree" size={14} />
              </ControlButton>
            )}
            <ControlButton onClick={() => setSearchOpen(true)} title={`${t("search.title")} (${MOD}+K)`} aria-label={t("search.title")}>
              <Icon name="search" size={14} />
            </ControlButton>
            <ControlButton onClick={() => setHelpOpen(true)} title={`${t("shortcuts.title")} (?)`} aria-label={t("shortcuts.title")}>
              <span className="text-[13px] font-semibold">?</span>
            </ControlButton>
          </Controls>
        </ReactFlow>
      </div>

      {empty && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center px-4">
          <div className="glass pop-in pointer-events-auto max-w-md rounded-[24px] p-2">
            <EmptyState icon="account_tree" title={t("emptyTitle")} text={readOnly ? t("emptyTextViewer") : t("emptyText")}
              action={!readOnly && (
                <div className="flex flex-wrap items-center justify-center gap-2">
                  <Button variant="primary" icon="text_fields" onClick={() => addBlock("text")}>{t("empty.addText")}</Button>
                  <Link href="/production" className="inline-flex h-10 items-center gap-1.5 rounded-full px-4 text-sm font-medium text-text-2 hover:bg-fill-2">
                    <Icon name="auto_awesome" size={16} />{t("empty.template")}
                  </Link>
                </div>
              )} />
            {!readOnly && <p className="-mt-6 pb-4 text-center text-xs text-muted">{smallScreen ? t("empty.dragHintPhone") : t("empty.dragHint")}</p>}
          </div>
        </div>
      )}

      {!tipHidden && nodeCount >= 2 && edgeCount === 0 && !readOnly && !selectedBlock && (
        <div role="note" className="glass-strong pop-in absolute inset-x-0 top-[76px] z-20 mx-auto flex w-max max-w-[calc(100%-24px)] items-center gap-3 rounded-2xl py-2 pe-2 ps-3 text-[13px]">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-fill-2"><Icon name="link" size={16} /></span>
          <span className="max-w-md">{t("tip.link")}</span>
          <Button size="sm" variant="ghost" onClick={dismissTip}>{t("tip.ok")}</Button>
        </div>
      )}

      {selectedIds.length > 1 && !readOnly && (
        <div className="glass-strong pop-in absolute inset-x-0 top-[76px] z-20 mx-auto flex w-max max-w-[calc(100%-24px)] flex-wrap items-center gap-1.5 rounded-full py-1.5 pe-1.5 ps-4 text-[13px]">
          <span className="font-semibold">{t("selected", { count: selectedIds.length })}</span>
          <Button size="sm" variant="ghost" icon="select_group" onClick={() => group(selectedIds)} title={`${MOD}+G`}>{t("group")}</Button>
          <Button size="sm" variant="ghost" icon="content_copy" onClick={() => copy(selectedIds)} title={`${MOD}+C`}>{t("copy")}</Button>
          <Button size="sm" variant="ghost" icon="content_paste" onClick={() => duplicate(selectedIds)} title={`${MOD}+D`}>{t("duplicate")}</Button>
          <Button size="sm" variant="ghost" icon="account_tree" onClick={() => tidy(selectedIds)} title="Shift+T" className="max-sm:hidden">{t("menu.tidy")}</Button>
          <Button size="sm" variant="ghost" icon="play_arrow" onClick={() => run(selectedIds)} title={`${MOD}+Enter`}>{t("run")}</Button>
          <Button size="sm" variant="danger" icon="delete" onClick={deleteSelection} title="Delete">{t("delete")}</Button>
        </div>
      )}

      {!readOnly && !smallScreen && <Toolbar onAdd={(kind) => addBlock(kind)} inspectorOpen={!!selectedBlock} />}
      {!readOnly && smallScreen && !selectedBlock && (
        <div className="absolute inset-x-0 bottom-4 z-20 flex justify-center">
          <Button variant="primary" size="lg" icon="add" onClick={() => setAddSheet(true)} className="shadow-[0_14px_30px_-10px_rgba(0,0,0,.5)]">{t("addBlock")}</Button>
        </div>
      )}

      {selectedBlock && (
        <div ref={inspectorBox} className="absolute inset-x-2 bottom-2 z-30 flex max-h-[62vh] lg:inset-x-auto lg:bottom-3 lg:end-3 lg:top-[76px] lg:max-h-none lg:w-[350px]">
          <Inspector key={selectedBlock.id} node={selectedBlock} onClose={() => select([])} />
        </div>
      )}

      {summary && <RunSummary result={summary} raised={!!selectedBlock} onClose={() => setSummary(null)} onShowFailed={() => showIds(summary.failed)} />}
      <div aria-live="polite" role="status" className="sr-only">{announce}</div>

      <input id={fileInputId} type="file" accept="image/*,video/*,audio/*" className="hidden"
        onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />

      {menu && <ContextMenu x={menu.x} y={menu.y} items={menuItems(menu)} label={t("menu.label")} onClose={() => setMenu(null)} />}
      {linkPicker && (
        <KindPopover x={linkPicker.x} y={linkPicker.y} kinds={pickerKinds} title={t("picker.linkTitle")}
          onPick={(kind) => addLinked(kind, linkPicker)} onClose={() => setLinkPicker(null)} />
      )}
      {addAt && (
        <KindPopover x={addAt.x} y={addAt.y} kinds={TOOLBAR_KINDS} title={t("menu.addBlock")}
          onPick={(kind) => addBlock(kind, { x: addAt.flow.x, y: addAt.flow.y })} onClose={() => setAddAt(null)} />
      )}
      {addSheet && (
        <Modal open onClose={() => setAddSheet(false)} title={t("addBlock")} size="md">
          <KindList kinds={TOOLBAR_KINDS} onPick={(kind) => { setAddSheet(false); addBlock(kind); }} />
        </Modal>
      )}
      {preflight && <PreflightDialog state={preflight} blocks={blocksById} onClose={() => setPreflight(null)} onShow={(ids) => { setPreflight(null); showIds(ids); }} />}
      {lightbox && <Lightbox nodeId={lightbox.nodeId} outputId={lightbox.outputId} onClose={() => setLightbox(null)} />}
      {searchOpen && (
        <SearchPalette blocks={graph.nodes} groups={graph.groups} onClose={() => setSearchOpen(false)}
          onPickBlock={focusBlock} onPickGroup={(g) => fitTo(g.nodes)} />
      )}
      {helpOpen && <ShortcutsSheet onClose={() => setHelpOpen(false)} />}

      {designNode && designInputs && graph.brand && (
        <DesignEditor initial={designNode.design as Partial<DesignState> | null} aspect={designNode.aspect}
          imageUrl={designInputs.imageUrl} headline={designInputs.headline} brand={graph.brand}
          onSave={(png, design) => actions.saveDesign(designNode.id, png, design as unknown as Record<string, unknown>)}
          onClose={() => setDesignNodeId(null)} />
      )}

      <style>{`
        .production-flow .react-flow__handle { min-width: 0; min-height: 0; }
        .production-flow .react-flow__node:focus { outline: none; }
        .production-flow .react-flow__node:focus-visible .block-card { outline: 3px solid rgba(37, 99, 235, .55); outline-offset: 3px; }
        .production-flow .react-flow__controls-button { background: rgba(255,255,255,.8); border-bottom-color: rgba(0,0,0,.06); }
        .production-flow .react-flow__controls-button:focus-visible { outline: 2px solid rgba(37, 99, 235, .6); outline-offset: -2px; }
        .production-flow .react-flow__edge.selected .react-flow__edge-path { stroke-width: 3; }
        .production-tidying .react-flow__node { transition: transform 300ms cubic-bezier(.2,.8,.2,1); }
        @keyframes production-dash { to { stroke-dashoffset: -12; } }
        @media (prefers-reduced-motion: reduce) { .production-tidying .react-flow__node { transition: none; } }
      `}</style>
    </div>
  );
}

export type { BlockNode };
