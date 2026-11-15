/**
 * Public legal pages (privacy policy, data deletion): readable without an account, linked from the Meta app
 * settings and from the sign-in pages. Arabic for "ar", English for every other language.
 */
import { useLocale } from "next-intl";
import type { ReactNode } from "react";
import { BrandLogo } from "@/components/brand-mark";
import { Link } from "@/i18n/navigation";

export default function LegalLayout({ children }: { children: ReactNode }) {
  const ar = useLocale() === "ar";
  return (
    <div className="min-h-screen bg-white text-[#111]">
      <header className="mx-auto flex max-w-3xl items-center justify-between px-5 py-6">
        <Link href="/welcome" className="text-[15px]"><BrandLogo size={34} /></Link>
        <nav className="flex gap-4 text-sm text-text-2">
          <Link href="/privacy" className="hover:underline">{ar ? "الخصوصية" : "Privacy"}</Link>
          <Link href="/data-deletion" className="hover:underline">{ar ? "حذف البيانات" : "Data deletion"}</Link>
        </nav>
      </header>
      <main className="mx-auto max-w-3xl px-5 pb-16">{children}</main>
      <footer className="pb-8 text-center text-xs text-faint" dir="ltr">© {new Date().getFullYear()} Stravica Social</footer>
    </div>
  );
}
