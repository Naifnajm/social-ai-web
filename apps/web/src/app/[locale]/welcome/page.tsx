import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { Landing } from "./landing";

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "landing" });
  return { title: { absolute: t("metaTitle") }, description: t("metaDescription") };
}

/**
 * Runs before first paint: lets the motion script own the starting states (hidden words, intro screen),
 * skips the intro screen on later visits in the same tab, and gives everything back if the script never loads.
 */
const BOOT = `(function(){var d=document.documentElement;d.classList.add('lx-js');try{if(sessionStorage.getItem('lx-seen'))d.classList.add('lx-seen')}catch(e){}if(matchMedia('(prefers-reduced-motion: reduce)').matches)d.classList.add('lx-seen');setTimeout(function(){if(!window.__lxReady){d.classList.remove('lx-js');d.classList.add('lx-seen')}},6000)})();`;

/** Public marketing page (signed-out visitors of /<locale> are sent here by the app shell). */
export default async function WelcomePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  return (
    <>
      <script dangerouslySetInnerHTML={{ __html: BOOT }} />
      <Landing />
    </>
  );
}
