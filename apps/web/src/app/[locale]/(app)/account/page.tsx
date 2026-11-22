"use client";
/** Account center › Profile: photo, name, username, sign-in e-mail (with confirmation), language and time zone. */
import { useTranslations } from "next-intl";
import { useMemo, useRef, useState } from "react";
import { Avatar, Badge, Button, Card, Field, Input, Modal, SectionTitle, Select, toast } from "@/components/ui";
import { usePathname, useRouter } from "@/i18n/navigation";
import { LOCALE_NAMES, routing } from "@/i18n/routing";
import { ApiError, api } from "@/lib/api";
import { type Me, useSession } from "@/lib/session";

const onError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : String(err));

function timeZones(current: string): string[] {
  let zones: string[] = [];
  try {
    zones = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.("timeZone") ?? [];
  } catch {
    /* older browsers */
  }
  return Array.from(new Set([current, "UTC", ...zones])).filter(Boolean);
}

export default function AccountProfilePage() {
  const t = useTranslations("account.profile");
  const { me, setMe } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const file = useRef<HTMLInputElement>(null);
  const [form, setForm] = useState({ name: me?.user.name ?? "", username: me?.user.username ?? "", locale: me?.user.locale ?? "ar", timezone: me?.user.timezone ?? "Asia/Riyadh" });
  const [busy, setBusy] = useState("");
  const [emailOpen, setEmailOpen] = useState(false);
  const zones = useMemo(() => timeZones(me?.user.timezone ?? "UTC"), [me?.user.timezone]);
  if (!me) return null;

  const save = async () => {
    setBusy("save");
    try {
      const data = await api.patch<Me>("/auth/me", form);
      setMe(data);
      toast.success(t("saved"));
      if (form.locale !== me.user.locale) router.replace(pathname, { locale: form.locale });
    } catch (err) {
      onError(err);
    } finally {
      setBusy("");
    }
  };
  const upload = async (picked: File | undefined) => {
    if (!picked) return;
    setBusy("photo");
    try {
      await api.upload("/account/avatar", picked);
      setMe(await api.get<Me>("/auth/me"));
    } catch (err) {
      onError(err);
    } finally {
      setBusy("");
      if (file.current) file.current.value = "";
    }
  };
  const removePhoto = () => api.patch<Me>("/auth/me", { avatar_url: null }).then(setMe).catch(onError);
  const resend = () => api.post("/auth/email/verify-request").then(() => toast.success(t("resent"))).catch(onError);

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <SectionTitle icon="person">{t("title")}</SectionTitle>
        <div className="mb-5 flex flex-wrap items-center gap-4">
          <Avatar name={me.user.name} src={me.user.avatar_url} size={72} />
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-2">
              <Button size="sm" icon="upload" loading={busy === "photo"} onClick={() => file.current?.click()}>{t("upload")}</Button>
              {me.user.avatar_url && <Button size="sm" variant="ghost" icon="delete" onClick={removePhoto}>{t("remove")}</Button>}
            </div>
            <p className="text-xs text-muted">{t("photoHint")}</p>
            <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => upload(e.target.files?.[0])} />
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("name")}><Input value={form.name} maxLength={120} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label={t("username")} hint={t("usernameHint")}>
            <Input value={form.username} dir="ltr" autoCapitalize="none" spellCheck={false} maxLength={30} onChange={(e) => setForm({ ...form, username: e.target.value.toLowerCase() })} />
          </Field>
          <Field label={t("language")}>
            <Select value={form.locale} onChange={(e) => setForm({ ...form, locale: e.target.value })}>
              {routing.locales.map((code) => <option key={code} value={code}>{LOCALE_NAMES[code]}</option>)}
            </Select>
          </Field>
          <Field label={t("timezone")}>
            <Select value={form.timezone} dir="ltr" onChange={(e) => setForm({ ...form, timezone: e.target.value })}>
              {zones.map((zone) => <option key={zone} value={zone}>{zone.replaceAll("_", " ")}</option>)}
            </Select>
          </Field>
        </div>
        <div className="mt-4 flex justify-end">
          <Button variant="primary" loading={busy === "save"} onClick={save}>{t("save")}</Button>
        </div>
      </Card>

      <Card>
        <SectionTitle icon="mail" actions={<Button size="sm" onClick={() => setEmailOpen(true)}>{t("changeEmail")}</Button>}>{t("email")}</SectionTitle>
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-medium" dir="ltr">{me.user.email}</span>
          <Badge tone={me.user.email_verified ? "ok" : "warn"}>{me.user.email_verified ? t("verified") : t("unverified")}</Badge>
          {!me.user.email_verified && <Button size="sm" variant="ghost" onClick={resend}>{t("resend")}</Button>}
        </div>
      </Card>
      <EmailDialog open={emailOpen} onClose={() => setEmailOpen(false)} />
    </div>
  );
}

function EmailDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useTranslations("account.profile");
  const tc = useTranslations("adminUsers");
  const setMe = useSession((s) => s.setMe);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      setMe(await api.post<Me>("/auth/email", { email, password }));
      toast.success(t("emailChanged"));
      setPassword("");
      onClose();
    } catch (err) {
      onError(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onClose={onClose} title={t("changeEmail")} size="sm"
      footer={<><Button variant="ghost" onClick={onClose}>{tc("cancel")}</Button><Button variant="primary" loading={busy} disabled={!email || !password} onClick={submit}>{t("save")}</Button></>}>
      <div className="flex flex-col gap-3">
        <Field label={t("newEmail")}><Input type="email" dir="ltr" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label={t("password")}><Input type="password" dir="ltr" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        <p className="text-xs text-muted">{t("emailNote")}</p>
      </div>
    </Modal>
  );
}
