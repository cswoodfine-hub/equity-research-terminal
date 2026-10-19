// Tests for the pure helpers of frontend/components/compsval/table.js (spec section 4).
// Run: node --test "*.test.js" from this folder. The DOM part (mountTable) is not loaded here.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

import * as core from "../../components/compsval/core.js";
import * as table from "../../components/compsval/table.js";

const {
  BASE_IDS, LAYOUT_WIDTHS, MAX_PINS, AUTO_WIDTH_MAX, AUTO_WIDTH_PRIMARY_MAX, layoutColumns, headerWidth, groupRuns,
  visibleSummaryIds, placeFocal, markerFor, cellReasonText, periodText, cellTip, describeCell, relevanceLines,
  sourceText, unitLineText, filterShort, parseFilterValue, sortSteps, moveActive, cellDomId,
  sparkPoints, findColumns, esc, autoPinsPrimary, normLayout, boxHeightFor,
} = table;

const HERE = path.dirname(fileURLToPath(import.meta.url));
const load = (name) => {
  const p = path.join(HERE, name);
  return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, "utf8")) : null;
};
const PAYLOAD = load("fixture_payload.json") || load("fixture_min.json");
const SRC_DIR = path.join(HERE, "../../components/compsval");

function viewFor(focal, actions = []) {
  let st = core.defaultState(PAYLOAD, {focal, engine: ""});
  for (const a of actions) st = core.reduce(st, a, PAYLOAD);
  return {state: st, view: core.deriveView(PAYLOAD, st)};
}
const sum = (cols) => cols.reduce((s, c) => s + c.width, 0);
const ids = (cols) => cols.map((c) => c.id);

// A stub column list in the shape of view.table.columns.
function stubCols(extra = []) {
  const base = core.FROZEN_BASE.map((b) => ({id: b.id, group: "company", label: b.label, width: b.width, frozen: true,
    autoPinned: false, isPrimary: false, numeric: false, unitLine: ""}));
  const mk = (id, o = {}) => ({id, group: core.COLUMN_BY_ID[id].group, label: core.COLUMN_BY_ID[id].label,
    width: core.COLUMN_BY_ID[id].width, frozen: false, autoPinned: false, isPrimary: false, numeric: true,
    unitLine: "× · calc.", ...o});
  return base.concat(extra.map((e) => (typeof e === "string" ? mk(e) : mk(e.id, e))));
}

// ----- 4.1 frozen block ---------------------------------------------------------------------

test("base block widths match the spec's frozen budgets per layout", () => {
  for (const [layout, want] of [["wide", 332], ["ultrawide", 332], ["narrow", 248]]) {
    const L = layoutColumns(stubCols(["market_cap", "ev"]), layout, {});
    assert.deepEqual(ids(L.cols).slice(0, 5), BASE_IDS);
    assert.equal(L.frozenWidth, want, layout);
    assert.equal(L.frozenCount, 5, layout);
  }
  // Laptop and narrow add the auto-pinned primary: 384 and 328 (spec 4.1).
  const cols = stubCols(["market_cap", {id: "pe", autoPinned: true, isPrimary: true}, "ev"]);
  const lap = layoutColumns(cols, "laptop", {});
  assert.equal(lap.frozenWidth, 384);
  assert.deepEqual(ids(lap.cols).slice(0, 6), BASE_IDS.concat(["pe"]));
  assert.equal(lap.cols[5].pin, "auto");
  assert.equal(lap.cols[5].width, 84);
  const nar = layoutColumns(cols, "narrow", {});
  assert.equal(nar.frozenWidth, 328);
  assert.equal(nar.cols[5].width, 80);
  assert.equal(core.FROZEN_BASE_WIDTH.laptop, 384);
  assert.equal(core.FROZEN_BASE_WIDTH.narrow, 328);
});

test("the primary keeps its preset position at wide and is not frozen there", () => {
  const cols = stubCols(["market_cap", {id: "pe", autoPinned: true, isPrimary: true}, "ev"]);
  const L = layoutColumns(cols, "wide", {});
  assert.deepEqual(ids(L.cols), BASE_IDS.concat(["market_cap", "pe", "ev"]));
  assert.equal(L.cols.find((c) => c.id === "pe").frozen, false);
  assert.equal(autoPinsPrimary("wide"), false);
  assert.equal(autoPinsPrimary("laptop"), true);
  assert.equal(normLayout("nonsense"), "wide");
});

test("frozen left offsets accumulate over the frozen columns only", () => {
  const L = layoutColumns(stubCols(["market_cap"]), "wide", {});
  assert.deepEqual(L.cols.slice(0, 5).map((c) => c.left), [0, 20, 48, 92, 268]);
  assert.equal(L.cols[5].left, null);
});

test("manual pins: two at wide, one at laptop, none at narrow, within 40% of the box", () => {
  const cols = stubCols([{id: "market_cap", frozen: true}, {id: "ev", frozen: true}, {id: "beta", frozen: true}, "pe"]);
  const wide = layoutColumns(cols, "wide", {boxWidth: 2000});
  assert.deepEqual(wide.cols.filter((c) => c.pin === "manual").map((c) => c.id), ["market_cap", "ev"]);
  assert.equal(wide.cols.find((c) => c.id === "beta").pin, "manual-off");
  assert.equal(wide.cols.find((c) => c.id === "beta").frozen, false);
  assert.equal(wide.frozenWidth, 332 + 84 + 84);
  assert.equal(layoutColumns(cols, "laptop", {boxWidth: 2000}).cols.filter((c) => c.pin === "manual").length, MAX_PINS.laptop);
  assert.equal(layoutColumns(cols, "narrow", {boxWidth: 2000}).cols.filter((c) => c.pin === "manual").length, 0);
  // 40% of 1000 is 400: the base block (332) leaves no room for an 84 px pin.
  const tight = layoutColumns(cols, "wide", {boxWidth: 1000});
  assert.equal(tight.frozenWidth, 332);
  assert.ok(tight.frozenWidth <= core.FROZEN_MAX_SHARE * 1000);
  // Unfrozen pins keep their place ahead of the preset's columns.
  assert.deepEqual(ids(tight.cols).slice(5), ["market_cap", "ev", "beta", "pe"]);
});

test("an analyst width wins over the layout width and the header fit", () => {
  const cols = stubCols(["market_cap", {id: "loe_share_5y", unitLine: "% · calc."}]);
  const L = layoutColumns(cols, "laptop", {widths: {company: 200, market_cap: 140}});
  assert.equal(L.cols.find((c) => c.id === "company").width, 200);
  assert.equal(L.cols.find((c) => c.id === "market_cap").width, 140);
  assert.equal(L.cols.find((c) => c.id === "ticker").width, LAYOUT_WIDTHS.laptop.ticker);
});

test("headerWidth fits the label and unit line between the catalogue width and the cap", () => {
  assert.equal(headerWidth({label: "P/B", unitLine: "× · calc.", width: 84}), 84);
  const long = headerWidth({label: "Losing exclusivity 5y", unitLine: "% · calc.", width: 96});
  assert.ok(long > 96 && long <= AUTO_WIDTH_MAX);
  assert.equal(headerWidth({label: "P/E", unitLine: "× · NTM street E · calc. · Primary", width: 84, isPrimary: true}), AUTO_WIDTH_PRIMARY_MAX);
  assert.equal(headerWidth({label: "x".repeat(60), unitLine: "", width: 84}), AUTO_WIDTH_MAX);
  assert.equal(headerWidth({label: "Wide by hand", unitLine: "", width: 300}), 300);
});

test("groupRuns splits a group at the end of the frozen block", () => {
  const L = layoutColumns(stubCols(["market_cap", "ev", "pe", "ev_ebitda", "revenue_growth"]), "wide", {});
  const runs = groupRuns(L.cols);
  assert.deepEqual(runs.map((r) => [r.label, r.span, r.frozen]), [
    ["Company", 5, true], ["Company", 2, false], ["Valuation", 2, false], ["Growth", 1, false]]);
  assert.equal(runs[0].left, 0);
  assert.equal(runs.reduce((s, r) => s + r.span, 0), L.cols.length);
  // Group starts are marked after the first unfrozen column, never at the frozen edge.
  assert.equal(L.cols.find((c) => c.id === "market_cap").groupStart, false);
  assert.equal(L.cols.find((c) => c.id === "pe").groupStart, true);
});

test("the real view lays out at every layout with the primary frozen only when narrow or laptop", {skip: !PAYLOAD}, () => {
  const {view, state} = viewFor("AZN");
  const prim = view.table.columns.find((c) => c.isPrimary);
  assert.ok(prim, "AZN has a primary column");
  for (const layout of ["ultrawide", "wide", "laptop", "narrow"]) {
    const L = layoutColumns(view.table.columns, layout, {widths: state.widths, boxWidth: 1200});
    assert.equal(L.cols.length, view.table.columns.length, layout);
    assert.deepEqual([...new Set(ids(L.cols))].sort(), ids(view.table.columns).slice().sort(), layout);
    const frozen = L.cols.filter((c) => c.frozen);
    assert.equal(sum(frozen), L.frozenWidth, layout);
    assert.equal(frozen.some((c) => c.id === prim.id), autoPinsPrimary(layout), layout);
    assert.ok(L.cols.every((c) => Number.isFinite(c.width) && c.width > 0), layout);
  }
});

test("boxHeightFor keeps the summary rows in view at rest and fills #main once scrolled to", () => {
  // Spec 1.6, 1440 x 810: #main 391, chart strip and toolbar put the box 160 px down.
  assert.equal(boxHeightFor(391, 160), 223);
  assert.equal(boxHeightFor(391, 0), 391);
  assert.equal(boxHeightFor(391, 4), 383);
  assert.equal(boxHeightFor(481, 56), 417);
  // Far below the fold the box keeps a usable minimum; a box scrolled past the top keeps all of #main.
  assert.equal(boxHeightFor(391, 380), 180);
  assert.equal(boxHeightFor(391, -200), 391);
  assert.equal(boxHeightFor(120, 60), 120);
  assert.equal(boxHeightFor(0, 0), null);
  assert.equal(boxHeightFor(NaN, 0), null);
  // It grows monotonically as #main scrolls the box towards its top.
  let last = 0;
  for (let off = 300; off >= 0; off -= 10) { const h = boxHeightFor(500, off); assert.ok(h >= last); last = h; }
});

// ----- 4.6 summary rows, 4.7 focal row ------------------------------------------------------

test("visibleSummaryIds: five rows at wide, median and n at laptop until expanded", () => {
  const all = ["mean", "median", "p25", "p75", "n"];
  assert.deepEqual(visibleSummaryIds(all, "wide", false), all);
  assert.deepEqual(visibleSummaryIds(all, "ultrawide", false), all);
  assert.deepEqual(visibleSummaryIds(all, "laptop", false), ["median", "n"]);
  assert.deepEqual(visibleSummaryIds(all, "narrow", true), all);
  assert.deepEqual(visibleSummaryIds(["n"], "laptop", false), ["n"]);
  assert.deepEqual(visibleSummaryIds(null, "wide", false), []);
});

test("placeFocal keeps the focal first while pinned and sorts it in when unpinned", () => {
  const c = (t, v, status = "ok") => ({ticker: t, v, status, text: String(v)});
  const rows = [
    {ticker: "F", isFocal: true, cells: {pe: c("F", 15)}},
    {ticker: "A", cells: {pe: c("A", 30)}},
    {ticker: "B", cells: {pe: c("B", 20)}},
    {ticker: "C", cells: {pe: c("C", 10)}},
    {ticker: "D", cells: {pe: c("D", null, "nm")}},
  ];
  const order = (r) => r.map((x) => x.ticker).join("");
  assert.equal(order(placeFocal(rows, {colId: "pe", dir: "desc"}, true)), "FABCD");
  assert.equal(order(placeFocal(rows, null, false)), "FABCD");
  assert.equal(order(placeFocal(rows, {colId: "pe", dir: "desc"}, false)), "ABFCD");
  const asc = [rows[0], rows[3], rows[2], rows[1], rows[4]];
  assert.equal(order(placeFocal(asc, {colId: "pe", dir: "asc"}, false)), "CFBAD");
  // Relevance has no focal value: the focal stays first.
  assert.equal(order(placeFocal(rows, {colId: "rel", dir: "desc"}, false)), "FABCD");
  // A focal with no value goes after every peer value, before nothing.
  const nf = [{ticker: "F", isFocal: true, cells: {pe: c("F", null, "na")}}].concat(rows.slice(1));
  assert.equal(order(placeFocal(nf, {colId: "pe", dir: "desc"}, false)), "ABCDF");
  assert.equal(rows[0].ticker, "F", "the input is not mutated");
});

// ----- 4.4 markers and 4.9 data quality -----------------------------------------------------

test("markerFor follows the marker rules of 4.4, 4.9 and 12.7", () => {
  const col = {numeric: true};
  const ok = (o) => ({status: "ok", v: 1, flags: [], marks: [], tag: null, tagDiffers: false, amber: false, red: false, ...o});
  assert.deepEqual(markerFor(ok({}), col), {text: "", tone: ""});
  assert.deepEqual(markerFor(ok({tag: "E"}), col), {text: "", tone: ""}, "tag letters stay in the header by default");
  assert.deepEqual(markerFor(ok({tag: "A", tagDiffers: true}), col), {text: "A", tone: "amber"});
  assert.deepEqual(markerFor(ok({tag: "M"}), col), {text: "M", tone: "muted"});
  // 12.7: only a flag that bears on the printed value (cell.marks) draws the "!".
  assert.deepEqual(markerFor(ok({amber: true, flags: ["stale_balance_sheet"]}), col), {text: "", tone: ""}, "a flag that only touches the cell draws nothing");
  assert.deepEqual(markerFor(ok({amber: true, marks: ["stale_balance_sheet"]}), col), {text: "!", tone: "amber"});
  assert.deepEqual(markerFor(ok({tag: "M", amber: true, marks: ["x"]}), col), {text: "M", tone: "muted"}, "! only when no tag shows");
  assert.deepEqual(markerFor(ok({tag: "E"}), col, "quality"), {text: "E", tone: "muted"});
  assert.deepEqual(markerFor(ok({tag: "A", tagDiffers: true}), col, "quality"), {text: "A", tone: "amber"});
  assert.deepEqual(markerFor(ok({tag: "A", amber: true, marks: ["derived_operating_income"]}), col, "quality"), {text: "d", tone: "amber"});
  assert.deepEqual(markerFor(ok({tag: "A", amber: true, marks: ["derived_operating_income"]}), col), {text: "!", tone: "amber"});
  assert.deepEqual(markerFor({status: "nm", amber: true, flags: [], marks: ["x"]}, col), {text: "!", tone: "amber"});
  assert.deepEqual(markerFor({status: "nm", amber: true, flags: ["x"], marks: []}, col), {text: "", tone: ""});
  assert.deepEqual(markerFor(ok({amber: true, marks: ["x"]}), {numeric: false}), {text: "", tone: ""});
});


test("cell reason, period and tooltip copy", () => {
  assert.equal(cellReasonText({status: "na", reason: "No share count on file."}), "No value. No share count on file.");
  assert.equal(cellReasonText({status: "nm", reason: "EBITDA was $-12m in FY2025."}), "Not meaningful. EBITDA was $-12m in FY2025.");
  assert.equal(cellReasonText({status: "nb", reason: core.NA_TEXT.not_burning}), core.NA_TEXT.not_burning);
  assert.equal(cellReasonText({status: "ok"}), "");
  assert.equal(periodText({period: "FY2025", tag: "A", tagDiffers: true}, {id: "ev_revenue"}),
    "No LTM figure for this company, so this cell shows FY2025, marked A.");
  assert.equal(periodText({period: "FY2025"}, {id: "gross_margin"}), "Period: FY2025.");
  assert.equal(periodText({period: "31 Dec 2025"}, {id: "ev"}), "As of 31 Dec 2025.");
  const col = {id: "pe", label: "P/E", unitText: "×", numeric: true, tooltip: "Price over earnings per share."};
  const row = {ticker: "AZN", excluded: false};
  assert.equal(cellTip({status: "ok", v: 16.2, flagLines: [], period: "NTM"}, col, row), null, "a clean value has no tooltip");
  const flagged = cellTip({status: "ok", v: 16.2, period: "NTM", flagLines: ["FY1 EPS estimates run wide."], amber: true}, col, row);
  assert.equal(flagged.title, "AZN · P/E, ×");
  assert.deepEqual(flagged.lines, ["Period: NTM.", "FY1 EPS estimates run wide."]);
  const nm = cellTip({status: "nm", reason: "Consensus moves from a loss to a profit.", flagLines: []}, col, row);
  assert.equal(nm.body, "Not meaningful. Consensus moves from a loss to a profit.");
  const excl = cellTip({status: "ok", v: 1, flagLines: []}, col, {ticker: "PFE", excluded: true});
  assert.ok(excl.lines.includes("Excluded from statistics. Still shown. X includes it again."));
  const cf = cellTip({status: "ok", v: 1, flagLines: [], cf: {kind: "premium", tooltip: "12% above the peer median"}}, col, row);
  assert.deepEqual(cf.lines, ["12% above the peer median."]);
  const d = describeCell({status: "ok", v: 1, tag: "M", period: null, flagLines: ["Flag."]}, col, row);
  assert.equal(d, "Model output. Flag. Price over earnings per share.");
});

test("real cells: every non-ok cell explains itself and no tooltip carries a banned word", {skip: !PAYLOAD}, () => {
  for (const focal of ["AZN", "CRSP", "GILD"]) {
    if (!PAYLOAD.companies.some((c) => c.ticker === focal)) continue;
    const {view} = viewFor(focal, [{type: "SET_CF_MODE", mode: "premium"}]);
    const cols = Object.fromEntries(view.table.columns.map((c) => [c.id, c]));
    for (const row of view.table.rows) {
      for (const [id, cell] of Object.entries(row.cells)) {
        const col = cols[id];
        if (!col || !col.numeric) continue;
        const tip = cellTip(cell, col, row);
        if (cell.status !== "ok") {
          assert.ok(tip && tip.body && tip.body.length > 12, `${row.ticker} ${id} has a reason`);
          assert.ok(!/undefined|null|NaN/.test(tip.body), `${row.ticker} ${id}: ${tip.body}`);
        }
        const text = describeCell(cell, col, row, "premium") + (tip ? [tip.title, tip.body].concat(tip.lines).join(" ") : "");
        for (const w of core.BANNED_WORDS) assert.ok(!text.toLowerCase().includes(w), `${w} in ${row.ticker} ${id}`);
        assert.ok(!text.includes("—"), `em dash in ${row.ticker} ${id}`);
        const mk = markerFor(cell, col, "quality");
        assert.ok(["", "!", "d", "A", "E", "G", "M"].includes(mk.text));
      }
    }
  }
});

test("relevance lines, source words and the unit line", () => {
  const rel = {score: 84, level: "high", components: {subsector: 0.96, model: 1, scale: 0.5}, missing: [{id: "geography", reason: "region not known"}]};
  const lines = relevanceLines(rel);
  assert.equal(lines.length, 6);
  assert.equal(lines[0], "Subsector: 96%, weight 25%");
  assert.ok(lines.includes("Geography, not scored: region not known"));
  assert.ok(lines.some((l) => l.startsWith("Growth, not scored:")));
  assert.equal(sourceText({source: "system", pool: "A"}), "System set, pool A, same subsector and stage");
  assert.equal(sourceText({source: "analyst"}), "Added by you");
  assert.equal(sourceText({source: "saved"}), "Saved peer set");
  assert.equal(sourceText({isFocal: true}), "");
  assert.equal(unitLineText({unitLine: "× · NTM street E · calc. · Primary", isPrimary: true}), "Primary · × · NTM street E · calc.");
  assert.equal(unitLineText({unitLine: "× · FY25 A · calc.", isPrimary: false}), "× · FY25 A · calc.");
  assert.equal(unitLineText({}), "");
});

// ----- 4.8 sorting, filtering, finding ------------------------------------------------------

test("sortSteps counts SORT actions along desc, asc, none", () => {
  assert.equal(sortSteps(null, "pe", "desc"), 1);
  assert.equal(sortSteps(null, "pe", "asc"), 2);
  assert.equal(sortSteps({colId: "pe", dir: "desc"}, "pe", "asc"), 1);
  assert.equal(sortSteps({colId: "pe", dir: "asc"}, "pe", "desc"), 2);
  assert.equal(sortSteps({colId: "pe", dir: "desc"}, "pe", "desc"), 0);
  assert.equal(sortSteps({colId: "ev", dir: "asc"}, "pe", "desc"), 1);
  assert.equal(sortSteps({colId: "pe", dir: "asc"}, "pe", null), 1);
  // The count agrees with the reducer.
  let st = core.defaultState(PAYLOAD, {focal: PAYLOAD.companies[0].ticker, engine: ""});
  for (const want of ["asc", "desc", "asc", null, "desc"]) {
    const n = sortSteps(st.sort, "market_cap", want);
    for (let i = 0; i < n; i++) st = core.reduce(st, {type: "SORT", colId: "market_cap"}, PAYLOAD);
    assert.equal(st.sort ? st.sort.dir : null, want);
  }
});

test("filter text and number parsing", () => {
  assert.equal(filterShort({op: ">=", value: 10}), "≥ 10");
  assert.equal(filterShort({op: "<=", value: 2.5}), "≤ 2.5");
  assert.equal(filterShort({op: "has", value: null}), "has value");
  assert.equal(filterShort({op: "text", value: "us"}), "“us”");
  assert.equal(filterShort(null), "");
  assert.equal(parseFilterValue("10"), 10);
  assert.equal(parseFilterValue(" 1,250.5 "), 1250.5);
  assert.equal(parseFilterValue("−3.5%"), -3.5);
  assert.equal(parseFilterValue("16.2×"), 16.2);
  assert.equal(parseFilterValue("12x"), 12);
  assert.equal(parseFilterValue(""), null);
  assert.equal(parseFilterValue("n.m."), null);
  assert.equal(parseFilterValue(null), null);
});

test("findColumns ranks label prefix, word start, label, then definition", () => {
  const first = (q) => findColumns(q).map((c) => c.id);
  assert.equal(first("p/e")[0], "pe");
  assert.equal(first("ev")[0], "ev");
  assert.ok(first("ev").indexOf("ev_revenue") < first("ev").indexOf("pipeline_to_ev"));
  assert.ok(first("margin").slice(0, 4).every((id) => /margin/.test(id)));
  assert.ok(first("cash").includes("mcap_to_cash") && first("cash").includes("runway_months"));
  assert.ok(first("ifrs 16").includes("ev_ebitda"), "a definition word finds the column");
  assert.deepEqual(first("zzzz"), []);
  assert.equal(findColumns("", core.COLUMNS, new Set(), 12).length, 12);
  const r = findColumns("beta", core.COLUMNS, new Set(["beta"]))[0];
  assert.deepEqual(r, {id: "beta", label: "Beta", group: "Balance sheet and risk", unit: "", inTable: true});
  // Every catalogue column is reachable by its own label (4.5).
  for (const c of core.COLUMNS) assert.ok(findColumns(c.label, core.COLUMNS, new Set(), 60).some((x) => x.id === c.id), c.id);
});

// ----- 7.2, 7.4 grid movement ---------------------------------------------------------------

test("moveActive moves within bounds and treats a summary label as one cell", () => {
  const rows = ["head", "AZN", "PFE", "MRK", "sum:median", "sum:n"];
  const cols = ["exp", "incl", "rel", "company", "ticker", "pe", "ev"];
  const labelCols = new Set(BASE_IDS);
  const mv = (a, k) => moveActive(a, k, rows, cols, {labelCols, defaultRow: "AZN", defaultCol: "pe"});
  assert.deepEqual(mv(null, "down"), {row: "AZN", col: "pe"});
  assert.deepEqual(mv({row: "AZN", col: "pe"}, "down"), {row: "PFE", col: "pe"});
  assert.deepEqual(mv({row: "AZN", col: "pe"}, "up"), {row: "head", col: "pe"});
  assert.deepEqual(mv({row: "head", col: "pe"}, "up"), {row: "head", col: "pe"});
  assert.deepEqual(mv({row: "AZN", col: "ev"}, "right"), {row: "AZN", col: "ev"});
  assert.deepEqual(mv({row: "AZN", col: "pe"}, "home"), {row: "AZN", col: "exp"});
  assert.deepEqual(mv({row: "AZN", col: "pe"}, "end"), {row: "AZN", col: "ev"});
  assert.deepEqual(mv({row: "AZN", col: "pe"}, "pagedown"), {row: "sum:n", col: "pe"});
  assert.deepEqual(mv({row: "sum:n", col: "pe"}, "pageup"), {row: "head", col: "pe"});
  assert.deepEqual(mv({row: "PFE", col: "pe"}, "first"), {row: "head", col: "pe"});
  assert.deepEqual(mv({row: "PFE", col: "pe"}, "last"), {row: "sum:n", col: "pe"});
  // Summary rows: the frozen columns are one label cell.
  assert.deepEqual(mv({row: "sum:median", col: "pe"}, "left"), {row: "sum:median", col: "exp"});
  assert.deepEqual(mv({row: "sum:median", col: "exp"}, "left"), {row: "sum:median", col: "exp"});
  assert.deepEqual(mv({row: "sum:median", col: "company"}, "right"), {row: "sum:median", col: "pe"});
  assert.deepEqual(mv({row: "sum:median", col: "pe"}, "right"), {row: "sum:median", col: "ev"});
  // A row or column that left the table falls back to the default.
  assert.deepEqual(mv({row: "GONE", col: "pe"}, "down"), {row: "AZN", col: "pe"});
  assert.deepEqual(mv({row: "PFE", col: "gone"}, "right"), {row: "PFE", col: "pe"});
  assert.equal(moveActive(null, "down", [], cols), null);
});

test("cellDomId names header, body and summary cells", () => {
  assert.equal(cellDomId({row: "AZN", col: "pe"}), "c-AZN-pe");
  assert.equal(cellDomId({row: "head", col: "ev_ebitda"}), "c-head-ev_ebitda");
  assert.equal(cellDomId({row: "sum:median", col: "pe"}), "c-sum-median-pe");
  assert.equal(cellDomId({row: "sum:n", col: "ticker"}), "c-sum-n-label");
  assert.equal(cellDomId(null), null);
});

// ----- small renderers ----------------------------------------------------------------------

test("sparkPoints spans the box and keeps a flat series in view", () => {
  assert.equal(sparkPoints([1, 2, 3], 72, 14), "0,13 36,7 72,1");
  assert.equal(sparkPoints([5, 5], 10, 14), "0,13 10,13");
  assert.equal(sparkPoints([1], 72, 14), "");
  assert.equal(sparkPoints([1, null, 3], 10, 14), "0,13 10,1");
});

test("esc escapes markup in text and attributes", () => {
  assert.equal(esc("<b a=\"1\">Johnson & Johnson's</b>"), "&lt;b a=&quot;1&quot;&gt;Johnson &amp; Johnson&#39;s&lt;/b&gt;");
  assert.equal(esc(null), "");
  assert.equal(esc(12), "12");
});

// ----- house style and the stylesheet contract ----------------------------------------------

test("table.js copy: no em dash, no banned word; table.css: tokens only, .tb- rules only", () => {
  const js = fs.readFileSync(path.join(SRC_DIR, "table.js"), "utf8");
  assert.ok(!js.includes("—"), "the null glyph comes from core.NULL_GLYPH, never a literal");
  for (const w of core.BANNED_WORDS) assert.ok(!js.toLowerCase().includes(w), `banned word ${w} in table.js`);
  const css = fs.readFileSync(path.join(SRC_DIR, "table.css"), "utf8");
  const body = css.replace(/\/\*[\s\S]*?\*\//g, "");
  assert.ok(!/#[0-9a-fA-F]{3,8}\b/.test(body), "no hex colour in table.css");
  assert.ok(!/\brgba?\(|\bhsla?\(/.test(body), "no colour function literal in table.css");
  assert.ok(!/overscroll-behavior/.test(body), "the table box must let the wheel chain into #main (1.2)");
  for (const w of core.BANNED_WORDS) assert.ok(!css.toLowerCase().includes(w), `banned word ${w} in table.css`);
  // Every rule is scoped to a .tb- class, so this sheet cannot restyle another owner's parts.
  const selectors = body.replace(/@media[^{]+\{/g, "").split("}").map((r) => r.split("{")[0].trim()).filter(Boolean);
  for (const sel of selectors) {
    for (const part of sel.split(",")) assert.ok(/\.tb[-\s.[:>,]|\.tb$/.test(part.trim() + " "), `selector not scoped to .tb: ${part.trim()}`);
  }
});
