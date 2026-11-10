"use client";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button, Card, Field, Input, PageHeader, toast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";

export default function NewWorkspacePage() {
  const t = useTranslations("shell");
  const { switchWorkspace } = useSession();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    try {
      const ws = await api.post<{ id: number }>("/workspaces", { name });
      await switchWorkspace(ws.id);
      window.location.href = "/";
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : String(err));
      setBusy(false);
    }
  };
  return (
    <div className="mx-auto max-w-lg pt-2">
      <PageHeader icon="add" title={t("newWorkspace")} subtitle={t("newWorkspaceHint")} />
      <Card>
        <Field label={t("workspaceName")}><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <div className="mt-4 flex justify-end"><Button variant="primary" loading={busy} disabled={!name.trim()} onClick={create}>{t("create")}</Button></div>
      </Card>
    </div>
  );
}
