/**
 * AI feature client: types of the /api/ai endpoints + small hooks shared by the model picker, the media dialog
 * and the settings pages.
 *
 *   const picker = useAiPicker("image");                 // grouped models with prices + wallet
 *   const estimate = useAiEstimate({ capability: "video", model_id, seconds: 8, prompt });
 *   const job = await api.post<MediaJob>("/ai/media", { kind: "image", prompt });
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "./api";

export type Capability = "text" | "image" | "video" | "audio" | "stt";
export type MediaKind = "image" | "video" | "audio";
export type AudioMode = "speech" | "sfx" | "music";
export type Aspect = "1:1" | "4:5" | "9:16" | "16:9";

export type Wallet = { kind: "balance" | "budget" | "spent"; amount: number; unit: string; spent: number; budget?: number | null };

export type PickerModel = {
  id: number; name: string; label: string; unit: string; price: number; price_in: number; price_out: number;
  price_label: string; default: boolean;
};
export type PickerGroup = {
  provider_id: number; provider: string; provider_type: string; is_default: boolean; has_key: boolean; state: string;
  models: PickerModel[]; wallet: Wallet;
};
export type Estimate = {
  cost: number; detail: string; model: string; model_id: number | null; provider: string; provider_id: number | null;
  wallet: Wallet | null; known: boolean;
};

export type JobMedia = { id: number; filename: string; mimetype: string; url: string; width?: number | null; height?: number | null; duration?: number | null };
export type MediaJob = {
  id: number; kind: MediaKind; state: "running" | "done" | "failed"; progress: number; prompt: string; title: string;
  aspect: string; style?: string | null; seconds: number; audio_mode: AudioMode; voice?: string | null;
  provider_id?: number | null; provider?: string | null; model_name?: string | null; media_id?: number | null;
  media?: JobMedia | null; error?: string | null; notice?: string | null; cost: number; created_at: string;
};

export type AiStatus = { text: boolean; image: boolean; video: boolean; audio: boolean; stt: boolean; default_provider?: string | null };

export const useAiStatus = () => useQuery({ queryKey: ["ai", "status"], queryFn: () => api.get<AiStatus>("/ai/status"), staleTime: 60_000 });

export function useAiPicker(capability: Capability, enabled = true) {
  return useQuery({
    queryKey: ["ai", "picker", capability],
    queryFn: () => api.get<{ capability: Capability; groups: PickerGroup[] }>("/ai/pickers", { capability }).then((r) => r.groups),
    enabled,
    staleTime: 30_000,
  });
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

export type EstimateInput = {
  capability: Capability; model_id?: number | null; provider_id?: number | null; prompt?: string; seconds?: number;
  audio_mode?: AudioMode;
};

/** Live cost estimate (debounced, prompt length matters for text and speech only). */
export function useAiEstimate(input: EstimateInput, enabled = true) {
  const lengthMatters = input.capability === "text" || (input.capability === "audio" && (input.audio_mode ?? "speech") === "speech");
  const key = useDebounced({ ...input, prompt: lengthMatters ? input.prompt ?? "" : "" }, 400);
  return useQuery({
    queryKey: ["ai", "estimate", key],
    queryFn: () => api.post<Estimate>("/ai/estimate", key),
    enabled,
    placeholderData: (previous) => previous,
    staleTime: 30_000,
  });
}

const usd2 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const usd4 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 4 });
const whole = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

/** Dollars: 2 decimals for amounts ≥ $1, up to 4 for small task costs. */
// wrapped in Unicode LTR isolates so "$12.50" stays intact inside Arabic sentences
export const money = (value: number, precise = false) => `\u2066${(precise && Math.abs(value) < 1 ? usd4 : usd2).format(value || 0)}\u2069`;
export const count = (value: number) => whole.format(value || 0);

export const ASPECTS: Aspect[] = ["1:1", "4:5", "9:16", "16:9"];
export const STYLES = ["photo", "illustration", "3d", "minimal", "cinematic", "product"] as const;
export const CAPABILITY_ICONS: Record<Capability, string> = {
  text: "text_fields", image: "image", video: "movie", audio: "graphic_eq", stt: "subtitles",
};
