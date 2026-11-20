// Pure tests for figures.js: the Figures view arranges the cells the Table view prints and
// computes nothing of its own, so every number here is checked against `view.table`. node --test.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

import * as core from "../../components/compsval/core.js";
import {
  measures, withUnit, tone, distanceText, position, domainOf, profileRows, rankedBars, gridModel,
} from "../../components/compsval/figures.js";

const PAYLOAD = JSON.parse(fs.readFileSync(new URL("./fixture_payload.json", import.meta.url), "utf8"));
const FOCAL = PAYLOAD.companies.find((c) => c.ticker === "AZN") ? "AZN" : PAYLOAD.companies[0].ticker;

function viewFor(ticker, actions = [], uiView = "figures") {
  const rec = PAYLOAD.companies.find((c) => c.ticker === ticker);
  let st = core.defaultState(PAYLOAD, {focal: ticker, engine: rec.engine}, null, null);
  for (const a of actions) st = core.reduce(st, a, PAYLOAD);
  return core.deriveView(PAYLOAD, {...st, ui: {...st.ui, view: uiView}});
}
const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const plotted = (cell) => !!cell && cell.status === "ok" && isNum(cell.v);

test("Figures is a view of its own, between the scorecard and the table, and shares the comparables' drawer", () => {
  assert.deepEqual(core.VIEWS, ["scorecard", "figures", "table"]);
  assert.deepEqual(core.COMPS_VIEWS, ["figures", "table"]);
  assert.equal(core.SCORECARD_COPY.views.figures, "Figures");
  const rec = PAYLOAD.companies.find((c) => c.ticker === FOCAL);
  let st = core.defaultState(PAYLOAD, {focal: FOCAL, engine: rec.engine}, null, null);
  st = core.reduce(st, {type: "SET_VIEW", value: "table"}, PAYLOAD);
  st = {...st, ui: {...st.ui, peers: true}};
  st = core.reduce(st, {type: "SET_VIEW", value: "figures"}, PAYLOAD);
  assert.equal(st.ui.view, "figures");
  assert.equal(st.ui.peers, true, "the peer drawer stays open across the two comparables views");
  st = core.reduce(st, {type: "SET_VIEW", value: "scorecard"}, PAYLOAD);
  assert.equal(st.ui.peers, false);
  assert.equal(viewFor(FOCAL).uiView, "figures");
});

test("the figures and the table share one methodology, and the scorecard keeps its own", () => {
  const ids = (v) => v.method.sections.map((x) => x.id);
  assert.deepEqual(ids(viewFor(FOCAL, [], "figures")), ids(viewFor(FOCAL, [], "table")));
  assert.ok(ids(viewFor(FOCAL, [], "figures")).length > ids(viewFor(FOCAL, [], "scorecard")).length);
});

test("the first figure has one row a measure of the preset, in the table's order", () => {
  for (const preset of core.PRESETS.filter((p) => p.id !== "custom")) {
    const view = viewFor(FOCAL, [{type: "SET_PRESET", preset: preset.id}]);
    const rows = profileRows(view.table);
    assert.deepEqual(rows.map((r) => r.colId), measures(view.table).map((c) => c.id), preset.id);
    assert.ok(rows.length > 0, preset.id);
  }
});

test("every number in the first figure is the table's own", () => {
  const view = viewFor(FOCAL);
  const table = view.table;
  const focal = table.rows.find((r) => r.isFocal);
  const medianRow = table.summary.find((s) => s.id === "median");
  for (const row of profileRows(table)) {
    const cell = focal.cells[row.colId];
    const col = table.columns.find((c) => c.id === row.colId);
    if (plotted(cell)) {
      assert.equal(row.focal.v, cell.v, row.colId);
      assert.equal(row.focal.text, withUnit(core.fmtCell(cell, core.COLUMN_BY_ID[row.colId]), col), row.colId);
    } else {
      assert.equal(row.focal.v, null, row.colId);
      assert.equal(row.focal.pos, null, row.colId);
      assert.equal(row.distance, "", row.colId);
    }
    if (row.median) {
      assert.equal(row.median.v, table.stats[row.colId].median, row.colId);
      assert.equal(row.median.v, medianRow.cells[row.colId].v, row.colId);
    }
    if (plotted(cell) && row.median) {
      assert.equal(row.vsMedian, cell.vsMedian, row.colId);
      assert.equal(row.distance, distanceText(cell.vsMedian), row.colId);
    }
    // the rank is among the peers in the statistics, largest first
    if (row.rank) {
      const counted = table.rows.filter((r) => !r.isFocal && !r.excluded && plotted(r.cells[row.colId]));
      assert.equal(row.of, counted.length + 1, row.colId);
      assert.equal(row.rank, 1 + counted.filter((r) => r.cells[row.colId].v > cell.v).length, row.colId);
    }
  }
});

test("a cell the table prints as not meaningful or not available is never drawn", () => {
  let seen = 0;
  for (const preset of core.PRESETS.filter((p) => p.id !== "custom")) {
    const view = viewFor(FOCAL, [{type: "SET_PRESET", preset: preset.id}]);
    const table = view.table;
    const peers = table.rows.filter((r) => !r.isFocal);
    for (const row of profileRows(table)) {
      const drawn = peers.filter((r) => plotted(r.cells[row.colId]));
      assert.deepEqual(row.peers.map((p) => p.ticker).sort(), drawn.map((r) => r.ticker).sort(), row.colId);
      assert.equal(row.missing, peers.length - drawn.length, row.colId);
      seen += row.missing;
      for (const p of row.peers) assert.ok(isNum(p.pos) && p.pos >= 0 && p.pos <= 100, `${row.colId} ${p.ticker}`);
      const bars = rankedBars(table, row.colId);
      assert.equal(bars.bars.length + bars.missing.length, table.rows.length, row.colId);
      for (const m of bars.missing) assert.ok(!plotted(table.rows.find((r) => r.ticker === m.ticker).cells[row.colId]));
    }
    const grid = gridModel(table);
    grid.rows.forEach((r, i) => r.cells.forEach((c, j) => {
      const cell = table.rows[i].cells[grid.columns[j].id];
      if (!plotted(cell)) { assert.equal(c.shade, null); assert.equal(c.pct, null); }
      else if (c.shade !== null) assert.ok(c.shade >= 0 && c.shade <= 1);
    }));
  }
  assert.ok(seen > 0, "the fixture holds at least one cell with no figure, so the rule was exercised");
});

test("the second figure ranks every company with a figure, largest first, on a scale that holds nil", () => {
  const view = viewFor(FOCAL);
  for (const col of measures(view.table)) {
    const model = rankedBars(view.table, col.id);
    const values = model.bars.map((b) => b.v);
    assert.deepEqual(values, values.slice().sort((a, b) => b - a), col.id);
    if (!model.bars.length) continue;
    assert.ok(model.domain[0] <= 0 && model.domain[1] >= 0, col.id);
    assert.ok(model.zero >= 0 && model.zero <= 100, col.id);
    assert.equal(model.bars.filter((b) => b.isFocal).length <= 1, true);
  }
  assert.equal(rankedBars(view.table, "no_such_column").colId, measures(view.table)[0].id);
});

test("colour means direction only where a measure has a better end", () => {
  assert.equal(tone({dir: "+"}, 0.2), "up");
  assert.equal(tone({dir: "+"}, -0.2), "down");
  assert.equal(tone({dir: "-"}, 0.2), "down");
  assert.equal(tone({dir: "-"}, -0.2), "up");
  assert.equal(tone({dir: "n"}, 0.5), "none");          // a premium is a premium
  assert.equal(tone({dir: "+"}, 0), "none");
  assert.equal(tone({dir: "+"}, null), "none");
  const view = viewFor(FOCAL);
  const grid = gridModel(view.table);
  grid.columns.forEach((c, j) => {
    for (const r of grid.rows) {
      const cell = r.cells[j];
      if (c.dir === "n") assert.equal(cell.tone, "size", c.id);
      else assert.ok(["up", "down", "none"].includes(cell.tone), c.id);
    }
  });
});

test("the small helpers", () => {
  assert.equal(distanceText(0.052), "+5%");
  assert.equal(distanceText(-0.118), "−12%");
  assert.equal(distanceText(0.001), "at median");
  assert.equal(distanceText(null), "");
  assert.equal(position(5, [0, 10]), 50);
  assert.equal(position(-5, [0, 10]), 0);
  assert.equal(position(5, [5, 5]), 50);
  assert.equal(position(null, [0, 10]), null);
  assert.deepEqual(domainOf([]), null);
  const d = domainOf([10, 20]);
  assert.ok(d[0] < 10 && d[1] > 20);
  assert.equal(withUnit("16.2", {unitText: "×"}), "16.2×");
  assert.equal(withUnit("8.6", {unitText: "%"}), "8.6%");
  assert.equal(withUnit("n.m.", {unitText: "×"}), "n.m.");
  assert.equal(withUnit("292.0", {unitText: "USD bn"}), "292.0");
});
