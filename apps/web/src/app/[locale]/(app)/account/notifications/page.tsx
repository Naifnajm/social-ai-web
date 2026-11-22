"use client";
/** Account center › E-mails: which e-mails the platform sends this person. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Card, SectionTitle, Spinner, Switch, toast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

type Prefs = { email_security: boolean; email_product: boolean };

export default function AccountNotificationsPage() {
  const t = useTranslations("account.notifications");
  const client = useQueryClient();
  const prefs = useQuery({ queryKey: ["account-prefs"], queryFn: () => api.get<Prefs>("/account/notifications") });
  const save = async (next: Prefs) => {
    client.setQueryData(["account-prefs"], next);
    try {
      await api.put("/account/notifications", next);
      toast.success(t("saved"));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : String(err));
      client.invalidateQueries({ queryKey: ["account-prefs"] });
    }
  };
  const data = prefs.data;
  return (
    <Card>
      <SectionTitle icon="mail">{t("title")}</SectionTitle>
      {!data ? <div className="flex justify-center py-10"><Spinner /></div> : (
        <div className="flex flex-col divide-y divide-line/60">
          {(["email_security", "email_product"] as const).map((key) => (
            <div key={key} className="flex items-start gap-4 py-3">
              <div className="flex-1">
                <div className="font-medium">{t(key === "email_security" ? "security" : "product")}</div>
                <div className="text-sm text-muted">{t(key === "email_security" ? "securityText" : "productText")}</div>
              </div>
              <Switch checked={data[key]} onChange={(value) => save({ ...data, [key]: value })} />
            </div>
          ))}
          <p className="pt-3 text-xs text-muted">{t("inApp")}</p>
        </div>
      )}
    </Card>
  );
}
