/** Ideas of the day: shapes returned by /api/ideas (see apps/api/app/modules/ideas/router.py, idea_out). */

export type IdeaFormat = "post" | "carousel" | "video";
export type IdeaState = "new" | "scheduled" | "draft" | "rejected" | "expired";
export type ReasonKind = "question" | "rising" | "event" | "pillar" | "product" | "format" | "top_post" | "best_time" | "brief";
export type RejectReason = "not_relevant" | "not_our_tone" | "already_done" | "bad_timing" | "other";
export type ApproveMode = "suggested" | "best_time" | "schedule" | "draft";

export type Slide = { title: string; body: string };
export type Scene = { visual: string; text: string };
export type VideoScript = { hook: string; duration: number; scenes: Scene[]; voiceover: string };

export type Idea = {
  id: number;
  state: IdeaState;
  format: IdeaFormat;
  language: string;
  title: string;
  reasons: { kind: ReasonKind | string; label: string }[];
  caption: string;
  variants: Record<string, string>;
  hashtags: string[];
  slides: Slide[];
  video: VideoScript | null;
  platforms: string[];
  account_ids: number[];
  suggested_at: string | null;
  slot_label: string | null;
  pillar_id: number | null;
  product_id: number | null;
  media_ids: number[];
  media_urls: string[];
  ai_written: boolean;
  edited: boolean;
  created_at: string;
  post: { id: number; state: string; scheduled_at: string | null } | null;
};

export type IdeaAccount = { id: number; name: string; platform: string; avatar_url: string | null };

export type IdeaSettings = {
  daily: boolean;
  count: number;
  language: string;
  hour: number;
  languages: string[];
  has_ai: boolean;
  accounts: IdeaAccount[];
};

export type ApproveResult = { post_id: number; url: string; post_state: string; scheduled_at: string | null; skipped_accounts?: string[]; idea: Idea };

export type IdeaPatch = Partial<{
  title: string;
  caption: string;
  variants: Record<string, string>;
  hashtags: string[];
  slides: Slide[];
  video: VideoScript;
  suggested_at: string | null;
  account_ids: number[];
}>;

export type GenerateIn = { count?: number; language?: string; focus?: string; formats?: IdeaFormat[] };

export const FORMATS: IdeaFormat[] = ["post", "carousel", "video"];
export const REJECT_REASONS: RejectReason[] = ["not_relevant", "not_our_tone", "already_done", "bad_timing", "other"];
