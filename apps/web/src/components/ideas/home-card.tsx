"use client";
/** Home page: "Today's ideas" teaser, shown when new ideas are waiting. */
import { useTranslations } from "next-intl";
import { Icon } from "@/components/icon";
import { Card } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { FORMAT_ICON, useIdeas } from "./shared";

export function IdeasHomeCard() {
  const t = useTranslations("ideas.home");
  const ideas = useIdeas("new");
  const fresh = (ideas.data ?? []).filter((i) => i.state === "new");
  if (!fresh.length) return null;
  const first = fresh[0];
  return (
    <Link href="/ideas" className="mb-5 block">
      <Card className="flex flex-wrap items-center gap-4 transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-lift)]">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[linear-gradient(135deg,#ff5c9d,#b3124f)] text-white shadow-[0_10px_24px_-10px_rgba(224,36,111,.75)]">
          <Icon name="lightbulb" size={22} duo />
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-semibold">{t("title", { n: fresh.length })}</div>
          <p className="flex min-w-0 items-center gap-1.5 text-sm text-muted">
            <Icon name={FORMAT_ICON[first.format]} size={14} className="shrink-0" />
            <span dir="auto" className="truncate">{first.title}</span>
          </p>
        </div>
        <span className="inline-flex h-9 items-center gap-1.5 rounded-full bg-ink px-4 text-[13px] font-semibold text-white">
          {t("open")}
          <Icon name="east" size={15} className="rtl:-scale-x-100" />
        </span>
      </Card>
    </Link>
  );
}
