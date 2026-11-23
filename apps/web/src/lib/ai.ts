/**
 * AI feature client: types of the /api/ai endpoints + small hooks shared by the model picker, the media dialog
 * and the settings pages.
 *
 *   const picker = useAiPicker("image");                 // grouped models with prices + wallet
 *   const estimate = useAiEstimate({ capability: "video", model_id, seconds: 8, prompt });
 *   const job = await api.post<MediaJob>("/ai/media", { kind: "image", prompt });
 */
import { useQuery } from "@tanstack/react-query";
import { useLocale } from "next-intl";
import { useEffect, useState } from "react";
import { api } from "./api";

export type Capability = "text" | "image" | "video" | "audio" | "stt";
export type MediaKind = "image" | "video" | "audio";
export type AudioMode = "speech" | "sfx" | "music";
export type Aspect = "1:1" | "4:5" | "9:16" | "16:9";

/** `credits`: the platform's AI, paid from the plan's monthly AI and bought credits (amount null = unlimited). */
export type Wallet = { kind: "balance" | "budget" | "spent" | "credits"; amount: number | null; unit: string; spent: number; budget?: number | null };

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
  wallet: Wallet | null; known: boolean; credits?: number | null;
};

export type JobMedia = { id: number; filename: string; mimetype: string; url: string; width?: number | null; height?: number | null; duration?: number | null };
export type MediaJob = {
  id: number; kind: MediaKind; state: "running" | "done" | "failed"; progress: number; prompt: string; title: string;
  aspect: string; style?: string | null; shot?: Shot | null; brand_score?: number | null; seconds: number; audio_mode: AudioMode; voice?: string | null;
  provider_id?: number | null; provider?: string | null; model_name?: string | null; media_id?: number | null;
  media?: JobMedia | null; error?: string | null; notice?: string | null; cost: number; created_at: string;
};

/** Camera settings of an image/video ("shoot it like a real camera"), see GET /api/ai/camera.
 * `{mode: "auto"}` lets the description decide; manual adds `<group>: <option key>` and maybe a preset. */
export type Shot = { mode: "auto" | "manual"; preset?: string } & Record<string, string | undefined>;
export type CameraOption = { key: string; label: string; icon: string };
export type CameraGroup = { key: string; label: string; icon: string; kinds: ("image" | "video")[]; options: CameraOption[] };
export type CameraPreset = { key: string; label: string; icon: string; values: Record<string, string> };
export type CameraOptions = { groups: CameraGroup[]; presets: CameraPreset[] };

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

/** Camera groups/options/presets with icons (labels come translated by the API). */
export function useCameraOptions(enabled = true) {
  const locale = useLocale();
  return useQuery({
    queryKey: ["ai", "camera", locale],
    queryFn: () => api.get<CameraOptions>("/ai/camera"),
    enabled,
    staleTime: Infinity,
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
/** Credits (whole numbers, or one decimal under 10). */
export const credits = (value: number) => (Math.abs(value) < 10 && value % 1 ? value.toFixed(1) : whole.format(Math.round(value || 0)));

export const ASPECTS: Aspect[] = ["1:1", "4:5", "9:16", "16:9"];
export const STYLES = ["photo", "illustration", "3d", "minimal", "cinematic", "product"] as const;
export const CAPABILITY_ICONS: Record<Capability, string> = {
  text: "text_fields", image: "image", video: "movie", audio: "graphic_eq", stt: "subtitles",
};

// ---------------------------------------------------------------- voices (drop-downs instead of typed ids)
/** OpenAI text-to-speech voices (also used by Azure OpenAI). */
export const OPENAI_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse"];

type VoiceSource = { provider_type: string; name: string; capabilities: Capability[]; available_models?: string[] };

/** Voices of one provider: OpenAI's fixed list, or the "Name (id)" entries ElevenLabs returned at its last test. */
export function providerVoices(p: Pick<VoiceSource, "provider_type" | "available_models">): { value: string; label: string }[] {
  if (p.provider_type === "openai" || p.provider_type === "azure_openai") return OPENAI_VOICES.map((v) => ({ value: v, label: v }));
  return (p.available_models ?? []).map((entry) => {
    const m = /^(.*) \(([^()]+)\)$/.exec(entry);
    return m ? { value: m[2], label: m[1] } : null;
  }).filter((v): v is { value: string; label: string } => !!v);
}

/** Every voice of the workspace's audio providers, labelled with the provider (empty when the list can't be read). */
export function useVoiceChoices(enabled = true) {
  const providers = useQuery({
    queryKey: ["ai", "providers"], queryFn: () => api.get<VoiceSource[]>("/ai/providers"), enabled, retry: false, staleTime: 60_000,
  });
  return (providers.data ?? []).filter((p) => p.capabilities.includes("audio"))
    .flatMap((p) => providerVoices(p).map((v) => ({ value: v.value, label: v.label, hint: p.name })));
}
