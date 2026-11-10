"use client";
/** Settings › Brand templates: template sets (post + story), loose templates, and publishing from Telegram. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import {
  type BrandKitBrief, CATEGORIES, type QuickData, type Template, type TelegramSettings, type TemplateSet,
} from "@/components/templates/types";
import { Badge, Button, Card, EmptyState, Field, IconButton, Input, Modal, SectionTitle, Segmented, Select, Spinner, Switch, cx, toast } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";

const onError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : String(err));

export default function BrandTemplatesSettingsPage() {
  const t = useTranslations("templates");
  const can = useSession((s) => s.can);
  const canEdit = can("editor");
  const qc = useQueryClient();
  const sets = useQuery({ queryKey: ["template-sets"], queryFn: () => api.get<TemplateSet[]>("/templates/sets") });
  const loose = useQuery({ queryKey: ["templates", "loose"], queryFn: async () => (await api.get<Template[]>("/templates")).filter((x) => !x.set_id) });
  const kits = useQuery({ queryKey: ["template-brand-kits"], queryFn: () => api.get<BrandKitBrief[]>("/templates/brand-kits") });
  const [editing, setEditing] = useState<Partial<TemplateSet> | null>(null);
  const [deleting, setDeleting] = useState<TemplateSet | null>(null);

  const saveSet = useMutation({
    mutationFn: (s: Partial<TemplateSet>) => {
      const body = { name: s.name?.trim(), category: s.category, brand_kit_id: s.brand_kit_id ?? null };
      return s.id ? api.patch(`/templates/sets/${s.id}`, body) : api.post("/templates/sets", body);
    },
    onSuccess: () => {
      setEditing(null);
      toast.success(t("saved"));
      qc.invalidateQueries({ queryKey: ["template-sets"] });
    },
    onError,
  });
  const deleteSet = useMutation({
    mutationFn: ({ id, all }: { id: number; all: boolean }) => api.delete(`/templates/sets/${id}${all ? "?delete_templates=true" : ""}`),
    onSuccess: () => {
      setDeleting(null);
      qc.invalidateQueries({ queryKey: ["template-sets"] });
      qc.invalidateQueries({ queryKey: ["templates"] });
    },
    onError,
  });

  const loading = sets.isLoading || loose.isLoading;
  const empty = !loading && !sets.data?.length && !loose.data?.length;

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <SectionTitle icon="photo_frame" actions={canEdit && !empty && (
          <>
            <Button size="sm" icon="add" onClick={() => setEditing({ name: "", category: "offers" })}>{t("newSet")}</Button>
            <Link href="/templates/new"><Button size="sm" variant="primary" icon="add">{t("newTemplate")}</Button></Link>
          </>
        )}>
          {t("title")}
        </SectionTitle>
        <p className="-mt-1 mb-4 text-sm text-muted">{t("subtitle")}</p>

        {loading && <div className="flex justify-center py-10"><Spinner /></div>}
        {empty && (
          <EmptyState icon="photo_frame" title={t("emptyTitle")} text={t("emptyText")}
            action={canEdit && (
              <div className="flex flex-wrap justify-center gap-2">
                <Button variant="primary" icon="add" onClick={() => setEditing({ name: "", category: "offers" })}>{t("newSet")}</Button>
                <Link href="/templates/new"><Button icon="photo_frame">{t("newTemplate")}</Button></Link>
              </div>
            )} />
        )}

        <div className="flex flex-col gap-3">
          {sets.data?.map((s) => (
            <div key={s.id} className="rounded-2xl border border-line bg-white/45 p-3 sm:p-4">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <span className="bidi truncate text-[15px] font-semibold">{s.name}</span>
                <Badge>{t(`categories.${s.category}`)}</Badge>
                {!s.active && <Badge tone="warn">{t("inactive")}</Badge>}
                <span className="text-xs text-muted">{t("usedTimes", { count: s.usage_count })}</span>
                {canEdit && (
                  <div className="ms-auto flex items-center">
                    <IconButton icon="edit_square" label={t("editSet")} onClick={() => setEditing(s)} />
                    <IconButton icon="delete" label={t("delete")} onClick={() => setDeleting(s)} />
                  </div>
                )}
              </div>
              <div className="flex gap-3 overflow-x-auto pb-1">
                {s.templates.map((tpl) => <TemplateThumb key={tpl.id} tpl={tpl} />)}
                {canEdit && !s.story_template_id && <AddThumb href={`/templates/new?set=${s.id}&format=story_9x16`} label={t("addStory")} story />}
                {canEdit && !s.post_template_id && <AddThumb href={`/templates/new?set=${s.id}&format=post_4x5`} label={t("addPost")} />}
                {canEdit && s.post_template_id && s.story_template_id && <AddThumb href={`/templates/new?set=${s.id}`} label={t("addFormat")} />}
              </div>
            </div>
          ))}
          {!!loose.data?.length && (
            <div className="rounded-2xl border border-line bg-white/45 p-3 sm:p-4">
              <div className="mb-3 text-[15px] font-semibold">{t("withoutSet")}</div>
              <div className="flex gap-3 overflow-x-auto pb-1">
                {loose.data.map((tpl) => <TemplateThumb key={tpl.id} tpl={tpl} />)}
              </div>
            </div>
          )}
        </div>
      </Card>

      <Card className="text-sm text-muted">
        <SectionTitle icon="lightbulb">{t("howTitle")}</SectionTitle>
        <ol className="grid gap-1.5 ps-5 [list-style:decimal]">
          <li>{t("how1")}</li>
          <li>{t("how2")}</li>
          <li>{t("how3")}</li>
        </ol>
      </Card>

      {can("admin") && <TelegramCard sets={sets.data ?? []} />}

      <Modal open={!!editing} onClose={() => setEditing(null)} title={editing?.id ? t("editSet") : t("newSet")}
        footer={<><Button onClick={() => setEditing(null)}>{t("cancel")}</Button>
          <Button variant="primary" loading={saveSet.isPending} disabled={!editing?.name?.trim()} onClick={() => editing && saveSet.mutate(editing)}>{t("save")}</Button></>}>
        {editing && (
          <div className="flex flex-col gap-4">
            <Field label={t("setName")} hint={t("setNameHint")}>
              <Input autoFocus value={editing.name ?? ""} onChange={(e) => setEditing({ ...editing, name: e.target.value })} className="bidi" maxLength={120} />
            </Field>
            <Field label={t("category")}>
              <Select value={editing.category ?? "other"} onChange={(e) => setEditing({ ...editing, category: e.target.value })}>
                {CATEGORIES.map((c) => <option key={c} value={c}>{t(`categories.${c}`)}</option>)}
              </Select>
            </Field>
            <Field label={t("editor.brandKit")} hint={t("setKitHint")}>
              <Select value={editing.brand_kit_id ?? ""} onChange={(e) => setEditing({ ...editing, brand_kit_id: e.target.value ? Number(e.target.value) : null })}>
                <option value="">{t("editor.defaultKit")}</option>
                {kits.data?.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
              </Select>
            </Field>
          </div>
        )}
      </Modal>

      <Modal open={!!deleting} onClose={() => setDeleting(null)} title={t("deleteSetTitle")} size="sm"
        footer={<>
          <Button onClick={() => deleting && deleteSet.mutate({ id: deleting.id, all: false })}>{t("deleteSetKeep")}</Button>
          <Button variant="danger" loading={deleteSet.isPending} onClick={() => deleting && deleteSet.mutate({ id: deleting.id, all: true })}>{t("deleteSetAll")}</Button>
        </>}>
        <p className="text-sm text-text-2">{t("deleteSetText", { name: deleting?.name ?? "" })}</p>
      </Modal>
    </div>
  );
}

function TemplateThumb({ tpl }: { tpl: Template }) {
  const t = useTranslations("templates");
  const story = tpl.format === "story_9x16";
  return (
    <Link href={`/templates/${tpl.id}`} className="group flex w-[120px] shrink-0 flex-col gap-1.5 sm:w-[136px]">
      <span className="flex h-[170px] items-end justify-center rounded-xl bg-fill p-1.5 transition group-hover:bg-fill-2">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={tpl.preview_url} alt="" loading="lazy" className={cx("max-h-full rounded-lg object-contain shadow-[0_8px_20px_-10px_rgba(0,0,0,.5)]", story ? "h-full" : "w-full")} />
      </span>
      <span className="bidi truncate text-[13px] font-medium">{tpl.name}</span>
      <span className="flex items-center gap-1 text-[11px] text-muted">
        <Badge className="!px-1.5" ><span dir="ltr">{tpl.aspect}</span></Badge>
        {story ? t("story") : t("post")}
        {!tpl.frame_media_id && <Icon name="warning" size={12} className="ms-auto text-warn" />}
      </span>
    </Link>
  );
}

function AddThumb({ href, label, story }: { href: string; label: string; story?: boolean }) {
  return (
    <Link href={href} className="flex w-[120px] shrink-0 flex-col gap-1.5 sm:w-[136px]">
      <span className="flex h-[170px] flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-black/15 text-muted transition hover:bg-fill">
        <span className={cx("flex items-center justify-center rounded-lg border-2 border-dashed border-black/15", story ? "h-16 w-9" : "h-12 w-10")}>
          <Icon name="add" size={18} />
        </span>
        <span className="px-2 text-center text-xs font-medium">{label}</span>
      </span>
    </Link>
  );
}

function TelegramCard({ sets }: { sets: TemplateSet[] }) {
  const t = useTranslations("templates");
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["templates-telegram"], queryFn: () => api.get<TelegramSettings>("/templates/telegram-settings") });
  const quick = useQuery({ queryKey: ["quick-data"], queryFn: () => api.get<QuickData>("/templates/quick") });
  const [form, setForm] = useState<TelegramSettings | null>(null);
  const [publishers, setPublishers] = useState("");
  if (settings.data && !form) {
    setForm(settings.data);
    setPublishers(settings.data.publishers.join(", "));
  }
  const save = useMutation({
    mutationFn: () => api.put<TelegramSettings>("/templates/telegram-settings", {
      ...form, publishers: publishers.split(/[,\s;]+/).filter(Boolean),
    }),
    onSuccess: (data) => {
      setForm(data);
      setPublishers(data.publishers.join(", "));
      qc.setQueryData(["templates-telegram"], data);
      toast.success(t("saved"));
    },
    onError,
  });
  const accounts = (quick.data?.accounts ?? []).filter((a) => a.platform !== "telegram");
  const hasBot = (quick.data?.accounts ?? []).some((a) => a.platform === "telegram");

  return (
    <Card>
      <SectionTitle icon="send">{t("telegram.title")}</SectionTitle>
      <p className="-mt-1 mb-4 text-sm text-muted">{t("telegram.subtitle")}</p>
      {!form ? <div className="flex justify-center py-6"><Spinner /></div> : (
        <div className="flex flex-col gap-4">
          {!hasBot && quick.data && (
            <p className="flex items-start gap-1.5 rounded-xl bg-warn-bg px-3 py-2 text-xs text-warn"><Icon name="info" size={14} className="mt-0.5" />{t("telegram.noBot")}</p>
          )}
          <Field label={t("telegram.publishers")} hint={t("telegram.publishersHint")}>
            <Input dir="ltr" value={publishers} onChange={(e) => setPublishers(e.target.value)} placeholder="@sara, 123456789" />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("telegram.mode")}>
              <Segmented value={form.mode} onChange={(v) => setForm({ ...form, mode: v })} size="sm" className="self-start"
                options={[{ value: "draft", label: t("telegram.modeDraft") }, { value: "publish", label: t("telegram.modePublish") }, { value: "best_time", label: t("telegram.modeBest") }]} />
            </Field>
            <Field label={t("telegram.publishAs")}>
              <Segmented value={form.publish_as} onChange={(v) => setForm({ ...form, publish_as: v })} size="sm" className="self-start"
                options={[{ value: "feed", label: t("post") }, { value: "story", label: t("story") }, { value: "feed_story", label: t("both") }]} />
            </Field>
          </div>
          <Field label={t("telegram.defaultSet")} hint={t("telegram.defaultSetHint")}>
            <Select value={form.default_set_id ?? ""} onChange={(e) => setForm({ ...form, default_set_id: e.target.value ? Number(e.target.value) : null })}>
              <option value="">{t("telegram.noDefault")}</option>
              {sets.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          </Field>
          <Field label={t("telegram.accounts")} hint={t("telegram.accountsHint")}>
            <div className="flex flex-wrap gap-2">
              {accounts.map((a) => {
                const on = form.account_ids.includes(a.id);
                return (
                  <button key={a.id} type="button" onClick={() => setForm({ ...form, account_ids: on ? form.account_ids.filter((x) => x !== a.id) : [...form.account_ids, a.id] })}
                    className={cx("flex h-9 items-center gap-2 rounded-full border ps-1 pe-3 text-sm transition", on ? "border-ink bg-ink text-white" : "border-line bg-white/60 hover:bg-white")}>
                    <PlatformBadge platform={a.platform} size={26} />
                    <span className="max-w-[140px] truncate">{a.name}</span>
                  </button>
                );
              })}
              {!accounts.length && <span className="text-xs text-muted">{t("noAccounts")}</span>}
            </div>
          </Field>
          <Switch checked={form.ai_caption} onChange={(v) => setForm({ ...form, ai_caption: v })} label={t("telegram.aiCaption")} />
          <div className="rounded-2xl bg-fill p-3 text-xs leading-relaxed text-text-2">
            <div className="mb-1 font-semibold text-text">{t("telegram.examples")}</div>
            {t("telegram.examplesText").split("\n").map((line) => (
              <code key={line} dir="auto" className="block font-sans">{line}</code>
            ))}
          </div>
          <div className="flex justify-end">
            <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>{t("save")}</Button>
          </div>
        </div>
      )}
    </Card>
  );
}
