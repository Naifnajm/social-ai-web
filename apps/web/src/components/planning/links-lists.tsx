"use client";
/** Links & sales › Links (tracked short links) and Conversions (orders, leads) lists. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import { Badge, Button, Card, EmptyState, Field, IconButton, Input, Modal, Select, Spinner, Textarea, toast } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Campaign, Conversion, TrackedLink } from "./types";
import { CopyField, onError, useFormat } from "./ui";

const SOURCES = ["instagram", "facebook", "tiktok", "x", "linkedin", "threads", "telegram", "bio", "whatsapp", "qr"];

export function LinksTab() {
  const t = useTranslations("links");
  const fmt = useFormat();
  const qc = useQueryClient();
  const canEdit = useSession((s) => s.can("editor"));
  const currency = useSession((s) => s.workspace?.currency || "SAR");
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [creating, setCreating] = useState(false);
  const { data, isLoading } = useQuery({ queryKey: ["links", q, kind], queryFn: () => api.get<TrackedLink[]>("/links", { q, kind }) });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/links/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["links"] }),
    onError,
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 sm:max-w-xs">
          <Icon name="search" size={16} className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-faint" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("searchLinks")} className="ps-9" />
        </div>
        <Select className="!w-auto" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">{t("allLinks")}</option>
          <option value="post">{t("postLinks")}</option>
          <option value="manual">{t("manualLinks")}</option>
        </Select>
        {canEdit && <Button variant="primary" icon="add" className="ms-auto" onClick={() => setCreating(true)}>{t("newLink")}</Button>}
      </div>
      {isLoading ? <div className="flex justify-center py-12"><Spinner /></div> : !data?.length ? (
        <Card><EmptyState icon="link" title={t("noLinks")} text={t("noLinksText")} /></Card>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {data.map((link) => (
            <Card key={link.id} className="!p-4">
              <div className="flex items-start gap-3">
                {link.platform ? <PlatformBadge platform={link.platform} size={32} /> : <span className="flex h-8 w-8 items-center justify-center rounded-[10px] bg-ink text-white"><Icon name="link" size={16} /></span>}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-[13.5px] font-semibold bidi">{link.label || link.post_name || link.utm_campaign}</span>
                    {link.kind === "manual" && <Badge>{t("manual")}</Badge>}
                  </div>
                  <a href={link.url} target="_blank" rel="noreferrer" dir="ltr" className="block truncate text-[12px] text-muted hover:underline">{link.url}</a>
                </div>
                <div className="text-end">
                  <div className="text-[18px] font-bold">{fmt.number(link.clicks)}</div>
                  <div className="text-[10.5px] text-muted">{t("clicks")}</div>
                </div>
              </div>
              <div className="mt-3"><CopyField value={link.short_url} /></div>
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-muted">
                {link.post_id && <Link href={`/planner?post=${link.post_id}`} className="inline-flex items-center gap-1 hover:text-text"><Icon name="send" size={12} />{link.post_name || t("untitled")}</Link>}
                {link.campaign_name && <Link href={`/campaigns/${link.campaign_id}`} className="inline-flex items-center gap-1 hover:text-text"><Icon name="campaign" size={12} />{link.campaign_name}</Link>}
                <span dir="ltr">utm_source={link.utm_source}</span>
                {link.conversions > 0 && <span className="font-semibold text-text">{t("conversionsShort", { count: link.conversions })} · {fmt.money(link.revenue, currency)}</span>}
                {canEdit && link.kind === "manual" && (
                  <IconButton icon="delete" label={t("delete")} className="ms-auto !h-7 !w-7" onClick={() => window.confirm(t("confirmDeleteLink")) && remove.mutate(link.id)} />
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
      {creating && <NewLinkModal onClose={() => setCreating(false)} />}
    </div>
  );
}

function NewLinkModal({ onClose }: { onClose: () => void }) {
  const t = useTranslations("links");
  const qc = useQueryClient();
  const campaigns = useQuery({ queryKey: ["campaigns", false], queryFn: () => api.get<Campaign[]>("/campaigns") });
  const [form, setForm] = useState({ url: "", label: "", utm_source: "instagram", campaign_id: "" });
  const [created, setCreated] = useState<TrackedLink | null>(null);
  const save = useMutation({
    mutationFn: () => api.post<TrackedLink>("/links", { ...form, campaign_id: form.campaign_id ? Number(form.campaign_id) : null }),
    onSuccess: (link) => { setCreated(link); qc.invalidateQueries({ queryKey: ["links"] }); },
    onError,
  });
  return (
    <Modal open onClose={onClose} title={t("newLink")}
      footer={created ? <Button variant="primary" onClick={onClose}>{t("done")}</Button> : <>
        <Button onClick={onClose}>{t("cancel")}</Button>
        <Button variant="primary" disabled={!form.url.trim()} loading={save.isPending} onClick={() => save.mutate()}>{t("create")}</Button>
      </>}>
      {created ? (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-text-2">{t("linkReady")}</p>
          <CopyField value={created.short_url} />
          <p className="text-[12px] text-muted">{t("destination")}: <span dir="ltr" className="break-all">{created.destination}</span></p>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <Field label={t("url")}><Input dir="ltr" type="url" placeholder="https://" value={form.url} autoFocus onChange={(e) => setForm({ ...form, url: e.target.value })} /></Field>
          <Field label={t("label")} hint={t("labelHint")}><Input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} /></Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("place")}>
              <Select value={form.utm_source} onChange={(e) => setForm({ ...form, utm_source: e.target.value })}>
                {SOURCES.map((s) => <option key={s} value={s}>{t.has(`places.${s}`) ? t(`places.${s}`) : s}</option>)}
              </Select>
            </Field>
            <Field label={t("campaign")}>
              <Select value={form.campaign_id} onChange={(e) => setForm({ ...form, campaign_id: e.target.value })}>
                <option value="">{t("none")}</option>
                {campaigns.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            </Field>
          </div>
        </div>
      )}
    </Modal>
  );
}

export function ConversionsTab({ onSetup }: { onSetup: () => void }) {
  const t = useTranslations("links");
  const fmt = useFormat();
  const qc = useQueryClient();
  const { can } = useSession();
  const [kind, setKind] = useState("");
  const [adding, setAdding] = useState(false);
  const { data, isLoading } = useQuery({ queryKey: ["conversions", kind], queryFn: () => api.get<Conversion[]>("/links/conversions", { kind, days: 365 }) });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/links/conversions/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["conversions"] }); qc.invalidateQueries({ queryKey: ["links-summary"] }); },
    onError,
  });
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select className="!w-auto" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">{t("allKinds")}</option>
          {["order", "lead", "signup", "other"].map((k) => <option key={k} value={k}>{t(`kinds.${k}`)}</option>)}
        </Select>
        <Button variant="ghost" icon="settings" onClick={onSetup}>{t("howToTrack")}</Button>
        {can("editor") && <Button variant="primary" icon="add" className="ms-auto" onClick={() => setAdding(true)}>{t("addConversion")}</Button>}
      </div>
      {isLoading ? <div className="flex justify-center py-12"><Spinner /></div> : !data?.length ? (
        <Card><EmptyState icon="shopping_cart" title={t("noConversions")} text={t("noConversionsText")}
          action={<Button variant="primary" icon="settings" onClick={onSetup}>{t("setupTracking")}</Button>} /></Card>
      ) : (
        <Card padded={false} className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-[13px]">
            <thead>
              <tr className="border-b border-line text-[12px] text-muted">
                <th className="px-4 py-3 text-start font-medium">{t("date")}</th>
                <th className="px-3 py-3 text-start font-medium">{t("kind")}</th>
                <th className="px-3 py-3 text-start font-medium">{t("from")}</th>
                <th className="px-3 py-3 text-start font-medium">{t("reference")}</th>
                <th className="px-3 py-3 text-end font-medium">{t("value")}</th>
                <th className="w-10" />
              </tr>
            </thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.id} className="border-b border-line last:border-0">
                  <td className="px-4 py-2.5 text-text-2">{fmt.dateTime(c.occurred_at)}</td>
                  <td className="px-3 py-2.5"><Badge tone={c.kind === "order" ? "ink" : "neutral"}>{t(`kinds.${c.kind}`)}</Badge></td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      {c.platform && <PlatformBadge platform={c.platform} size={20} />}
                      <span className="min-w-0 truncate bidi">{c.post_name || c.campaign_name || c.utm_campaign || (c.platform ? "" : t("unattributed"))}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-muted" dir="ltr">{c.external_id || "—"}</td>
                  <td className="px-3 py-2.5 text-end font-semibold bidi">{c.value ? fmt.money(c.value, c.currency || "") : "—"}</td>
                  <td className="px-2">{can("admin") && <IconButton icon="delete" label={t("delete")} className="!h-8 !w-8" onClick={() => window.confirm(t("confirmDeleteConversion")) && remove.mutate(c.id)} />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {adding && <ConversionModal onClose={() => setAdding(false)} />}
    </div>
  );
}

function ConversionModal({ onClose }: { onClose: () => void }) {
  const t = useTranslations("links");
  const qc = useQueryClient();
  const currency = useSession((s) => s.workspace?.currency || "SAR");
  const campaigns = useQuery({ queryKey: ["campaigns", false], queryFn: () => api.get<Campaign[]>("/campaigns") });
  const [form, setForm] = useState({ kind: "order", value: "", currency, external_id: "", utm_source: "instagram", utm_campaign: "", code: "", note: "" });
  const save = useMutation({
    mutationFn: () => api.post("/links/conversions", {
      kind: form.kind, value: Number(form.value || 0), currency: form.currency || null, external_id: form.external_id || null,
      code: form.code || null, utm_source: form.code ? null : form.utm_source, utm_medium: form.code ? null : "social",
      utm_campaign: form.utm_campaign || null, note: form.note || null,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["conversions"] });
      qc.invalidateQueries({ queryKey: ["links-summary"] });
      toast.success(t("conversionAdded"));
      onClose();
    },
    onError,
  });
  return (
    <Modal open onClose={onClose} title={t("addConversion")}
      footer={<><Button onClick={onClose}>{t("cancel")}</Button><Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>{t("save")}</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("kind")}>
          <Select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            {["order", "lead", "signup", "other"].map((k) => <option key={k} value={k}>{t(`kinds.${k}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("value")}>
          <div className="flex gap-2">
            <Input type="number" min={0} dir="ltr" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
            <Input dir="ltr" maxLength={3} className="!w-20 uppercase" value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })} />
          </div>
        </Field>
        <Field label={t("reference")} hint={t("referenceHint")}><Input dir="ltr" value={form.external_id} onChange={(e) => setForm({ ...form, external_id: e.target.value })} /></Field>
        <Field label={t("place")}>
          <Select value={form.utm_source} onChange={(e) => setForm({ ...form, utm_source: e.target.value })}>
            {SOURCES.map((s) => <option key={s} value={s}>{t.has(`places.${s}`) ? t(`places.${s}`) : s}</option>)}
          </Select>
        </Field>
        <Field label={t("campaign")} className="sm:col-span-2">
          <Select value={form.utm_campaign} onChange={(e) => setForm({ ...form, utm_campaign: e.target.value })}>
            <option value="">{t("none")}</option>
            {campaigns.data?.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
          </Select>
        </Field>
        <Field label={t("note")} className="sm:col-span-2"><Textarea rows={2} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></Field>
      </div>
    </Modal>
  );
}
