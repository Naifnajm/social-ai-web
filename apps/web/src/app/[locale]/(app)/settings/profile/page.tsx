"use client";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button, Card, Field, Input, SectionTitle, toast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";

export default function ProfilePage() {
  const t = useTranslations("settings");
  const { me, load } = useSession();
  const [name, setName] = useState(me?.user.name ?? "");
  const [username, setUsername] = useState(me?.user.username ?? "");
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const onError = (err: unknown) => toast.error(err instanceof ApiError ? err.message : String(err));

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <SectionTitle icon="person">{t("profile")}</SectionTitle>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("name")}><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label={t("email")}><Input value={me?.user.email ?? ""} disabled dir="ltr" /></Field>
          <Field label={t("username")} hint={t("usernameHint")}><Input value={username} dir="ltr" autoCapitalize="none" spellCheck={false} maxLength={30} onChange={(e) => setUsername(e.target.value.toLowerCase())} /></Field>
        </div>
        <div className="mt-4 flex justify-end">
          <Button variant="primary" onClick={() => api.patch("/auth/me", { name, username }).then(() => { load(); toast.success(t("saved")); }).catch(onError)}>{t("save")}</Button>
        </div>
      </Card>
      <Card>
        <SectionTitle icon="lock">{t("password")}</SectionTitle>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("currentPassword")}><Input type="password" dir="ltr" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
          <Field label={t("newPassword")}><Input type="password" dir="ltr" minLength={8} value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
        </div>
        <div className="mt-4 flex justify-end">
          <Button onClick={() => api.post("/auth/password", pw).then(() => { toast.success(t("passwordChanged")); window.location.href = "/"; }).catch(onError)}>{t("changePassword")}</Button>
        </div>
      </Card>
    </div>
  );
}
