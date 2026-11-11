"use client";
import { useLocale } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";

/** Link to the same page in the other language. */
export function LocaleSwitch() {
  const locale = useLocale();
  const pathname = usePathname();
  return (
    <Link href={pathname} locale={locale === "ar" ? "en" : "ar"} className="rounded-full px-3 py-1.5 text-sm font-medium text-muted transition hover:bg-fill hover:text-text">
      {locale === "ar" ? "English" : "العربية"}
    </Link>
  );
}
