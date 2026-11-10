"use client";
/**
 * AI model dropdown grouped by provider, with the price of each model, the estimated cost of the task and what is
 * left in the provider's wallet (balance / monthly budget / spent). Reusable by every feature:
 *
 *   const [modelId, setModelId] = useState<number | null>(null);
 *   <ModelPicker capability="video" value={modelId} onChange={setModelId} prompt={prompt} seconds={8} />
 *
 * `value = null` means "automatic" (the provider's default model). Pass `estimate={false}` to hide the cost chip,
 * or `onEstimate` to receive the live estimate (e.g. to disable a button when credit is short).
 */
import { useTranslations } from "next-intl";
import { useEffect } from "react";
import { Link } from "@/i18n/navigation";
import { type AudioMode, type Capability, type Estimate, type Wallet, money, count, useAiEstimate, useAiPicker } from "@/lib/ai";
import { useSession } from "@/lib/session";
import { Icon } from "./icon";
import { Select, Spinner, cx } from "./ui";

type Props = {
  capability: Capability;
  value: number | null;
  onChange: (modelId: number | null) => void;
  prompt?: string;
  seconds?: number;
  audioMode?: AudioMode;
  providerId?: number | null;
  estimate?: boolean;
  onEstimate?: (estimate: Estimate | undefined, notEnough: boolean) => void;
  compact?: boolean;
  label?: string;
  className?: string;
};

export function walletLevel(wallet?: Wallet | null) {
  if (!wallet || wallet.kind === "spent") return "neutral";
  if (wallet.kind === "budget") return wallet.amount <= 0 ? "empty" : wallet.budget && wallet.amount < wallet.budget * 0.15 ? "low" : "ok";
  return wallet.amount <= 0 ? "empty" : "ok";
}

export function WalletChip({ wallet, title }: { wallet?: Wallet | null; title?: string }) {
  const t = useTranslations("ai.picker");
  if (!wallet) return null;
  const level = walletLevel(wallet);
  let text: string;
  if (wallet.kind === "balance") {
    const amount = wallet.unit === "USD" ? money(wallet.amount) : `${count(wallet.amount)} ${t.has(`units.${wallet.unit}`) ? t(`units.${wallet.unit}`) : wallet.unit}`;
    text = t("balance", { amount });
  } else if (wallet.kind === "budget") {
    text = t("left", { left: money(wallet.amount), budget: money(wallet.budget ?? 0) });
  } else {
    text = t("spent", { amount: money(wallet.spent) });
  }
  return (
    <span title={title} className={cx("inline-flex h-6 items-center gap-1 whitespace-nowrap rounded-full px-2.5 text-[11.5px] font-medium",
      level === "neutral" && "bg-fill-2 text-text-2", level === "ok" && "bg-ok-bg text-ok",
      level === "low" && "bg-warn-bg text-warn", level === "empty" && "bg-bad-bg text-bad")}>
      <Icon name="account_balance" size={13} />
      <span dir="auto">{text}</span>
    </span>
  );
}

export function CostChip({ estimate, over }: { estimate?: Estimate | null; over?: boolean }) {
  const t = useTranslations("ai.picker");
  if (!estimate) return null;
  let text: string;
  if (!estimate.known && !estimate.cost) {
    if (!estimate.model) return null;
    text = t("unknownPrice");
  } else text = estimate.cost ? money(estimate.cost, true) : t("free");
  return (
    <span title={estimate.detail} className={cx("inline-flex h-6 items-center gap-1 whitespace-nowrap rounded-full border px-2.5 text-[11.5px]",
      over ? "border-transparent bg-bad-bg text-bad" : "border-line bg-white/70 text-text")}>
      <Icon name="payments" size={13} />
      {estimate.known || estimate.cost ? <>{t("estimated")} <b className="font-semibold" dir="ltr">{text}</b></> : text}
      {estimate.detail && (estimate.known || estimate.cost) ? <span className="hidden text-[10.5px] text-muted sm:inline" dir="ltr">({estimate.detail})</span> : null}
    </span>
  );
}

export function ModelPicker({ capability, value, onChange, prompt = "", seconds = 0, audioMode = "speech", providerId,
  estimate: showEstimate = true, onEstimate, compact, label, className }: Props) {
  const t = useTranslations("ai.picker");
  const can = useSession((s) => s.can);
  const groups = useAiPicker(capability);
  const estimate = useAiEstimate({ capability, model_id: value, provider_id: value ? null : providerId, prompt, seconds, audio_mode: audioMode },
    showEstimate || !!onEstimate);

  const selectedGroup = (() => {
    const list = groups.data ?? [];
    if (value) return list.find((g) => g.models.some((m) => m.id === value)) ?? list[0];
    return list.find((g) => g.provider_id === (estimate.data?.provider_id ?? providerId)) ?? list[0];
  })();
  const wallet = estimate.data?.wallet ?? selectedGroup?.wallet;
  const notEnough = Boolean(estimate.data && wallet && wallet.unit === "USD" && wallet.kind !== "spent" && estimate.data.cost > wallet.amount);

  useEffect(() => {
    onEstimate?.(estimate.data, notEnough);
  }, [estimate.data, notEnough, onEstimate]);

  if (groups.isLoading) return <div className={cx("flex h-10 items-center", className)}><Spinner size={16} /></div>;
  if (!groups.data?.length) {
    return (
      <div className={cx("flex items-center gap-2 rounded-xl bg-fill px-3 py-2.5 text-[13px] text-muted", className)}>
        <Icon name="info" size={16} />
        <span className="flex-1">{t(`none.${capability}`)}</span>
        {can("admin") && <Link href="/settings/ai" className="font-semibold text-text underline-offset-2 hover:underline">{t("addProvider")}</Link>}
      </div>
    );
  }

  return (
    <div className={cx("flex flex-col gap-1.5", className)}>
      {label && <span className="text-[13px] font-medium text-text-2">{label}</span>}
      <Select aria-label={label || t("model")} value={value ?? ""} className={compact ? "!h-9 text-[13px]" : undefined}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
        <option value="">{t("automatic")}</option>
        {groups.data.map((group) => (
          <optgroup key={group.provider_id} label={group.provider}>
            {group.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}{m.default ? ` (${t("default")})` : ""}{m.price_label ? `  ·  ${m.price_label}` : ""}
              </option>
            ))}
          </optgroup>
        ))}
      </Select>
      <div className="flex flex-wrap items-center gap-1.5">
        <WalletChip wallet={wallet} title={selectedGroup?.provider} />
        {showEstimate && <CostChip estimate={estimate.data} over={notEnough} />}
      </div>
      {notEnough && (
        <div className="flex items-center gap-1 text-xs text-bad">
          <Icon name="warning" size={14} /> {t("notEnough")}
        </div>
      )}
    </div>
  );
}
