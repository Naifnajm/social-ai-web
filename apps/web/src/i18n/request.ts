import fs from "node:fs";
import path from "node:path";
import { hasLocale } from "next-intl";
import { getRequestConfig } from "next-intl/server";
import { routing } from "./routing";

// Messages are split per feature: messages/<locale>/<feature>.json becomes the namespace <feature>
// (use it with useTranslations("<feature>")). Each feature adds its own file — nothing shared to edit.
// English is the fallback for keys not translated yet.
const cache = new Map<string, Record<string, unknown>>();

function readLocale(locale: string): Record<string, unknown> {
  const dir = path.join(process.cwd(), "messages", locale);
  const out: Record<string, unknown> = {};
  if (!fs.existsSync(dir)) return out;
  for (const file of fs.readdirSync(dir).sort()) {
    if (file.endsWith(".json")) {
      out[file.slice(0, -5)] = JSON.parse(fs.readFileSync(path.join(dir, file), "utf8"));
    }
  }
  return out;
}

function deepMerge(base: Record<string, unknown>, over: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...base };
  for (const [key, value] of Object.entries(over)) {
    const current = out[key];
    out[key] =
      value && typeof value === "object" && !Array.isArray(value) && current && typeof current === "object"
        ? deepMerge(current as Record<string, unknown>, value as Record<string, unknown>)
        : value;
  }
  return out;
}

export function loadMessages(locale: string): Record<string, unknown> {
  if (process.env.NODE_ENV === "production" && cache.has(locale)) return cache.get(locale)!;
  const messages = locale === "en" ? readLocale("en") : deepMerge(readLocale("en"), readLocale(locale));
  cache.set(locale, messages);
  return messages;
}

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested) ? requested : routing.defaultLocale;
  return { locale, messages: loadMessages(locale), timeZone: "Asia/Riyadh" };
});
