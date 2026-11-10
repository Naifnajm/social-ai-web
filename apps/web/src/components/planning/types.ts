/** Types of the planning API (campaigns, pillars, planner, evergreen, library, links, products, reports). */

export type Ref = { id: number; name: string; color: string };

export type PlannerPost = {
  id: number;
  name: string;
  preview: string;
  state: string;
  day: string | null;
  time: string | null;
  scheduled_at: string | null;
  published_at: string | null;
  platforms: string[];
  account_ids: number[];
  media: { id: number; kind: string; url: string } | null;
  media_count: number;
  campaign: Ref | null;
  pillar: Ref | null;
  author: string;
  evergreen: boolean;
  recycled: boolean;
  movable: boolean;
};

export type CampaignStats = {
  post_count: number;
  published_count: number;
  scheduled_count: number;
  draft_count: number;
  impressions: number;
  reach: number;
  engagements: number;
  engagement_rate: number;
  video_views: number;
  progress: number;
  clicks: number;
  conversions: number;
  revenue: number;
};

export type CampaignState = "planned" | "running" | "finished";

export type Campaign = {
  id: number;
  name: string;
  tagline: string | null;
  goal: string | null;
  date_start: string | null;
  date_end: string | null;
  color: string;
  state: CampaignState;
  budget: number | null;
  owner_id: number | null;
  owner_name: string | null;
  auto_state: boolean;
  archived: boolean;
  target_posts: number | null;
  days_left: number | null;
  stats: CampaignStats;
};

export type CampaignDetail = Campaign & {
  networks: { platform: string; posts: number; impressions: number; engagements: number; engagement_rate: number; clicks: number; revenue: number }[];
  posts: PlannerPost[];
  currency: string;
};

export type Pillar = {
  id: number;
  name: string;
  color: string;
  description: string | null;
  target_share: number;
  position: number;
  active: boolean;
  published_30: number;
  share_30: number;
  planned_30: number;
  planned_share_30: number;
  gap: number;
};

export type BestHint = { weekday: number; time: string | null; top: boolean; source: string };
export type BestSlot = { at: string; local: string; weekday: number; time: string; source: string };

export type PlannerData = {
  start: string;
  end: string;
  today: string;
  timezone: string;
  posts: PlannerPost[];
  unplanned: PlannerPost[];
  best: BestHint[];
  best_slots: BestSlot[];
  accounts: { id: number; name: string; platform: string; avatar_url: string | null }[];
  campaigns: { id: number; name: string; color: string; state: string; date_start: string | null; date_end: string | null }[];
  pillars: Pillar[];
};

export type Evergreen = {
  post: PlannerPost;
  evergreen: boolean;
  interval_days: number;
  until: string | null;
  rewrite: boolean;
  recycle_count: number;
  last_recycled_at: string | null;
  next_recycle_at: string | null;
  waiting_copy: boolean;
};

export type LibraryItem = {
  id: number;
  filename: string;
  mimetype: string;
  kind: string;
  size: number;
  source: string;
  width: number | null;
  height: number | null;
  duration: number | null;
  tags: string[];
  favorite: boolean;
  used: number;
  author: string | null;
  created_by_id: number | null;
  created_at: string;
  url: string;
  thumb_url: string;
};

export type LibraryPage = { items: LibraryItem[]; total: number; tags: { name: string; count: number }[]; counts: Record<string, number> };

export type TrackedLink = {
  id: number;
  code: string;
  short_url: string;
  url: string;
  destination: string;
  kind: string;
  label: string | null;
  post_id: number | null;
  post_name: string | null;
  platform: string | null;
  campaign_id: number | null;
  campaign_name: string | null;
  utm_source: string | null;
  utm_medium: string | null;
  utm_campaign: string | null;
  clicks: number;
  conversions: number;
  revenue: number;
  last_click_at: string | null;
  created_at: string;
};

export type Totals = { clicks: number; conversions: number; orders: number; leads: number; revenue: number; conversion_rate: number };
export type ResultRow = { key: string; label: string; color: string | null; clicks: number; conversions: number; orders: number; leads: number; revenue: number };

export type LinksSummary = {
  days: number;
  currency: string;
  enabled: boolean;
  totals: Totals;
  previous: Totals;
  by_platform: ResultRow[];
  by_campaign: ResultRow[];
  top_posts: { id: number; name: string; platforms: string[]; clicks: number; conversions: number; revenue: number; thumb_url: string | null; published_at: string | null }[];
  daily: { date: string; clicks: number; conversions: number; revenue: number }[];
};

export type Conversion = {
  id: number;
  kind: string;
  value: number;
  currency: string | null;
  external_id: string | null;
  occurred_at: string;
  source: string;
  post_id: number | null;
  post_name: string | null;
  platform: string | null;
  campaign_id: number | null;
  campaign_name: string | null;
  product_id: number | null;
  utm_source: string | null;
  utm_medium: string | null;
  utm_campaign: string | null;
  note: string | null;
};

export type LinkSettings = {
  enabled: boolean;
  retag: boolean;
  add_ref: boolean;
  base_url: string | null;
  default_base_url: string;
  public_key: string;
  has_secret: boolean;
  snippet: string;
  pixel_url: string;
  server_url: string;
};

export type Product = {
  id: number;
  name: string;
  description: string | null;
  price: number | null;
  currency: string;
  price_label: string;
  image_media_id: number | null;
  image_url: string | null;
  url: string | null;
  sku: string | null;
  active: boolean;
  announced_post_id: number | null;
  announced_post_state: string | null;
  announced_at: string | null;
  created_at: string;
};

export type ProductSettings = {
  auto_announce: boolean;
  account_ids: number[];
  caption: "ai" | "template";
  template: string;
  mode: "draft" | "best_time";
  design: string;
  campaign_id: number | null;
};

export type ReportSchedule = {
  id: number;
  name: string;
  recipients: string[];
  frequency: "weekly" | "monthly";
  weekday: number;
  month_day: number;
  hour: number;
  period: "last_7" | "last_30" | "prev_month";
  account_ids: number[];
  language: "ar" | "en";
  include_ai: boolean;
  active: boolean;
  last_sent_at: string | null;
  next_send_at: string | null;
  last_error: string | null;
  send_count: number;
};

export type Account = { id: number; name: string; platform: string; avatar_url: string | null };
