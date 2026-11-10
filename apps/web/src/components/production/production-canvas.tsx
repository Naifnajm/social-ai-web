"use client";
/**
 * Production canvas (React Flow): typed blocks and links, groups, undo/redo, copy/paste, keyboard shortcuts,
 * file drop, inspector, variables & batch versions, brand kit, run all with cost estimate, design editor.
 * The page is RTL in Arabic, but the flow itself stays left-to-right (inputs on the left, output on the right).
 */
import "@xyflow/react/dist/style.css";
import {
  Background, BackgroundVariant, type Connection, Controls, type Edge, type EdgeChange, MiniMap, type Node, type NodeChange,
  ReactFlow, ReactFlowProvider, applyNodeChanges, useReactFlow,
} from "@xyflow/react";
import { useTranslations } from "next-intl";
import { type DragEvent, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Button, EmptyState, Spinner, cx, toast } from "@/components/ui";
import { useSession } from "@/lib/session";
import { BlockNodeComponent, type BlockFlowNode } from "./block-node";
import { CanvasContext, type CanvasApi } from "./canvas-context";
import { DesignEditor, type DesignState } from "./design-editor";
import { GroupFrame, type GroupFlowNode, TypedEdge, type TypedFlowEdge } from "./flow-parts";
import { Inspector } from "./inspector";
import { KIND_META, NODE_W, isRunning, pickPort, typeColor } from "./meta";
import { TopBar } from "./top-bar";
import { Toolbar } from "./toolbar";
import type { BlockGroup, BlockNode, Graph } from "./types";
import { errorText, useBoard } from "./use-board";

type FlowNode = BlockFlowNode | GroupFlowNode;
type UndoEntry =
  | { type: "archive"; node_ids: number[]; edge_ids: number[] }
  | { type: "add"; node_ids: number[]; edge_ids: number[] }
  | { type: "connect"; edge_id: number; replaced: number[] }
  | { type: "move"; before: Record<number, [number, number]>; after: Record<number, [number, number]> };

const CLIPBOARD_KEY = "production.clipboard";
const nodeTypes = { block: BlockNodeComponent, "group-frame": GroupFrame };
const edgeTypes = { typed: TypedEdge };
const FRAME_PAD = 28;
const FRAME_HEAD = 46;

function readClipboard(): number[] {
  try {
    const data = JSON.parse(window.localStorage.getItem(CLIPBOARD_KEY) || "null");
    return Array.isArray(data?.ids) ? data.ids : [];
  } catch {
    return [];
  }
}

function writeClipboard(ids: number[]) {
  try {
    window.localStorage.setItem(CLIPBOARD_KEY, JSON.stringify({ ids, at: Date.now() }));
  } catch {
    /* storage unavailable */
  }
}

/** Builds the React Flow block nodes from the graph, keeping selection / sizes / drag state of the previous ones. */
function buildBlocks(graph: Graph, previous: FlowNode[]): BlockFlowNode[] {
  const prev = new Map(previous.filter((n) => n.type === "block").map((n) => [n.id, n as BlockFlowNode]));
  return graph.nodes.map((block) => {
    const id = String(block.id);
    const old = prev.get(id);
    return {
      id,
      type: "block" as const,
      position: old?.dragging ? old.position : { x: block.x, y: block.y },
      data: { block },
      selected: old?.selected,
      measured: old?.measured,
      dragging: old?.dragging,
      zIndex: 1,
      dragHandle: undefined,
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
    frames.push({
      id: `group-${group.id}`,
      type: "group-frame",
      position: { x: minX, y: minY },
      data: { groupId: group.id, name: group.name, color: group.color, width: maxX - minX, height: maxY - minY },
      zIndex: 0,
      selectable: false,
      dragHandle: ".group-handle",
      style: { pointerEvents: "none" },
    });
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
  const fileInputId = useId();
  const [uploadTarget, setUploadTarget] = useState<number | null>(null);
  const viewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dragStart = useRef<Record<number, [number, number]>>({});

  const [rfNodes, setRfNodes] = useState<BlockFlowNode[]>([]);
  const [synced, setSynced] = useState<Graph["nodes"] | null>(null);
  const [selectedEdges, setSelectedEdges] = useState<string[]>([]);
  const [designNodeId, setDesignNodeId] = useState<number | null>(null);
  const [undoStack, setUndoStack] = useState<UndoEntry[]>([]);
  const [redoStack, setRedoStack] = useState<UndoEntry[]>([]);
  const [dropping, setDropping] = useState(false);
  const [smallScreen] = useState(() => typeof window !== "undefined" && window.innerWidth < 768);

  // keep the React Flow nodes in step with the server graph (adjusting state while rendering, no effect)
  if (graph && synced !== graph.nodes) {
    setSynced(graph.nodes);
    setRfNodes((prev) => buildBlocks(graph, prev));
  }

  const blocksById = useMemo(() => new Map((graph?.nodes || []).map((n) => [n.id, n])), [graph?.nodes]);
  const selectedIds = useMemo(() => rfNodes.filter((n) => n.selected).map((n) => Number(n.id)), [rfNodes]);
  const selectedBlock = selectedIds.length === 1 ? blocksById.get(selectedIds[0]) || null : null;
  const frames = useMemo(() => groupFrames(graph?.groups || [], rfNodes), [graph?.groups, rfNodes]);
  const displayNodes = useMemo<FlowNode[]>(() => [...frames, ...rfNodes], [frames, rfNodes]);
  const edges = useMemo<TypedFlowEdge[]>(() => (graph?.edges || []).map((e) => ({
    id: String(e.id),
    source: String(e.source),
    target: String(e.target),
    sourceHandle: "out",
    targetHandle: e.port,
    type: "typed" as const,
    data: { type: e.type, running: isRunning(blocksById.get(e.target)?.state || "") },
    selected: selectedEdges.includes(String(e.id)),
  })), [graph?.edges, blocksById, selectedEdges]);

  const pushUndo = useCallback((entry: UndoEntry) => {
    setUndoStack((s) => [...s.slice(-49), entry]);
    setRedoStack([]);
  }, []);

  const select = useCallback((ids: number[]) => {
    setRfNodes((nodes) => nodes.map((n) => ({ ...n, selected: ids.includes(Number(n.id)) })));
    setSelectedEdges([]);
  }, []);

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
  }, [rfNodes, actions, pushUndo]);

  // ------------------------------------------------------------------ links
  const wouldLoop = useCallback((source: number, target: number) => {
    const ups = new Map<number, number[]>();
    for (const e of graph?.edges || []) ups.set(e.target, [...(ups.get(e.target) || []), e.source]);
    const todo = [source];
    const seen = new Set<number>();
    while (todo.length) {
      const id = todo.pop()!;
      if (id === target) return true;
      for (const up of ups.get(id) || []) if (!seen.has(up)) { seen.add(up); todo.push(up); }
    }
    return false;
  }, [graph?.edges]);

  const isValidConnection = useCallback((conn: Connection | Edge) => {
    if (!graph) return false;
    const source = blocksById.get(Number(conn.source));
    const target = blocksById.get(Number(conn.target));
    if (!source || !target) return false;
    return !!pickPort(graph.kinds, source, target, conn.targetHandle) && !wouldLoop(source.id, target.id);
  }, [graph, blocksById, wouldLoop]);

  const onConnect = useCallback(async (conn: Connection) => {
    try {
      const edge = await actions.connect(Number(conn.source), Number(conn.target), conn.targetHandle);
      pushUndo({ type: "connect", edge_id: edge.id, replaced: edge.replaced });
    } catch {
      /* toast shown */
    }
  }, [actions, pushUndo]);

  // ------------------------------------------------------------------ add / delete / paste / group
  const centerPosition = useCallback(() => {
    const rect = wrapper.current?.getBoundingClientRect();
    const point = flow.screenToFlowPosition({ x: (rect?.left || 0) + (rect?.width || 800) / 2, y: (rect?.top || 0) + (rect?.height || 600) / 2.4 });
    return { x: Math.round(point.x - NODE_W / 2 + (Math.random() - 0.5) * 60), y: Math.round(point.y - 120 + (Math.random() - 0.5) * 60) };
  }, [flow]);

  const addBlock = useCallback(async (kind: string, position?: { x: number; y: number }) => {
    if (readOnly) return;
    const { x, y } = position || centerPosition();
    try {
      const node = await actions.addNode(kind, Math.round(x), Math.round(y));
      pushUndo({ type: "add", node_ids: [node.id], edge_ids: [] });
      select([node.id]);
      return node;
    } catch {
      return undefined;
    }
  }, [readOnly, centerPosition, actions, pushUndo, select]);

  const deleteSelection = useCallback(async () => {
    if (readOnly || (!selectedIds.length && !selectedEdges.length)) return;
    const removed = await actions.archive(selectedIds, selectedEdges.map(Number)).catch(() => null);
    if (removed && (removed.node_ids.length || removed.edge_ids.length)) pushUndo({ type: "archive", ...removed });
    setSelectedEdges([]);
  }, [readOnly, selectedIds, selectedEdges, actions, pushUndo]);

  const paste = useCallback(async (ids: number[], dx = 40, dy = 40) => {
    if (readOnly || !ids.length) return;
    const result = await actions.paste(ids, dx, dy).catch(() => null);
    if (!result) return;
    pushUndo({ type: "add", node_ids: result.nodes.map((n) => n.id), edge_ids: result.edges.map((e) => e.id) });
    select(result.nodes.map((n) => n.id));
  }, [readOnly, actions, pushUndo, select]);

  const group = useCallback(async () => {
    if (readOnly || selectedIds.length < 1) return;
    await actions.group(selectedIds).catch(() => undefined);
  }, [readOnly, selectedIds, actions]);

  const apply = useCallback(async (entry: UndoEntry, direction: "undo" | "redo") => {
    const undo = direction === "undo";
    if (entry.type === "archive") {
      if (undo) await actions.restore(entry.node_ids, entry.edge_ids);
      else await actions.archive(entry.node_ids, entry.edge_ids);
    } else if (entry.type === "add") {
      if (undo) await actions.archive(entry.node_ids, entry.edge_ids);
      else await actions.restore(entry.node_ids, entry.edge_ids);
    } else if (entry.type === "connect") {
      if (undo) {
        await actions.archive([], [entry.edge_id]);
        if (entry.replaced.length) await actions.restore([], entry.replaced);
      } else {
        if (entry.replaced.length) await actions.archive([], entry.replaced);
        await actions.restore([], [entry.edge_id]);
      }
    } else {
      await actions.savePositions(undo ? entry.before : entry.after);
    }
  }, [actions]);

  const undo = useCallback(async () => {
    const entry = undoStack[undoStack.length - 1];
    if (!entry || readOnly) return;
    setUndoStack((s) => s.slice(0, -1));
    try {
      await apply(entry, "undo");
      setRedoStack((s) => [...s, entry]);
    } catch (err) {
      toast.error(errorText(err));
    }
  }, [undoStack, readOnly, apply]);

  const redo = useCallback(async () => {
    const entry = redoStack[redoStack.length - 1];
    if (!entry || readOnly) return;
    setRedoStack((s) => s.slice(0, -1));
    try {
      await apply(entry, "redo");
      setUndoStack((s) => [...s, entry]);
    } catch (err) {
      toast.error(errorText(err));
    }
  }, [redoStack, readOnly, apply]);

  const runNode = useCallback((nodeId: number, force = false) => {
    actions.run([nodeId], { force }).catch(() => undefined);
  }, [actions]);

  const runSelection = useCallback(() => {
    actions.run(selectedIds.length ? selectedIds : null).catch(() => undefined);
  }, [actions, selectedIds]);

  // ------------------------------------------------------------------ keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.closest("input, textarea, select, [contenteditable=true]") || target.closest("[role=dialog]"))) return;
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
        writeClipboard(selectedIds);
        toast.info(t("copied", { count: selectedIds.length }));
      } else if (mod && key === "v") {
        paste(readClipboard());
      } else if (mod && key === "d" && selectedIds.length) {
        e.preventDefault();
        paste(selectedIds, 40, 40);
      } else if (mod && key === "a") {
        e.preventDefault();
        select(rfNodes.map((n) => Number(n.id)));
      } else if (mod && key === "g") {
        e.preventDefault();
        group();
      } else if (mod && key === "enter") {
        e.preventDefault();
        runSelection();
      } else if (key === "escape") {
        select([]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [deleteSelection, undo, redo, paste, selectedIds, select, rfNodes, group, runSelection, t]);

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
        const node = await actions.addNode("upload", Math.round(position.x - NODE_W / 2 + index * 40), Math.round(position.y - 40 + index * 40), { name: file.name.slice(0, 160) });
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

  const onMoveEnd = useCallback((event: unknown, viewport: { x: number; y: number; zoom: number }) => {
    // only moves made by the person are remembered (not fitView), and not from a phone
    if (readOnly || !event || smallScreen) return;
    if (viewTimer.current) clearTimeout(viewTimer.current);
    viewTimer.current = setTimeout(() => actions.saveView(viewport.zoom, viewport.x, viewport.y), 600);
  }, [actions, readOnly, smallScreen]);

  const canvasApi = useMemo<CanvasApi | null>(() => graph ? {
    graph, actions, readOnly, select, openDesign: setDesignNodeId, pickFile, runNode,
  } : null, [graph, actions, readOnly, select, pickFile, runNode]);

  if (query.isLoading) {
    return <div className="flex h-full items-center justify-center"><Spinner size={28} /></div>;
  }
  if (!graph || !canvasApi) {
    return <EmptyState icon="error" title={t("notFound")} text={query.error ? errorText(query.error) : undefined} />;
  }

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

  return (
    <CanvasContext.Provider value={canvasApi}>
      <div className="relative h-full w-full overflow-hidden">
        <TopBar graph={graph} canUndo={!!undoStack.length && !readOnly} canRedo={!!redoStack.length && !readOnly} onUndo={undo} onRedo={redo} />

        <div ref={wrapper} dir="ltr" className={cx("absolute inset-0", dropping && "outline-dashed outline-2 -outline-offset-[12px] outline-black/40")}
          onDragOver={onDragOver} onDragLeave={() => setDropping(false)} onDrop={onDrop}>
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
            isValidConnection={isValidConnection}
            onMoveEnd={onMoveEnd}
            onPaneClick={() => setSelectedEdges([])}
            defaultViewport={{ x: graph.board.pan_x || 0, y: graph.board.pan_y || 0, zoom: graph.board.zoom || 1 }}
            fitView={!savedView || smallScreen}
            fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
            minZoom={0.15}
            maxZoom={2}
            deleteKeyCode={null}
            selectionKeyCode="Shift"
            multiSelectionKeyCode={["Meta", "Control", "Shift"]}
            nodesDraggable={!readOnly}
            nodesConnectable={!readOnly}
            connectionRadius={28}
            connectionLineStyle={{ stroke: "#0a0a0a", strokeWidth: 2, strokeDasharray: "6 5" }}
            proOptions={{ hideAttribution: true }}
            className="production-flow"
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1.4} color="rgba(0,0,0,.2)" bgColor="#f2f2f4" />
            <MiniMap pannable zoomable className="!hidden !rounded-2xl !border !border-white/70 !bg-white/70 !shadow-[0_10px_30px_-10px_rgba(0,0,0,.25)] backdrop-blur-xl md:!block"
              position="bottom-left" nodeBorderRadius={12}
              nodeColor={(n) => (n.type === "block" ? KIND_META[(n as BlockFlowNode).data.block.kind]?.color || "#999" : "transparent")}
              maskColor="rgba(242,242,244,.6)" />
            <Controls position="bottom-left" showInteractive={false}
              className="!mb-[150px] !overflow-hidden !rounded-xl !border !border-white/70 !shadow-[0_8px_24px_-10px_rgba(0,0,0,.25)] max-md:!mb-24" />
          </ReactFlow>
        </div>

        {!graph.nodes.length && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <div className="glass pointer-events-auto max-w-sm rounded-[24px] p-2">
              <EmptyState icon="account_tree" title={t("emptyTitle")} text={t("emptyText")} />
            </div>
          </div>
        )}

        {selectedIds.length > 1 && !readOnly && (
          <div className="glass-strong pop-in absolute inset-x-0 top-[76px] z-20 mx-auto flex w-max max-w-[calc(100%-24px)] flex-wrap items-center gap-1.5 rounded-full py-1.5 pe-1.5 ps-4 text-[13px]">
            <span className="font-semibold">{t("selected", { count: selectedIds.length })}</span>
            <Button size="sm" variant="ghost" icon="select_group" onClick={group}>{t("group")}</Button>
            <Button size="sm" variant="ghost" icon="content_copy" onClick={() => { writeClipboard(selectedIds); toast.info(t("copied", { count: selectedIds.length })); }}>{t("copy")}</Button>
            <Button size="sm" variant="ghost" icon="content_paste" onClick={() => paste(selectedIds)}>{t("duplicate")}</Button>
            <Button size="sm" variant="ghost" icon="play_arrow" onClick={runSelection}>{t("run")}</Button>
            <Button size="sm" variant="danger" icon="delete" onClick={deleteSelection}>{t("delete")}</Button>
          </div>
        )}

        {!readOnly && <Toolbar onAdd={(kind) => addBlock(kind)} inspectorOpen={!!selectedBlock} />}

        {selectedBlock && (
          <div className="absolute inset-x-2 bottom-2 z-30 flex max-h-[62vh] lg:inset-x-auto lg:bottom-3 lg:right-3 lg:top-[76px] lg:max-h-none lg:w-[350px]">
            <Inspector key={selectedBlock.id} node={selectedBlock} onClose={() => select([])} />
          </div>
        )}

        <input id={fileInputId} type="file" accept="image/*,video/*,audio/*" className="hidden"
          onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />

        {designNode && designInputs && graph.brand && (
          <DesignEditor initial={designNode.design as Partial<DesignState> | null} aspect={designNode.aspect}
            imageUrl={designInputs.imageUrl} headline={designInputs.headline} brand={graph.brand}
            onSave={(png, design) => actions.saveDesign(designNode.id, png, design as unknown as Record<string, unknown>)}
            onClose={() => setDesignNodeId(null)} />
        )}

        <style>{`
          .production-flow .react-flow__handle { min-width: 0; min-height: 0; }
          .production-flow .react-flow__node.selectable:focus-visible { outline: none; }
          .production-flow .react-flow__controls-button { background: rgba(255,255,255,.8); border-bottom-color: rgba(0,0,0,.06); }
          .production-flow .react-flow__edge.selected .react-flow__edge-path { stroke-width: 3; }
          .production-flow .react-flow__connection-path { stroke: ${typeColor("media")}; }
          @keyframes production-dash { to { stroke-dashoffset: -12; } }
        `}</style>
      </div>
    </CanvasContext.Provider>
  );
}

export type { BlockNode };
