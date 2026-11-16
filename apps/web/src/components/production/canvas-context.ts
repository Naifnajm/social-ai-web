"use client";
/** Convenience hook for panels (inspector, approval, top bar): the graph, the API actions and the canvas callbacks.
 * Blocks on the canvas subscribe to narrower slices of `useCanvasStore` instead. */
import { useShallow } from "zustand/react/shallow";
import { useCanvasStore } from "./store";

export function useCanvas() {
  const value = useCanvasStore(useShallow((s) => ({ graph: s.graph, actions: s.actions, readOnly: s.readOnly, ui: s.ui })));
  if (!value.graph || !value.actions) throw new Error("useCanvas outside the production canvas");
  return { ...value, graph: value.graph, actions: value.actions };
}
