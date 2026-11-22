"use client";
/** The link of the "confirm your e-mail" message. */
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/icon";
import { Button, Spinner } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";

function Verify() {
  const t = useTranslations("account.verify");
  const token = useSearchParams().get("token") || "";
  const [state, setState] = useState<"checking" | "ok" | "bad">("checking");
  const sent = useRef(false);
  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    api.post("/auth/email/verify", { token }).then(() => setState("ok"), () => setState("bad"));
  }, [token]);
  return (
    <div className="flex flex-col items-center gap-4 text-center">
      <h1 className="text-xl font-bold tracking-tight">{t("title")}</h1>
      {state === "checking" ? <Spinner /> : (
        <>
          <Icon name={state === "ok" ? "check_circle" : "error"} size={40} className={state === "ok" ? "text-ok" : "text-bad"} />
          <p className="text-sm text-text-2">{t(state)}</p>
          <Link href="/account"><Button variant="primary">{t("continue")}</Button></Link>
        </>
      )}
      {state === "checking" && <p className="text-sm text-muted">{t("checking")}</p>}
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <Verify />
    </Suspense>
  );
}
