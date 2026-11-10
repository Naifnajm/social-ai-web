"use client";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Button, Spinner } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";

export default function InvitePage() {
  const t = useTranslations("auth");
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const { me, load, switchWorkspace } = useSession();
  const [state, setState] = useState<"checking" | "anonymous" | "ready" | "error">("checking");
  const [error, setError] = useState("");

  useEffect(() => {
    (me ? Promise.resolve(me) : load()).then((m) => setState(m ? "ready" : "anonymous"));
  }, [me, load]);

  const accept = async () => {
    try {
      const data = await api.post<{ workspace: { id: number } }>(`/invitations/${token}/accept`);
      await switchWorkspace(data.workspace.id);
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("error"));
      setState("error");
    }
  };

  if (state === "checking") return <div className="flex justify-center py-8"><Spinner /></div>;
  return (
    <div className="flex flex-col gap-4 text-center">
      <h1 className="text-xl font-bold tracking-tight">{t("inviteTitle")}</h1>
      <p className="text-sm text-muted">{t("inviteText")}</p>
      {error && <p className="rounded-xl bg-bad-bg px-3 py-2 text-sm text-bad">{error}</p>}
      {state === "anonymous" ? (
        <div className="flex flex-col gap-2">
          <Link href={`/signup?invitation=${token}`}><Button variant="primary" size="lg" className="w-full">{t("signup")}</Button></Link>
          <Link href={`/login?next=/invite/${token}`}><Button size="lg" className="w-full">{t("login")}</Button></Link>
        </div>
      ) : (
        <Button variant="primary" size="lg" onClick={accept}>{t("acceptInvite")}</Button>
      )}
    </div>
  );
}
