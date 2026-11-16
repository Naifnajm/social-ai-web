"use client";
/** What the brand guard found or fixed in an AI text (`brand_notes` of POST /api/ai/text). Renders nothing when empty.
 *
 *   <BrandNotes notes={result.brand_notes} onDismiss={() => setNotes([])} />
 */
import { useTranslations } from "next-intl";
import { Icon } from "./icon";
import { cx } from "./ui";

export function BrandNotes({ notes, onDismiss, className }: { notes?: string[] | null; onDismiss?: () => void; className?: string }) {
  const t = useTranslations("ai.brandNotes");
  if (!notes?.length) return null;
  return (
    <div role="status" className={cx("flex items-start gap-2 rounded-xl bg-warn-bg px-3 py-2 text-[13px] text-warn", className)}>
      <Icon name="shield" size={16} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <span className="font-semibold">{t("title")}</span>
        <ul className="mt-0.5">
          {notes.map((note, i) => <li key={i} className="bidi">{note}</li>)}
        </ul>
      </div>
      {onDismiss && (
        <button type="button" onClick={onDismiss} aria-label={t("dismiss")} className="shrink-0 rounded-full p-0.5 hover:bg-black/5">
          <Icon name="close" size={14} />
        </button>
      )}
    </div>
  );
}
