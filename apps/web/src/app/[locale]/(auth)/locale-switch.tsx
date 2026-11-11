"use client";
import { LanguageMenu } from "@/components/language-menu";

/** The same page in another language. */
export function LocaleSwitch() {
  return <LanguageMenu className="rounded-full px-3 py-1.5 text-sm font-medium text-muted transition hover:bg-fill hover:text-text" />;
}
