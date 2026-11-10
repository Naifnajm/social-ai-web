"use client";
import { useParams } from "next/navigation";
import { InboxScreen } from "../_components/inbox-screen";

/** /inbox and /inbox/<conversation id> (links from notifications and the mobile app). */
export default function InboxPage() {
  const params = useParams<{ id?: string[] }>();
  const raw = params.id?.[0];
  const id = raw && /^\d+$/.test(raw) ? Number(raw) : null;
  return <InboxScreen initialId={id} />;
}
