"use client";
/** Floating pieces of the canvas: context menu, block picker, run preflight, run summary, search and shortcuts. */
import { useTranslations } from "next-intl";
import { type KeyboardEvent as ReactKeyboardEvent, type ReactNode, type RefObject, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/icon";
import { Button, Modal, cx } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { credits as creditsText } from "@/lib/ai";
import { useSession } from "@/lib/session";
import { KIND_META, usd } from "./meta";
import type { BlockGroup, BlockNode, RunEstimate } from "./types";

export const MOD = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl";

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-fill-2 px-1.5 font-sans text-[11px] font-medium text-text-2 shadow-[inset_0_-1px_0_rgba(0,0,0,.08)]" dir="ltr">{children}</kbd>;
}

/** Keeps a popover inside the window. */
function useClamped(x: number, y: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x, y, ready: false });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    setPos({ x: Math.max(8, Math.min(x, window.innerWidth - width - 8)), y: Math.max(8, Math.min(y, window.innerHeight - height - 8)), ready: true });
  }, [x, y]);
  return { ref, pos };
}

/** Closes on a click outside, Escape, scroll of the canvas or resize. */
function useDismiss(ref: RefObject<HTMLElement | null>, onClose: () => void) {
  useEffect(() => {
    const down = (e: PointerEvent) => !ref.current?.contains(e.target as Node) && onClose();
    const key = (e: KeyboardEvent) => e.key === "Escape" && (e.stopPropagation(), onClose());
    window.addEventListener("pointerdown", down, true);
    window.addEventListener("keydown", key, true);
    window.addEventListener("resize", onClose);
    window.addEventListener("wheel", onClose, { passive: true });
    return () => {
      window.removeEventListener("pointerdown", down, true);
      window.removeEventListener("keydown", key, true);
      window.removeEventListener("resize", onClose);
      window.removeEventListener("wheel", onClose);
    };
  }, [ref, onClose]);
}

export type MenuItem = { icon: string; label: string; shortcut?: string; onClick: () => void; danger?: boolean; disabled?: boolean } | "-";

export function ContextMenu({ x, y, items, onClose, label }: { x: number; y: number; items: MenuItem[]; onClose: () => void; label: string }) {
  const { ref, pos } = useClamped(x, y);
  useDismiss(ref, onClose);
  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
  }, [ref]);
  const onKey = (e: ReactKeyboardEvent) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const buttons = [...(ref.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") || [])];
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    buttons[(index + (e.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length]?.focus();
  };
  return (
    <div ref={ref} role="menu" aria-label={label} onKeyDown={onKey} onContextMenu={(e) => e.preventDefault()}
      className={cx("glass-strong fixed z-[60] w-60 rounded-2xl p-1.5 transition-opacity duration-150", pos.ready ? "pop-in opacity-100" : "opacity-0")}
      style={{ left: pos.x, top: pos.y }}>
      {items.map((item, i) => item === "-" ? <div key={i} className="mx-2 my-1 h-px bg-line" role="separator" /> : (
        <button key={i} type="button" role="menuitem" disabled={item.disabled}
          onClick={() => { onClose(); item.onClick(); }}
          className={cx("flex h-9 w-full items-center gap-2.5 rounded-xl px-2.5 text-start text-[13px] outline-none transition-colors duration-100 disabled:opacity-40",
            item.danger ? "text-bad hover:bg-bad-bg focus-visible:bg-bad-bg" : "hover:bg-fill-2 focus-visible:bg-fill-2")}>
          <Icon name={item.icon} size={16} className={item.danger ? "" : "text-text-2"} />
          <span className="flex-1 truncate">{item.label}</span>
          {item.shortcut && <span className="text-[11px] text-muted" dir="ltr">{item.shortcut}</span>}
        </button>
      ))}
    </div>
  );
}

/** Pick a kind of block (after dropping a link on the empty canvas, or from the phone's "Add block" sheet). */
export function KindList({ kinds, onPick }: { kinds: string[]; onPick: (kind: string) => void }) {
  const t = useTranslations("production");
  return (
    <div className="flex flex-col gap-0.5">
      {kinds.map((kind) => (
        <button key={kind} type="button" onClick={() => onPick(kind)}
          className="flex items-center gap-2.5 rounded-xl px-2 py-1.5 text-start outline-none transition-colors duration-100 hover:bg-fill-2 focus-visible:bg-fill-2">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl"
            style={{ color: `color-mix(in srgb, ${KIND_META[kind].color} 82%, #000)`, background: `color-mix(in srgb, ${KIND_META[kind].color} 13%, #fff)` }}>
            <Icon name={KIND_META[kind].icon} size={17} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] font-semibold">{t(`kinds.${kind}`)}</span>
            <span className="block truncate text-[11.5px] text-muted">{t(`kindDescriptions.${kind}`)}</span>
          </span>
        </button>
      ))}
    </div>
  );
}

export function KindPopover({ x, y, kinds, title, onPick, onClose }: { x: number; y: number; kinds: string[]; title: string; onPick: (kind: string) => void; onClose: () => void }) {
  const t = useTranslations("production");
  const { ref, pos } = useClamped(x, y);
  useDismiss(ref, onClose);
  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, [ref]);
  return (
    <div ref={ref} role="dialog" aria-label={title}
      className={cx("glass-strong fixed z-[60] flex max-h-[min(440px,80vh)] w-72 flex-col rounded-2xl transition-opacity duration-150", pos.ready ? "pop-in opacity-100" : "opacity-0")}
      style={{ left: pos.x, top: pos.y }}>
      <div className="px-3.5 pb-1 pt-3 text-[12px] font-semibold uppercase tracking-wide text-muted">{title}</div>
      <div className="overflow-y-auto p-1.5">
        {kinds.length ? <KindList kinds={kinds} onPick={(kind) => { onClose(); onPick(kind); }} /> : <p className="px-2 py-3 text-[13px] text-muted">{t("picker.none")}</p>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ run preflight
export type Preflight =
  | { kind: "missing"; estimate: RunEstimate }
  | { kind: "confirm"; estimate: RunEstimate; label: string; onRun: () => void };

export function PreflightDialog({ state, blocks, onClose, onShow }: {
  state: Preflight; blocks: Map<number, BlockNode>; onClose: () => void; onShow: (ids: number[]) => void;
}) {
  const t = useTranslations("production.preflight");
  const tp = useTranslations("production");
  const admin = useSession((s) => s.can("admin"));
  const est = state.estimate;
  const names = (ids: number[]) => ids.map((id) => blocks.get(id)?.name).filter(Boolean) as string[];
  const over = est.credits != null && est.credits_available != null && est.credits > est.credits_available;

  if (state.kind === "missing") {
    return (
      <Modal open onClose={onClose} size="md" title={t("missingTitle")}
        footer={<>
          <Button variant="ghost" onClick={onClose}>{tp("close")}</Button>
          {admin && <Link href="/settings/ai" className="inline-flex h-10 items-center gap-1.5 rounded-full bg-ink px-4 text-sm font-medium text-white hover:bg-ink-2"><Icon name="settings" size={16} />{t("openProviders")}</Link>}
        </>}>
        <p className="mb-3 text-sm text-text-2">{admin ? t("missingText") : t("missingTextMember")}</p>
        <ul className="flex flex-col gap-2">
          {(est.missing || []).map((m) => (
            <li key={m.capability} className="rounded-2xl bg-white/60 p-3 ring-1 ring-line">
              <div className="flex items-center gap-2 text-[13px] font-semibold">
                <Icon name="warning" size={16} className="text-warn" />{t(`capabilities.${m.capability}`)}
                <button type="button" onClick={() => onShow(m.node_ids)} className="ms-auto rounded-full px-2.5 py-1 text-xs font-medium text-text-2 hover:bg-fill-2">{t("show")}</button>
              </div>
              <div className="bidi mt-1 text-xs text-muted" dir="auto">{names(m.node_ids).join(" · ")}</div>
            </li>
          ))}
        </ul>
      </Modal>
    );
  }

  const empty = est.empty_text || [];
  return (
    <Modal open onClose={onClose} size="sm" title={state.label}
      footer={<>
        <Button variant="ghost" onClick={onClose}>{tp("cancel")}</Button>
        <Button variant="primary" icon="play_arrow" autoFocus onClick={() => { onClose(); state.onRun(); }}>{empty.length ? t("runAnyway") : t("run")}</Button>
      </>}>
      <div className="flex flex-col gap-3">
        <dl className="grid grid-cols-2 gap-2">
          <Stat label={t("cost")} value={est.credits != null ? tp("creditsAmount", { amount: creditsText(est.credits) }) : usd(est.cost)}
            sub={est.credits != null ? usd(est.cost) : undefined} />
          <Stat label={t("blocks")} value={String(est.blocks)} sub={est.reused ? tp("reused", { count: est.reused }) : undefined} />
        </dl>
        {est.credits != null && (
          <div className={cx("flex items-center gap-2 rounded-2xl px-3 py-2.5 text-[13px]", over ? "bg-bad-bg text-bad" : "bg-fill text-text-2")}>
            <Icon name="toll" size={17} />
            <span className="flex-1">{est.credits_available == null ? t("unlimited") : t("available", { amount: creditsText(est.credits_available) })}</span>
            {over && <Link href="/settings/billing#credits" className="shrink-0 rounded-full bg-ink px-3 py-1.5 text-xs font-semibold text-white hover:bg-ink-2">{t("buy")}</Link>}
          </div>
        )}
        {over && <p className="text-xs text-bad">{t("notEnough")}</p>}
        {!!empty.length && (
          <div className="rounded-2xl bg-warn-bg px-3 py-2.5 text-[13px] text-warn">
            <div className="flex items-center gap-2 font-semibold">
              <Icon name="warning" size={16} />{t("emptyText", { count: empty.length })}
              <button type="button" onClick={() => { onClose(); onShow(empty); }} className="ms-auto rounded-full px-2.5 py-0.5 text-xs font-medium hover:bg-black/5">{t("show")}</button>
            </div>
            <div className="bidi mt-1 text-xs" dir="auto">{names(empty).join(" · ")}</div>
          </div>
        )}
      </div>
    </Modal>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-2xl bg-white/60 px-3 py-2.5 ring-1 ring-line">
      <dt className="text-[11.5px] text-muted">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums tracking-tight">{value}</dd>
      {sub && <dd className="text-[11.5px] text-muted">{sub}</dd>}
    </div>
  );
}

// ------------------------------------------------------------------ run summary
export type RunResult = { done: number; failed: number[]; stopped: number; at: number };

export function RunSummary({ result, onShowFailed, onClose, raised }: { result: RunResult; onShowFailed: () => void; onClose: () => void; raised?: boolean }) {
  const t = useTranslations("production.summary");
  useEffect(() => {
    if (result.failed.length) return;
    const timer = setTimeout(onClose, 7000);
    return () => clearTimeout(timer);
  }, [result, onClose]);
  const failed = result.failed.length;
  return (
    <div role="status" className={cx("glass-strong pop-in absolute inset-x-0 z-30 mx-auto flex w-max max-w-[calc(100%-24px)] items-center gap-2 rounded-full py-1.5 pe-1.5 ps-4 text-[13px] transition-[bottom] duration-200",
      raised ? "bottom-[calc(62vh+20px)] lg:bottom-28" : "bottom-28")}>
      <Icon name={failed ? "error" : "check_circle"} size={17} className={failed ? "text-bad" : "text-ok"} />
      <span className="font-medium">
        {t("done", { count: result.done })}
        {!!failed && <span className="text-bad"> · {t("failed", { count: failed })}</span>}
        {!!result.stopped && <span className="text-muted"> · {t("stopped", { count: result.stopped })}</span>}
      </span>
      {!!failed && <Button size="sm" variant="ghost" icon="search" onClick={onShowFailed}>{t("showFailed")}</Button>}
      <button type="button" onClick={onClose} aria-label={t("dismiss")} className="flex h-8 w-8 items-center justify-center rounded-full text-muted hover:bg-fill-2">
        <Icon name="close" size={15} />
      </button>
    </div>
  );
}

// ------------------------------------------------------------------ search / jump
export function SearchPalette({ blocks, groups, onPickBlock, onPickGroup, onClose }: {
  blocks: BlockNode[]; groups: BlockGroup[]; onPickBlock: (id: number) => void; onPickGroup: (group: BlockGroup) => void; onClose: () => void;
}) {
  const t = useTranslations("production");
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const results = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const match = (s: string) => !needle || s.toLowerCase().includes(needle);
    return [
      ...groups.filter((g) => match(g.name)).map((g) => ({ type: "group" as const, id: g.id, name: g.name, sub: t("blocks", { count: g.nodes.length }), icon: "select_group", group: g })),
      ...blocks.filter((b) => match(b.name) || match(t(`kinds.${b.kind}`))).map((b) => ({ type: "block" as const, id: b.id, name: b.name, sub: `${t(`kinds.${b.kind}`)} · ${t(`states.${b.state}`)}`, icon: KIND_META[b.kind]?.icon || "add", group: null })),
    ].slice(0, 50);
  }, [q, blocks, groups, t]);
  const pick = (index: number) => {
    const item = results[index];
    if (!item) return;
    onClose();
    if (item.type === "group" && item.group) onPickGroup(item.group);
    else onPickBlock(item.id);
  };
  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center bg-black/15 px-3 pt-[12vh] backdrop-blur-[2px]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal aria-label={t("search.title")} className="glass-strong pop-in flex max-h-[60vh] w-full max-w-lg flex-col overflow-hidden rounded-[22px]">
        <div className="flex items-center gap-2 border-b border-line px-4">
          <Icon name="search" size={18} className="text-muted" />
          <input autoFocus value={q} dir="auto" placeholder={t("search.placeholder")} aria-label={t("search.title")}
            role="combobox" aria-expanded aria-controls="production-search-list" aria-activedescendant={results[active] ? `production-search-${active}` : undefined}
            onChange={(e) => { setQ(e.target.value); setActive(0); }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
              else if (e.key === "Enter") { e.preventDefault(); pick(active); }
              else if (e.key === "Escape") { e.preventDefault(); onClose(); }
            }}
            className="h-12 flex-1 bg-transparent text-[15px] outline-none" />
          <Kbd>Esc</Kbd>
        </div>
        <ul id="production-search-list" role="listbox" className="overflow-y-auto p-1.5">
          {results.map((item, i) => (
            <li key={`${item.type}-${item.id}`} id={`production-search-${i}`} role="option" aria-selected={i === active}
              onMouseEnter={() => setActive(i)} onClick={() => pick(i)}
              className={cx("flex cursor-pointer items-center gap-2.5 rounded-xl px-2.5 py-2", i === active && "bg-fill-2")}>
              <Icon name={item.icon} size={17} className="text-text-2" />
              <span className="bidi min-w-0 flex-1 truncate text-[13.5px] font-medium" dir="auto">{item.name}</span>
              <span className="shrink-0 text-xs text-muted">{item.sub}</span>
            </li>
          ))}
          {!results.length && <li className="px-3 py-6 text-center text-sm text-muted">{t("search.none")}</li>}
        </ul>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ keyboard shortcuts
export function ShortcutsSheet({ onClose }: { onClose: () => void }) {
  const t = useTranslations("production.shortcuts");
  const rows: [string, string[]][] = [
    ["runSelection", [MOD, "Enter"]],
    ["stop", ["Esc", "Esc"]],
    ["undo", [MOD, "Z"]],
    ["redo", [MOD, "Shift", "Z"]],
    ["copy", [MOD, "C"]],
    ["paste", [MOD, "V"]],
    ["duplicate", [MOD, "D"]],
    ["delete", ["Delete"]],
    ["selectAll", [MOD, "A"]],
    ["group", [MOD, "G"]],
    ["search", [MOD, "K"]],
    ["fit", ["Shift", "1"]],
    ["tidy", ["Shift", "T"]],
    ["pan", [t("scroll")]],
    ["zoom", [MOD, t("scroll")]],
    ["multi", ["Shift", t("click")]],
    ["menu", [t("rightClick")]],
    ["help", ["?"]],
  ];
  return (
    <Modal open onClose={onClose} title={t("title")} size="md">
      <ul className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
        {rows.map(([key, keys]) => (
          <li key={key} className="flex items-center justify-between gap-3 border-b border-line py-2 text-[13px]">
            <span>{t(key)}</span>
            <span className="flex shrink-0 items-center gap-1">{keys.map((k, i) => <Kbd key={i}>{k}</Kbd>)}</span>
          </li>
        ))}
      </ul>
    </Modal>
  );
}
