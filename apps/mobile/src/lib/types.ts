/** Response types of the platform API (see /api/openapi.json). Only the fields the app uses. */

export type Role = 'viewer' | 'editor' | 'approver' | 'admin' | 'owner';

export type Me = {
  user: { id: number; email: string; name: string; locale: string; timezone: string; avatar_url?: string | null };
  workspaces: { workspace_id: number; workspace_name: string; role: Role }[];
  current_workspace_id: number | null;
};

export type SessionOut = { access_token: string; refresh_token: string; me: Me };

export type Workspace = {
  id: number;
  name: string;
  slug: string;
  locale: string;
  timezone: string;
  currency: string;
  plan_code: string;
  status: string;
};

export type UserRef = { id: number; name: string; avatar_url?: string | null };
export type Tag = { id: number; name: string; color?: number };

export type Intent = 'question' | 'order' | 'complaint' | 'lead' | 'praise' | 'spam' | 'other';
export type Sentiment = 'positive' | 'neutral' | 'negative';
export type ConvState = 'open' | 'pending' | 'done';

export type ConversationRow = {
  id: number;
  account_id: number;
  account_name: string;
  platform: string;
  kind: 'dm' | 'comment';
  name: string;
  handle?: string | null;
  avatar_url?: string | null;
  snippet?: string | null;
  last_message_at?: string | null;
  unread: boolean;
  state: ConvState;
  intent?: Intent | null;
  sentiment?: Sentiment | null;
  assignee?: UserRef | null;
  tags?: Tag[];
  has_suggestion?: boolean;
  bot_paused?: boolean;
  is_hidden?: boolean;
};

export type FolderCounts = { all?: number; unassigned?: number; mine?: number; pending?: number; unread?: number };
export type ConversationPage = { items: ConversationRow[]; next_cursor?: string | null; counts: FolderCounts };

export type Attachment = { id: number; filename: string; mimetype: string; url: string };
export type Message = {
  id: number;
  direction: 'in' | 'out';
  channel: 'dm' | 'public' | 'private';
  author?: string | null;
  body: string;
  sent_at: string;
  is_bot: boolean;
  user?: UserRef | null;
  state: 'received' | 'suggested' | 'sent' | 'failed';
  error?: string | null;
  confidence?: number;
  note?: string | null;
  hidden?: boolean;
  trigger?: string | null;
  attachments?: Attachment[];
};

export type Contact = {
  id: number;
  name: string;
  handle?: string | null;
  phone?: string | null;
  email?: string | null;
  note?: string | null;
  conversations?: number;
};

export type Thread = ConversationRow & {
  external_user_id?: string | null;
  messages: Message[];
  suggestion?: Message | null;
  contact?: Contact | null;
  post?: { url?: string | null; preview?: string | null; post_id?: number | null } | null;
  note?: string | null;
  handover_reason?: string | null;
  bot_error?: string | null;
  window: { limited: boolean; open: boolean; hours_left: number; human_agent: boolean };
  bot_mode: 'off' | 'suggest' | 'auto';
  can_private: boolean;
  can_hide: boolean;
  can_like: boolean;
};

export type Canned = { id: number; name: string; body: string; shortcut?: string | null; active?: boolean };

export type InboxMeta = {
  accounts: { id: number; name: string; platform: string }[];
  platforms: string[];
  members: UserRef[];
  tags: Tag[];
  canned: Canned[];
  has_provider: boolean;
  user_id: number;
  can_reply: boolean;
  can_manage: boolean;
};

export type InboxStats = {
  days: number;
  conversations: number;
  open: number;
  pending: number;
  done: number;
  unread: number;
  received: number;
  replies: number;
  bot_replies: number;
  bot_share: number;
  avg_first_response_minutes: number;
  sentiment: Record<string, number>;
  intents: Record<string, number>;
  by_platform: { platform: string; conversations: number; dm: number; comment: number; pending: number }[];
};

export type MediaItem = {
  id: number;
  filename: string;
  mimetype: string;
  size: number;
  width?: number | null;
  height?: number | null;
  url?: string;
  thumb_url?: string;
};

export type Account = {
  id: number;
  name: string;
  platform: string;
  platform_label: string;
  username?: string | null;
  avatar_url?: string | null;
  state: string;
  last_error?: string | null;
  followers?: number;
  active?: boolean;
  inbox_only?: boolean;
  can_publish?: boolean;
};

export type TargetOut = {
  id: number;
  account_id: number;
  account_name?: string;
  platform: string;
  state: string;
  external_url?: string | null;
  error?: string | null;
  published_at?: string | null;
  story_state?: string | null;
  story_error?: string | null;
  impressions?: number;
  likes?: number;
  comments?: number;
  shares?: number;
  engagements?: number;
};

export type Post = {
  id: number;
  name?: string | null;
  content?: string;
  state: string;
  publish_as: string;
  scheduled_at?: string | null;
  published_at?: string | null;
  planned_date?: string | null;
  created_at: string;
  author_name?: string | null;
  accounts?: { id: number; name: string; platform: string; avatar_url?: string | null }[];
  account_ids?: number[];
  platforms?: string[];
  media?: MediaItem[];
  story_media?: MediaItem[];
  requested_action?: string | null;
  approval_requested_by_name?: string | null;
  approval_requested_at?: string | null;
  approval_note?: string | null;
  targets?: TargetOut[];
  can_edit?: boolean;
  can_retry?: boolean;
};

export type PlannerPost = {
  id: number;
  name: string;
  preview: string;
  state: string;
  day?: string | null;
  time?: string | null;
  scheduled_at?: string | null;
  published_at?: string | null;
  platforms: string[];
  account_ids: number[];
  media?: { id: number; kind: string; url: string } | null;
  media_count?: number;
  campaign?: { id: number; name: string; color: string } | null;
  pillar?: { id: number; name: string; color: string } | null;
  author?: string;
};

export type PlannerOut = {
  start: string;
  end: string;
  today: string;
  timezone: string;
  posts: PlannerPost[];
  unplanned: PlannerPost[];
};

export type Tip = { level: 'danger' | 'warning' | 'success' | 'info'; icon: string; title: string; text: string };
export type Dashboard = {
  period: { days: number; start: string; end: string };
  has_metrics: boolean;
  kpis: Record<string, number>;
  deltas: Record<string, number | null>;
  series: { date: string; posts: number; impressions: number; engagements: number }[];
  breakdown: { platform: string; label: string; posts: number; impressions: number; engagements: number; engagement_rate: number; followers: number }[];
  best_slots: { weekday: number; hour: number; score: number }[];
  best_source: 'own' | 'benchmark';
  top_posts: { id: number; name: string; platform: string; account: string; url: string; date: string; impressions: number; engagements: number; engagement_rate: number }[];
  accounts: { id: number; name: string; platform: string; followers: number; state: string; avatar_url: string }[];
  tips: Tip[];
  last_sync?: string | null;
};

export type NotificationItem = {
  id: number;
  kind: string;
  title: string;
  body?: string | null;
  link?: string | null;
  read_at?: string | null;
  created_at: string;
};

export type TemplateBrief = { id: number; name: string; format: string; aspect: string; role: 'post' | 'story'; text_enabled: boolean; text_default: string; preview_url: string };
export type Choice = { key: string; name: string; category: string; templates: TemplateBrief[]; usage: number };
export type QuickAccount = { id: number; name: string; platform: string; username: string | null; avatar_url: string | null; state: string; can_story: boolean };
export type QuickData = {
  choices: Choice[];
  accounts: QuickAccount[];
  recent: MediaItem[];
  story_platforms: string[];
  best_slots: { at: string; label: string }[];
  has_ai: boolean;
  can_manage: boolean;
};
export type QuickPreview = { media_id: number; video: boolean; error: string | null; items: { role: 'post' | 'story'; template_id: number; aspect: string; src: string }[] };
export type PostResult = {
  id: number;
  name: string;
  state: string;
  scheduled_at: string | null;
  results: { account_id: number; account: string; platform: string; state: string; url: string; error: string; story_state: string; story_error: string }[];
};

export type StudioOut = {
  accounts: Account[];
  story_platforms: string[];
  needs_approval: boolean;
  is_approver: boolean;
  timezone: string;
  kpis: { published: number; scheduled: number; failed: number; to_approve: number; accounts: number };
};

export type BestSlot = { at: string; local: string; label: string; score?: number };
