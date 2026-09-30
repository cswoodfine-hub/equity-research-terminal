// Tests for frontend/components/compsval/shell.js and shell.css (spec 1.2, 1.3, 7.2, 9.1, 11.1).
// Run: node --test "*.test.js" from this folder. shell.js builds nothing without a DOM, so only
// its pure helpers run here; the rest is checked at source level (every command has a handler,
// ctx carries what 11.1 lists, the stylesheet keeps its prefix and holds no colour literal).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

import * as core from "../../components/compsval/core.js";
import * as shell from "../../components/compsval/shell.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const COMP = path.join(HERE, "../../components/compsval");
const ASSETS = path.join(HERE, "../../assets");
const JS = fs.readFileSync(path.join(COMP, "shell.js"), "utf8");
const CSS = fs.readFileSync(path.join(COMP, "shell.css"), "utf8");
const CSS_NO_COMMENTS = CSS.replace(/\/\*[\s\S]*?\*\//g, "");

test("layoutFor: the breakpoints of 1.3 read the frame width", () => {
  assert.equal(shell.layoutFor(2500), "ultrawide");
  assert.equal(shell.layoutFor(2200), "ultrawide");
  assert.equal(shell.layoutFor(2199), "wide");
  assert.equal(shell.layoutFor(1860), "wide");
  assert.equal(shell.layoutFor(1700), "wide");
  assert.equal(shell.layoutFor(1699), "laptop");
  assert.equal(shell.layoutFor(1380), "laptop");
  assert.equal(shell.layoutFor(1100), "laptop");
  assert.equal(shell.layoutFor(1099), "narrow");
  assert.equal(shell.layoutFor(0), "narrow");
});

test("heightModeFor: short under 720 px or past 120 px of scroll, with hysteresis", () => {
  // A 585 px frame (1440 x 810 screen) opens short whatever the scroll.
  assert.equal(shell.heightModeFor("tall", 585, 0), "short");
  assert.equal(shell.heightModeFor("short", 719, 0), "short");
  // A 735 px frame (1920 x 1080 screen) opens tall.
  assert.equal(shell.heightModeFor("short", 735, 0), "tall");
  assert.equal(shell.heightModeFor("tall", 735, 120), "tall");
  assert.equal(shell.heightModeFor("tall", 735, 121), "short");
  // Between the two thresholds the mode holds, so the band does not flicker.
  assert.equal(shell.heightModeFor("short", 735, 80), "short");
  assert.equal(shell.heightModeFor("tall", 735, 80), "tall");
  assert.equal(shell.heightModeFor("short", 735, 40), "short");
  assert.equal(shell.heightModeFor("short", 735, 39), "tall");
  assert.equal(shell.heightModeFor(undefined, 735, 80), "tall");
  assert.equal(core.SHORT_FRAME_PX, 720);
  assert.equal(core.COLLAPSE_AT_PX, 120);
  assert.equal(core.EXPAND_BELOW_PX, 40);
});

test("frameHeightFor: viewport less the frame top less 12, floor 560, fallback to the height arg", () => {
  assert.equal(shell.frameHeightFor(810, 213, 900), 585);
  assert.equal(shell.frameHeightFor(1080, 203, 900), 865);
  assert.equal(shell.frameHeightFor(600, 203, 900), 560);
  assert.equal(shell.frameHeightFor(NaN, NaN, 900), 900);
  assert.equal(shell.frameHeightFor(NaN, NaN, 300), 560);
  assert.equal(shell.frameHeightFor(NaN, NaN, undefined), 900);
});

test("the module loads without a DOM and exports the 11.1 entry points", () => {
  for (const name of ["installTokens", "installSharedCss", "copyFontFaces", "fitFrame"]) {
    assert.equal(typeof shell[name], "function", name);
  }
  for (const name of ["componentReady", "setFrameHeight", "setComponentValue"]) {
    assert.equal(typeof shell.Streamlit[name], "function", name);
  }
});

test("every command of core.COMMANDS has a handler in the shell", () => {
  const gridIds = /\["peer\.exclude", "peer\.remove", "detail\.open", "row\.expand", "sort\.focused"\]/;
  assert.match(JS, gridIds, "the grid commands are routed to gridCommand");
  const missing = [];
  for (const c of core.COMMANDS) {
    if (/^preset\.[1-7]$/.test(c.id)) continue;                       // the preset regex
    if (["peer.exclude", "peer.remove", "detail.open", "row.expand", "sort.focused"].includes(c.id)) {
      if (!JS.includes(`case "${c.id}"`)) missing.push(c.id);
      continue;
    }
    if (!JS.includes(`case "${c.id}"`)) missing.push(c.id);
  }
  assert.deepEqual(missing, []);
  assert.match(JS, /\/\^preset\\\.\(\\d\)\$\//, "preset.N is matched by pattern");
  assert.equal(core.PRESETS.length, 7);
});

test("the mounts and their export names follow 11.1", () => {
  // Revision 3 (12.1, 12.6): notes and sources live in the methodology drawer, so they have no mount.
  for (const fn of ["mountTable", "mountCharts", "mountBridgeChart", "mountBridgeInputs", "mountObservations",
    "mountPeerPanel", "mountMethod", "mountDetail"]) {
    assert.ok(JS.includes(`fn: "${fn}"`), fn);
  }
  // Dynamic imports, so a missing module costs its slot and not the page.
  assert.ok(!/^import .* from "\.\/(table|charts|panels)\.js"/m.test(JS), "table, charts and panels are not static imports");
  for (const f of ["./table.js", "./charts.js", "./panels.js"]) assert.ok(JS.includes(`"${f}"`), f);
  assert.ok(JS.includes('core.stateMsg("calc_failed_section"'), "a failed mount shows the calculation-failure state");
});

test("ctx carries every member 11.1 lists", () => {
  const block = JS.slice(JS.indexOf("const ctx = {"), JS.indexOf("// Global listeners"));
  for (const k of ["dispatch", "getState", "getView", "openDetail", "closeDetail", "openMethod", "announce", "tooltip",
    "menu", "toast", "send", "clickParentTab"]) {
    assert.match(block, new RegExp(`\\b${k}\\b`), k);
  }
  for (const k of ["show", "hide", "describe", "open", "close"]) assert.match(block, new RegExp(`\\b${k}:?\\b`), k);
  for (const k of ["storageOk", "layout", "height"]) assert.ok(block.includes(`defineProperty(ctx, "${k}"`), k);
});

test("storage is wrapped in try/catch and goes through core.migrateState", () => {
  assert.ok(JS.includes("core.migrateState("));
  assert.ok(JS.includes("core.STORAGE_KEY") && JS.includes("core.SESSION_KEY"));
  const store = JS.slice(JS.indexOf("const store = {"), JS.indexOf("// Module state"));
  assert.ok((store.match(/try \{/g) || []).length >= 5, "every storage access is guarded");
});

test("the shell registers no listener on the parent except resize (7.1)", () => {
  const parentListeners = JS.match(/(pw|window\.parent)\.addEventListener\("([a-z]+)"/g) || [];
  assert.deepEqual(parentListeners, ['pw.addEventListener("resize"']);
});

test("house style: no em dash and no banned word in the shell's source", () => {
  assert.ok(!JS.includes("—"), "shell.js has no em dash (the null glyph comes from core)");
  assert.ok(!CSS.includes("—"), "shell.css has no em dash");
  const lower = JS.toLowerCase();
  for (const w of core.BANNED_WORDS) assert.ok(!new RegExp(`\\b${w}\\b`).test(lower), w);
  // The fixed labels pass the label lint (sentence case).
  for (const label of ["Edit peers", "Reset filters", "Why?", "Save current set", "CSV of this view", "Copy as TSV",
    "Copy summary", "Keyboard shortcuts", "Single-key shortcuts", "Why this summary", "Reload the comps",
    "System-generated summary", "Peer set"]) {
    assert.ok(JS.includes(label), label);
    assert.deepEqual(core.lintCopy(label, "label"), [], label);
  }
});

test("shell.css: no colour literal, and every rule is scoped to the shell", () => {
  assert.ok(!/#[0-9a-fA-F]{3,8}\b/.test(CSS_NO_COMMENTS), "no hex colour");
  assert.ok(!/\b(rgb|rgba|hsl|hsla)\(/.test(CSS_NO_COMMENTS), "no rgb or hsl colour");
  const bodies = CSS_NO_COMMENTS.replace(/@media[^{]*\{/g, "");
  const selectors = [];
  for (const m of bodies.matchAll(/([^{}]+)\{[^{}]*\}/g)) {
    for (const sel of m[1].split(",")) if (sel.trim()) selectors.push(sel.trim());
  }
  assert.ok(selectors.length > 100);
  // The bridge-only frame (12.5) sizes html, body and #app itself.
  const stray = selectors.filter((s) => !s.includes(".sh-") && s !== "html:not([data-tokens]) #app" && !s.includes('[data-mode="bridge"]'));
  assert.deepEqual(stray, []);
});

test("shell.css reads only properties that tokens.css, research.css or the shell define", () => {
  const defined = new Set(["ts", "band-h", "main-h"]);          // set on #app by shell.js
  for (const file of ["tokens.css", "research.css"]) {
    const text = fs.readFileSync(path.join(ASSETS, file), "utf8");
    for (const m of text.matchAll(/(--[a-z0-9-]+)\s*:/g)) defined.add(m[1].slice(2));
  }
  const used = new Set(Array.from(CSS_NO_COMMENTS.matchAll(/var\((--[a-z0-9-]+)/g)).map((m) => m[1].slice(2)));
  const unknown = Array.from(used).filter((v) => !defined.has(v));
  assert.deepEqual(unknown, []);
  assert.ok(JS.includes('setProperty("--band-h"') && JS.includes('setProperty("--main-h"') && JS.includes('setProperty("--ts"'));
});

test("the collapse steps of 1.5 exist as classes in both files", () => {
  for (let n = 1; n <= 8; n++) assert.ok(CSS.includes(`.sh-c${n} `), `.sh-c${n}`);
  assert.ok(JS.includes("sh-c${n}"));
  assert.match(JS, /STEP_ROOM = 24/);
});

test("focus goes back to a control's twin after its bar was rebuilt, and before a panel leaves", () => {
  assert.ok(JS.includes("function twinOf(el)"), "twinOf finds the re-rendered element by data-key or id");
  for (const fn of ["closeOverlay", "closeDetail", "closeMethod", "closeMenu"]) {
    const at = JS.indexOf(`function ${fn}(`);
    const body = JS.slice(at, JS.indexOf("\n}\n", at));
    assert.ok(body.includes("twinOf("), `${fn} restores focus through twinOf`);
  }
  // The table keeps its place when the side panel closes (11.2): the shell moves focus with
  // preventScroll before the render that hides the panel.
  const cd = JS.slice(JS.indexOf("function closeDetail("), JS.indexOf("function openMethod("));
  assert.ok(cd.indexOf("focusEl(twinOf(ret))") < cd.indexOf("flush()"), "focus returns before the flush");
  assert.ok(JS.includes("el.focus({preventScroll: true})"));
});

test("an overlay opens in the same task, so type-ahead lands in its input (7.2)", () => {
  const oo = JS.slice(JS.indexOf("function openOverlay("), JS.indexOf("function closeOverlay("));
  assert.ok(oo.includes("flush();"), "openOverlay renders at once");
  assert.ok(oo.indexOf("pending.overlayFocus = kind") < oo.indexOf("flush();"));
});

test("a wheel over the pinned band scrolls #main (1.2)", () => {
  assert.match(JS, /for \(const el of \[ctxEl, bannerRow, kpiRow, scopeRow\]\) \{\s*el\.addEventListener\("wheel"/);
  assert.ok(JS.includes("{passive: true}"));
});
