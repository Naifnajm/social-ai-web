"use client";
import { createContext, useContext } from "react";
import type { BoardActions } from "./use-board";
import type { Graph } from "./types";

export type CanvasApi = {
  graph: Graph;
  actions: BoardActions;
  readOnly: boolean;
  select: (ids: number[]) => void;
  openDesign: (nodeId: number) => void;
  pickFile: (nodeId: number) => void;
  runNode: (nodeId: number, force?: boolean) => void;
};

export const CanvasContext = createContext<CanvasApi | null>(null);

export function useCanvas() {
  const value = useContext(CanvasContext);
  if (!value) throw new Error("useCanvas outside the production canvas");
  return value;
}
