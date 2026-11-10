"use client";
/** Small form controls of the template editor. */
import type { ReactNode } from "react";
import { Icon } from "@/components/icon";
import { cx } from "@/components/ui";

const HEX = /^#[0-9a-fA-F]{6}$/;

export function ColorInput({ value, onChange, placeholder, allowEmpty }: {
  value: string | null;
  onChange: (v: string | null) => void;
  placeholder?: string;
  allowEmpty?: boolean;
}) {
  const current = value && HEX.test(value) ? value : "#111111";
  return (
    <div className="flex h-10 items-center gap-2 rounded-xl border border-line bg-white/70 px-1.5">
      <label className="relative h-7 w-7 shrink-0 cursor-pointer overflow-hidden rounded-lg shadow-[inset_0_0_0_1px_rgba(0,0,0,.12)]"
        style={{ background: value ? current : "repeating-conic-gradient(#e4e4e7 0% 25%, #fff 0% 50%) 50% / 10px 10px" }}>
        <input type="color" value={current} onChange={(e) => onChange(e.target.value)} className="absolute inset-0 cursor-pointer opacity-0" />
      </label>
      <input dir="ltr" value={value ?? ""} placeholder={placeholder} maxLength={7}
        onChange={(e) => {
          const v = e.target.value.trim();
          onChange(v ? (v.startsWith("#") ? v : `#${v}`) : null);
        }}
        className="min-w-0 flex-1 bg-transparent text-sm uppercase outline-none placeholder:normal-case placeholder:text-faint" />
      {allowEmpty && value && (
        <button type="button" onClick={() => onChange(null)} className="rounded-full p-1 text-muted hover:bg-fill-2" aria-label="clear">
          <Icon name="close" size={14} />
        </button>
      )}
    </div>
  );
}

export function Range({ value, onChange, min, max, step = 1, suffix }: {
  value: number; onChange: (v: number) => void; min: number; max: number; step?: number; suffix?: string;
}) {
  return (
    <div className="flex h-10 items-center gap-3">
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))}
        className="h-1.5 min-w-0 flex-1 cursor-pointer accent-[var(--ink)]" />
      <span className="w-14 shrink-0 text-end text-sm tabular-nums text-text-2" dir="ltr">{Math.round(value * 10) / 10}{suffix}</span>
    </div>
  );
}

export function NumberBox({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] font-medium text-muted">{label}</span>
      <input type="number" dir="ltr" step={0.5} min={0} max={100} value={Math.round(value * 100) / 100}
        onChange={(e) => onChange(Math.min(100, Math.max(0, Number(e.target.value) || 0)))}
        className="h-9 w-full rounded-lg border border-line bg-white/70 px-2 text-sm tabular-nums outline-none focus:border-black/30" />
    </label>
  );
}

export function Section({ icon, title, children, aside }: { icon: string; title: ReactNode; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="border-t border-line pt-4 first:border-0 first:pt-0">
      <div className="mb-3 flex items-center gap-2">
        <Icon name={icon} size={17} className="text-text-2" />
        <h3 className="text-[14px] font-semibold">{title}</h3>
        {aside && <div className="ms-auto">{aside}</div>}
      </div>
      <div className="flex flex-col gap-3">{children}</div>
    </section>
  );
}

export function CornerPicker({ value, onChange, labels }: {
  value: "top_left" | "top_right" | "bottom_left" | "bottom_right";
  onChange: (v: "top_left" | "top_right" | "bottom_left" | "bottom_right") => void;
  labels: Record<string, string>;
}) {
  const corners = ["top_left", "top_right", "bottom_left", "bottom_right"] as const;
  return (
    <div dir="ltr" className="grid h-[84px] w-[68px] grid-cols-2 grid-rows-2 gap-1 rounded-xl border border-line bg-white/60 p-1">
      {corners.map((c) => (
        <button key={c} type="button" title={labels[c]} aria-label={labels[c]} onClick={() => onChange(c)}
          className={cx("flex rounded-lg transition", c.startsWith("top") ? "items-start" : "items-end",
            c.endsWith("left") ? "justify-start" : "justify-end", value === c ? "bg-ink/90" : "hover:bg-fill-2")}>
          <span className={cx("m-1 h-2.5 w-2.5 rounded-[3px]", value === c ? "bg-white" : "bg-faint")} />
        </button>
      ))}
    </div>
  );
}
