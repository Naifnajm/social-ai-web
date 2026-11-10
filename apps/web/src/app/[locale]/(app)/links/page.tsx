"use client";
/** Links & sales: clicks on the tracked links of your posts, conversions (orders, leads), products and setup. */
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConversionsTab, LinksTab } from "@/components/planning/links-lists";
import { OverviewTab } from "@/components/planning/links-overview";
import { SetupTab } from "@/components/planning/links-setup";
import { ProductsTab } from "@/components/planning/products";
import { PageHeader, Segmented } from "@/components/ui";

type Tab = "overview" | "links" | "conversions" | "products" | "setup";
const TABS: Tab[] = ["overview", "links", "conversions", "products", "setup"];

export default function LinksPage() {
  const t = useTranslations("links");
  const [tab, setTab] = useState<Tab>(() => {
    if (typeof window === "undefined") return "overview";
    const wanted = new URLSearchParams(window.location.search).get("tab") as Tab | null;
    return wanted && TABS.includes(wanted) ? wanted : "overview";
  });
  const change = (next: Tab) => {
    setTab(next);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    window.history.replaceState(null, "", url.toString());
  };
  const icons: Record<Tab, string> = { overview: "bar_chart", links: "link", conversions: "shopping_cart", products: "storefront", setup: "settings" };
  return (
    <div className="pt-2">
      <PageHeader icon="link" title={t("title")} subtitle={t("subtitle")} />
      <div className="-mx-4 mb-5 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <Segmented value={tab} onChange={change} className="w-max" options={TABS.map((key) => ({ value: key, label: t(`tabs.${key}`), icon: icons[key] }))} />
      </div>
      {tab === "overview" && <OverviewTab onSetup={() => change("setup")} />}
      {tab === "links" && <LinksTab />}
      {tab === "conversions" && <ConversionsTab onSetup={() => change("setup")} />}
      {tab === "products" && <ProductsTab />}
      {tab === "setup" && <SetupTab />}
    </div>
  );
}
