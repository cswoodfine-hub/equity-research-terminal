// Tests for frontend/components/compsval/scorecard.js and scorecard.css (company-scorecard.md 3.4,
// 4.2, 7.2). Run: node --test "*.test.js" from this folder. No DOM here: the chart's bindings are
// pure functions over anything with closest(), getAttribute() and classList, so a few stand-ins
// carry the events, and core.reduce and core.deriveView carry the state the frame would hold.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

import * as core from "../../components/compsval/core.js";
import {chartAction, runChartAction, togglePick, markChart, cellStyle, SHORT_FRAME} from "../../components/compsval/scorecard.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const COMP = path.join(HERE, "../../components/compsval");
const ASSETS = path.join(HERE, "../../assets");
const JS = fs.readFileSync(path.join(COMP, "scorecard.js"), "utf8");
const CSS = fs.readFileSync(path.join(COMP, "scorecard.css"), "utf8");
const CSS_NO_COMMENTS = CSS.replace(/\/\*[\s\S]*?\*\//g, "");
const PAYLOAD = JSON.parse(fs.readFileSync(path.join(HERE, "fixture_payload.json"), "utf8"));
const SC_PATH = path.join(HERE, "../../../backend/tests/fixtures/company_score/sample_scorecard.json");
const SCORECARD = fs.existsSync(SC_PATH) ? JSON.parse(fs.readFileSync(SC_PATH, "utf8")) : null;
const P = SCORECARD ? {...PAYLOAD, scorecard: SCORECARD} : null;

/** A stand-in element: classes, attributes, a parent chain for closest(). */
function el(cls, attrs = {}, parent = null) {
  const classes = new Set(cls.split(" ").filter(Boolean));
  const a = {...attrs};
  return {
    parent,
    classList: {
      contains: (c) => classes.has(c),
      toggle: (c, on) => { if (on === undefined ? !classes.has(c) : on) classes.add(c); else classes.delete(c); },
      has: (c) => classes.has(c),
    },
    getAttribute: (k) => (k in a ? a[k] : null),
    setAttribute: (k, v) => { a[k] = String(v); },
    closest(sel) {
      const want = sel.replace(/^\./, "");
      for (let n = this; n; n = n.parent) if (n.classList.contains(want)) return n;
      return null;
    },
  };
}
/** The frame's state and view, moved by the same dispatch the shell runs. */
function frame(focal) {
  let state = core.defaultState(P, {focal, engine: ""}, null, null);
  const calls = [];
  const ctx = {
    getState: () => state,
    dispatch: (a) => { calls.push(a); state = core.reduce(state, a, P); },
    openDetail: (t) => ctx.dispatch({type: "OPEN_DETAIL", ticker: t}),
    announce: (t) => calls.push({announce: t}),
    toast: (t) => calls.push({toast: t}),
  };
  return {ctx, calls, view: () => core.deriveView(P, state), state: () => state};
}

test("chartAction: a click or Enter on a bubble opens it, Space picks it, a label opens its company", () => {
  const g = el("cm-pt", {"data-ticker": "LLY"});
  const dot = el("cm-dot", {}, g);
  assert.deepEqual(chartAction(dot, "click"), {kind: "open", ticker: "LLY"});
  assert.deepEqual(chartAction(g, "Enter"), {kind: "open", ticker: "LLY"});
  assert.deepEqual(chartAction(g, " "), {kind: "pick", ticker: "LLY"});
  const label = el("cm-label", {"data-ticker": "PFE"});
  assert.deepEqual(chartAction(label, "click"), {kind: "open", ticker: "PFE"});
  assert.equal(chartAction(label, " "), null, "Space on a label picks nothing");
  assert.equal(chartAction(el("grid-line"), "click"), null);
  assert.equal(chartAction(null, "click"), null);
  assert.equal(chartAction(g, "x"), null);
});

test("clicking .cm-pt opens the company panel", {skip: !P}, () => {
  const f = frame("AZN");
  const dot = el("cm-dot", {}, el("cm-pt", {"data-ticker": "LLY"}));
  assert.equal(runChartAction(chartAction(dot, "click"), f.ctx), true);
  const v = f.view();
  assert.equal(v.detail.ticker, "LLY");
  assert.equal(v.detail.scorecard.state, "ok");
  assert.equal(v.scorecard.rows.find((r) => r.ticker === "LLY").open, true);
  // The bubble is marked open, so the frame draws its ring.
  const g = el("cm-pt", {"data-ticker": "LLY"});
  markChart({querySelectorAll: () => [g]}, v.scorecard);
  assert.ok(g.classList.has("is-open"));
});

test("Space toggles is-picked on a bubble, and a fourth pick is refused", {skip: !P}, () => {
  const f = frame("AZN");
  const bubbles = ["AZN", "LLY", "PFE", "VRTX"].map((t) => el("cm-pt", {"data-ticker": t}));
  const root = {querySelectorAll: (sel) => (sel === ".cm-pt" ? bubbles : [])};
  const [, lly, pfe, vrtx] = bubbles;
  markChart(root, f.view().scorecard);
  assert.ok(bubbles[0].classList.has("is-picked"), "the open company is ticked when the view opens");
  assert.ok(!lly.classList.has("is-picked"));
  runChartAction(chartAction(lly, " "), f.ctx);
  markChart(root, f.view().scorecard);
  assert.ok(lly.classList.has("is-picked"));
  assert.equal(lly.getAttribute("aria-pressed"), "true");
  runChartAction(chartAction(lly, " "), f.ctx);
  markChart(root, f.view().scorecard);
  assert.ok(!lly.classList.has("is-picked"), "Space again unticks it");
  runChartAction(chartAction(lly, " "), f.ctx);
  runChartAction(chartAction(pfe, " "), f.ctx);
  assert.equal(togglePick(f.ctx, "VRTX"), false);
  markChart(root, f.view().scorecard);
  assert.ok(!vrtx.classList.has("is-picked"));
  assert.ok(f.calls.some((c) => c.toast === "Compare takes up to three. Untick one first."));
  assert.deepEqual(f.state().ui.compare, ["AZN", "LLY", "PFE"]);
  assert.equal(f.view().scorecard.compareLabel, "Compare 3");
  assert.equal(f.view().scorecard.compareEnabled, true);
});

test("cellStyle hands the shade to the stylesheet as --sc-a, and nothing for an unshaded cell", () => {
  assert.deepEqual(cellStyle({fill: "up", alpha: 0.459}), {"--sc-a": "0.459"});
  assert.equal(cellStyle({fill: null, alpha: 0}), null);
  assert.equal(SHORT_FRAME, 600);
});

test("scorecard.js copy: no em dash, no banned word; no colour literal", () => {
  assert.ok(!JS.includes("—"), "no em dash");
  const lower = JS.toLowerCase();
  for (const w of core.BANNED_WORDS) assert.ok(!new RegExp(`\\b${w}\\b`).test(lower), w);
  assert.ok(!/#[0-9a-fA-F]{3,8}\b/.test(JS.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "")), "no hex colour");
  // "Table" and "Scorecard" are the names of the two views (8.1), so they keep their capital.
  for (const label of ["Open the Table view", "Scorecard unavailable"]) assert.deepEqual(core.lintCopy(label, "label", ["Table"]), [], label);
});

test("scorecard.css: tokens only, and every rule scoped to the scorecard, the map or Compare", () => {
  assert.ok(!/#[0-9a-fA-F]{3,8}\b/.test(CSS_NO_COMMENTS), "no hex colour");
  assert.ok(!/\b(rgb|rgba|hsl|hsla)\(/.test(CSS_NO_COMMENTS), "no rgb or hsl colour");
  assert.ok(!/\bblue\b/i.test(CSS_NO_COMMENTS), "no blue");
  const selectors = [];
  for (const m of CSS_NO_COMMENTS.replace(/@media[^{]*\{/g, "").matchAll(/([^{}]+)\{[^{}]*\}/g)) {
    for (const sel of m[1].split(",")) if (sel.trim()) selectors.push(sel.trim());
  }
  assert.ok(selectors.length > 40);
  const stray = selectors.filter((s) => !/\.(sc|cm|cmp)-/.test(s) && !s.startsWith('#app[data-view="scorecard"]'));
  assert.deepEqual(stray, []);
  const defined = new Set(["ts", "band-h", "main-h", "sc-a", "sc-under"]);
  for (const file of ["tokens.css", "research.css"]) {
    const text = fs.readFileSync(path.join(ASSETS, file), "utf8");
    for (const m of text.matchAll(/(--[a-z0-9-]+)\s*:/g)) defined.add(m[1].slice(2));
  }
  const used = new Set(Array.from(CSS_NO_COMMENTS.matchAll(/var\((--[a-z0-9-]+)/g)).map((m) => m[1].slice(2)));
  assert.deepEqual(Array.from(used).filter((v) => !defined.has(v)), []);
  // The rings the frame shows are the TEXT ring Python drew, made visible by class.
  assert.match(CSS, /\.cm-pt\.is-open \.cm-ring/);
  assert.match(CSS, /\.cm-pt\.is-picked \.cm-ring/);
});

test("Compare: the best mark stays visible on a shaded cell, and the pinned head keeps its rule", () => {
  // An UP mark on an UP fill at 0.85 vanished (LLY's growth 100): on a shaded cell it is TEXT.
  assert.match(CSS_NO_COMMENTS, /\.cmp-best\s*\{\s*color:\s*var\(--up\)/);
  assert.match(CSS_NO_COMMENTS, /\.cmp-shade \.cmp-best\s*\{\s*color:\s*var\(--text\)/);
  // A collapsed border stays with the table when the head sticks, so the scrolled rows'
  // shading ran up under the head with no rule: borders are the cells' own.
  const table = /\.cmp-table\s*\{([^}]*)\}/.exec(CSS_NO_COMMENTS)[1];
  assert.match(table, /border-collapse:\s*separate/);
  const head = /\.cmp-table thead th\s*\{([^}]*)\}/.exec(CSS_NO_COMMENTS)[1];
  assert.match(head, /position:\s*sticky/);
  assert.match(head, /background:\s*var\(--ground\)/);
  assert.match(head, /border-bottom:\s*1px solid var\(--rule-strong\)/);
});
