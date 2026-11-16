"use client";
/**
 * Canvas state shared by the blocks, the inspector and the chrome (zustand). Blocks subscribe to their own slice
 * (`useCanvasStore((s) => s.portCounts.get(id))`), so a poll that changes one block re-renders that block only.
 * Also holds the undo / redo history (moves, links, adds, deletes, block settings, groups).
 */
import { create } from "zustand";
import { pickPort } from "./meta";
import type { BlockGroup, BlockNode, Graph, Kind } from "./types";
import type { BoardActions } from "./use-board";

export type UndoEntry =
  | { type: "archive"; node_ids: number[]; edge_ids: number[] }
  | { type: "add"; node_ids: number[]; edge_ids: number[]; replaced?: number[] }
  | { type: "connect"; edge_id: number; replaced: number[] }
  | { type: "move"; before: Record<number, [number, number]>; after: Record<number, [number, number]> }
  | { type: "update"; id: number; before: Record<string, unknown>; after: Record<string, unknown>; at: number }
  | { type: "group"; group_id: number; node_ids: number[]; name: string }
  | { type: "ungroup"; group_id: number; node_ids: number[]; name: string }
  | { type: "rename-group"; group_id: number; before: string; after: string };

export type RunMode = { downstream?: boolean; force?: boolean };

/** Callbacks of the canvas the blocks and panels use (stable references). */
export type CanvasUi = {
  select: (ids: number[]) => void;
  openDesign: (nodeId: number) => void;
  pickFile: (nodeId: number) => void;
  /** run with the preflight checks (missing providers, empty texts, cost confirmation) */
  run: (nodeIds: number[] | null, mode?: RunMode) => void;
  openLightbox: (nodeId: number, outputId?: number | null) => void;
  focusBlock: (nodeId: number) => void;
};

type State = {
  graph: Graph | null;
  blocks: Map<number, BlockNode>;
  kinds: Map<string, Kind>;
  /** links per input port of each block (same object while unchanged) */
  portCounts: Map<number, Record<string, number>>;
  readOnly: boolean;
  actions: BoardActions | null;
  ui: CanvasUi;
  /** blocks to point at (e.g. empty text blocks a run needs) */
  highlight: number[];
  /** AI credits per US dollar when the board is paid with the platform's AI credits, else null */
  creditsPerUsd: number | null;
  undoStack: UndoEntry[];
  redoStack: UndoEntry[];
  /** blocks of the run in progress (queued, running or finished since it started) */
  runIds: number[];
};

const EMPTY: Record<string, number> = {};
const impl: { current: CanvasUi | null } = { current: null };
const call = <K extends keyof CanvasUi>(key: K) => ((...args: unknown[]) =>
  (impl.current?.[key] as ((...a: unknown[]) => void) | undefined)?.(...args)) as CanvasUi[K];

export const useCanvasStore = create<State>(() => ({
  graph: null,
  blocks: new Map(),
  kinds: new Map(),
  portCounts: new Map(),
  readOnly: true,
  actions: null,
  ui: { select: call("select"), openDesign: call("openDesign"), pickFile: call("pickFile"), run: call("run"),
    openLightbox: call("openLightbox"), focusBlock: call("focusBlock") },
  highlight: [],
  creditsPerUsd: null,
  undoStack: [],
  redoStack: [],
  runIds: [],
}));

const get = useCanvasStore.getState;
const set = useCanvasStore.setState;

/** The canvas gives its current callbacks (called through the stable `ui` object). */
export function bindUi(ui: CanvasUi) {
  impl.current = ui;
}

/** A new board opens: forget the history of the previous one. */
export function resetCanvas(actions: BoardActions, readOnly: boolean) {
  groupAlias.clear();
  set({ graph: null, blocks: new Map(), kinds: new Map(), portCounts: new Map(), actions, readOnly, highlight: [], undoStack: [], redoStack: [], runIds: [] });
}

export function setCanvasMeta(values: Partial<Pick<State, "actions" | "readOnly" | "creditsPerUsd" | "highlight" | "runIds">>) {
  set(values);
}

/** Derives the per-block lookups once per graph, keeping unchanged parts identical. */
export function syncGraph(graph: Graph) {
  const state = get();
  if (state.graph === graph) return;
  const blocks = state.graph?.nodes === graph.nodes ? state.blocks : new Map(graph.nodes.map((n) => [n.id, n]));
  const kinds = state.graph?.kinds === graph.kinds ? state.kinds : new Map(graph.kinds.map((k) => [k.key, k]));
  let portCounts = state.portCounts;
  if (state.graph?.edges !== graph.edges || state.graph?.nodes !== graph.nodes) {
    const fresh = new Map<number, Record<string, number>>();
    for (const e of graph.edges) {
      const counts = fresh.get(e.target) || {};
      counts[e.port] = (counts[e.port] || 0) + 1;
      fresh.set(e.target, counts);
    }
    portCounts = new Map();
    for (const node of graph.nodes) {
      const next = fresh.get(node.id) || EMPTY;
      const prev = state.portCounts.get(node.id);
      portCounts.set(node.id, prev && JSON.stringify(prev) === JSON.stringify(next) ? prev : next);
    }
  }
  set({ graph, blocks, kinds, portCounts });
}

let upsCache: { edges: Graph["edges"] | null; ups: Map<number, number[]> } = { edges: null, ups: new Map() };
function upstreamOf(edges: Graph["edges"]) {
  if (upsCache.edges !== edges) {
    const ups = new Map<number, number[]>();
    for (const e of edges) ups.set(e.target, [...(ups.get(e.target) || []), e.source]);
    upsCache = { edges, ups };
  }
  return upsCache.ups;
}

/** Would linking `source` → `target` (on `port`) be accepted: compatible types and no loop. */
export function canLink(sourceId: number, targetId: number, port?: string | null) {
  const { graph, blocks } = get();
  const source = blocks.get(sourceId);
  const target = blocks.get(targetId);
  if (!graph || !source || !target) return false;
  if (!pickPort(graph.kinds, source, target, port)) return false;
  const ups = upstreamOf(graph.edges);
  const todo = [sourceId];
  const seen = new Set<number>();
  while (todo.length) {
    const id = todo.pop()!;
    if (id === targetId) return false;
    for (const up of ups.get(id) || []) if (!seen.has(up)) { seen.add(up); todo.push(up); }
  }
  return true;
}

// ------------------------------------------------------------------ undo / redo
export function pushUndo(entry: UndoEntry) {
  set((s) => ({ undoStack: [...s.undoStack.slice(-79), entry], redoStack: [] }));
}

/** Group ids change when an undo makes a group again: later entries follow the new id. */
const groupAlias = new Map<number, number>();
const groupId = (id: number) => {
  let current = id;
  for (let i = 0; i < 20 && groupAlias.has(current); i++) current = groupAlias.get(current)!;
  return current;
};

const COALESCE_MS = 800;

/** Changes block settings (optimistic) and records them for undo; quick bursts on the same fields make one step. */
export async function updateNode(id: number, values: Record<string, unknown>) {
  const { actions, readOnly, blocks, undoStack } = get();
  const node = blocks.get(id);
  if (!actions || readOnly || !node) return;
  const before: Record<string, unknown> = {};
  for (const key of Object.keys(values)) before[key] = (node as Record<string, unknown>)[key] ?? null;
  if (JSON.stringify(before) === JSON.stringify(values)) return;
  const now = Date.now();
  const last = undoStack[undoStack.length - 1];
  const sameFields = last?.type === "update" && last.id === id && Object.keys(last.after).sort().join() === Object.keys(values).sort().join();
  if (last?.type === "update" && sameFields && now - last.at < COALESCE_MS) {
    set((s) => ({ undoStack: [...s.undoStack.slice(0, -1), { ...last, after: values, at: now }], redoStack: [] }));
  } else {
    pushUndo({ type: "update", id, before, after: values, at: now });
  }
  await actions.updateNode(id, values).catch(() => undefined);
}

export async function groupNodes(nodeIds: number[]) {
  const { actions, readOnly } = get();
  if (!actions || readOnly || !nodeIds.length) return;
  const group = await actions.group(nodeIds).catch(() => null);
  if (group) pushUndo({ type: "group", group_id: group.id, node_ids: group.nodes, name: group.name });
}

export async function ungroup(group: BlockGroup) {
  const { actions, readOnly } = get();
  if (!actions || readOnly) return;
  await actions.ungroup(group.id).then(() => pushUndo({ type: "ungroup", group_id: group.id, node_ids: group.nodes, name: group.name }))
    .catch(() => undefined);
}

export async function renameGroup(group: BlockGroup, name: string) {
  const { actions, readOnly } = get();
  if (!actions || readOnly || name === group.name) return;
  await actions.renameGroup(group.id, name).then(() => pushUndo({ type: "rename-group", group_id: group.id, before: group.name, after: name }))
    .catch(() => undefined);
}

async function regroup(entry: { group_id: number; node_ids: number[]; name: string }, actions: BoardActions) {
  const group = await actions.group(entry.node_ids, entry.name);
  groupAlias.set(groupId(entry.group_id), group.id);
}

async function apply(entry: UndoEntry, undo: boolean, actions: BoardActions) {
  switch (entry.type) {
    case "archive":
      return undo ? actions.restore(entry.node_ids, entry.edge_ids) : void (await actions.archive(entry.node_ids, entry.edge_ids));
    case "add":
      if (undo) {
        await actions.archive(entry.node_ids, entry.edge_ids);
        if (entry.replaced?.length) await actions.restore([], entry.replaced);
      } else {
        if (entry.replaced?.length) await actions.archive([], entry.replaced);
        await actions.restore(entry.node_ids, entry.edge_ids);
      }
      return;
    case "connect":
      if (undo) {
        await actions.archive([], [entry.edge_id]);
        if (entry.replaced.length) await actions.restore([], entry.replaced);
      } else {
        if (entry.replaced.length) await actions.archive([], entry.replaced);
        await actions.restore([], [entry.edge_id]);
      }
      return;
    case "move":
      return actions.savePositions(undo ? entry.before : entry.after);
    case "update":
      return void (await actions.updateNode(entry.id, undo ? entry.before : entry.after));
    case "group":
      return undo ? actions.ungroup(groupId(entry.group_id)) : regroup(entry, actions);
    case "ungroup":
      return undo ? regroup(entry, actions) : actions.ungroup(groupId(entry.group_id));
    case "rename-group":
      return actions.renameGroup(groupId(entry.group_id), undo ? entry.before : entry.after);
  }
}

let undoing = false;

export async function undo() {
  const { undoStack, actions, readOnly } = get();
  const entry = undoStack[undoStack.length - 1];
  if (!entry || !actions || readOnly || undoing) return;
  undoing = true;
  set((s) => ({ undoStack: s.undoStack.slice(0, -1) }));
  try {
    await apply(entry, true, actions);
    set((s) => ({ redoStack: [...s.redoStack, entry] }));
  } catch {
    /* the action showed the error */
  } finally {
    undoing = false;
  }
}

export async function redo() {
  const { redoStack, actions, readOnly } = get();
  const entry = redoStack[redoStack.length - 1];
  if (!entry || !actions || readOnly || undoing) return;
  undoing = true;
  set((s) => ({ redoStack: s.redoStack.slice(0, -1) }));
  try {
    await apply(entry, false, actions);
    set((s) => ({ undoStack: [...s.undoStack, { ...entry, ...(entry.type === "update" ? { at: 0 } : {}) }] }));
  } catch {
    /* the action showed the error */
  } finally {
    undoing = false;
  }
}
