/** Types of the publishing API (accounts, posts, studio, performance). */
export type Platform = "facebook" | "instagram" | "linkedin" | "x" | "tiktok" | "threads" | "telegram" | "whatsapp";
export type PostState = "draft" | "to_approve" | "scheduled" | "publishing" | "posted" | "partial" | "failed";
export type PublishAs = "feed" | "story" | "feed_story";
export type SubmitAction = "draft" | "publish" | "schedule" | "best_time";

export type Account = {
  id: number;
  name: string;
  platform: Platform;
  platform_label: string;
  username?: string | null;
  external_id?: string | null;
  avatar_url?: string | null;
  state: "draft" | "connected" | "expired" | "error" | "disconnected";
  last_error?: string | null;
  last_check_at?: string | null;
  followers: number;
  followers_updated_at?: string | null;
  token_expires_at?: string | null;
  has_token: boolean;
  can_refresh: boolean;
  active: boolean;
  inbox_only: boolean;
  can_publish: boolean;
  connected_with: "oauth" | "token";
  oauth_app?: "workspace" | "platform" | null;
  privacy_level?: string | null;
  created_at: string;
};

export type PlatformOption = {
  key: Platform;
  label: string;
  method: "oauth" | "token";
  oauth_platform?: string | null;
  configured: boolean;
  source?: "workspace" | "platform" | null;
  help: string;
};

export type OAuthSetup = {
  platform: string;
  requested: string;
  brand: string;
  portal_url: string;
  id_label: string;
  secret_label: string;
  steps: string[];
  note?: string | null;
  redirect_uri: string;
  configured: boolean;
  source?: "workspace" | "platform" | null;
  own_app: boolean;
  client_id: string;
};

export type Media = { id: number; filename: string; mimetype: string; size: number; width?: number | null; height?: number | null; url: string; thumb_url: string };

export type Target = {
  id: number;
  account_id: number;
  account_name: string;
  account_avatar?: string | null;
  platform: Platform;
  state: "pending" | "sending" | "posted" | "failed";
  external_url?: string | null;
  error?: string | null;
  published_at?: string | null;
  media_type?: string | null;
  story_state?: "pending" | "sending" | "posted" | "failed" | "skipped" | null;
  story_url?: string | null;
  story_error?: string | null;
  impressions: number;
  likes: number;
  comments: number;
  shares: number;
  engagements: number;
  engagement_rate: number;
};

export type Post = {
  id: number;
  name?: string | null;
  content: string;
  variants: Record<string, string>;
  state: PostState;
  publish_as: PublishAs;
  scheduled_at?: string | null;
  published_at?: string | null;
  planned_date?: string | null;
  created_at: string;
  updated_at: string;
  author_name?: string | null;
  accounts: { id: number; name: string; platform: Platform; avatar_url?: string | null; username?: string | null }[];
  account_ids: number[];
  platforms: Platform[];
  media: Media[];
  story_media: Media[];
  platform_media: Record<string, number[]>;
  campaign_id?: number | null;
  pillar_id?: number | null;
  ai_brief?: string | null;
  requested_action?: string | null;
  approval_requested_by_name?: string | null;
  approval_requested_at?: string | null;
  approved_by_id?: number | null;
  approved_at?: string | null;
  approval_note?: string | null;
  targets: Target[];
  can_edit: boolean;
  can_retry: boolean;
  totals: Record<string, number>;
};

export type Rule = { label: string; max_chars: number; max_images: number; requires_media: boolean; video: boolean; audio: boolean; story: boolean };

export type Studio = {
  accounts: Account[];
  rules: Record<string, Rule>;
  story_platforms: Platform[];
  needs_approval: boolean;
  is_approver: boolean;
  approvals_enabled: boolean;
  kpis: { published: number; scheduled: number; failed: number; to_approve: number; accounts: number };
  recent_posts: Post[];
  timezone: string;
  can_connect: boolean;
};

export type BestSlot = { at: string; local: string; label: string; score: number };
export type Problem = { platform?: string | null; account_id?: number | null; message: string };

export type Tip = { level: "danger" | "warning" | "success" | "info"; icon: string; title: string; text: string; action?: string | null };

export type Dashboard = {
  period: { days: number; start: string; end: string };
  platform?: string | null;
  timezone: string;
  has_metrics: boolean;
  kpis: Record<string, number>;
  deltas: Record<string, number | null>;
  breakdown: { platform: Platform; label: string; posts: number; impressions: number; engagements: number; engagement_rate: number; followers: number; per_week: number; rhythm: [number, number] }[];
  series: { date: string; posts: number; impressions: number; engagements: number }[];
  followers_series: { date: string; followers: number }[];
  heatmap: { score: number; count: number }[][];
  best_slots: { weekday: number; hour: number; score: number }[];
  best_source: "own" | "benchmark";
  content: Record<"media" | "length" | "hashtags", { key: string; label: string; count: number; engagement_rate: number; avg_engagements: number }[]>;
  top_posts: { id: number; name: string; platform: Platform; account: string; url: string; date: string; media_id?: number | null; impressions: number; engagements: number; engagement_rate: number; likes: number; comments: number; shares: number; media_type: string }[];
  accounts: { id: number; name: string; platform: Platform; followers: number; state: string; avatar_url: string }[];
  tips: Tip[];
  last_sync?: string | null;
  extra: Record<string, unknown>;
};

export const PUBLISH_PLATFORMS: Platform[] = ["facebook", "instagram", "linkedin", "x", "tiktok", "threads", "telegram"];
export const PLATFORM_LABELS: Record<string, string> = {
  facebook: "Facebook", instagram: "Instagram", linkedin: "LinkedIn", x: "X", tiktok: "TikTok", threads: "Threads", telegram: "Telegram", whatsapp: "WhatsApp",
};
