"use client";
/** Custom edge (coloured by data type) and group frame of the Production canvas. */
import { BaseEdge, type Edge, type EdgeProps, type Node, type NodeProps, getBezierPath } from "@xyflow/react";
import { useTranslations } from "next-intl";
import { memo, useState } from "react";
import { Icon } from "@/components/icon";
import { useCanvas } from "./canvas-context";
import { typeColor } from "./meta";

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

export type GroupFlowNode = Node<{ groupId: number; name: string; color: string; width: number; height: number }, "group-frame">;

function GroupFrameView({ data }: NodeProps<GroupFlowNode>) {
  const t = useTranslations("production");
  const { actions, readOnly } = useCanvas();
  const [name, setName] = useState(data.name);
  return (
    <div className="pointer-events-none relative rounded-[28px] border-[1.5px] border-dashed"
      style={{ width: data.width, height: data.height, borderColor: `${data.color}66`, background: `${data.color}0d` }}>
      <div className="group-handle pointer-events-auto absolute start-2 top-2 flex h-8 max-w-[calc(100%-16px)] cursor-grab items-center gap-1.5 rounded-full border border-white/70 bg-white/85 pe-1.5 ps-3 shadow-[0_6px_18px_-8px_rgba(0,0,0,.25)] backdrop-blur-xl active:cursor-grabbing">
        <span className="flex h-6 w-5 shrink-0 items-center justify-center" title={t("moveGroup")}>
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: data.color }} />
        </span>
        <input value={name} disabled={readOnly} onChange={(e) => setName(e.target.value)} dir="auto"
          onBlur={() => name.trim() && name !== data.name && actions.renameGroup(data.groupId, name.trim())}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          className="nodrag bidi w-32 rounded-md bg-transparent px-1 hover:bg-fill focus:bg-white text-[13px] font-semibold outline-none" aria-label={t("groupName")} />
        {!readOnly && (
          <button type="button" title={t("ungroup")} onClick={() => actions.ungroup(data.groupId)}
            className="nodrag flex h-6 w-6 items-center justify-center rounded-full text-muted hover:bg-fill-2 hover:text-ink">
            <Icon name="group_off" size={14} />
          </button>
        )}
      </div>
    </div>
  );
}

export const GroupFrame = memo(GroupFrameView);
