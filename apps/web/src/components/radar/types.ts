/** Types of the radar API (apps/api/app/modules/listening): setups, numbers, mentions and events. */

export const SOURCES = ["owned", "instagram", "facebook", "threads", "youtube", "youtube_comments", "google_business", "linkedin",
  "news", "web", "x", "reddit", "tiktok", "telegram", "app_store", "google_play"] as const;
export type Source = (typeof SOURCES)[number];
export const SENTIMENTS = ["positive", "neutral", "negative"] as const;
export type Sentiment = (typeof SENTIMENTS)[number];
export const INTENTS = ["question", "purchase", "complaint", "praise", "news", "other"] as const;
export type Intent = (typeof INTENTS)[number];
export const LANGUAGES = ["ar", "en", "fr", "de", "nl"] as const;
export type Severity = "urgent" | "high" | "normal" | "info";
export type EventKind = "crisis" | "spike" | "opportunity" | "competitor" | "influencer" | "rising";
export type EventState = "open" | "acted" | "dismissed";
export type Feedback = "useful" | "not_useful" | "wrong";
export type ActAction = "studio" | "planner" | "approval" | "inbox" | "dismiss";

export type RadarStatus = {
  enabled: boolean;
  x_enabled: boolean;
  queries_used: number;
  queries_limit: number | null;
  sources: { source: Source; in_plan: boolean; ready: boolean; paid: boolean; status: HealthStatus; access: Access; beta: boolean }[];
  queries: { id: number; name: string; active: boolean }[];
  x_price_per_post: number;
};

export type Competitor = { name: string; keywords: string[] };

export type Access = "owned" | "public" | "provider";
export type HealthStatus = "ready" | "needs_connection" | "needs_key" | "needs_permission" | "needs_setup" | "quota_exhausted"
  | "out_of_credits" | "not_in_plan" | "disabled" | "error";
export type HealthAction =
  | { kind: "connect"; platform: string }
  | { kind: "ask_admin"; what: string }
  | { kind: "request_permission"; permission: string; doc: string }
  | { kind: "edit_setup"; field: string }
  | { kind: "buy_credits" }
  | { kind: "upgrade" }
  | { kind: "test" };
export type Health = { status: HealthStatus; message: string; action: HealthAction | null; note?: string | null; at?: string };
export type SourceCost = { free: boolean; unit: string | null; unit_price: number; unit_cost?: number; per_1000: number; own_key: boolean };
export type SourceRow = {
  key: string;
  label: string;
  access: Access;
  beta: boolean;
  platform: string | null;
  permission: string | null;
  permission_doc: string | null;
  option: string | null;
  byo: boolean;
  available: boolean;
  terms_note: string | null;
  docs: string | null;
  health: Health;
  cost: SourceCost;
  usage: { units: number; cost: number; price: number; calls: number } | null;
  in_query: boolean;
  quota: { used: number; limit: number; per: "day" | "month" } | null;
};
export type Spend = { usd: number; by_source: Record<string, number>; cap_usd: number | null };
export type SourcesOut = {
  query_id: number | null;
  sources: SourceRow[];
  credits: { included: number | null; included_used: number; included_left: number | null; balance: number; available_usd: number | null };
  spend: Spend | null;
};
export type QueryOptions = { telegram_channels?: string[]; app_store_ids?: string[]; google_play_ids?: string[]; subreddits?: string[]; youtube_channel_ids?: string[] };

export type XUsage = { reads: number; cap: number; cost_usd: number; cap_cost_usd: number; capped: boolean };

export type ListeningQuery = {
  id: number;
  name: string;
  keywords: string[];
  required: string[];
  excluded: string[];
  languages: string[];
  countries: string[];
  competitors: Competitor[];
  sources: Source[];
  active: boolean;
  x_monthly_cap: number;
  last_collected_at: string | null;
  last_error: string | null;
  mentions: number;
  x_usage: XUsage;
  monthly_cap_usd: number | null;
  options: QueryOptions;
  spend: Spend;
};

export type QueryInput = Omit<ListeningQuery, "id" | "last_collected_at" | "last_error" | "mentions" | "x_usage" | "spend">;

export type Estimate = {
  expected_month: number | null;
  by_source: Record<string, number>;
  x: XUsage | null;
  x_cap_cost_usd: number;
  costs: Record<string, { unit: string; unit_price: number; own_key: boolean; expected_units: number; expected_usd: number; units_month?: number; usd_month?: number }>;
  spend: Spend | null;
  queries_used: number;
  queries_limit: number | null;
};

export type Word = { word: string; count: number; sentiment: Sentiment; positive: number; negative: number };

export type EventShort = {
  id: number;
  kind: EventKind;
  severity: Severity;
  state: EventState;
  title: string;
  what: string;
  started_at: string;
  brand: string | null;
};

export type Overview = {
  query_id: number;
  days: number;
  last_collected_at: string | null;
  kpis: {
    mentions: { value: number; delta: number | null };
    reach: { value: number; delta: number | null; measured: number; total: number; potential: number; estimated: boolean };
    net_sentiment: { value: number; change: number | null };
    share_of_voice: { value: number | null; change: number | null };
  };
  series: { date: string; count: number; event: EventKind | null }[];
  sentiment: Record<Sentiment, number>;
  sources: { source: string; count: number }[];
  words: Word[];
  events: EventShort[];
};

export type Mention = {
  id: number;
  source: Source;
  platform: string;
  url: string | null;
  author_name: string | null;
  author_handle: string | null;
  author_followers: number;
  text: string;
  lang: string | null;
  country: string | null;
  published_at: string;
  brand: string | null;
  reach: number | null;
  reach_estimated: number | null;
  engagement: number;
  sentiment: Sentiment | null;
  intent: Intent | null;
  topic: string | null;
  emotion: string | null;
  status: "new" | "reviewed" | "muted" | "converted" | "spam";
  corrected: boolean;
  conversation_id: number | null;
  can_inbox: boolean;
  spam_reason: string | null;
  also_on: string[];
  in_report: boolean;
  assigned_to_id: number | null;
  stars: number | null;
};

export type MentionCounts = { all: number; negative: number; purchase: number; influencers: number; unanswered: number; spam: number };
export type MentionPage = { items: Mention[]; total: number; counts: MentionCounts };

export type Voice = {
  words: Word[];
  phrases: { phrase: string; count: number; sentiment: Sentiment }[];
  hashtags: { tag: string; count: number; change: number | null }[];
  rising: { word: string; count: number; before: number; change: number | null; sentiment: Sentiment }[];
  top_positive: Mention | null;
  top_negative: Mention | null;
  total: number;
};

export type Breakdowns = {
  heatmap: number[][]; // 7 rows (Sunday first) × 12 two-hour slots
  emotions: { emotion: string; share: number }[];
  topics: { topic: string; count: number; net_sentiment: number }[];
  countries: { country: string; share: number }[];
  languages: { lang: string; share: number }[];
  intents: { intent: Intent; count: number }[];
};

export type Competitors = {
  brands: string[];
  weeks: { week_start: string; shares: number[]; counts: number[] }[];
  table: {
    brand: string;
    own: boolean;
    mentions: number;
    share_of_voice: number;
    net_sentiment: number;
    passion: number;
    top_topic: string | null;
    top_complaint: string | null;
  }[];
};

export type RadarEvent = EventShort & {
  query_id: number;
  topic: string | null;
  why: string;
  suggestion: string;
  draft: string | null;
  ai_written: boolean;
  feedback: Feedback | null;
  acted_action: ActAction | null;
  acted_ref: string | null;
  metrics: { count?: number; usual?: number; reach?: number; hourly?: number[]; [key: string]: unknown };
  evidence_count: number;
  evidence?: Mention[];
  links?: { inbox: string | null; ideas: string | null };
};

export type SearchResult = {
  q: string;
  total: number;
  sentiment: Record<Sentiment, number>;
  items: Mention[];
  news: (Partial<Mention> & { text: string; url?: string | null; sentiment?: Sentiment | null })[];
  intents: Record<Intent, number>;
  emotions: Record<string, number>;
};
