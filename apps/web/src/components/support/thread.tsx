"use client";
/** A ticket's conversation, shared by the person's support page and the platform support desk. */
import { useLocale, useTranslations } from "next-intl";
import { cx } from "@/components/ui";

export type Message = { id: number; body: string; staff: boolean; author: string | null; created_at: string };
export type Ticket = {
  id: number; subject: string; category: string; status: "open" | "answered" | "closed"; error_ref: string | null;
  unread: boolean; author: string | null; created_at: string; last_message_at: string; messages?: Message[] | null;
};
export const STATUS_TONE = { open: "warn", answered: "ok", closed: "neutral" } as const;

export function useWhen() {
  const locale = useLocale();
  const format = new Intl.DateTimeFormat(locale === "ar" ? "ar-SA-u-nu-latn-ca-gregory" : locale, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  return (value: string) => format.format(new Date(value));
}

export function Thread({ messages, me }: { messages: Message[]; me: "user" | "staff" }) {
  const t = useTranslations("support");
  const when = useWhen();
  return (
    <div className="flex flex-col gap-3">
      {messages.map((m) => {
        const mine = (me === "staff") === m.staff;
        return (
          <div key={m.id} className={cx("max-w-[85%] rounded-2xl px-4 py-3 text-sm", mine ? "self-end bg-ink text-white" : "self-start bg-fill-2")}>
            <div className={cx("mb-1 text-xs font-semibold", mine ? "text-white/60" : m.staff ? "text-accent-deep" : "text-muted")}>
              {m.staff ? t("team") : m.author || t("you")} · <span className="font-normal">{when(m.created_at)}</span>
            </div>
            <p className="bidi whitespace-pre-wrap leading-relaxed">{m.body}</p>
          </div>
        );
      })}
    </div>
  );
}
