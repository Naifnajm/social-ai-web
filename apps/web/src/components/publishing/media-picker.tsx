"use client";
/** Pick files from the workspace media library (GET /api/media). */
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon } from "@/components/icon";
import { Button, EmptyState, Modal, Segmented, Spinner, cx } from "@/components/ui";
import { api } from "@/lib/api";
import type { Media } from "./types";
import { kindOf } from "./util";

export function MediaThumb({ media, className }: { media: Media; className?: string }) {
  const kind = kindOf(media.mimetype);
  if (kind === "image") {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={media.url} alt={media.filename} className={cx("h-full w-full object-cover", className)} loading="lazy" />;
  }
  if (kind === "video") {
    return (
      <span className={cx("relative block h-full w-full bg-black", className)}>
        <video src={media.url} muted preload="metadata" className="h-full w-full object-cover" />
        <span className="absolute inset-0 flex items-center justify-center text-white"><Icon name="play_circle" size={28} /></span>
      </span>
    );
  }
  return (
    <span className={cx("flex h-full w-full flex-col items-center justify-center gap-1 bg-fill-2 text-muted", className)}>
      <Icon name="graphic_eq" size={26} />
      <span className="max-w-full truncate px-2 text-[10px]">{media.filename}</span>
    </span>
  );
}

export function MediaPicker({ open, onClose, onPick, selected }: { open: boolean; onClose: () => void; onPick: (items: Media[]) => void; selected: number[] }) {
  const t = useTranslations("publishing.studio");
  const [kind, setKind] = useState<"" | "image" | "video" | "audio">("");
  const [chosen, setChosen] = useState<Media[]>([]);
  const { data, isLoading } = useQuery({ queryKey: ["media", kind], queryFn: () => api.get<Media[]>("/media", { kind, limit: 120 }), enabled: open });
  const toggle = (m: Media) => setChosen((c) => (c.some((x) => x.id === m.id) ? c.filter((x) => x.id !== m.id) : [...c, m]));
  const done = () => {
    onPick(chosen);
    setChosen([]);
    onClose();
  };
  return (
    <Modal open={open} onClose={onClose} size="xl" title={t("library")}
      footer={<><Button onClick={onClose}>{t("cancel")}</Button><Button variant="primary" disabled={!chosen.length} onClick={done}>{t("addSelected", { count: chosen.length })}</Button></>}>
      <Segmented size="sm" className="mb-4" value={kind} onChange={setKind} options={[
        { value: "", label: t("all") }, { value: "image", label: t("images"), icon: "image" },
        { value: "video", label: t("videos"), icon: "movie" }, { value: "audio", label: t("audio"), icon: "music_note" },
      ]} />
      {isLoading ? <div className="flex justify-center py-10"><Spinner /></div> : !data?.length ? (
        <EmptyState icon="photo_library" title={t("libraryEmpty")} />
      ) : (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-6">
          {data.map((m) => {
            const on = chosen.some((x) => x.id === m.id);
            const already = selected.includes(m.id);
            return (
              <button key={m.id} disabled={already} onClick={() => toggle(m)}
                className={cx("relative aspect-square overflow-hidden rounded-xl ring-offset-2 transition disabled:opacity-40", on ? "ring-2 ring-ink" : "hover:opacity-90")}>
                <MediaThumb media={m} />
                {on && <span className="absolute end-1.5 top-1.5 rounded-full bg-ink text-white"><Icon name="check_circle" size={20} /></span>}
              </button>
            );
          })}
        </div>
      )}
    </Modal>
  );
}
