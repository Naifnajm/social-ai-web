"use client";
import { useEffect } from "react";
import { Spinner } from "@/components/ui";
import { useRouter } from "@/i18n/navigation";

/** The profile moved to the account center (old links and bookmarks keep working). */
export default function ProfileRedirect() {
  const router = useRouter();
  useEffect(() => router.replace("/account"), [router]);
  return <div className="flex justify-center py-12"><Spinner /></div>;
}
