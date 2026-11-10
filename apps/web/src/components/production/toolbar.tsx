"use client";
/** Bottom floating toolbar: click a block kind to add it, or drag it onto the canvas. */
import { useTranslations } from "next-intl";
import { Icon } from "@/components/icon";
import { cx } from "@/components/ui";
import { KIND_META, TOOLBAR_KINDS } from "./meta";

export function Toolbar({ onAdd, inspectorOpen }: { onAdd: (kind: string) => void; inspectorOpen?: boolean }) {
  const t = useTranslations("production");
  return (
    <div className={cx("glass-strong absolute inset-x-0 bottom-4 z-20 mx-auto flex w-max max-w-[calc(100%-24px)] items-center gap-0.5 overflow-x-auto rounded-[22px] p-1.5",
      inspectorOpen && "max-lg:hidden lg:right-[372px] lg:max-w-[calc(100%-396px)]")}>
      {TOOLBAR_KINDS.map((kind, index) => (
        <div key={kind} className="flex items-center">
          {(index === 3 || index === 8 || index === 11) && <span className="mx-1 h-7 w-px shrink-0 bg-line" />}
          <button type="button" draggable onClick={() => onAdd(kind)}
            onDragStart={(e) => { e.dataTransfer.setData("application/production-kind", kind); e.dataTransfer.effectAllowed = "copy"; }}
            title={t(`kindHints.${kind}`)}
            className="group flex w-[62px] shrink-0 cursor-grab flex-col items-center gap-1 rounded-2xl px-1 py-1.5 text-[10.5px] font-medium text-text-2 transition hover:bg-white active:cursor-grabbing">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl transition group-hover:scale-105"
              style={{ color: `color-mix(in srgb, ${KIND_META[kind].color} 82%, #000)`, background: `color-mix(in srgb, ${KIND_META[kind].color} 13%, #fff)` }}>
              <Icon name={KIND_META[kind].icon} size={18} />
            </span>
            <span className="max-w-full truncate">{t(`kinds.${kind}`)}</span>
          </button>
        </div>
      ))}
    </div>
  );
}
