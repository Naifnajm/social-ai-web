#!/usr/bin/env node
// Icon set check: `node apps/web/scripts/check-icons.mjs` (from the repo root or apps/web).
// 1. apps/web/src/components/icons.json must equal packages/icons/icons.json (the build output of
//    packages/icons/build.py; never edit the web copy by hand).
// 2. Every icon name the code uses must be in the set: <Icon name=…>, icon=… / icon: … props and fields,
//    *ICON* lookup tables in the web app, and the "icon" values the API sends (camera panel, production
//    templates, analytics tips, …). Names are found with regexes, so a fully dynamic name is not checked;
//    an unknown name still renders as a question mark (see components/icon.tsx).
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "../../..");
const read = (p) => readFileSync(join(root, p), "utf8");
const errors = [];

const pkg = read("packages/icons/icons.json");
const web = read("apps/web/src/components/icons.json");
if (JSON.stringify(JSON.parse(pkg)) !== JSON.stringify(JSON.parse(web)))
  errors.push("apps/web/src/components/icons.json differs from packages/icons/icons.json: rebuild (packages/icons/build.py) and copy it");
const icons = new Set(Object.keys(JSON.parse(pkg)));

function* walk(dir, exts) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* walk(p, exts);
    else if (exts.some((e) => name.endsWith(e))) yield p;
  }
}

const used = new Map(); // name -> first place seen
const add = (name, file) => used.has(name) || used.set(name, relative(root, file));
// Literals in an expression, minus the ones it compares against or passes to calls (kind === "video" ? … : …).
const literals = (expr) =>
  expr
    .replace(/[!=]==?\s*"[^"]*"|"[^"]*"\s*[!=]==?/g, "")
    .replace(/\w\s*\(\s*"[^"]*"/g, "")
    .match(/"[a-z0-9_]+"/g)?.map((s) => s.slice(1, -1)) ?? [];

for (const file of walk(join(root, "apps/web/src"), [".ts", ".tsx"])) {
  const src = readFileSync(file, "utf8");
  for (const m of src.matchAll(/<Icon\b[^>]*?\bname=(?:"([^"]*)"|\{([^}]*)\})/gs))
    (m[1] !== undefined ? [m[1]] : literals(m[2])).forEach((n) => add(n, file));
  for (const m of src.matchAll(/\bicon=(?:"([^"]*)"|\{([^}]*)\})/g))
    (m[1] !== undefined ? [m[1]] : literals(m[2])).forEach((n) => add(n, file));
  for (const m of src.matchAll(/\bicon\??\s*:\s*"([a-z0-9_]+)"/g)) add(m[1], file);
  for (const m of src.matchAll(/(?:const|let)\s+\w*ICON\w*[^=]*=\s*(\{[\s\S]*?\n\};?|\{[^\n]*\})/g))
    for (const v of m[1].matchAll(/:\s*"([a-z0-9_]+)"/g)) add(v[1], file);
}

for (const file of walk(join(root, "apps/api/app"), [".py"])) {
  const src = readFileSync(file, "utf8");
  for (const m of src.matchAll(/["']icon["']\s*:\s*["']([a-z0-9_]+)["']/g)) add(m[1], file);
  for (const m of src.matchAll(/\btip\(\s*"\w+",\s*"([a-z0-9_]+)"/g)) add(m[1], file);
  if (file.endsWith("ai/camera.py")) {
    for (const m of src.matchAll(/\(lazy\("[^"]*"\),\s*"([a-z0-9_]+)"/g)) add(m[1], file); // GROUPS, PRESETS
    const groupIcons = src.match(/GROUP_ICONS\s*=\s*\{([\s\S]*?)\}/);
    for (const m of groupIcons?.[1].matchAll(/:\s*"([a-z0-9_]+)"/g) ?? []) add(m[1], file);
  }
}

const missing = [...used].filter(([name]) => !icons.has(name));
for (const [name, where] of missing) errors.push(`unknown icon "${name}" (${where}): add it to MAP in packages/icons/build.py`);
if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}
console.log(`icons ok: ${used.size} names used, ${icons.size} in the set`);
