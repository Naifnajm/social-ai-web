import type { Capability, Wallet } from "@/lib/ai";

export type CatalogModel = { name: string; label: string; capability: Capability; unit: string; price_in: number; price_out: number; price: number; price_label: string };
export type CatalogEntry = {
  type: string; label: string; capabilities: Capability[]; engine?: string | null; base_url: string; needs_base_url: boolean;
  no_key: boolean; key_url?: string | null; default_models: Partial<Record<Capability, string>>; voice?: string | null;
  max_tokens: number; balance_supported: boolean; models: CatalogModel[];
};
export type Provider = {
  id: number; name: string; provider_type: string; type_label: string; capabilities: Capability[]; has_key: boolean;
  base_url?: string | null; text_model?: string | null; image_model?: string | null; video_model?: string | null;
  audio_model?: string | null; voice?: string | null; max_tokens: number; is_default: boolean; active: boolean;
  state: "draft" | "ok" | "error"; last_error?: string | null; tested_at?: string | null; available_models: string[];
  key_url?: string | null; balance_supported: boolean; balance?: number | null; balance_unit?: string | null;
  balance_checked_at?: string | null; monthly_budget?: number | null; spent_month: number; spent_total: number;
  wallet: Wallet; models_count: number;
};
export type AiModel = {
  id: number; provider_id: number; name: string; label: string; capability: Capability; unit: string; price_in: number;
  price_out: number; price: number; price_label: string; active: boolean; sequence: number;
};
export type TestResult = { ok: boolean; message: string; models: string[]; warning?: string | null; provider: Provider };

export const MODEL_FIELDS: Partial<Record<Capability, "text_model" | "image_model" | "video_model" | "audio_model">> = {
  text: "text_model", image: "image_model", video: "video_model", audio: "audio_model",
};
export const UNITS = ["tokens", "image", "second", "1k_chars", "minute", "free"] as const;
