/** Types of the brand templates API (`/api/templates/...`). */

export type TemplateFormat = "post_4x5" | "post_1x1" | "story_9x16" | "landscape_16x9";
export type PublishAs = "feed" | "story" | "feed_story";

export const FORMATS: { value: TemplateFormat; aspect: string; w: number; h: number }[] = [
  { value: "post_4x5", aspect: "4:5", w: 1080, h: 1350 },
  { value: "post_1x1", aspect: "1:1", w: 1080, h: 1080 },
  { value: "story_9x16", aspect: "9:16", w: 1080, h: 1920 },
  { value: "landscape_16x9", aspect: "16:9", w: 1920, h: 1080 },
];
export const formatInfo = (f: string) => FORMATS.find((x) => x.value === f) ?? FORMATS[0];
export const CATEGORIES = ["offers", "product", "event", "quote", "other"] as const;

export type Template = {
  id: number;
  name: string;
  sequence: number;
  active: boolean;
  set_id: number | null;
  set_name: string | null;
  brand_kit_id: number | null;
  category: string;
  format: TemplateFormat;
  aspect: string;
  width: number;
  height: number;
  frame_media_id: number | null;
  frame_has_window: boolean;
  background_color: string | null;
  box_x: number;
  box_y: number;
  box_w: number;
  box_h: number;
  photo_fit: "cover" | "contain";
  text_enabled: boolean;
  text_x: number;
  text_y: number;
  text_w: number;
  text_h: number;
  text_size: number;
  text_color: string;
  text_bg_color: string | null;
  text_align: "auto" | "left" | "center" | "right";
  text_bold: boolean;
  text_max_lines: number;
  text_default: string | null;
  logo_enabled: boolean;
  logo_position: "top_left" | "top_right" | "bottom_left" | "bottom_right";
  logo_size: number;
  preview_media_id: number | null;
  preview_url: string;
  usage_count: number;
};

/** Editable values (the editor's form). */
export type TemplateForm = Omit<Template, "id" | "set_name" | "aspect" | "width" | "height" | "frame_has_window" |
  "preview_media_id" | "preview_url" | "usage_count" | "sequence" | "active">;

export type TemplateSet = {
  id: number;
  name: string;
  sequence: number;
  active: boolean;
  category: string;
  brand_kit_id: number | null;
  post_template_id: number | null;
  story_template_id: number | null;
  templates: Template[];
  usage_count: number;
};

export type Detection = {
  box_x: number;
  box_y: number;
  box_w: number;
  box_h: number;
  frame_has_window: boolean;
  format: TemplateFormat;
  width: number;
  height: number;
};

export type MediaItem = { id: number; filename: string; mimetype: string; source?: string; url: string; thumb_url: string; width?: number | null; height?: number | null };

export type BrandKitBrief = { id: number; name: string; color_primary: string; logo_media_id: number | null; is_default: boolean };

export type ChoiceTemplate = {
  id: number;
  name: string;
  format: TemplateFormat;
  aspect: string;
  role: "post" | "story";
  text_enabled: boolean;
  text_default: string;
  preview_url: string;
};
export type Choice = { key: string; name: string; category: string; templates: ChoiceTemplate[]; usage: number };

export type QuickAccount = { id: number; name: string; platform: string; username: string | null; avatar_url: string | null; state: string; can_story: boolean };
export type QuickData = {
  choices: Choice[];
  accounts: QuickAccount[];
  recent: MediaItem[];
  story_platforms: string[];
  best_slots: { at: string; label: string }[];
  has_ai: boolean;
  ffmpeg: boolean;
  can_manage: boolean;
};

export type QuickPreview = {
  media_id: number;
  video: boolean;
  error: string | null;
  items: { role: "post" | "story"; template_id: number; aspect: string; src: string }[];
};

export type PostResult = {
  id: number;
  name: string;
  state: string;
  scheduled_at: string | null;
  results: { account_id: number; account: string; platform: string; state: string; url: string; error: string; story_state: string; story_error: string }[];
};

export type TelegramSettings = {
  publishers: string[];
  mode: "draft" | "publish" | "best_time";
  publish_as: PublishAs;
  default_set_id: number | null;
  account_ids: number[];
  ai_caption: boolean;
};
