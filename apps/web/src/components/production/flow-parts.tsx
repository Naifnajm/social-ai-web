"use client";
/** Custom edge (coloured by data type) and group frame of the Production canvas. */
import { BaseEdge, type ConnectionLineComponentProps, type Edge, type EdgeProps, type Node, type NodeProps, getBezierPath } from "@xyflow/react";
import { useTranslations } from "next-intl";
import { memo, useState } from "react";
import { Icon } from "@/components/icon";
import { typeColor } from "./meta";
import { renameGroup, ungroup, useCanvasStore } from "./store";

export type TypedFlowEdge = Edge<{ type?: string | null; running?: boolean }, "typed">;

function TypedEdgeView({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, selected }: EdgeProps<TypedFlowEdge>) {
  const [path] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, curvature: 0.35 });
  const color = typeColor(data?.type);
  return (
    <>
      {selected && <path d={path} fill="none" stroke={color} strokeOpacity={0.18} strokeWidth={10} />}
      <BaseEdge id={id} path={path} interactionWidth={18}
        style={{ stroke: color, strokeWidth: selected ? 3 : 2.2, strokeDasharray: data?.running ? "6 6" : undefined,
          animation: data?.running ? "production-dash 0.8s linear infinite" : undefined }} />
    </>
  );
}

export const TypedEdge = memo(TypedEdgeView);

/** The link being dragged: green over a port that accepts it, red over one that does not. */
export function ConnectionLine({ fromX, fromY, toX, toY, fromPosition, toPosition, connectionStatus }: ConnectionLineComponentProps) {
  const [path] = getBezierPath({ sourceX: fromX, sourceY: fromY, sourcePosition: fromPosition, targetX: toX, targetY: toY, targetPosition: toPosition, curvature: 0.35 });
  const color = connectionStatus === "valid" ? "#16a34a" : connectionStatus === "invalid" ? "#dc2626" : "#0a0a0a";
  return (
    <g>
      <path d={path} fill="none" stroke={color} strokeOpacity={0.16} strokeWidth={connectionStatus ? 9 : 0} style={{ transition: "stroke 150ms, stroke-width 150ms" }} />
      <path d={path} fill="none" stroke={color} strokeWidth={2.2} strokeDasharray={connectionStatus === "valid" ? undefined : "6 5"} style={{ transition: "stroke 150ms" }} />
      <circle cx={toX} cy={toY} r={connectionStatus ? 5 : 3.5} fill={color} style={{ transition: "fill 150ms, r 150ms" }} />
    </g>
  );
}

export type GroupFlowNode = Node<{ groupId: number; name: string; color: string; width: number; height: number }, "group-frame">;

function GroupFrameView({ data }: NodeProps<GroupFlowNode>) {
  const t = useTranslations("production");
  const readOnly = useCanvasStore((s) => s.readOnly);
  const group = useCanvasStore((s) => s.graph?.groups.find((g) => g.id === data.groupId));
  const [name, setName] = useState(data.name);
  const [shown, setShown] = useState(data.name);
  if (shown !== data.name) { // renamed elsewhere (undo / redo)
    setShown(data.name);
    setName(data.name);
  }
  return (
    <div className="pointer-events-none relative rounded-[28px] border-[1.5px] border-dashed"
      style={{ width: data.width, height: data.height, borderColor: `${data.color}66`, background: `${data.color}0d` }}>
      <div className="group-handle pointer-events-auto absolute start-2 top-2 flex h-8 max-w-[calc(100%-16px)] cursor-grab items-center gap-1.5 rounded-full border border-white/70 bg-white/85 pe-1.5 ps-3 shadow-[0_6px_18px_-8px_rgba(0,0,0,.25)] backdrop-blur-xl active:cursor-grabbing">
        <span className="flex h-6 w-5 shrink-0 items-center justify-center" title={t("moveGroup")}>
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: data.color }} />
        </span>
        <input value={name} disabled={readOnly} onChange={(e) => setName(e.target.value)} dir="auto"
          onBlur={() => group && name.trim() && name !== data.name && renameGroup(group, name.trim())}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          className="nodrag bidi w-32 rounded-md bg-transparent px-1 hover:bg-fill focus:bg-white text-[13px] font-semibold outline-none" aria-label={t("groupName")} />
        {!readOnly && (
          <button type="button" title={t("ungroup")} aria-label={t("ungroup")} onClick={() => group && ungroup(group)}
            className="nodrag flex h-6 w-6 items-center justify-center rounded-full text-muted hover:bg-fill-2 hover:text-ink">
            <Icon name="group_off" size={14} />
          </button>
        )}
      </div>
    </div>
  );
}

export const GroupFrame = memo(GroupFrameView);
