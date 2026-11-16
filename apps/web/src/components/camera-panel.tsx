"use client";
/**
 * Camera panel: shoot an AI image or video like with a real camera. Auto lets the description decide; Manual picks
 * the camera, lens, aperture, angle, framing, light, colour look and (video) camera movement with icon tiles, or a
 * preset. Options and their translated labels come from GET /api/ai/camera.
 *
 *   const [shot, setShot] = useState<Shot | null>(null);
 *   <CameraPanel kind="image" value={shot} onChange={setShot} />
 *
 * The value is the API's "shot": `{mode: "auto"}` or `{mode: "manual", preset?, lens: "85", light: "golden_hour", …}`.
 * `kind="all"` shows the groups of images and videos (e.g. a brand's approved photo style).
 */
import { useTranslations } from "next-intl";
import { useState } from "react";
import { type CameraOptions, type Shot, useCameraOptions } from "@/lib/ai";
import { Icon } from "./icon";
import { Button, Segmented, Spinner, cx } from "./ui";

type Kind = "image" | "video" | "all";

const groupsFor = (options: CameraOptions | undefined, kind: Kind) =>
  (options?.groups ?? []).filter((g) => kind === "all" || g.kinds.includes(kind));

/** The chosen values of a shot (group -> option key), without mode and preset. */
export function shotValues(shot: Shot | null | undefined, options?: CameraOptions): Record<string, string> {
  if (!shot) return {};
  const known = options ? new Set(options.groups.map((g) => g.key)) : null;
  return Object.fromEntries(Object.entries(shot).filter(([k, v]) => k !== "mode" && k !== "preset" && v && (!known || known.has(k)))) as Record<string, string>;
}

export const isManual = (shot: Shot | null | undefined) =>
  !!shot && (shot.mode === "manual" || Object.keys(shotValues(shot)).length > 0 || !!shot.preset);

/** "85mm portrait · f/1.8 · Golden hour" (empty for auto). */
export function shotSummary(shot: Shot | null | undefined, options: CameraOptions | undefined, kind: Kind = "all", max = 4): string {
  if (!options || !isManual(shot)) return "";
  const values = shotValues(shot, options);
  const labels: string[] = [];
  for (const group of groupsFor(options, kind)) {
    const option = group.options.find((o) => o.key === values[group.key]);
    if (option) labels.push(option.label);
  }
  if (!labels.length && shot?.preset) {
    const preset = options.presets.find((p) => p.key === shot.preset);
    if (preset) labels.push(preset.label);
  }
  return labels.length > max ? `${labels.slice(0, max).join(" · ")} · +${labels.length - max}` : labels.join(" · ");
}

export function CameraPanel({ value, onChange, kind, label, hint, defaultOpen = false, disabled, emptyText, className }: {
  value: Shot | null | undefined;
  onChange: (shot: Shot) => void;
  kind: Kind;
  label?: string;
  hint?: string;
  defaultOpen?: boolean;
  disabled?: boolean;
  /** Collapsed text when nothing is chosen (default: "Auto — the description decides"). */
  emptyText?: string;
  className?: string;
}) {
  const t = useTranslations("ai.camera");
  const [open, setOpen] = useState(defaultOpen);
  const options = useCameraOptions();
  const manual = isManual(value);
  const [lastManual, setLastManual] = useState<Shot | null>(manual ? value ?? null : null);
  const groups = groupsFor(options.data, kind);
  const values = shotValues(value, options.data);
  const summary = shotSummary(value, options.data, kind);

  const setMode = (mode: "auto" | "manual") => {
    if (mode === "auto") {
      if (manual && value) setLastManual(value);
      onChange({ mode: "auto" });
    } else {
      onChange(lastManual ?? { mode: "manual" });
    }
  };
  const pickPreset = (key: string) => {
    const preset = options.data?.presets.find((p) => p.key === key);
    if (!preset) return;
    if (value?.preset === key) onChange({ mode: "manual" });
    else onChange({ mode: "manual", preset: key, ...preset.values });
  };
  // a tweak after a preset keeps its values (already copied) but not the preset, so a cleared group stays cleared
  const pick = (group: string, key: string) => {
    const next: Shot = { mode: "manual", ...values };
    if (next[group] === key) delete next[group];
    else next[group] = key;
    onChange(next);
  };

  return (
    <div className={cx("rounded-2xl bg-white/55 ring-1 ring-line", disabled && "opacity-70", className)}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-3 py-2.5 text-start">
        <span className={cx("flex h-8 w-8 shrink-0 items-center justify-center rounded-xl", manual ? "bg-ink text-white" : "bg-fill-2 text-text-2")}>
          <Icon name="photo_camera" size={17} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[13px] font-semibold">{label || t("title")}</span>
          <span className="block truncate text-xs text-muted">
            {manual ? summary || t("manualEmpty") : emptyText || t("autoSummary")}
          </span>
        </span>
        <Icon name={open ? "expand_less" : "expand_more"} size={18} className="shrink-0 text-muted" />
      </button>

      {open && (
        <div className="flex flex-col gap-3 border-t border-line px-3 pb-3 pt-3">
          {hint && <p className="-mt-0.5 text-xs text-muted">{hint}</p>}
          <div className="flex flex-wrap items-center gap-2">
            <Segmented size="sm" value={manual ? "manual" : "auto"} onChange={(m) => !disabled && setMode(m)}
              options={[{ value: "auto", label: t("auto"), icon: "auto_awesome" }, { value: "manual", label: t("manual"), icon: "tune" }]} />
            <span className="min-w-0 grow basis-44 text-xs text-muted">{manual ? t("manualHint") : t("autoHint")}</span>
            {manual && Object.keys(values).length > 0 && !disabled && (
              <Button size="sm" variant="ghost" icon="undo" onClick={() => onChange({ mode: "manual" })}>{t("reset")}</Button>
            )}
          </div>

          {manual && (options.isLoading ? <div className="flex justify-center py-4"><Spinner /></div> : (
            <>
              {!!options.data?.presets.length && (
                <div className="flex flex-col gap-1.5">
                  <span className="text-[12px] font-semibold text-text-2">{t("presets")}</span>
                  <div className="-mx-3 flex gap-1.5 overflow-x-auto px-3 pb-1">
                    {options.data.presets.map((p) => {
                      const active = value?.preset === p.key;
                      return (
                        <button key={p.key} type="button" disabled={disabled} aria-pressed={active} onClick={() => pickPreset(p.key)}
                          className={cx("inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-3 text-[12.5px] font-medium ring-1 transition",
                            active ? "bg-ink text-white ring-ink" : "bg-white/80 text-text-2 ring-line hover:text-text hover:ring-ink/40")}>
                          <Icon name={p.icon} size={15} />{p.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              {groups.map((group) => {
                const selected = group.options.find((o) => o.key === values[group.key]);
                return (
                  <div key={group.key} className="flex flex-col gap-1.5">
                    <div className="flex items-center gap-1.5 text-[12px] font-semibold text-text-2">
                      <Icon name={group.icon} size={14} />
                      <span>{group.label}</span>
                      {selected && <span className="ms-auto truncate font-normal text-muted">{selected.label}</span>}
                    </div>
                    <div className="-mx-3 flex gap-1.5 overflow-x-auto px-3 pb-1" role="group" aria-label={group.label}>
                      {group.options.map((o) => {
                        const active = values[group.key] === o.key;
                        return (
                          <button key={o.key} type="button" disabled={disabled} aria-pressed={active} title={o.label} onClick={() => pick(group.key, o.key)}
                            className={cx("flex w-[74px] shrink-0 flex-col items-center gap-1 rounded-xl px-1 pb-1.5 pt-2 text-center ring-1 transition",
                              active ? "bg-ink text-white ring-ink shadow-[0_6px_16px_-8px_rgba(0,0,0,.6)]" : "bg-white/75 text-text-2 ring-line hover:text-text hover:ring-ink/40")}>
                            <Icon name={o.icon} size={20} />
                            <span className="line-clamp-2 text-[10.5px] font-medium leading-tight">{o.label}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </>
          ))}
        </div>
      )}
    </div>
  );
}
