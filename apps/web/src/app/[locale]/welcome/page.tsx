import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { Landing } from "./landing";

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "landing" });
  return { title: { absolute: t("metaTitle") }, description: t("metaDescription") };
}

/** Public marketing page (signed-out visitors of /<locale> are sent here by the app shell). */
export default async function WelcomePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <Landing />;
}
