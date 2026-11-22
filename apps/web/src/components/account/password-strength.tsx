"use client";
/** A quick strength estimate while typing (the API has the final word: length, common passwords, e-mail-like). */
import { useTranslations } from "next-intl";
import { cx } from "../ui";

const COMMON = ["password", "123456", "qwerty", "azerty", "welcome", "admin", "letmein", "iloveyou", "stravica"];

export function passwordScore(value: string, email?: string): number {
  if (!value) return 0;
  const lower = value.toLowerCase();
  if (value.length < 8 || COMMON.some((c) => lower.includes(c)) || new Set(lower).size <= 3) return 0;
  const local = (email || "").toLowerCase().split("@")[0];
  if (local.length >= 4 && lower.includes(local)) return 1;
  let score = value.length >= 12 ? 2 : 1;
  const kinds = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((re) => re.test(value)).length;
  if (kinds >= 3) score++;
  if (value.length >= 16) score++;
  return Math.min(score, 4);
}

const COLORS = ["bg-bad", "bg-bad", "bg-warn", "bg-ok", "bg-ok"];

export function PasswordStrength({ value, email }: { value: string; email?: string }) {
  const t = useTranslations("account.security");
  if (!value) return <p className="text-xs text-muted">{t("strengthHint")}</p>;
  const score = passwordScore(value, email);
  return (
    <div className="flex flex-col gap-1" aria-live="polite">
      <div className="flex gap-1">
        {[0, 1, 2, 3].map((i) => <span key={i} className={cx("h-1.5 flex-1 rounded-full", i < Math.max(score, 1) ? COLORS[score] : "bg-track")} />)}
      </div>
      <p className="text-xs text-muted">{t(`strength.s${score}`)} · {t("strengthHint")}</p>
    </div>
  );
}
