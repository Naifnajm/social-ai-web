"use client";
/** Links & sales › Products: a light catalogue and "announce new product" (post with brand design + AI caption). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { Icon, PlatformBadge } from "@/components/icon";
import { Badge, Button, Card, EmptyState, Field, IconButton, Input, Modal, SectionTitle, Select, Spinner, Switch, Textarea, cx, toast } from "@/components/ui";
import { Link, useRouter } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Account, Campaign, Product, ProductSettings } from "./types";
import { StateBadge, onError } from "./ui";

export function ProductsTab() {
  const t = useTranslations("links");
  const qc = useQueryClient();
  const router = useRouter();
  const { can } = useSession();
  const [editing, setEditing] = useState<Product | "new" | null>(null);
  const { data, isLoading } = useQuery({ queryKey: ["products"], queryFn: () => api.get<Product[]>("/products") });
  const announce = useMutation({
    mutationFn: ({ id, force }: { id: number; force?: boolean }) => api.post<{ post_id: number; studio_url: string; state: string }>(`/products/${id}/announce`, { force }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["products"] });
      toast.success(t("products.announced"));
      router.push(r.studio_url);
    },
    onError,
  });

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <p className="flex-1 text-[13px] text-muted">{t("products.intro")}</p>
          {can("editor") && <Button variant="primary" icon="add" onClick={() => setEditing("new")}>{t("products.add")}</Button>}
        </div>
        {isLoading ? <div className="flex justify-center py-12"><Spinner /></div> : !data?.length ? (
          <Card><EmptyState icon="storefront" title={t("products.emptyTitle")} text={t("products.emptyText")}
            action={can("editor") && <Button variant="primary" icon="add" onClick={() => setEditing("new")}>{t("products.add")}</Button>} /></Card>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 2xl:grid-cols-3">
            {data.map((p) => (
              <Card key={p.id} padded={false} className={cx("overflow-hidden", !p.active && "opacity-60")}>
                <button type="button" className="block aspect-[4/3] w-full overflow-hidden bg-fill-2" onClick={() => setEditing(p)}>
                  {p.image_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={p.image_url} alt="" className="h-full w-full object-cover" />
                  ) : <span className="flex h-full items-center justify-center text-faint"><Icon name="storefront" size={36} /></span>}
                </button>
                <div className="p-3.5">
                  <div className="flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-semibold bidi">{p.name}</div>
                      <div className="text-[13px] text-text-2 bidi">{p.price_label || t("products.noPrice")}</div>
                    </div>
                    {can("editor") && <IconButton icon="edit_square" label={t("products.edit")} onClick={() => setEditing(p)} />}
                  </div>
                  <div className="mt-3 flex items-center gap-2">
                    {p.announced_post_id ? (
                      <>
                        <Link href={`/planner?post=${p.announced_post_id}`} className="flex min-w-0 flex-1 items-center gap-1.5 text-[12px] text-muted hover:text-text">
                          <Icon name="send" size={13} /> {t("products.announcedPost")} {p.announced_post_state && <StateBadge state={p.announced_post_state} />}
                        </Link>
                        {can("editor") && <Button size="sm" variant="ghost" icon="autorenew" loading={announce.isPending} onClick={() => announce.mutate({ id: p.id, force: true })}>{t("products.again")}</Button>}
                      </>
                    ) : can("editor") && (
                      <Button size="sm" variant="primary" icon="campaign" className="w-full" loading={announce.isPending} onClick={() => announce.mutate({ id: p.id })}>{t("products.announce")}</Button>
                    )}
                  </div>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
      <ProductSettingsCard />
      {editing && <ProductModal product={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function ProductModal({ product, onClose }: { product: Product | null; onClose: () => void }) {
  const t = useTranslations("links");
  const qc = useQueryClient();
  const currency = useSession((s) => s.workspace?.currency || "SAR");
  const fileInput = useRef<HTMLInputElement>(null);
  const [form, setForm] = useState({
    name: product?.name ?? "", description: product?.description ?? "", price: product?.price != null ? String(product.price) : "",
    currency: product?.currency ?? currency, url: product?.url ?? "", sku: product?.sku ?? "", active: product?.active ?? true,
    image_media_id: product?.image_media_id ?? null as number | null,
  });
  const [uploading, setUploading] = useState(false);
  const save = useMutation({
    mutationFn: () => {
      const body = { ...form, price: form.price ? Number(form.price) : null, url: form.url || null, sku: form.sku || null, description: form.description || null };
      return product ? api.patch(`/products/${product.id}`, body) : api.post("/products", body);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["products"] }); toast.success(t("saved")); onClose(); },
    onError,
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/products/${product?.id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["products"] }); onClose(); },
    onError,
  });
  const upload = async (file?: File) => {
    if (!file) return;
    setUploading(true);
    try {
      const media = await api.upload<{ id: number }>("/media", file);
      setForm((f) => ({ ...f, image_media_id: media.id }));
    } catch (err) {
      onError(err);
    } finally {
      setUploading(false);
    }
  };
  return (
    <Modal open onClose={onClose} title={product ? t("products.edit") : t("products.add")} size="lg"
      footer={<>
        {product && <Button variant="danger" icon="delete" loading={remove.isPending} onClick={() => window.confirm(t("products.confirmDelete")) && remove.mutate()}>{t("delete")}</Button>}
        <Button className="ms-auto" onClick={onClose}>{t("cancel")}</Button>
        <Button variant="primary" disabled={!form.name.trim()} loading={save.isPending} onClick={() => save.mutate()}>{t("save")}</Button>
      </>}>
      <div className="grid gap-4 sm:grid-cols-[180px_minmax(0,1fr)]">
        <div>
          <input ref={fileInput} type="file" accept="image/*" className="hidden" onChange={(e) => upload(e.target.files?.[0])} />
          <button type="button" onClick={() => fileInput.current?.click()} className="relative flex aspect-square w-full items-center justify-center overflow-hidden rounded-2xl border border-dashed border-line-strong bg-fill text-muted hover:bg-fill-2">
            {form.image_media_id ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={`/api/media/${form.image_media_id}/file`} alt="" className="h-full w-full object-cover" />
            ) : uploading ? <Spinner /> : <span className="flex flex-col items-center gap-1 text-[12px]"><Icon name="add_photo" size={26} />{t("products.photo")}</span>}
          </button>
        </div>
        <div className="grid gap-3">
          <Field label={t("products.name")}><Input value={form.name} autoFocus onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <div className="grid grid-cols-[minmax(0,1fr)_90px] gap-2">
            <Field label={t("products.price")}><Input type="number" min={0} step="0.01" dir="ltr" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} /></Field>
            <Field label={t("products.currency")}><Input dir="ltr" maxLength={3} value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })} /></Field>
          </div>
          <Field label={t("products.url")}><Input dir="ltr" type="url" placeholder="https://" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} /></Field>
        </div>
        <Field label={t("products.description")} className="sm:col-span-2"><Textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        <Field label={t("products.sku")}><Input dir="ltr" value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} /></Field>
        <div className="flex items-end pb-2"><Switch checked={form.active} onChange={(active) => setForm({ ...form, active })} label={t("products.active")} /></div>
      </div>
    </Modal>
  );
}

function ProductSettingsCard() {
  const t = useTranslations("links");
  const qc = useQueryClient();
  const isAdmin = useSession((s) => s.can("admin"));
  const { data } = useQuery({ queryKey: ["product-settings"], queryFn: () => api.get<ProductSettings>("/products/settings") });
  const accounts = useQuery({ queryKey: ["planner-accounts"], queryFn: () => api.get<Account[]>("/planner/accounts") });
  const campaigns = useQuery({ queryKey: ["campaigns", false], queryFn: () => api.get<Campaign[]>("/campaigns") });
  const [form, setForm] = useState<ProductSettings | null>(null);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- form follows the loaded settings
    if (data) setForm(data);
  }, [data]);
  const save = useMutation({
    mutationFn: (body: ProductSettings) => api.put<ProductSettings>("/products/settings", body),
    onSuccess: (row) => { qc.setQueryData(["product-settings"], row); toast.success(t("saved")); },
    onError,
  });
  if (!form) return <Card><Spinner /></Card>;
  const toggleAccount = (id: number) =>
    setForm({ ...form, account_ids: form.account_ids.includes(id) ? form.account_ids.filter((x) => x !== id) : [...form.account_ids, id] });
  return (
    <Card className="h-fit">
      <SectionTitle icon="bolt">{t("products.automation")}</SectionTitle>
      <div className="flex flex-col gap-4">
        <Switch checked={form.auto_announce} disabled={!isAdmin} onChange={(v) => setForm({ ...form, auto_announce: v })} label={t("products.auto")} />
        <Field label={t("products.accounts")}>
          <div className="flex flex-wrap gap-1.5">
            {accounts.data?.length ? accounts.data.map((a) => (
              <button key={a.id} type="button" disabled={!isAdmin} onClick={() => toggleAccount(a.id)}
                className={cx("inline-flex items-center gap-1.5 rounded-full border py-1 ps-1 pe-2.5 text-[12px] font-medium transition",
                  form.account_ids.includes(a.id) ? "border-ink bg-ink text-white" : "border-line bg-white/70")}>
                <PlatformBadge platform={a.platform} size={20} /> <span className="max-w-28 truncate bidi">{a.name}</span>
              </button>
            )) : <span className="text-[12px] text-faint">{t("products.noAccounts")}</span>}
          </div>
        </Field>
        <Field label={t("products.caption")}>
          <Select value={form.caption} disabled={!isAdmin} onChange={(e) => setForm({ ...form, caption: e.target.value as "ai" | "template" })}>
            <option value="ai">{t("products.captionAi")}</option>
            <option value="template">{t("products.captionTemplate")}</option>
          </Select>
        </Field>
        <Field label={t("products.template")} hint={t("products.templateHint")}>
          <Textarea rows={3} value={form.template} disabled={!isAdmin} onChange={(e) => setForm({ ...form, template: e.target.value })} />
        </Field>
        <Field label={t("products.mode")}>
          <Select value={form.mode} disabled={!isAdmin} onChange={(e) => setForm({ ...form, mode: e.target.value as "draft" | "best_time" })}>
            <option value="draft">{t("products.modeDraft")}</option>
            <option value="best_time">{t("products.modeBest")}</option>
          </Select>
        </Field>
        <Field label={t("campaign")}>
          <Select value={form.campaign_id ?? ""} disabled={!isAdmin} onChange={(e) => setForm({ ...form, campaign_id: e.target.value ? Number(e.target.value) : null })}>
            <option value="">{t("none")}</option>
            {campaigns.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
        </Field>
        <Field label={t("products.design")} hint={t("products.designHint")}>
          <Input dir="ltr" placeholder="set:1" value={form.design} disabled={!isAdmin} onChange={(e) => setForm({ ...form, design: e.target.value })} />
        </Field>
        {isAdmin && <Button variant="primary" loading={save.isPending} onClick={() => save.mutate(form)}>{t("save")}</Button>}
        {!isAdmin && <Badge>{t("adminOnly")}</Badge>}
      </div>
    </Card>
  );
}
