/**
 * AI provider logos by provider type: <AiProviderLogo type="openai" label="OpenAI" size={40} />.
 * Logos from LobeHub Icons (MIT), built into ai-brands.json by packages/icons/build_ai.py; they are trademarks of
 * their owners. A type with no logo is drawn with the first two letters of its name.
 */
import brands from "./ai-brands.json";

const LOGOS = brands as Record<string, { body: string; color: boolean }>;

/** "Other OpenAI-compatible API" → "Ot", "Groq" → "Gr" (first two letters of the name). */
export function twoLetters(label: string) {
  const word = (label || "").replace(/[^\p{L}\p{N} ]/gu, "").trim().split(/\s+/)[0] || "AI";
  return word.slice(0, 1).toUpperCase() + word.slice(1, 2).toLowerCase();
}

export function AiProviderLogo({ type, label, size = 40 }: { type: string; label: string; size?: number }) {
  const logo = LOGOS[type];
  if (!logo) {
    return (
      <span aria-hidden className="flex shrink-0 items-center justify-center rounded-[13px] bg-ink font-semibold tracking-tight text-white shadow-[0_8px_18px_-10px_rgba(0,0,0,.7)]"
        style={{ width: size, height: size, fontSize: size * 0.38 }} dir="ltr">
        {twoLetters(label)}
      </span>
    );
  }
  return (
    <span aria-hidden title={label} className="flex shrink-0 items-center justify-center rounded-[13px] bg-white text-ink ring-1 ring-line shadow-[0_8px_18px_-12px_rgba(0,0,0,.45)]"
      style={{ width: size, height: size }}>
      <svg viewBox="0 0 24 24" width={size * 0.56} height={size * 0.56} fill="currentColor" dangerouslySetInnerHTML={{ __html: logo.body }} />
    </span>
  );
}
