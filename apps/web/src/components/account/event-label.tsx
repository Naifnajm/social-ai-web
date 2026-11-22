"use client";
/** Human labels for the account trail (``user_events.type``, e.g. "admin.temporary_password"). */
import { useTranslations } from "next-intl";

export function EventLabel({ type }: { type: string }) {
  const t = useTranslations("account.events");
  const key = type.replace(/^2fa\./, "twofa.");
  return <>{t.has(key) ? t(key) : type}</>;
}

/** "Chrome · macOS" from a user agent, without a library. */
export function device(agent: string | null): string {
  if (!agent) return "—";
  const browser = /Edg\//.test(agent) ? "Edge" : /OPR\//.test(agent) ? "Opera" : /Chrome\//.test(agent) ? "Chrome"
    : /Firefox\//.test(agent) ? "Firefox" : /Safari\//.test(agent) ? "Safari" : /python|curl|okhttp|testclient/i.test(agent) ? "API" : "Browser";
  const os = /iPhone|iPad/.test(agent) ? "iOS" : /Android/.test(agent) ? "Android" : /Mac OS X/.test(agent) ? "macOS"
    : /Windows/.test(agent) ? "Windows" : /Linux/.test(agent) ? "Linux" : "";
  return os ? `${browser} · ${os}` : browser;
}
