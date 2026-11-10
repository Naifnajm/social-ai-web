"use client";
/** Board data for the canvas: the graph (React Query), polling while a run is busy, and the API actions. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo } from "react";
import { toast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { BlockEdge, BlockGroup, BlockNode, Graph, RunEstimate } from "./types";

export const boardKey = (id: number) => ["production", "board", id] as const;

export function errorText(err: unknown) {
  return err instanceof ApiError ? err.message : String(err);
}

function fail(err: unknown): never {
  toast.error(errorText(err));
  throw err;
}

export function useBoard(boardId: number) {
  const qc = useQueryClient();
  const key = useMemo(() => boardKey(boardId), [boardId]);
  const query = useQuery({ queryKey: key, queryFn: () => api.get<Graph>(`/production/boards/${boardId}`) });
  const busy = !!query.data?.busy;

  // while blocks run, poll the light graph (states, progress, results) and merge it in
  const poll = useQuery({
    queryKey: [...key, "light"],
    queryFn: () => api.get<Graph>(`/production/boards/${boardId}`, { light: true }),
    enabled: busy,
    refetchInterval: busy ? 2500 : false,
  });
  useEffect(() => {
    const light = poll.data;
    if (!light) return;
    const current = qc.getQueryData<Graph>(key);
    if (!current) return;
    const estimates = new Map(current.nodes.map((n) => [n.id, n.estimate]));
    qc.setQueryData<Graph>(key, {
      ...current,
      board: light.board,
      nodes: light.nodes.map((n) => ({ ...n, estimate: n.estimate ?? estimates.get(n.id) ?? null })),
      edges: light.edges,
      groups: light.groups,
      busy: light.busy,
    });
    if (!light.busy) qc.invalidateQueries({ queryKey: key, exact: true });
  }, [poll.data, qc, key]);

  const setGraph = useCallback((update: (g: Graph) => Graph) => {
    const current = qc.getQueryData<Graph>(key);
    if (current) qc.setQueryData<Graph>(key, update(current));
  }, [qc, key]);
  const replaceGraph = useCallback((graph: Graph) => qc.setQueryData<Graph>(key, graph), [qc, key]);
  const refresh = useCallback(() => qc.invalidateQueries({ queryKey: key, exact: true }), [qc, key]);

  const putNode = useCallback((node: BlockNode) => setGraph((g) => ({
    ...g,
    nodes: g.nodes.some((n) => n.id === node.id) ? g.nodes.map((n) => (n.id === node.id ? node : n)) : [...g.nodes, node],
  })), [setGraph]);

  const actions = useMemo(() => ({
    async updateNode(id: number, values: Partial<BlockNode> & Record<string, unknown>) {
      setGraph((g) => ({ ...g, nodes: g.nodes.map((n) => (n.id === id ? { ...n, ...values } as BlockNode : n)) }));
      try {
        const node = await api.patch<BlockNode>(`/production/nodes/${id}`, values);
        putNode(node);
        return node;
      } catch (err) {
        refresh();
        return fail(err);
      }
    },
    async addNode(kind: string, x: number, y: number, values: Record<string, unknown> = {}) {
      const node = await api.post<BlockNode>(`/production/boards/${boardId}/nodes`, { kind, x, y, ...values }).catch(fail);
      putNode(node);
      return node;
    },
    async connect(source: number, target: number, port?: string | null) {
      const edge = await api.post<BlockEdge & { replaced: number[] }>(`/production/boards/${boardId}/edges`, {
        source_id: source, target_id: target, port: port || null,
      }).catch(fail);
      setGraph((g) => ({ ...g, edges: [...g.edges.filter((e) => e.id !== edge.id && !edge.replaced.includes(e.id)), edge] }));
      refresh();
      return edge;
    },
    async archive(nodeIds: number[], edgeIds: number[]) {
      const removed = await api.post<{ node_ids: number[]; edge_ids: number[] }>(`/production/boards/${boardId}/archive`, {
        node_ids: nodeIds, edge_ids: edgeIds,
      }).catch(fail);
      setGraph((g) => ({
        ...g,
        nodes: g.nodes.filter((n) => !removed.node_ids.includes(n.id)),
        edges: g.edges.filter((e) => !removed.edge_ids.includes(e.id)),
      }));
      refresh();
      return removed;
    },
    async restore(nodeIds: number[], edgeIds: number[]) {
      replaceGraph(await api.post<Graph>(`/production/boards/${boardId}/restore`, { node_ids: nodeIds, edge_ids: edgeIds }).catch(fail));
    },
    async paste(nodeIds: number[], dx = 40, dy = 40) {
      const result = await api.post<{ nodes: BlockNode[]; edges: BlockEdge[] }>(`/production/boards/${boardId}/paste`, {
        node_ids: nodeIds, dx, dy,
      }).catch(fail);
      setGraph((g) => ({ ...g, nodes: [...g.nodes, ...result.nodes], edges: [...g.edges, ...result.edges] }));
      return result;
    },
    async group(nodeIds: number[], name?: string) {
      const group = await api.post<BlockGroup>(`/production/boards/${boardId}/groups`, { node_ids: nodeIds, name }).catch(fail);
      setGraph((g) => ({
        ...g,
        groups: [...g.groups, group],
        nodes: g.nodes.map((n) => (group.nodes.includes(n.id) ? { ...n, group_id: group.id } : n)),
      }));
      return group;
    },
    async renameGroup(id: number, name: string) {
      const group = await api.patch<BlockGroup>(`/production/groups/${id}`, { name }).catch(fail);
      setGraph((g) => ({ ...g, groups: g.groups.map((x) => (x.id === id ? group : x)) }));
    },
    async ungroup(id: number) {
      await api.delete(`/production/groups/${id}`).catch(fail);
      setGraph((g) => ({
        ...g,
        groups: g.groups.filter((x) => x.id !== id),
        nodes: g.nodes.map((n) => (n.group_id === id ? { ...n, group_id: null } : n)),
      }));
    },
    async savePositions(positions: Record<number, [number, number]>) {
      setGraph((g) => ({ ...g, nodes: g.nodes.map((n) => (positions[n.id] ? { ...n, x: positions[n.id][0], y: positions[n.id][1] } : n)) }));
      await api.post(`/production/boards/${boardId}/positions`, { positions }).catch(() => undefined);
    },
    saveView(zoom: number, panX: number, panY: number) {
      api.put(`/production/boards/${boardId}/view`, { zoom, pan_x: panX, pan_y: panY }).catch(() => undefined);
    },
    async updateBoard(values: { name?: string; brand_kit_id?: number | null }) {
      replaceGraph(await api.patch<Graph>(`/production/boards/${boardId}`, values).catch(fail));
    },
    async run(nodeIds?: number[] | null, opts: { force?: boolean; downstream?: boolean } = {}) {
      setGraph((g) => ({ ...g, busy: true }));
      try {
        replaceGraph(await api.post<Graph>(`/production/boards/${boardId}/run`, {
          node_ids: nodeIds || null, force: !!opts.force, downstream: opts.downstream ?? true,
        }));
      } catch (err) {
        refresh();
        return fail(err);
      }
    },
    estimate(nodeIds?: number[] | null, force = false) {
      return api.get<RunEstimate>(`/production/boards/${boardId}/estimate`, { node_ids: nodeIds || undefined, force });
    },
    async selectOutput(nodeId: number, outputId: number) {
      putNode(await api.post<BlockNode>(`/production/nodes/${nodeId}/select-output`, { output_id: outputId }).catch(fail));
      refresh();
    },
    async uploadFile(nodeId: number, file: File) {
      const media = await api.upload<{ id: number }>("/media", file).catch(fail);
      putNode(await api.post<BlockNode>(`/production/nodes/${nodeId}/upload`, { media_id: media.id }).catch(fail));
      refresh();
    },
    async approve(nodeId: number, comment?: string) {
      replaceGraph(await api.post<Graph>(`/production/nodes/${nodeId}/approve`, { comment: comment || null }).catch(fail));
    },
    async reject(nodeId: number, comment?: string) {
      replaceGraph(await api.post<Graph>(`/production/nodes/${nodeId}/reject`, { comment: comment || null }).catch(fail));
    },
    async setVariables(variables: { key: string; value: string }[]) {
      replaceGraph(await api.put<Graph>(`/production/boards/${boardId}/variables`, { variables }).catch(fail));
    },
    batch(rows: Record<string, string>[]) {
      return api.post<{ id: number; name: string }[]>(`/production/boards/${boardId}/batch`, { rows }).catch(fail);
    },
    async saveDesign(nodeId: number, png: string, layers: Record<string, unknown>) {
      putNode(await api.post<BlockNode>(`/production/nodes/${nodeId}/design`, { png, layers }).catch(fail));
      refresh();
    },
    sendToStudio(nodeId: number) {
      return api.post<{ post_id: number }>(`/production/nodes/${nodeId}/send-to-studio`).catch(fail);
    },
  }), [boardId, setGraph, replaceGraph, putNode, refresh]);

  return { query, graph: query.data, actions, refresh, setGraph };
}

export type BoardActions = ReturnType<typeof useBoard>["actions"];
