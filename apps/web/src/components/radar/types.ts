/** Types of the radar API (apps/api/app/modules/listening): setups, numbers, mentions and events. */

export const SOURCES = ["owned", "instagram", "facebook", "youtube", "google_business", "news", "x"] as const;
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
  sources: { source: Source; in_plan: boolean; ready: boolean; paid: boolean }[];
  queries: { id: number; name: string; active: boolean }[];
  x_price_per_post: number;
};

export type Competitor = { name: string; keywords: string[] };

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
};

export type QueryInput = Omit<ListeningQuery, "id" | "last_collected_at" | "last_error" | "mentions" | "x_usage">;

export type Estimate = {
  expected_month: number | null;
  by_source: Record<string, number>;
  x: XUsage | null;
  x_cap_cost_usd: number;
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
    reach: { value: number; delta: number | null };
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
  reach: number;
  engagement: number;
  sentiment: Sentiment | null;
  intent: Intent | null;
  topic: string | null;
  emotion: string | null;
  status: "new" | "reviewed" | "muted" | "converted";
  corrected: boolean;
  conversation_id: number | null;
  can_inbox: boolean;
};

export type MentionCounts = { all: number; negative: number; purchase: number; influencers: number; unanswered: number };
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
