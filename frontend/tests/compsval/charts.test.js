// Pure geometry and helper tests for charts.js and panels.js (owner D). node --test.
// Nothing here touches the DOM: the helpers under test are the exported pure functions, run
// against hand-built inputs and against core.deriveView on the real fixture payload.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

import * as core from "../../components/compsval/core.js";
import {
  DOT, linearScale, logScale, makeScale, niceStep, decimalsOf, niceTicks, logTicks, ticksFor,
  paddedDomain, fmtValue, tickFormatter, textWidth, stackPoints, placeLabels, dotGeometry, waterfallRows,
  bridgeStripValues, lcfirst, sig,
} from "../../components/compsval/charts.js";
import {
  parseNumberInput, inputText, bridgeMetricOptions, sortPeerRows, searchCompanies, methodTarget, historyValues,
  catalystDate,
} from "../../components/compsval/panels.js";

const PAYLOAD = JSON.parse(fs.readFileSync(new URL("./fixture_payload.json", import.meta.url), "utf8"));
const close = (a, b, eps = 1e-9) => Math.abs(a - b) <= eps * Math.max(1, Math.abs(a), Math.abs(b));

function viewFor(ticker, actions = []) {
  const rec = PAYLOAD.companies.find((c) => c.ticker === ticker);
  let st = core.defaultState(PAYLOAD, {focal: ticker, engine: rec.engine}, null, null);
  for (const a of actions) st = core.reduce(st, a, PAYLOAD);
  // The Table view, where the dot plot, the bridge and the method drawer's sections live.
  return core.deriveView(PAYLOAD, {...st, ui: {...st.ui, view: "table"}});
}

// ------------------------------------------------------------------------------------------
// Scales
// ------------------------------------------------------------------------------------------

test("linearScale maps the domain onto the range and inverts", () => {
  const sc = linearScale([10, 20], [0, 100]);
  assert.equal(sc(10), 0);
  assert.equal(sc(20), 100);
  assert.equal(sc(15), 50);
  assert.ok(close(sc.invert(sc(13.7)), 13.7));
  const rev = linearScale([0, 1], [300, 10]);
  assert.equal(rev(0), 300);
  assert.equal(rev(1), 10);
  assert.equal(sc.kind, "linear");
});

test("linearScale puts a zero-width domain in the middle of the range", () => {
  const sc = linearScale([5, 5], [0, 100]);
  assert.equal(sc(5), 50);
  assert.equal(sc(999), 50);
});

test("logScale spaces decades evenly and falls back to linear for non-positive ends", () => {
  const sc = logScale([1, 1000], [0, 300]);
  assert.ok(close(sc(1), 0));
  assert.ok(close(sc(10), 100));
  assert.ok(close(sc(100), 200));
  assert.ok(close(sc(1000), 300));
  assert.ok(close(sc.invert(sc(42)), 42));
  assert.equal(sc.kind, "log");
  assert.equal(logScale([0, 10], [0, 100]).kind, "linear");
  assert.equal(logScale([-5, 10], [0, 100]).kind, "linear");
  assert.equal(makeScale("log", [1, 10], [0, 1]).kind, "log");
  assert.equal(makeScale("linear", [1, 10], [0, 1]).kind, "linear");
});

// ------------------------------------------------------------------------------------------
// Ticks and domains
// ------------------------------------------------------------------------------------------

test("niceStep picks 1, 2, 2.5 or 5 times a power of ten", () => {
  assert.equal(niceStep(10, 5), 2);
  assert.equal(niceStep(1, 5), 0.2);
  assert.equal(niceStep(25, 5), 5);
  assert.equal(niceStep(12, 5), 2.5);
  assert.equal(niceStep(0, 5), 1);
  assert.equal(niceStep(NaN, 5), 1);
});

test("decimalsOf counts the decimals a value needs", () => {
  assert.equal(decimalsOf(5), 0);
  assert.equal(decimalsOf(2.5), 1);
  assert.equal(decimalsOf(0.05), 2);
  assert.equal(decimalsOf(null), 0);
});

test("niceTicks stay inside the domain on an even step", () => {
  const t = niceTicks(6.14, 31.26, 6);
  assert.deepEqual(t, [10, 15, 20, 25, 30]);
  assert.deepEqual(niceTicks(6.14, 31.26, 5), [10, 20, 30]);
  for (const v of t) assert.ok(v >= 6.14 && v <= 31.26);
  assert.deepEqual(niceTicks(0, 1, 5), [0, 0.2, 0.4, 0.6, 0.8, 1]);
  assert.deepEqual(niceTicks(-0.1, 0.33, 5), [-0.1, 0, 0.1, 0.2, 0.3]);
  assert.deepEqual(niceTicks(-0.1, 0.33, 4), [0, 0.2]);
  assert.deepEqual(niceTicks(3, 3), [3]);
  assert.deepEqual(niceTicks(null, 3), []);
  // Reversed ends are read in order.
  assert.deepEqual(niceTicks(1, 0, 5), [0, 0.2, 0.4, 0.6, 0.8, 1]);
});

test("logTicks give powers of ten, or the 1, 2, 5 sequence inside a short span", () => {
  assert.deepEqual(logTicks(0.5, 2000), [1, 10, 100, 1000]);
  assert.deepEqual(logTicks(2, 8), [2, 5]);
  assert.deepEqual(logTicks(0, 10), []);
  const sc = logScale([1, 1000], [0, 100]);
  assert.deepEqual(ticksFor(sc), [1, 10, 100, 1000]);
});

test("paddedDomain pads min to max by 8 %, in log space for a log scale", () => {
  const d = paddedDomain([10, null, 20, NaN, 15]);
  assert.ok(close(d[0], 9.2) && close(d[1], 20.8));
  const l = paddedDomain([1, 1000], 0.08, true);
  assert.ok(close(Math.log10(l[0]), -0.24) && close(Math.log10(l[1]), 3.24));
  // A single value still gets a span, never a zero-width domain.
  const one = paddedDomain([4]);
  assert.ok(one[0] < 4 && one[1] > 4);
  assert.equal(paddedDomain([]), null);
  assert.equal(paddedDomain([null, undefined]), null);
  // Log drops non-positive values rather than reading them as 0.
  const lp = paddedDomain([-3, 0, 10, 100], 0, true);
  assert.ok(close(lp[0], 10) && close(lp[1], 100));
});

// ------------------------------------------------------------------------------------------
// Formatting
// ------------------------------------------------------------------------------------------

test("fmtValue writes the column format with its unit, and the null glyph for no value", () => {
  assert.equal(fmtValue("pe", 16.2159), "16.2×");
  assert.equal(fmtValue("peg", 1.194), "1.19×");
  assert.equal(fmtValue("fcf_yield", 0.04526), "4.5%");
  assert.equal(fmtValue("market_cap", 259971.4), "260.0");
  assert.equal(fmtValue("pe", null), core.NULL_GLYPH);
  assert.equal(fmtValue("pe", NaN), core.NULL_GLYPH);
  assert.equal(fmtValue("revenue_growth", -0.052), "−5.2%");
});

test("tickFormatter takes its decimals from the tick step", () => {
  const f = tickFormatter("pe", [10, 12.5, 15]);
  assert.equal(f(12.5), "12.5×");
  assert.equal(f(10), "10.0×");
  const g = tickFormatter("revenue_growth", [0, 0.05, 0.1]);
  assert.equal(g(0.05), "5%");
  assert.equal(g(-0.1), "−10%");
  const m = tickFormatter("market_cap", [1000, 10000, 100000], "log");
  assert.equal(m(1000), "1");
  assert.equal(m(100000), "100");
  assert.equal(f(null), core.NULL_GLYPH);
});

test("textWidth grows with the text and the size", () => {
  assert.equal(textWidth(""), 0);
  assert.ok(textWidth("AZN", 12) > textWidth("AZN", 10));
  assert.ok(textWidth("ABBV") > textWidth("AZN"));
});

test("lcfirst lowers a word but keeps acronyms and codes", () => {
  assert.equal(lcfirst("Revenue growth"), "revenue growth");
  assert.equal(lcfirst("EPS growth"), "EPS growth");
  assert.equal(lcfirst("P/E"), "P/E");
  assert.equal(lcfirst(""), "");
});

// ------------------------------------------------------------------------------------------
// Collision: dot stacking and label placement
// ------------------------------------------------------------------------------------------

test("stackPoints splits points within 8 px into rows of 0, -6 and +6", () => {
  const off = stackPoints([100, 104, 106, 200]);
  assert.equal(off.length, 4);
  assert.equal(off[3], 0);
  // The three close points take three different rows.
  assert.equal(new Set(off.slice(0, 3)).size, 3);
  for (const o of off) assert.ok(DOT.stackRows.includes(o));
  // Two points 8 px apart or more share row 0.
  assert.deepEqual(stackPoints([10, 18, 26]), [0, 0, 0]);
  // A pinned point (the focal) keeps row 0 even when a peer sits on it.
  const pinned = stackPoints([50, 50], {pin: [1]});
  assert.equal(pinned[1], 0);
  assert.notEqual(pinned[0], 0);
  // A non-finite x is left at 0.
  assert.deepEqual(stackPoints([NaN, 5]), [0, 0]);
});

test("stackPoints puts a fourth crowded point in the row with most room", () => {
  const off = stackPoints([100, 101, 102, 103]);
  assert.equal(off.length, 4);
  for (const o of off) assert.ok(DOT.stackRows.includes(o));
});

test("placeLabels moves an overlapping label to the next row and drops what does not fit", () => {
  const items = [
    {x: 100, w: 40, anchor: "middle"},
    {x: 110, w: 40, anchor: "middle"},
    {x: 120, w: 40, anchor: "middle"},
    {x: 300, w: 40, anchor: "middle"},
  ];
  const p = placeLabels(items, {rows: 2, gap: 4});
  assert.equal(p[0].row, 0);
  assert.equal(p[1].row, 1);
  assert.equal(p[2].dropped, true);
  assert.equal(p[3].row, 0);
  // A required label always shows, in row 0.
  const q = placeLabels([{x: 100, w: 40, anchor: "middle"}, {x: 102, w: 40, anchor: "middle"}, {x: 104, w: 40, anchor: "middle", required: true}], {rows: 2});
  assert.equal(q[2].dropped, false);
  assert.equal(q[2].row, 0);
  // Labels are clamped inside [min, max].
  const r = placeLabels([{x: 5, w: 50, anchor: "middle"}, {x: 495, w: 50, anchor: "middle"}], {min: 0, max: 500});
  assert.equal(r[0].x0, 0);
  assert.equal(r[1].x1, 500);
  // Anchors: start begins at x, end finishes at x.
  const s = placeLabels([{x: 100, w: 20, anchor: "start"}, {x: 300, w: 20, anchor: "end"}]);
  assert.equal(s[0].x0, 100);
  assert.equal(s[1].x1, 300);
});

// ------------------------------------------------------------------------------------------
// Chart frames on the real view
// ------------------------------------------------------------------------------------------

test("dotGeometry: one lane is 56 + 24 px under the top pad; cohort lanes add the label column", () => {
  const v = viewFor("AZN");
  const dp = v.dotplot;
  assert.equal(dp.lanes.length, 1);
  const g = dotGeometry(dp, 560);
  assert.equal(g.multi, false);
  assert.equal(g.labelW, 0);
  assert.equal(g.height, DOT.top + DOT.laneH + DOT.axisH);
  assert.ok(close(g.scale(dp.domain[0]), g.x0));
  assert.ok(close(g.scale(dp.domain[1]), g.x1));
  // Every plotted point sits inside the plot: clamped values carry the extent.
  for (const p of dp.lanes[0].points) {
    const x = g.scale(p.x);
    assert.ok(x >= g.x0 - 1e-9 && x <= g.x1 + 1e-9, `${p.ticker} at ${x}`);
  }
  const v3 = viewFor("AZN", [{type: "SET_COHORTS", ids: ["system", "all:pharma", "stage"]}]);
  const g3 = dotGeometry(v3.dotplot, 560);
  assert.equal(v3.dotplot.lanes.length, 3);
  assert.equal(g3.multi, true);
  assert.equal(g3.labelW, DOT.laneLabelW);
  assert.equal(g3.height, DOT.top + 3 * DOT.laneH + DOT.axisH);
  assert.ok(g3.laneY(1) - g3.laneY(0) === DOT.laneH);
  // An analyst target range adds its row below the axis.
  const withTarget = dotGeometry({...dp, target: {lo: 14, hi: 16}}, 560);
  assert.equal(withTarget.height, g.height + DOT.targetH);
});

test("dotGeometry uses a log scale for market cap", () => {
  const v = viewFor("AZN", [{type: "SET_DOT_METRIC", colId: "market_cap"}]);
  assert.equal(v.dotplot.scale, "log");
  const g = dotGeometry(v.dotplot, 480);
  assert.equal(g.scale.kind, "log");
});

test("waterfallRows: implied EV from 0, net debt as a floating step, claims when on, equity from 0", () => {
  const rows = waterfallRows({EVi: 289300, ND: 23903, OC: -855, Eq: 289300 - 23903 - 855});
  assert.deepEqual(rows.map((r) => r.id), ["ev", "net_debt", "other_claims", "equity"]);
  assert.deepEqual([rows[0].x0, rows[0].x1], [0, 289300]);
  assert.deepEqual([rows[1].x0, rows[1].x1], [289300, 289300 - 23903]);
  assert.equal(rows[1].label, "Less net debt");
  assert.equal(rows[2].x1, 289300 - 23903 - 855);
  assert.equal(rows[3].x0, 0);
  assert.ok(close(rows[3].x1, rows[2].x1));
  const cash = waterfallRows({EVi: 3000, ND: -1778, OC: null, Eq: 4778});
  assert.equal(cash[1].label, "Plus net cash");
  assert.equal(cash.length, 3);
  assert.deepEqual(waterfallRows({EVi: 3000, ND: null}), []);
  assert.deepEqual(waterfallRows(null), []);
});

test("waterfallRows agrees with core's bridge on the EV/EBITDA route", () => {
  const v = viewFor("AZN", [{type: "SET_BRIDGE", patch: {colId: "ev_ebitda", basis: null, otherClaimsOn: true}}]);
  const b = v.bridge;
  assert.equal(b.enabled, true);
  assert.equal(b.isEV, true);
  const rows = waterfallRows(b);
  assert.ok(close(rows[rows.length - 1].x1, b.Eq, 1e-9));
  assert.ok(close(b.EVi - b.ND + b.OC, b.Eq, 1e-9));
  const vals = bridgeStripValues(b);
  assert.ok(vals.includes(b.V) && vals.includes(b.price));
  assert.ok(vals.every((x) => Number.isFinite(x)));
});

test("bridgeStripValues collects the per-share marks and nothing missing", () => {
  const b = {range: [100, 180], price: 166.15, V: 157.2, streetTarget: {value: 211.07}, modelFairValue: {value: 175.4}};
  assert.deepEqual(bridgeStripValues(b), [100, 180, 166.15, 157.2, 211.07, 175.4]);
  assert.deepEqual(bridgeStripValues({price: 50, V: null, streetTarget: null}), [50]);
  assert.deepEqual(bridgeStripValues(null), []);
});

test("sig ignores the record and analysis objects", () => {
  assert.equal(sig({a: 1, record: {x: 1}}), sig({a: 1, record: {x: 2}}));
  assert.notEqual(sig({a: 1}), sig({a: 2}));
});

// ------------------------------------------------------------------------------------------
// panels.js pure helpers
// ------------------------------------------------------------------------------------------

test("catalystDate prints a month-only date as its month (company-scorecard.md 4.1)", () => {
  // The payload keeps "YYYY-MM" for a month the registry gives without a day, so the panel
  // reads "Nov 2026" as Catalysts and Key insights do, never a dash.
  assert.equal(catalystDate({expected_date: "2026-11", date_confidence: "month"}), "Nov 2026");
  assert.equal(catalystDate({expected_date: null, date_confidence: "month"}), "·");
  assert.match(catalystDate({expected_date: "2026-12-15"}), /2026/);
});

test("the panel title's focus ring is for the keyboard only", () => {
  // Focus moves to the title when the panel opens; on a mouse open the ring drew a box.
  const css = fs.readFileSync(new URL("../../components/compsval/panels.css", import.meta.url), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "");
  assert.match(css, /\.pn-d-title:focus-visible\s*\{[^}]*outline:\s*2px solid/);
  assert.match(css, /\.pn-d-title:focus\s*\{\s*outline:\s*none;?\s*\}/);
});

test("parseNumberInput reads analyst input without guessing", () => {
  assert.equal(parseNumberInput("1,234.5"), 1234.5);
  assert.equal(parseNumberInput("−3.2"), -3.2);
  assert.equal(parseNumberInput(" 12 "), 12);
  assert.equal(parseNumberInput("15.3×"), 15.3);
  assert.equal(parseNumberInput("4.5%"), 4.5);
  assert.equal(parseNumberInput(".5"), 0.5);
  assert.equal(parseNumberInput(""), null);
  assert.equal(parseNumberInput(null), null);
  assert.ok(Number.isNaN(parseNumberInput("abc")));
  assert.ok(Number.isNaN(parseNumberInput("1.2.3")));
});

test("inputText writes a plain editable number", () => {
  assert.equal(inputText(15.339399, 2), "15.34");
  assert.equal(inputText(10.25, 2), "10.25");
  assert.equal(inputText(-23903.4, 0), "-23903");
  assert.equal(inputText(null), "");
  assert.equal(inputText(NaN), "");
});

test("bridgeMetricOptions lists each bridgeable column on each of its bases", () => {
  const opts = bridgeMetricOptions({fy0Label: "FY2025", fy1Label: "FY2026", fy2Label: "FY2027"});
  const ids = opts.map((o) => o.id);
  for (const c of core.BRIDGEABLE) assert.ok(opts.some((o) => o.colId === c), c);
  assert.ok(ids.includes("pe|NTM") && ids.includes("pe|FY0") && ids.includes("pe|LTM"));
  assert.ok(ids.includes("ev_ebitda|FY0"));
  assert.ok(ids.includes("price_to_book|"));
  assert.equal(new Set(ids).size, ids.length);
  // The view's bridge selects one of them.
  const b = viewFor("AZN").bridge;
  assert.ok(ids.includes(`${b.colId}|${b.basis && b.basis !== "-" ? b.basis : ""}`));
});

test("sortPeerRows sorts by a column and keeps ties stable by ticker", () => {
  const rows = viewFor("AZN").peers.rows;
  const desc = sortPeerRows(rows, {key: "relevance", dir: "desc"});
  for (let i = 1; i < desc.length; i++) assert.ok(desc[i - 1].relevance.score >= desc[i].relevance.score);
  const asc = sortPeerRows(rows, {key: "relevance", dir: "asc"});
  // Ties break by ticker in both directions, so the ends agree on the score, not the ticker.
  assert.equal(asc[0].relevance.score, desc[desc.length - 1].relevance.score);
  const byT = sortPeerRows(rows, {key: "ticker", dir: "asc"});
  assert.deepEqual(byT.map((r) => r.ticker), rows.map((r) => r.ticker).slice().sort());
  assert.deepEqual(sortPeerRows(rows, null).map((r) => r.ticker), rows.map((r) => r.ticker));
  assert.notEqual(sortPeerRows(rows, null), rows);
});

test("searchCompanies ranks a ticker prefix over a name match", () => {
  const list = [{ticker: "AZN", name: "AstraZeneca PLC"}, {ticker: "AMGN", name: "Amgen Inc"},
    {ticker: "GILD", name: "Gilead Sciences"}, {ticker: "SNY", name: "Sanofi"}, {ticker: "ZAZ", name: "Az Holdings"}];
  const r = searchCompanies(list, "az");
  assert.equal(r[0].ticker, "AZN");
  assert.ok(r.some((c) => c.ticker === "ZAZ"));
  assert.deepEqual(searchCompanies(list, "sci").map((c) => c.ticker), ["GILD"]);
  assert.deepEqual(searchCompanies(list, ""), []);
  assert.equal(searchCompanies(list, "a", 2).length, 2);
});

test("methodTarget resolves sections, aliases and column definitions", () => {
  const ids = viewFor("AZN").method.sections.map((s) => s.id);
  assert.deepEqual(methodTarget("outliers", ids), {section: "outliers", colId: null});
  assert.deepEqual(methodTarget("pe", ids), {section: "definitions", colId: "pe"});
  assert.deepEqual(methodTarget("def:ev_ebitda", ids), {section: "definitions", colId: "ev_ebitda"});
  assert.deepEqual(methodTarget("statistics", ids), {section: "stats", colId: null});
  assert.deepEqual(methodTarget("nowhere", ids), {section: ids[0], colId: null});
  assert.deepEqual(methodTarget(null, ids), {section: ids[0], colId: null});
});

test("historyValues drops n.m. years instead of clamping them", () => {
  assert.deepEqual(historyValues([0.09, 12.77, null, -0.9, 6], "revenue_growth"), [0.09, null, null, -0.9, null]);
  assert.deepEqual(historyValues([0.17, -1.4, -0.2], "net_margin"), [0.17, null, -0.2]);
  assert.deepEqual(historyValues(null, "net_margin"), []);
});
