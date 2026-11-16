"use client";
/** Header controls of the ideas page: "More ideas" (a small popover) and the daily settings (admins). */
import { useQueryClient, useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/icon";
import { onError } from "@/components/planning/ui";
import { Button, Field, IconButton, Input, Modal, Segmented, Select, Switch, cx, toast } from "@/components/ui";
import { LOCALE_NAMES, type Locale } from "@/i18n/routing";
import { api } from "@/lib/api";
import { FORMAT_ICON, useIdeaFormat } from "./shared";
import { FORMATS, type GenerateIn, type IdeaFormat, type IdeaSettings } from "./types";

const COUNTS = [1, 2, 3, 4, 5, 6];
const languageName = (code: string) => LOCALE_NAMES[code as Locale] ?? code;

export function MoreIdeas({ settings, busy, onGenerate }: { settings?: IdeaSettings; busy: boolean; onGenerate: (body: GenerateIn) => void }) {
  const t = useTranslations("ideas.more");
  const f = useTranslations("ideas.formats");
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState<number | null>(null);
  const [formats, setFormats] = useState<IdeaFormat[]>([]);
  const [language, setLanguage] = useState<string | null>(null);
  const [focus, setFocus] = useState("");
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const chosenCount = count ?? settings?.count ?? 3;
  const chosenLanguage = language ?? settings?.language ?? "ar";
  const go = () => {
    onGenerate({ count: chosenCount, language: chosenLanguage, focus: focus.trim() || undefined, formats: formats.length ? formats : undefined });
    setOpen(false);
  };
  const toggle = (fmt: IdeaFormat) => setFormats(formats.includes(fmt) ? formats.filter((x) => x !== fmt) : [...formats, fmt]);

  return (
    <div ref={box} className="relative">
      <Button variant="primary" icon="auto_awesome" loading={busy} onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="dialog">
        {t("button")}
      </Button>
      {open && (
        <div role="dialog" aria-label={t("title")}
          className="glass-strong pop-in absolute end-0 top-full z-30 mt-2 w-[min(22rem,calc(100vw-2rem))] rounded-[20px] p-4">
          <div className="mb-3 text-[15px] font-semibold tracking-tight">{t("title")}</div>
          <div className="flex flex-col gap-3.5">
            <Field label={t("count")}>
              <Segmented size="sm" value={chosenCount} onChange={setCount} options={COUNTS.map((n) => ({ value: n, label: <span className="tabular-nums">{n}</span> }))} />
            </Field>
            <div className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-text-2">{t("formats")}</span>
              <div className="flex flex-wrap gap-1.5">
                {FORMATS.map((fmt) => {
                  const on = formats.includes(fmt);
                  return (
                    <button key={fmt} type="button" aria-pressed={on} onClick={() => toggle(fmt)}
                      className={cx("inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-[12.5px] font-medium transition",
                        on ? "bg-ink text-white" : "bg-fill-2 text-text-2 hover:text-text")}>
                      <Icon name={FORMAT_ICON[fmt]} size={14} />{f(fmt)}
                    </button>
                  );
                })}
              </div>
              <span className="text-[11.5px] text-muted">{formats.length ? t("formatsSome") : t("formatsAll")}</span>
            </div>
            <Field label={t("language")}>
              <Select value={chosenLanguage} onChange={(e) => setLanguage(e.target.value)}>
                {(settings?.languages ?? ["ar", "en", "nl", "de", "fr"]).map((code) => <option key={code} value={code}>{languageName(code)}</option>)}
              </Select>
            </Field>
            <Field label={t("focus")} hint={t("focusHint")}>
              <Input dir="auto" value={focus} maxLength={300} onChange={(e) => setFocus(e.target.value)} placeholder={t("focusPlaceholder")}
                onKeyDown={(e) => e.key === "Enter" && go()} />
            </Field>
            <Button variant="primary" icon="auto_awesome" onClick={go} className="w-full">{t("go", { n: chosenCount })}</Button>
          </div>
        </div>
      )}
    </div>
  );
}

export function SettingsButton({ settings }: { settings?: IdeaSettings }) {
  const t = useTranslations("ideas.settings");
  const [open, setOpen] = useState(false);
  return (
    <>
      <IconButton icon="settings" label={t("title")} onClick={() => setOpen(true)} disabled={!settings} className="glass h-10 w-10" />
      {open && settings && <SettingsDialog settings={settings} onClose={() => setOpen(false)} />}
    </>
  );
}

function SettingsDialog({ settings, onClose }: { settings: IdeaSettings; onClose: () => void }) {
  const t = useTranslations("ideas.settings");
  const fmt = useIdeaFormat();
  const qc = useQueryClient();
  const [form, setForm] = useState({ daily: settings.daily, count: settings.count, hour: settings.hour, language: settings.language });
  const save = useMutation({
    mutationFn: () => api.put<IdeaSettings>("/ideas/settings", form),
    onSuccess: (data) => {
      qc.setQueryData(["ideas", "settings"], data);
      toast.success(t("saved"));
      onClose();
    },
    onError,
  });
  return (
    <Modal open onClose={onClose} title={t("title")} footer={
      <>
        <Button variant="ghost" onClick={onClose}>{t("cancel")}</Button>
        <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>{t("save")}</Button>
      </>
    }>
      <div className="flex flex-col gap-5">
        <div className="flex items-start gap-3 rounded-2xl bg-fill p-3">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold">{t("daily")}</div>
            <p className="mt-0.5 text-[12.5px] text-muted">{t("dailyHint")}</p>
          </div>
          <Switch checked={form.daily} onChange={(daily) => setForm({ ...form, daily })} />
        </div>
        <div className={cx("flex flex-col gap-4 transition-opacity", !form.daily && "opacity-50")}>
          <Field label={t("count")}>
            <Segmented size="sm" value={form.count} onChange={(count) => setForm({ ...form, count })}
              options={COUNTS.map((n) => ({ value: n, label: <span className="tabular-nums">{n}</span> }))} />
          </Field>
          <Field label={t("hour")} hint={t("hourHint", { zone: fmt.timeZone })}>
            <Select value={form.hour} onChange={(e) => setForm({ ...form, hour: Number(e.target.value) })} disabled={!form.daily}>
              {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{fmt.hourOnly(h)}</option>)}
            </Select>
          </Field>
        </div>
        <Field label={t("language")} hint={t("languageHint")}>
          <Select value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
            {settings.languages.map((code) => <option key={code} value={code}>{languageName(code)}</option>)}
          </Select>
        </Field>
      </div>
    </Modal>
  );
}
