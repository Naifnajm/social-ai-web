"use client";
/** Links & sales › Setup: link tracking switches, short-link domain, website snippet, pixel and server key. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { type ReactNode, useEffect, useState } from "react";
import { Icon } from "@/components/icon";
import { Button, Card, Field, Input, SectionTitle, Spinner, Switch, toast } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { LinkSettings } from "./types";
import { CopyField, onError } from "./ui";

export function SetupTab() {
  const t = useTranslations("links");
  const qc = useQueryClient();
  const isAdmin = useSession((s) => s.can("admin"));
  const { data } = useQuery({ queryKey: ["links-settings"], queryFn: () => api.get<LinkSettings>("/links/settings") });
  const [form, setForm] = useState({ enabled: true, retag: false, add_ref: true, base_url: "" });
  const [secret, setSecret] = useState<string | null>(null);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- form follows the loaded settings
    if (data) setForm({ enabled: data.enabled, retag: data.retag, add_ref: data.add_ref, base_url: data.base_url || "" });
  }, [data]);
  const save = useMutation({
    mutationFn: (body: typeof form) => api.put<LinkSettings>("/links/settings", { ...body, base_url: body.base_url || null }),
    onSuccess: (row) => { qc.setQueryData(["links-settings"], row); toast.success(t("saved")); },
    onError,
  });
  const makeSecret = useMutation({
    mutationFn: () => api.post<{ secret: string }>("/links/settings/secret"),
    onSuccess: (r) => { setSecret(r.secret); qc.invalidateQueries({ queryKey: ["links-settings"] }); },
    onError,
  });
  if (!data) return <div className="flex justify-center py-16"><Spinner /></div>;
  const toggle = (key: "enabled" | "retag" | "add_ref") => (value: boolean) => {
    const next = { ...form, [key]: value };
    setForm(next);
    save.mutate(next);
  };

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <SectionTitle icon="link">{t("setup.linksTitle")}</SectionTitle>
        <p className="-mt-1 mb-4 text-[13px] text-muted">{t("setup.linksIntro")}</p>
        <div className="flex flex-col gap-4">
          <Switch checked={form.enabled} disabled={!isAdmin} onChange={toggle("enabled")} label={t("setup.enabled")} />
          <Switch checked={form.retag} disabled={!isAdmin || !form.enabled} onChange={toggle("retag")} label={t("setup.retag")} />
          <Switch checked={form.add_ref} disabled={!isAdmin || !form.enabled} onChange={toggle("add_ref")} label={t("setup.addRef")} />
          <Field label={t("setup.domain")} hint={t("setup.domainHint", { url: data.default_base_url })}>
            <div className="flex gap-2">
              <Input dir="ltr" placeholder={data.default_base_url} value={form.base_url} disabled={!isAdmin} onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
              {isAdmin && <Button className="!h-10" loading={save.isPending} onClick={() => save.mutate(form)}>{t("save")}</Button>}
            </div>
          </Field>
          <div className="rounded-2xl bg-fill p-3 text-[12.5px] text-text-2">
            <div className="mb-1 font-semibold text-text">{t("setup.exampleTitle")}</div>
            <div dir="ltr" className="break-all font-mono text-[11.5px]">https://shop.example.com/offer</div>
            <div className="my-1 text-center text-muted">↓</div>
            <div dir="ltr" className="break-all font-mono text-[11.5px]">{(form.base_url || data.default_base_url).replace(/\/$/, "")}/r/Ab3xK9p</div>
            <div className="my-1 text-center text-muted">↓</div>
            <div dir="ltr" className="break-all font-mono text-[11.5px]">https://shop.example.com/offer?utm_source=instagram&amp;utm_medium=social&amp;utm_campaign=…{form.add_ref ? "&sref=Ab3xK9p" : ""}</div>
          </div>
        </div>
      </Card>

      <Card>
        <SectionTitle icon="shopping_cart">{t("setup.salesTitle")}</SectionTitle>
        <p className="-mt-1 mb-4 text-[13px] text-muted">{t("setup.salesIntro")}</p>
        <ol className="flex flex-col gap-4">
          <Step n={1} title={t("setup.step1")} text={t("setup.step1Text")}>
            <CopyField value={data.snippet} multiline />
          </Step>
          <Step n={2} title={t("setup.step2")} text={t("setup.step2Text")}>
            <CopyField value={data.pixel_url} />
          </Step>
          <Step n={3} title={t("setup.step3")} text={t("setup.step3Text")}>
            {secret ? (
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1.5 rounded-xl bg-warn-bg px-3 py-2 text-[12px] text-warn"><Icon name="key" size={14} />{t("setup.secretOnce")}</div>
                <CopyField value={secret} />
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted">
                {data.has_secret ? <span className="inline-flex items-center gap-1 text-ok"><Icon name="check_circle" size={15} />{t("setup.hasSecret")}</span> : <span>{t("setup.noSecret")}</span>}
                {isAdmin && <Button size="sm" icon="key" loading={makeSecret.isPending} onClick={() => (!data.has_secret || window.confirm(t("setup.confirmSecret"))) && makeSecret.mutate()}>{data.has_secret ? t("setup.newSecret") : t("setup.createSecret")}</Button>}
              </div>
            )}
            <div className="mt-2"><CopyField multiline value={`curl -X POST ${data.server_url} \\\n  -H "X-Stravica-Key: sk_…" \\\n  -d '{"kind":"order","value":199,"currency":"SAR","id":"ORDER-1001","code":"<sref>"}'`} /></div>
          </Step>
        </ol>
        <p className="mt-4 flex items-start gap-1.5 text-[12px] text-muted"><Icon name="lock" size={14} className="mt-0.5 shrink-0" />{t("setup.privacy")}</p>
      </Card>
    </div>
  );
}

function Step({ n, title, text, children }: { n: number; title: string; text: string; children: ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ink text-[12px] font-bold text-white">{n}</span>
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-semibold">{title}</div>
        <p className="mb-2 text-[12.5px] text-muted">{text}</p>
        {children}
      </div>
    </li>
  );
}
