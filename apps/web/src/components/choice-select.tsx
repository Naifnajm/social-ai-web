"use client";
/** A drop-down of known values (models, voices…) with a last "Other…" entry that switches to free typing, so a value
 * missing from the list can still be used. A value that is not in the list opens in typing mode. Without any known
 * values it is a plain text field. */
import { useTranslations } from "next-intl";
import { useState } from "react";
import { IconButton, Input, Select, cx } from "./ui";

export type Choice = { value: string; label?: string; hint?: string | null };

const OTHER = "__other__";

export function ChoiceSelect({ value, onChange, choices, emptyLabel, placeholder, disabled, className, "aria-label": ariaLabel }: {
  value: string; onChange: (value: string) => void; choices: Choice[];
  /** label of the empty choice ("" = automatic / provider default); omit to have no empty choice */
  emptyLabel?: string; placeholder?: string; disabled?: boolean; className?: string; "aria-label"?: string;
}) {
  const t = useTranslations("ai.choice");
  const known = choices.some((c) => c.value === value);
  const [typing, setTyping] = useState(() => !!value && !known);
  const unique = choices.filter((c, i) => c.value && choices.findIndex((o) => o.value === c.value) === i);

  if (!unique.length || typing) {
    return (
      <div className={cx("flex items-center gap-1.5", className)}>
        <Input dir="ltr" value={value} disabled={disabled} placeholder={placeholder} aria-label={ariaLabel}
          onChange={(e) => onChange(e.target.value)} className="flex-1" />
        {!!unique.length && (
          <IconButton type="button" icon="expand_more" label={t("backToList")} disabled={disabled}
            onClick={() => { setTyping(false); if (!unique.some((c) => c.value === value)) onChange(""); }} />
        )}
      </div>
    );
  }
  return (
    <Select dir="ltr" value={value} disabled={disabled} aria-label={ariaLabel} className={className}
      onChange={(e) => { if (e.target.value === OTHER) setTyping(true); else onChange(e.target.value); }}>
      {(emptyLabel !== undefined || !value) && <option value="">{emptyLabel ?? "—"}</option>}
      {unique.map((c) => (
        <option key={c.value} value={c.value}>
          {[c.label && c.label !== c.value ? `${c.label} (${c.value})` : c.value, c.hint].filter(Boolean).join(" · ")}
        </option>
      ))}
      <option value={OTHER}>{t("other")}</option>
    </Select>
  );
}
