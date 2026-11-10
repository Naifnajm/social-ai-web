/** Types of the inbox API (see apps/api/app/modules/inbox/schemas.py). */
export type ConvState = "open" | "pending" | "done";
export type Kind = "dm" | "comment";
export type Channel = "dm" | "public" | "private";
export type BotMode = "off" | "suggest" | "auto";
export type Folder = "all" | "unassigned" | "mine" | "pending" | "done";
export const INTENTS = ["question", "order", "complaint", "lead", "praise", "spam", "other"] as const;
export const SENTIMENTS = ["positive", "neutral", "negative"] as const;
export type Intent = (typeof INTENTS)[number];
export type Sentiment = (typeof SENTIMENTS)[number];

export type UserRef = { id: number; name: string; avatar_url?: string | null };
export type Tag = { id: number; name: string; color: number };

export type ConversationRow = {
  id: number;
  account_id: number;
  account_name: string;
  platform: string;
  kind: Kind;
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
  tags: Tag[];
  has_suggestion: boolean;
  bot_paused: boolean;
  is_hidden: boolean;
};

export type FolderCounts = { all: number; unassigned: number; mine: number; pending: number; unread: number };
export type ConversationPage = { items: ConversationRow[]; next_cursor?: string | null; counts: FolderCounts };

export type Attachment = { id: number; filename: string; mimetype: string; url: string };
export type Message = {
  id: number;
  direction: "in" | "out";
  channel: Channel;
  author?: string | null;
  body: string;
  sent_at: string;
  is_bot: boolean;
  user?: UserRef | null;
  state: "received" | "suggested" | "sent" | "failed";
  error?: string | null;
  confidence: number;
  note?: string | null;
  hidden: boolean;
  trigger?: string | null;
  attachments: Attachment[];
};

export type Contact = { id: number; name: string; handle?: string | null; phone?: string | null; email?: string | null; note?: string | null; conversations: number };

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
  bot_mode: BotMode;
  can_private: boolean;
  can_hide: boolean;
  can_like: boolean;
  first_inbound_at?: string | null;
};

export type BotSettings = {
  mode: BotMode;
  comment_mode: BotMode;
  hide_offensive: boolean;
  private_reply: boolean;
  confidence: number;
  when: "always" | "office_hours" | "outside_hours";
  hour_from: number;
  hour_to: number;
  brand_kit_id?: number | null;
  instructions: string;
};

export type InboxAccount = {
  id: number;
  name: string;
  platform: string;
  username?: string | null;
  avatar_url?: string | null;
  state: string;
  inbox_enabled: boolean;
  bot: BotSettings;
  webhook_kind?: "meta" | "telegram" | "twilio" | null;
  webhook_url?: string | null;
  telegram_webhook_active: boolean;
  last_sync_at?: string | null;
  sync_error?: string | null;
  whatsapp_provider?: "cloud" | "twilio" | null;
  whatsapp_number?: string | null;
  has_token: boolean;
  open_conversations: number;
};

export type Canned = { id: number; name: string; body: string; shortcut?: string | null; sequence: number; active: boolean };
export type Knowledge = { id: number; title: string; content: string; sequence: number; active: boolean };
export type Trigger = {
  id: number;
  name: string;
  keywords: string;
  public_reply?: string | null;
  dm_text?: string | null;
  account_ids: number[];
  post_id?: number | null;
  active: boolean;
  sequence: number;
  hit_count: number;
};

export type InboxMeta = {
  accounts: InboxAccount[];
  platforms: string[];
  members: UserRef[];
  tags: Tag[];
  canned: Canned[];
  has_provider: boolean;
  user_id: number;
  can_reply: boolean;
  can_manage: boolean;
};

export type InboxSettings = {
  handover_message: string;
  private_ack: string;
  human_agent_tag: boolean;
  create_contacts: boolean;
  company_info: string;
  meta_webhook_url: string;
  platform_meta_app: boolean;
  meta_app_id?: string | null;
  has_meta_app_secret: boolean;
  meta_verify_token?: string | null;
};

export const INTENT_ICON: Record<string, string> = {
  question: "lightbulb", order: "shopping_cart", complaint: "flag", lead: "trending_up", praise: "favorite",
  spam: "block", other: "chat",
};

export const TAG_COLORS = ["#71717a", "#d92d20", "#dc6803", "#ca8504", "#1f7a3d", "#0e9384", "#1570ef", "#444ce7", "#7a5af8", "#c11574", "#e04f16", "#475467"];
