"use client";
/** Top bar of the canvas: back, board name, undo/redo, variables & batch versions, brand kit, linked post, run all. */
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Icon } from "@/components/icon";
import { Button, IconButton, Input, cx, toast } from "@/components/ui";
import { Link } from "@/i18n/navigation";
import { useCanvas } from "./canvas-context";
import { usd } from "./meta";
import type { Graph, Variable } from "./types";

export function TopBar({ graph, canUndo, canRedo, onUndo, onRedo }: {
  graph: Graph; canUndo: boolean; canRedo: boolean; onUndo: () => void; onRedo: () => void;
}) {
  const t = useTranslations("production");
  const { actions, readOnly } = useCanvas();
  const [name, setName] = useState(graph.board.name);
  const [panel, setPanel] = useState(false);
  const [running, setRunning] = useState(false);
  const runAll = async () => {
    setRunning(true);
    try {
      await actions.run(null);
    } catch {
      /* toast shown */
    } finally {
      setRunning(false);
    }
  };
  const varsCount = graph.board.variables.length;
  return (
    <>
      <div className="glass-strong absolute inset-x-2 top-2 z-30 flex h-14 items-center gap-1.5 rounded-[20px] px-2 sm:inset-x-3 sm:top-3 sm:gap-2 sm:px-3">
        <Link href="/production" className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-text-2 hover:bg-fill-2" aria-label={t("back")}>
          <Icon name="arrow_back" size={18} className="rtl:rotate-180" />
        </Link>
        <input value={name} disabled={readOnly} dir="auto" aria-label={t("boardName")}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => name.trim() && name !== graph.board.name && actions.updateBoard({ name: name.trim() }).catch(() => setName(graph.board.name))}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          className="bidi min-w-0 flex-1 truncate rounded-lg bg-transparent px-1.5 py-1 text-[15px] font-semibold tracking-tight outline-none focus:bg-white/70 sm:max-w-[280px]" />

        {!readOnly && (
          <div className="hidden shrink-0 items-center gap-0.5 rounded-full bg-fill p-0.5 sm:flex">
            <IconButton icon="undo" label={t("undo")} disabled={!canUndo} onClick={onUndo} className="h-8 w-8" />
            <IconButton icon="redo" label={t("redo")} disabled={!canRedo} onClick={onRedo} className="h-8 w-8" />
          </div>
        )}

        <div className="ms-auto flex shrink-0 items-center gap-1.5">
          <button type="button" onClick={() => setPanel(!panel)}
            className={cx("inline-flex h-9 items-center gap-1.5 rounded-full px-3 text-[13px] font-medium transition", panel ? "bg-ink text-white" : "bg-fill hover:bg-fill-2")}>
            <Icon name="data_object" size={16} />
            <span className="hidden md:inline">{t("variables")}</span>
            {!!varsCount && <span className={cx("min-w-[18px] rounded-full px-1 text-center text-[11px] leading-[18px]", panel ? "bg-white text-ink" : "bg-ink text-white")}>{varsCount}</span>}
          </button>

          <label className="hidden h-9 items-center gap-1.5 rounded-full bg-fill px-3 text-[13px] font-medium lg:inline-flex">
            <Icon name="palette" size={16} />
            <select value={graph.board.brand_kit_id ?? ""} disabled={readOnly}
              onChange={(e) => actions.updateBoard({ brand_kit_id: e.target.value ? Number(e.target.value) : 0 }).catch(() => undefined)}
              className="max-w-[140px] cursor-pointer appearance-none bg-transparent outline-none" aria-label={t("brandKit")}>
              <option value="">{t("noBrandKit")}</option>
              {graph.brand_kits.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
            </select>
          </label>

          {graph.board.post && (
            <Link href={`/studio?post=${graph.board.post.id}`}
              className="hidden h-9 max-w-[200px] items-center gap-1.5 rounded-full bg-fill px-3 text-[13px] font-medium hover:bg-fill-2 xl:inline-flex">
              <Icon name="outbox" size={16} />
              <span className="bidi truncate" dir="auto">{graph.board.post.name || t("linkedPost")}</span>
              <span className="text-muted">· {t(`postStates.${graph.board.post.state}`)}</span>
            </Link>
          )}

          {!readOnly && (
            <>
              {graph.run_all.reused > 0 && <span className="hidden text-xs font-medium text-ok xl:inline">{t("reused", { count: graph.run_all.reused })}</span>}
              <Button variant="primary" icon={graph.busy ? undefined : "play_arrow"} loading={running || graph.busy} onClick={runAll} className="shrink-0">
                <span className="hidden sm:inline">{graph.busy ? t("running") : t("runAll")}</span>
                {!graph.busy && graph.run_all.cost > 0 && <span className="rounded-full bg-white/15 px-1.5 text-[11px] tabular-nums">≈ {usd(graph.run_all.cost)}</span>}
              </Button>
            </>
          )}
        </div>
      </div>
      {panel && <VariablesPanel graph={graph} onClose={() => setPanel(false)} />}
    </>
  );
}

function VariablesPanel({ graph, onClose }: { graph: Graph; onClose: () => void }) {
  const t = useTranslations("production");
  const { actions, readOnly } = useCanvas();
  const [vars, setVars] = useState<Variable[]>(() => {
    const defined = graph.board.variables.map((v) => ({ ...v }));
    for (const name of graph.board.used_variables) if (!defined.some((v) => v.key === name)) defined.push({ key: name, value: "" });
    return defined.length ? defined : [{ key: "", value: "" }];
  });
  const [rows, setRows] = useState<Record<string, string>[]>([]);
  const [saving, setSaving] = useState(false);
  const [created, setCreated] = useState<{ id: number; name: string }[]>([]);
  const keys = vars.map((v) => v.key.trim()).filter(Boolean);

  const save = async () => {
    setSaving(true);
    try {
      await actions.setVariables(vars.filter((v) => v.key.trim()));
      toast.success(t("saved"));
    } catch {
      /* toast shown */
    } finally {
      setSaving(false);
    }
  };
  const runBatch = async () => {
    setSaving(true);
    try {
      const boards = await actions.batch(rows);
      setCreated(boards);
      setRows([]);
      toast.success(t("batchCreated", { count: boards.length }));
    } catch {
      /* toast shown */
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="glass-strong pop-in absolute inset-x-2 top-[72px] z-40 flex max-h-[calc(100%-90px)] flex-col overflow-hidden rounded-[22px] sm:inset-x-auto sm:end-3 sm:w-[420px]">
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <Icon name="data_object" size={18} />
        <h3 className="flex-1 text-[15px] font-semibold">{t("variables")}</h3>
        <IconButton icon="close" label={t("close")} onClick={onClose} />
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3">
        <p className="mb-3 text-xs text-muted">{t.rich("variablesHelp", { code: (chunks) => <code className="rounded bg-fill-2 px-1 font-mono text-ink" dir="ltr">{chunks}</code> })}</p>
        <div className="flex flex-col gap-1.5">
          {vars.map((v, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <Input dir="ltr" className="!h-9 w-32 shrink-0 font-mono text-xs" placeholder="product" value={v.key} disabled={readOnly}
                onChange={(e) => setVars(vars.map((x, j) => (j === i ? { ...x, key: e.target.value.replace(/[{}]/g, "") } : x)))} />
              <Input dir="auto" className="!h-9 min-w-0 flex-1" placeholder={t("value")} value={v.value} disabled={readOnly}
                onChange={(e) => setVars(vars.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
              {!readOnly && <IconButton icon="remove" label={t("delete")} className="h-8 w-8" onClick={() => setVars(vars.filter((_, j) => j !== i))} />}
            </div>
          ))}
        </div>
        {!readOnly && (
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="ghost" icon="add" onClick={() => setVars([...vars, { key: "", value: "" }])}>{t("addVariable")}</Button>
            <Button size="sm" variant="primary" icon="save" loading={saving} onClick={save} className="ms-auto">{t("save")}</Button>
          </div>
        )}

        {!readOnly && keys.length > 0 && (
          <div className="mt-5 border-t border-line pt-4">
            <h4 className="mb-1 text-[13px] font-semibold">{t("batchTitle")}</h4>
            <p className="mb-3 text-xs text-muted">{t("batchHelp")}</p>
            <div className="flex max-h-60 flex-col gap-1.5 overflow-y-auto">
              {rows.map((row, i) => (
                <div key={i} className="flex items-center gap-1.5">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-fill-2 text-[11px]">{i + 1}</span>
                  {keys.map((key) => (
                    <Input key={key} dir="auto" className="!h-9 min-w-0 flex-1" placeholder={key} value={row[key] || ""}
                      onChange={(e) => setRows(rows.map((r, j) => (j === i ? { ...r, [key]: e.target.value } : r)))} />
                  ))}
                  <IconButton icon="remove" label={t("delete")} className="h-8 w-8" onClick={() => setRows(rows.filter((_, j) => j !== i))} />
                </div>
              ))}
            </div>
            <div className="mt-2 flex gap-2">
              <Button size="sm" variant="ghost" icon="add" disabled={rows.length >= 20} onClick={() => setRows([...rows, {}])}>{t("addVersion")}</Button>
              <Button size="sm" variant="primary" icon="rocket_launch" className="ms-auto" disabled={!rows.length} loading={saving} onClick={runBatch}>
                {t("createVersions", { count: rows.length })}
              </Button>
            </div>
            {!!created.length && (
              <ul className="mt-3 flex flex-col gap-1">
                {created.map((b) => (
                  <li key={b.id}>
                    <Link href={`/production/${b.id}`} className="bidi flex items-center gap-1.5 rounded-lg px-2 py-1 text-[13px] hover:bg-fill-2" dir="auto">
                      <Icon name="open_in_new" size={14} /> {b.name}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
