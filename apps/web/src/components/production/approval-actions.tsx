"use client";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Badge, Button, Textarea } from "@/components/ui";
import { useCanvas } from "./canvas-context";
import type { BlockNode } from "./types";

/** Approve / reject an Approval block (shown to the approver, or admins). */
export function ApprovalActions({ node }: { node: BlockNode }) {
  const t = useTranslations("production");
  const { actions } = useCanvas();
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const tone = node.approval_state === "approved" ? "ok" : node.approval_state === "rejected" ? "bad" : node.approval_state ? "warn" : "neutral";
  const act = async (kind: "approve" | "reject") => {
    setBusy(kind);
    try {
      await (kind === "approve" ? actions.approve(node.id, comment) : actions.reject(node.id, comment));
      setComment("");
    } catch {
      /* toast already shown */
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-center gap-2">
        <Badge tone={tone}>{t(`approval.${node.approval_state || "none"}`)}</Badge>
        {node.approver_name && <span className="text-xs text-muted">{t("approval.by", { name: node.approver_name })}</span>}
      </div>
      {node.state === "waiting" && node.can_approve && (
        <>
          <Textarea rows={2} value={comment} placeholder={t("approval.comment")} onChange={(e) => setComment(e.target.value)} />
          <div className="flex gap-2">
            <Button variant="primary" size="sm" icon="check" loading={busy === "approve"} onClick={() => act("approve")}>{t("approval.approve")}</Button>
            <Button variant="danger" size="sm" icon="close" loading={busy === "reject"} onClick={() => act("reject")}>{t("approval.reject")}</Button>
          </div>
        </>
      )}
      {node.state === "waiting" && !node.can_approve && <p className="text-xs text-muted">{t("approval.waitingFor", { name: node.approver_name || "" })}</p>}
    </div>
  );
}
