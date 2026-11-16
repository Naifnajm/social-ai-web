/** Types of the Production API (`/api/production/...`), mirroring apps/api/app/modules/production/schemas.py. */
import type { Shot } from "@/lib/ai";

export type MediaRef = { id: number; filename: string; mimetype: string; kind: string; url: string; width?: number | null; height?: number | null };
export type Estimate = { cost: number; model?: string | null; credits?: number | null };
export type MissingProvider = { capability: string; node_ids: number[] };
/** What a run would do (`GET /boards/{id}/estimate`, and `graph.run_all` for "run all"). */
export type RunEstimate = {
  cost: number;
  reused: number;
  blocks: number;
  /** total in AI credits when the platform's AI is used, else null */
  credits?: number | null;
  /** AI credits the workspace can still spend (null: unlimited or own keys) */
  credits_available?: number | null;
  missing?: MissingProvider[];
  empty_text?: number[];
};
export type OutputItem = {
  id: number;
  run: number;
  aspect?: string | null;
  cost: number;
  text?: string | null;
  model?: string | null;
  created_at?: string | null;
  media?: MediaRef | null;
  selected: boolean;
};

export type NodeState = "idle" | "queued" | "running" | "waiting" | "done" | "failed";

export type BlockNode = {
  id: number;
  board_id: number;
  kind: string;
  name: string;
  x: number;
  y: number;
  group_id?: number | null;
  prompt: string;
  text_value: string;
  provider_id?: number | null;
  model_id?: number | null;
  model_label?: string | null;
  aspect: string;
  style?: string | null;
  shot?: Shot | null;
  seconds: number;
  audio_mode: string;
  design?: Record<string, unknown> | null;
  variations: number;
  formats: string[];
  fit_mode: string;
  caption_position: string;
  caption_size: string;
  caption_language: string;
  template_ref?: string | null;
  approval_state?: string | null;
  approval_comment?: string | null;
  approver_id?: number | null;
  approver_name?: string | null;
  can_approve: boolean;
  account_ids: number[];
  publish_mode: string;
  publish_at?: string | null;
  state: NodeState;
  progress: number;
  error?: string | null;
  notice?: string | null;
  output_text?: string | null;
  output?: MediaRef | null;
  outputs: OutputItem[];
  run_no: number;
  post_id?: number | null;
  post_state?: string | null;
  out_type?: string | null;
  cost: number;
  estimate?: Estimate | null;
  fresh: boolean;
};

export type BlockEdge = { id: number; source: number; target: number; port: string; type?: string | null };
export type BlockGroup = { id: number; name: string; color: string; nodes: number[] };
export type Variable = { key: string; value: string };
export type Port = { key: string; label: string; accepts: string[]; multi: boolean };
export type Kind = { key: string; label: string; output?: string | null; accepts: string[]; generative: boolean; ports: Port[] };
export type Choice = { id: number; name: string };
export type AccountChoice = Choice & { platform: string; state: string; avatar_url?: string | null };
export type PickerModel = { id: number; name: string; label: string; price?: string | number | null; price_label?: string | null; default: boolean };
export type PickerGroup = { provider_id: number; provider: string; models: PickerModel[] };
export type BrandDesign = { id?: number | null; name: string; logo_url?: string | null; color: string; color2: string; text_color: string; font: string };

export type BoardInfo = {
  id: number;
  name: string;
  description?: string | null;
  template?: string | null;
  zoom: number;
  pan_x: number;
  pan_y: number;
  variables: Variable[];
  used_variables: string[];
  brand_kit_id?: number | null;
  post?: { id: number; name?: string | null; state: string } | null;
  cover_url?: string | null;
  updated_at?: string | null;
};

export type Graph = {
  board: BoardInfo;
  nodes: BlockNode[];
  edges: BlockEdge[];
  groups: BlockGroup[];
  kinds: Kind[];
  brand_kits: Choice[];
  accounts: AccountChoice[];
  members: Choice[];
  brand_templates: { value: string; label: string }[];
  pickers: Record<string, PickerGroup[]>;
  brand?: BrandDesign | null;
  styles: string[];
  aspects: string[];
  audio_modes: string[];
  publish_modes: string[];
  ffmpeg: boolean;
  subtitles: boolean;
  busy: boolean;
  run_all: RunEstimate;
};

export type BoardCard = {
  id: number;
  name: string;
  template?: string | null;
  node_count: number;
  output_count: number;
  status: "idle" | "running" | "failed";
  cover_url?: string | null;
  updated_at?: string | null;
};

export type BoardTemplate = { key: string; name: string; icon: string; description: string; blocks: number; video_mode?: "i2v" | "t2v" | null };
/** A video model offered when a production pipeline is created (`GET /api/ai/video-models`). */
export type VideoModelOption = {
  id: number;
  name: string;
  label: string;
  provider: string;
  provider_type: string;
  price_per_second: number;
  cost: number;
  audio: boolean;
  eu_limited: boolean;
  recommended: boolean;
  /** the price in AI credits when the platform's AI makes the clip */
  credits?: number | null;
};
