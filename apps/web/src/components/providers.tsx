"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useLocale } from "next-intl";
import { type ReactNode, useState } from "react";
import { setApiLocale } from "@/lib/api";
import { Toaster } from "./ui";

export function Providers({ children }: { children: ReactNode }) {
  const locale = useLocale();
  setApiLocale(locale);
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } } }),
  );
  return (
    <QueryClientProvider client={client}>
      {children}
      <Toaster />
    </QueryClientProvider>
  );
}
