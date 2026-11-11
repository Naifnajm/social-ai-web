import { defineRouting } from "next-intl/routing";

export const routing = defineRouting({
  locales: ["ar", "en", "nl", "de", "fr"],
  defaultLocale: "ar",
});

export type Locale = (typeof routing.locales)[number];
export const isRtl = (locale: string) => locale === "ar";

/** Each language in its own name, for the language menu. */
export const LOCALE_NAMES: Record<Locale, string> = {
  ar: "العربية", en: "English", nl: "Nederlands", de: "Deutsch", fr: "Français",
};

/** Screenshots exist in Arabic and English; the other languages show the English ones. */
export const shotLocale = (locale: string) => (locale === "ar" ? "ar" : "en");
