// Tests for frontend/components/compsval/core.js (spec docs/design/comps-valuation.md, 10.2).
// Run: node --test "*.test.js" from this folder.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

import * as core from "../../components/compsval/core.js";

const {
  quantile, median, mean, summarize, percentileRank, premium, fences, outlierClass,
  multipleDirection, cell, companyType, isPreRevenue, primaryMetric, relevance, defaultPeers, mixedModels,
  peerStats, bridge, dotplotModel, defaultState, reduce, persistable,
  migrateState, toCSV, toTSV, compareCells, normKey, handleKey, KEYMAP, COMMANDS, lintCopy, NA_TEXT, STATE_COPY,
  flagText, COLUMNS, FLAG_SEVERITY, UNDO_MS, PREMIUM_METRICS, peerSetTickers, metricAvailability,
} = core;

// Revision 4 (company-scorecard.md 5.2): the tests of the comparables table run on the Table view.
// The conclusion banner, the KPI strip, Drivers and risks and the scatter left the frame, and
// their tests with them (build step 6).
const deriveView = (p, s, extra = {}) => core.deriveView(p, s && s.ui ? {...s, ui: {...s.ui, view: "table"}} : s, extra);

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIX = JSON.parse(fs.readFileSync(path.join(HERE, "fixture_min.json"), "utf8"));
const PAYLOAD_PATH = path.join(HERE, "fixture_payload.json");
const PAYLOAD = fs.existsSync(PAYLOAD_PATH) ? JSON.parse(fs.readFileSync(PAYLOAD_PATH, "utf8")) : null;

const clone = (x) => JSON.parse(JSON.stringify(x));
const byT = (p, t) => p.companies.find((c) => c.ticker === t);
const AZN = () => clone(byT(FIX, "AZN"));
const CRSP = () => clone(byT(FIX, "CRSP"));
const CTX = {basis: "NTM", currency: "USD", earnings: "reported", fx: FIX.fx, fy0Label: "FY2025"};
const ctx = (o = {}) => ({...CTX, ...o});
const r2 = (v) => Number(v.toFixed(2));
const rowsOf = (recs, excluded = []) => recs.map((r) => ({ticker: r.ticker, record: r, isFocal: false, excluded: excluded.includes(r.ticker)}));
const payloadOf = (companies) => ({...clone(FIX), companies});

/** A synthetic test record (every value a test input, not a market fact). */
function rec(t, o = {}) {
  const price = o.price ?? 100;
  const shares = o.shares ?? 2000;
  const mcap = o.mcap ?? price * shares;
  const nd = "nd" in o ? o.nd : 1000;
  const cash = o.cash ?? 2000;
  const rev = "rev" in o ? o.rev : 10000;
  const op = "op" in o ? o.op : 2500;
  const ebitda = "ebitda" in o ? o.ebitda : 3000;
  const ni = "ni" in o ? o.ni : 1800;
  let e1 = "e1" in o ? o.e1 : 5, e2 = "e2" in o ? o.e2 : 5.5;
  if ("pe" in o) { e1 = price / o.pe; e2 = price / o.pe; }
  const e3 = "e3" in o ? o.e3 : (e1 != null ? e1 * 1.2 : null);
  const r = {
    ticker: t, name: `Synthetic ${t}`, engine: o.engine ?? "pharma", stage: o.stage ?? "commercial",
    country: o.country ?? "US", region: "region" in o ? o.region : "US",
    listing: {home_exchange: "NYSE", us_line: null, adr_ratio: null, otc: false},
    filer: {kind: "10-K filer", standard: "standard" in o ? o.standard : "US GAAP"},
    reporting_currency: o.rc ?? "USD", row_currency: o.rc ?? "USD", fiscal_year_end_month: 12,
    themes: o.themes ?? [], areas: o.areas ?? {},
    market: {price, price_as_of: "2026-09-28", market_cap_usd_m: mcap, market_cap_shares_m: mcap / price,
      shares_diluted_m: o.diluted ?? mcap / price, change_1d: 0.001, ttm_change: 0.05, beta: 1, vol_1y: 0.3,
      market_cap_basis: "diluted_weighted", market_cap_basis_text: "FY2025 weighted diluted shares, per US-listed share"},
    ev: {net_debt_usd_m: nd, total_debt_usd_m: nd == null ? null : nd + cash, cash_usd_m: cash,
      ev_usd_m: nd == null ? null : mcap + nd, balance_sheet_as_of: "2026-06-30",
      other_claims_usd_m: "oc" in o ? o.oc : null, other_claims_lines: []},
    periods: {
      FY0: {label: "FY2025", revenue_usd_m: rev, operating_income_usd_m: op,
        operating_income_basis: o.derived ? "derived" : "reported", ebitda_usd_m: ebitda, net_income_usd_m: ni,
        fcf_usd_m: o.fcf ?? 1500, equity_usd_m: o.equity ?? 8000, tax_rate: "tax" in o ? o.tax : 0.2,
        gross_profit_usd_m: rev == null ? null : rev * 0.7, amortisation_usd_m: o.amort ?? null,
        acquired_iprd_usd_m: o.iprd ?? null, rd_usd_m: 1000, rd_ex_iprd_usd_m: 1000},
      LTM: o.ltm ?? null,
      FY1: e1 == null ? null : {label: "FY2026", eps: e1, eps_n: o.n1 ?? 10, as_of: "2026-09-23"},
      FY2: e2 == null ? null : {label: "FY2027", eps: e2, eps_n: 10},
      FY3: e3 == null ? null : {label: "FY2028", eps: e3, eps_n: 5},
      NTM: e1 == null || e2 == null ? null : {eps: 0.25 * e1 + 0.75 * e2, weight_fy1: 0.25, sign_change: (e1 <= 0) !== (e2 <= 0)},
    },
    growth: {revenue_fy: "g" in o ? o.g : 0.05, bases: {revenue_fy: [rev, rev == null ? null : rev / 1.05]},
      eps_street_fy2: e1 > 0 && e2 != null ? e2 / e1 - 1 : null, eps_street_cagr: e1 > 0 && e3 > 0 ? Math.sqrt(e3 / e1) - 1 : null,
      ...(o.growth || {})},
    street: {price_target: {value: price * 1.1}},
    risk: {runway_months: o.runway ?? null, est_dispersion: o.disp ?? 0.1},
    healthcare: {lead_phase: o.phase ?? "Marketed", late_trials: o.late ?? 10, active_mapped_trials: 20, ...(o.hc || {})},
    model: {state: "not_modelled", ...(o.model || {})},
    flags: o.flags ?? [], na: o.na ?? {}, error: o.error ?? null,
  };
  if (o.patch) o.patch(r);
  return r;
}
/** Five synthetic big pharma peers with the given P/E NTM values (price 100). */
const pharmaPeers = (pes, extra = {}) => pes.map((pe, i) => rec(`SP${i + 1}`, {pe, op: 2500, g: [0.02, 0.03, 0.04, 0.05, 0.03, 0.035, 0.045][i % 7], ...extra}));

// 1 ---------------------------------------------------------------------------------------------
test("1 quantile: R type 7, odd and even, single, empty, nulls ignored", () => {
  assert.equal(quantile([1, 2, 3, 4], 0.25), 1.75);
  assert.equal(median([1, 2, 3, 4]), 2.5);
  assert.equal(quantile([1, 2, 3, 4], 0.75), 3.25);
  assert.equal(median([1, 2, 3, 4, 5]), 3);
  assert.equal(quantile([7], 0.3), 7);
  assert.equal(quantile([], 0.5), null);
  assert.equal(median([null, 1, NaN, 3, undefined]), 2);
  assert.equal(mean([null, 2, 4]), 3);
  assert.equal(summarize([]), null);
  assert.equal(summarize([1, 2, 3, 4]).iqr, 1.5);
});

// 2 ---------------------------------------------------------------------------------------------
test("2 percentileRank mid-rank with ties; premium both directions and nulls", () => {
  assert.equal(percentileRank(3, [1, 2, 3, 3, 5]), (2 + 0.5 * 2) / 5 * 100);
  assert.equal(percentileRank(null, [1, 2]), null);
  assert.equal(percentileRank(2, []), null);
  assert.ok(Math.abs(premium(16.2, 15, "richer_up") - 0.08) < 1e-12);
  assert.ok(Math.abs(premium(0.04, 0.05, "richer_down") - 0.25) < 1e-12);
  assert.equal(premium(10, 0, "richer_up"), null);
  assert.equal(premium(10, -2, "richer_up"), null);
  assert.equal(premium(10, 5, multipleDirection("pt_upside")), null);
  assert.equal(premium(10, 5, multipleDirection("pipeline_to_ev")), null);
  assert.equal(multipleDirection("fcf_yield"), "richer_down");
});

// 5 ---------------------------------------------------------------------------------------------
test("5 fences and outlierClass", () => {
  assert.equal(fences([1, 2, 3, 4]), null);
  assert.equal(outlierClass(100, [1, 2, 3, 4]), null);
  const v = [1, 2, 3, 4, 5];
  const iqr = quantile(v, 0.75) - quantile(v, 0.25);
  assert.equal(outlierClass(quantile(v, 0.75) + 3.1 * iqr, v), "extreme");
  assert.equal(outlierClass(quantile(v, 0.75) + 2 * iqr, v), "mild");
  assert.equal(outlierClass(3, v), null);
});

// 7 ---------------------------------------------------------------------------------------------
test("7 AZN cells on the fixture match the spec's checks", () => {
  const a = AZN();
  assert.equal(r2(cell(a, "pe", ctx()).v), 16.22);
  assert.equal(r2(cell(a, "pe", ctx({basis: "FY0"})).v), 25.41);
  assert.equal(r2(cell(a, "ev_revenue", ctx({basis: "FY0"})).v), 4.83);
  assert.equal(r2(cell(a, "price_to_sales", ctx({basis: "FY0"})).v), 4.43);
  assert.equal(r2(cell(a, "ev_ebitda", ctx()).v), 15.08);
  assert.equal(r2(cell(a, "fcf_yield", ctx()).v * 100), 4.53);
  assert.equal(r2(cell(a, "price_to_book", ctx()).v), 5.34);
  assert.equal(r2(cell(a, "mcap_to_cash", ctx()).v), 45.46);
  assert.equal(r2(cell(a, "operating_margin", ctx()).v * 100), 23.40);
  assert.equal(r2(cell(a, "operating_margin", ctx({earnings: "adjusted"})).v * 100), 30.56);
  assert.equal(r2(cell(a, "roic", ctx()).v * 100), 15.61);
  assert.equal(r2(cell(a, "peg", ctx()).v), 1.19);
  assert.equal(r2(cell(a, "net_debt_ebitda", ctx()).v), 1.27);
  assert.equal(cell(a, "pe", ctx()).text, "16.2");
  assert.equal(cell(a, "pe", ctx()).tag, "E");
  assert.equal(cell(a, "pe", ctx({basis: "FY0"})).tag, "A");
  assert.equal(cell(a, "runway_months", ctx()).status, "nb");
  assert.equal(cell(a, "runway_months", ctx()).text, "no burn");
  assert.ok(cell(a, "ev", ctx()).flags.includes("stale_balance_sheet"));
  assert.ok(cell(a, "ev", ctx()).amber);
  assert.ok(!cell(a, "pe", ctx()).flags.includes("stale_balance_sheet"));
});

// 8 ---------------------------------------------------------------------------------------------
test("8 derived operating income: no add-back on the adjusted basis", () => {
  const lly = rec("LLY_LIKE", {derived: true, op: 4560, rev: 10000, ebitda: 5000, iprd: 530, amort: 200,
    flags: [{code: "derived_operating_income", field: "periods.FY0.operating_income_usd_m", severity: "amber", params: {}}]});
  const rep = cell(lly, "operating_margin", ctx());
  const adj = cell(lly, "operating_margin", ctx({earnings: "adjusted"}));
  assert.equal(adj.v, rep.v);
  assert.ok(adj.flags.includes("derived_no_addback"));
  assert.ok(adj.flags.includes("derived_operating_income"));
  const e1 = cell(lly, "ev_ebitda", ctx()), e2 = cell(lly, "ev_ebitda", ctx({earnings: "adjusted"}));
  assert.equal(e2.v, e1.v);
  assert.ok(e2.flags.includes("derived_no_addback"));
  // A reported filer with nothing tagged keeps its figure and says why.
  const plain = rec("PLAIN", {});
  const pa = cell(plain, "operating_margin", ctx({earnings: "adjusted"}));
  assert.equal(pa.v, cell(plain, "operating_margin", ctx()).v);
  assert.ok(pa.flags.includes("no_tagged_addbacks"));
});

// 9 ---------------------------------------------------------------------------------------------
test("9 CRSP cells: n.m. with reasons, cash measures computed, never 0 for a null", () => {
  const c = CRSP();
  for (const id of ["pe", "ev_revenue", "price_to_sales", "ev_ebitda", "fcf_yield", "revenue_growth", "net_debt_ebitda"]) {
    const x = cell(c, id, ctx());
    assert.equal(x.status, "nm", id);
    assert.equal(x.text, "n.m.");
    assert.ok(x.reason && x.reason.length > 10, id);
  }
  assert.match(cell(c, "ev_revenue", ctx({basis: "FY0"})).reason, /under the \$100m floor/);
  assert.equal(r2(cell(c, "price_to_book", ctx()).v), 2.99);
  assert.equal(r2(cell(c, "mcap_to_cash", ctx()).v), 2.21);
  assert.equal(Number((cell(c, "cash_to_mcap", ctx()).v * 100).toFixed(1)), 45.2);
  assert.equal(cell(c, "runway_months", ctx()).text, "77");
  for (const col of COLUMNS) {
    const x = cell(c, col.id, ctx());
    if (x.status === "na" || x.status === "err") assert.equal(x.text, "—", col.id);
    if (x.status !== "ok") assert.notEqual(x.text, "0", col.id);
  }
  assert.equal(cell(c, "gross_margin", ctx()).status, "nm");
  assert.equal(cell(c, "major_products", ctx()).reason, NA_TEXT.no_product_revenue);
});

// 10 --------------------------------------------------------------------------------------------
test("10 growth guards", () => {
  const cagr = rec("G1", {rev: 500, growth: {revenue_cagr3: 0.431, bases: {revenue_fy: [500, 470], revenue_cagr3: [500, 4]}}});
  assert.equal(cell(cagr, "revenue_cagr3", ctx()).status, "nm");
  const eb = rec("G2", {growth: {ebitda_fy: 3.0, bases: {revenue_fy: [10000, 9500], ebitda_fy: [20, 5]}}});
  assert.equal(cell(eb, "ebitda_growth", ctx()).status, "nm");
  const eps = rec("G3", {growth: {eps_fy_gaap: 1.0, bases: {revenue_fy: [10000, 9500], eps_fy_gaap: [0.1, 0.05]}}});
  assert.equal(cell(eps, "eps_growth", ctx({basis: "FY0"})).status, "nm");
  const epsF = rec("G4", {e1: 0.05, e2: 0.5});
  assert.equal(cell(epsF, "eps_growth", ctx()).status, "nm");
  const big = rec("G5", {rev: 700, g: 6.0, patch: (r) => { r.growth.bases.revenue_fy = [700, 100]; }});
  assert.equal(cell(big, "revenue_growth", ctx()).status, "nm");
  assert.match(cell(big, "revenue_growth", ctx()).reason, /over 500%/);
  const ok = rec("G6", {g: 0.1, patch: (r) => { r.growth.bases.revenue_fy = [1100, 1000]; }});
  assert.equal(cell(ok, "revenue_growth", ctx()).status, "ok");
});

// 11 --------------------------------------------------------------------------------------------
test("11 companyType and isPreRevenue", () => {
  assert.equal(companyType(AZN()), "profitable");
  assert.equal(companyType(rec("GILD_LIKE", {e1: -0.48, e2: 9.87, op: 3000})), "profitable");
  assert.equal(companyType(CRSP()), "clinical");
  const arwr = rec("ARWR_LIKE", {stage: "clinical", rev: 829});
  assert.equal(companyType(arwr), "clinical");
  assert.equal(isPreRevenue(arwr), false);
  assert.equal(companyType(rec("SMALL", {rev: 50})), "sub_scale");
  assert.equal(companyType(rec("NOREV", {rev: null})), "sub_scale");
  assert.equal(companyType(rec("LOSS", {rev: 500, op: -10})), "loss_making");
  assert.equal(isPreRevenue(rec("Z0", {rev: 0})), true);
  assert.equal(isPreRevenue(rec("ZN", {rev: null})), true);
  assert.equal(isPreRevenue(CRSP()), false);
  if (PAYLOAD) {
    for (const t of ["ABEO", "AUTL", "QURE"]) assert.equal(companyType(byT(PAYLOAD, t)), "sub_scale", t);
    assert.equal(companyType(byT(PAYLOAD, "GILD")), "profitable");
    assert.equal(companyType(byT(PAYLOAD, "ARWR")), "clinical");
    assert.equal(isPreRevenue(byT(PAYLOAD, "ARWR")), false);
  }
});

// 12 --------------------------------------------------------------------------------------------
test("12 NTM sign change makes P/E NTM n.m.; P/E FY2 is computed", () => {
  for (const [t, a, b] of [["GILD_LIKE", -0.48, 9.87], ["AXSM_LIKE", -2.92, 3.76]]) {
    const r = rec(t, {e1: a, e2: b, flags: [{code: "eps_sign_change", field: "periods.NTM", severity: "amber", params: {fy1: a, fy2: b}}]});
    const ntm = cell(r, "pe", ctx());
    assert.equal(ntm.status, "nm");
    assert.match(ntm.reason, /from a loss to a profit within the next twelve months/);
    assert.ok(ntm.flags.includes("eps_sign_change"));
    const fy2 = cell(r, "pe", ctx({basis: "FY2"}));
    assert.equal(fy2.status, "ok");
    assert.ok(Math.abs(fy2.v - 100 / b) < 1e-9);
  }
});

// 13 --------------------------------------------------------------------------------------------
test("13 primaryMetric: candidates, states and overrides", () => {
  const a = AZN();
  const peers = FIX.companies.filter((c) => c.ticker.startsWith("SYN")).concat(pharmaPeers([13, 17]));
  const p = primaryMetric(a, peers, ctx());
  assert.equal(p.colId, "pe");
  assert.equal(p.state, "ok");
  assert.equal(p.reasonText, "P/E NTM is primary: AZN is profitable and 6 of 6 peers have a value.");
  const gild = rec("GILD_LIKE", {e1: -0.48, e2: 9.87, op: 3000});
  const g = primaryMetric(gild, pharmaPeers([12, 14, 15, 16, 18]), ctx());
  assert.equal(g.colId, "ev_ebitda");
  assert.equal(g.reasonText, "EV/EBITDA is primary: P/E NTM is not available (not meaningful for GILD_LIKE: consensus moves from a loss to a profit within the next twelve months), and 5 of 5 peers have a value.");
  const clin = [1.5, 1.9, 2.07, 2.5, 3.0].map((m, i) => rec(`CG${i}`, {engine: "cellgene", stage: "clinical", rev: null, cash: 2000, mcap: 2000 * m, e1: -2, e2: -1.5, phase: "Phase 2"}));
  const c = primaryMetric(CRSP(), clin, ctx());
  assert.equal(c.colId, "mcap_to_cash");
  assert.equal(c.state, "ok");
  assert.match(c.reasonText, /^Market cap \/ cash is primary: CRSP is clinical-stage, so revenue and earnings multiples are not used, and 5 of 5 peers have a value\.$/);
  const bntx = rec("BNTX_LIKE", {rev: 3000, op: -500, nd: null, e1: -1, e2: -0.5, na: {"ev.ev_usd_m": "no_debt_line"}});
  assert.equal(primaryMetric(bntx, pharmaPeers([12, 14, 15, 16, 18]), ctx()).colId, "price_to_sales");
  const krys = rec("KRYS_LIKE", {pe: 38.6, engine: "cellgene"});
  const thin = [rec("K1", {rev: 50, nd: null, pe: 20}), rec("K2", {rev: 50, nd: null, e1: -1, e2: -1}), rec("K3", {rev: 50, nd: null, e1: -1, e2: -1})];
  const k = primaryMetric(krys, thin, ctx());
  assert.equal(k.state, "too_few");
  assert.equal(k.colId, "pe");
  assert.equal(k.reasonText, "KRYS_LIKE trades at 38.6× P/E (NTM). One peer has a value, so there is no comparison.");
  const three = primaryMetric(a, pharmaPeers([12, 14, 16], {nd: null, rev: 50}), ctx());
  assert.equal(three.state, "low_confidence");
  assert.equal(three.colId, "pe");
  assert.equal(primaryMetric(a, peers, ctx(), "runway_months").colId, "pe");
  const ov = primaryMetric(a, peers, ctx(), "ev_revenue");
  assert.equal(ov.colId, "ev_revenue");
  assert.equal(ov.override, true);
  assert.match(ov.reasonText, /chosen by you/);
});

// 14 --------------------------------------------------------------------------------------------
test("14 LTM basis: per-cell FY0 fallback and the neutral starred chip", () => {
  const a = AZN();
  const x = cell(a, "ev_revenue", ctx({basis: "LTM"}));
  assert.equal(x.tagDiffers, true);
  assert.equal(x.period, "FY2025");
  assert.equal(x.tag, "A");
  const syna = byT(FIX, "SYNA");
  const y = cell(syna, "ev_revenue", ctx({basis: "LTM"}));
  assert.equal(y.tagDiffers, false);
  assert.equal(y.period, "LTM Jun-26");
  const st = {...defaultState(FIX, {focal: "AZN", engine: "pharma"}), basis: "LTM", preset: "core"};
  const v = deriveView(FIX, st);
  const col = v.table.columns.find((c) => c.id === "ev_revenue");
  assert.equal(col.basisChip.text, "LTM A*");
  assert.equal(col.basisChip.mixed, true);
  assert.equal(col.basisChip.amber, undefined);
});

// 15 --------------------------------------------------------------------------------------------
test("15 currency: EUR display, basis text, reported units, mixed-currency summaries", () => {
  const a = AZN();
  const eur = cell(a, "market_cap", ctx({currency: "EUR"}));
  assert.ok(Math.abs(eur.v - 259971.4 / 1.1378) < 1e-6);
  const st = {...defaultState(FIX, {focal: "AZN", engine: "pharma"}), currency: "EUR"};
  assert.match(deriveView(FIX, st).ctx.basisText, /^EUR at the ECB reference rate/);
  const rep = cell(a, "market_cap", ctx({currency: "REPORTED"}));
  assert.equal(rep.unit, "USD");
  const dkk = rec("DKK_LIKE", {rc: "DKK"});
  assert.equal(cell(dkk, "revenue", ctx({currency: "REPORTED"})).unit, "DKK");
  assert.ok(Math.abs(cell(dkk, "revenue", ctx({currency: "REPORTED"})).v - 10000 / FIX.fx.usd_per_unit.DKK) < 1e-6);
  const repState = {...defaultState(FIX, {focal: "AZN", engine: "pharma"}), currency: "REPORTED", preset: "core"};
  const same = deriveView(FIX, repState).table.summary.find((s) => s.id === "median").cells.market_cap;
  assert.notEqual(same.text, "—");
  const mixedP = clone(FIX);
  byT(mixedP, "SYNB").row_currency = "EUR";
  const mixed = deriveView(mixedP, repState).table.summary.find((s) => s.id === "median").cells.market_cap;
  assert.equal(mixed.text, "—");
  assert.equal(mixed.reason, "Mixed currencies. Statistics need one currency: pick USD, EUR, GBP, CHF or DKK.");
});

// 16 --------------------------------------------------------------------------------------------
test("16 relevance: identical, renormalised, geography dropped, pharma against clinical cell and gene", () => {
  const x = rec("X", {areas: {Oncology: 3}, themes: ["RNA"]});
  assert.equal(relevance(x, x).score, 100);
  const noG = rec("NG", {g: null});
  const rg = relevance(noG, noG);
  assert.equal(rg.score, 100);
  assert.ok(rg.missing.some((m) => m.id === "growth"));
  const noR = rec("NR", {region: null});
  const rr = relevance(noR, rec("Y", {}));
  assert.equal(rr.components.geography, undefined);
  assert.ok(rr.missing.some((m) => m.id === "geography"));
  assert.ok(relevance(AZN(), CRSP()).score < 40);
  assert.equal(relevance(x, x).level, "high");
});

// 17 --------------------------------------------------------------------------------------------
test("17 defaultPeers: whole cohort, cut, pools, reasons and warnings (12.8)", () => {
  const focal = rec("F0", {});
  // A cohort of WHOLE_COHORT_MAX other companies or fewer is the set, whole.
  const twenty = Array.from({length: 20}, (_, i) => rec(`M${i}`, {}));
  const d = defaultPeers(focal, [focal].concat(twenty));
  assert.equal(d.tickers.length, 20);
  assert.equal(d.whole, true);
  assert.ok(d.tickers.every((t) => d.pools[t] === "A"));
  // A distant company of the same subsector and stage: relevance under the floor of 40.
  const far = (t) => rec(t, {mcap: 1, op: -9000, g: 1.0, region: "Asia", country: "JP"});
  assert.ok(relevance(focal, far("Z")).score < core.MIN_DEFAULT_RELEVANCE);
  const mixed = [rec("N0", {}), rec("N1", {}), far("Z0"), far("Z1"), rec("N2", {}), rec("N3", {})];
  const dm = defaultPeers(focal, [focal].concat(mixed));
  assert.equal(dm.whole, true);
  assert.deepEqual(dm.tickers.slice().sort(), ["N0", "N1", "N2", "N3", "Z0", "Z1"]);
  assert.match(dm.reasons.Z0, /^Same subsector and stage, relevance \d+, under the usual floor of 40$/);
  assert.match(dm.reasons.N0, /^Same subsector and stage, relevance \d+$/);
  assert.equal(dm.warning, null);
  // A cohort of more than 20: the 15 most relevant at or above the floor.
  const big = Array.from({length: 16}, (_, i) => rec(`G${String(i).padStart(2, "0")}`, {})).concat(Array.from({length: 9}, (_, i) => far(`Z${i}`)));
  const db = defaultPeers(focal, [focal].concat(big));
  assert.equal(db.whole, false);
  assert.equal(db.tickers.length, core.MAX_DEFAULT_PEERS);
  assert.ok(db.tickers.every((t) => t.startsWith("G") && db.scores[t] >= core.MIN_DEFAULT_RELEVANCE));
  const thin = Array.from({length: 12}, (_, i) => rec(`G${String(i).padStart(2, "0")}`, {})).concat(Array.from({length: 13}, (_, i) => far(`Z${String(i).padStart(2, "0")}`)));
  const dt = defaultPeers(focal, [focal].concat(thin));
  assert.equal(dt.whole, false);
  assert.equal(dt.tickers.length, 12);
  assert.ok(dt.tickers.every((t) => t.startsWith("G")));
  // A cohort of three still pads from the other stage and still warns.
  const bf = rec("BF", {engine: "biotech"});
  const poolA = [0, 1, 2].map((i) => rec(`BA${i}`, {engine: "biotech"}));
  const poolB = [0, 1, 2].map((i) => rec(`BB${i}`, {engine: "biotech", stage: "clinical", rev: null, mcap: 5, g: null, price: 1, shares: 5}));
  const d2 = defaultPeers(bf, [bf, ...poolA, ...poolB]);
  assert.equal(d2.tickers.length, 5);
  assert.equal(d2.tickers.filter((t) => d2.pools[t] === "B").length, 2);
  const bt = d2.tickers.find((t) => d2.pools[t] === "B");
  assert.match(d2.reasons[bt], /^Added to reach five peers: same subsector, clinical stage, relevance \d+$/);
  assert.equal(d2.warning, "padded");
  const cf = rec("CF", {engine: "cellgene", stage: "clinical", rev: null});
  const d3 = defaultPeers(cf, [cf, rec("C1", {engine: "cellgene", stage: "clinical", rev: null}), rec("P1", {})]);
  assert.equal(d3.warning, "too_few");
  if (PAYLOAD) {
    // AZN: all 17 other big pharma, so LLY and BAYN are in.
    const dp = defaultPeers(byT(PAYLOAD, "AZN"), PAYLOAD.companies);
    assert.equal(dp.tickers.length, 17);
    assert.equal(dp.whole, true);
    assert.ok(dp.tickers.includes("LLY") && dp.tickers.includes("BAYN"));
    assert.ok(dp.tickers.every((t) => byT(PAYLOAD, t).engine === "pharma" && byT(PAYLOAD, t).stage === "commercial"));
    const v = view(PAYLOAD, "AZN");
    assert.equal(v.header.peerSet.full, "Big pharma, commercial, 17");
    assert.equal(v.header.peerSet.tooltip, "Every big pharma company at the commercial stage. A cohort of more than 20 is cut to the 15 most relevant.");
    const pe = (id) => v.table.summary.find((s) => s.id === id).cells.pe;
    assert.deepEqual([pe("median").text, pe("n").text], ["15.4", "14"]);
    // Stored edits still apply on top, and an added ticker now in the system set is a duplicate.
    const st = {...defaultState(PAYLOAD, {focal: "AZN", engine: "pharma"}), peerEdits: {AZN: {added: ["LLY", "CRSP"], removed: ["PFE"], notes: {}}}};
    const info = peerSetTickers(PAYLOAD, st);
    assert.deepEqual(info.added, ["CRSP"]);
    assert.equal(info.tickers.length, 17);
    assert.ok(!info.tickers.includes("PFE") && info.tickers.filter((t) => t === "LLY").length === 1);
  }
});

// 18 --------------------------------------------------------------------------------------------
test("18 mixedModels fires for a profitable focal with two clinical peers in five", () => {
  const peers = [rec("A1"), rec("A2"), rec("A3"), rec("C1", {stage: "clinical", rev: null}), rec("C2", {stage: "clinical", rev: null})];
  const m = mixedModels(AZN(), peers);
  assert.ok(m);
  assert.equal(m.focalType, "profitable");
  assert.equal(m.otherType, "pre-scale");
  assert.equal(m.k, 2);
  assert.equal(mixedModels(AZN(), [rec("A1"), rec("A2")]), null);
});

// 19 --------------------------------------------------------------------------------------------
test("19 peerStats: focal, exclusions, outliers; filters never change it", () => {
  const recs = pharmaPeers([10, 11, 12, 13, 14, 100]);
  const rows = [{ticker: "AZN", record: AZN(), isFocal: true, excluded: false}].concat(rowsOf(recs, ["SP2"]));
  const inc = peerStats(rows, "pe", ctx(), {outliers: "include"});
  assert.equal(inc.n, 5);
  assert.ok(!inc.values.some((v) => Math.abs(v - 11) < 1e-9));
  assert.deepEqual(inc.outliers.extreme, ["SP6"]);
  const exc = peerStats(rows, "pe", ctx(), {outliers: "exclude"});
  assert.equal(exc.n, 4);
  const focalV = cell(AZN(), "pe", ctx()).v;
  assert.equal(percentileRank(focalV, exc.values), percentileRank(focalV, [10, 12, 13, 14]));
  const p = payloadOf([AZN()].concat(pharmaPeers([12, 14, 15.36, 16, 18])));
  const st = {...defaultState(p, {focal: "AZN", engine: "pharma"}), preset: "core"};
  const withF = reduce(st, {type: "SET_FILTER", filter: {colId: "pe", op: ">=", value: 15}}, p);
  const a = deriveView(p, st), b = deriveView(p, withF);
  assert.equal(b.table.rows.length < a.table.rows.length, true);
  assert.deepEqual(b.table.summary.find((s) => s.id === "median").cells.pe, a.table.summary.find((s) => s.id === "median").cells.pe);
  assert.deepEqual(b.primary, a.primary);
});

// 20 --------------------------------------------------------------------------------------------
function ownMultiple(r, route) {
  const m = r.market, e = r.ev, f = r.periods.FY0;
  switch (route) {
    case "pe:NTM": return m.price / r.periods.NTM.eps;
    case "pe:FY0": return m.market_cap_usd_m / f.net_income_usd_m;
    case "ev_revenue:FY0": return e.ev_usd_m / f.revenue_usd_m;
    case "ev_ebitda:FY0": return e.ev_usd_m / f.ebitda_usd_m;
    case "price_to_sales:FY0": return m.market_cap_usd_m / f.revenue_usd_m;
    case "price_to_book:FY0": return m.market_cap_usd_m / f.equity_usd_m;
    case "mcap_to_cash:FY0": return m.market_cap_usd_m / e.cash_usd_m;
    default: return null;
  }
}
test("20 bridge: self-consistency, the AZN example, EV path, claims, shares, guards", () => {
  const focals = [AZN(), CRSP()].concat(PAYLOAD ? [clone(byT(PAYLOAD, "LLY"))] : []);
  const routes = ["pe:NTM", "pe:FY0", "ev_revenue:FY0", "ev_ebitda:FY0", "price_to_sales:FY0", "price_to_book:FY0", "mcap_to_cash:FY0"];
  let checked = 0;
  for (const f of focals) {
    for (const route of routes) {
      const [colId, basis] = route.split(":");
      const own = ownMultiple(f, route);
      if (!Number.isFinite(own)) continue;
      const b = bridge(f, [], {colId, basis, multipleOverride: own}, ctx({fx: PAYLOAD && f.ticker === "LLY" ? PAYLOAD.fx : FIX.fx}));
      if (!b.enabled || b.V === null) continue;
      assert.ok(Math.abs(b.V / f.market.price - 1) < 1e-9, `${f.ticker} ${route} ${b.V}`);
      checked++;
    }
  }
  assert.ok(checked >= 10);
  const a = AZN();
  const ex = bridge(a, [], {colId: "pe", multipleOverride: 15.36}, ctx());
  assert.equal(r2(ex.V), 157.38);
  assert.equal(r2(ex.upside * 100), -5.28);
  assert.ok(ex.steps.length >= 8);
  assert.match(ex.description, /^Implied value of 157\.38 USD per share/);
  const evb = bridge(a, [], {colId: "ev_ebitda", multipleOverride: 10}, ctx());
  const S = a.market.market_cap_shares_m;
  assert.ok(Math.abs(evb.V - (10 * 18829 - 23903) / S) < 1e-9);
  const on = bridge(a, [], {colId: "ev_ebitda", multipleOverride: 10, otherClaimsOn: true}, ctx());
  assert.ok(Math.abs(on.V - (10 * 18829 - 23903 - 855) / S) < 1e-9);
  const over = bridge(a, [], {colId: "ev_ebitda", multipleOverride: 10, otherClaimsOn: true, otherClaimsOverride: -1000}, ctx());
  assert.ok(Math.abs(over.V - (10 * 18829 - 23903 - 1000) / S) < 1e-9);
  const crspOn = bridge(CRSP(), [], {colId: "mcap_to_cash", multipleOverride: 2, otherClaimsOn: true}, ctx());
  assert.equal(crspOn.otherClaims.available, false);
  assert.equal(crspOn.otherClaims.on, false);
  assert.equal(crspOn.otherClaims.reason, NA_TEXT.none_on_file);
  const dil = bridge(a, [], {colId: "pe", basis: "FY0", multipleOverride: 20, sharesSource: "diluted"}, ctx());
  assert.equal(dil.S, a.market.shares_diluted_m);
  const neg = bridge(CRSP(), [], {colId: "pe", multipleOverride: 15}, ctx());
  assert.equal(neg.enabled, false);
  assert.equal(neg.reason, "NTM EPS is zero or negative for CRSP, so a multiple of it gives no value.");
  const eqNeg = bridge(a, [], {colId: "ev_ebitda", multipleOverride: 1}, ctx());
  assert.equal(eqNeg.enabled, true);
  assert.equal(eqNeg.V, null);
  assert.ok(eqNeg.steps.length > 0);
  assert.equal(eqNeg.reason, "Implied equity is negative: net debt and claims exceed the implied enterprise value.");
  const nb = bridge(a, [], {colId: "peg"}, ctx());
  assert.equal(nb.enabled, false);
  assert.match(nb.reason, /^No bridge for PEG\./);
});

// 22 --------------------------------------------------------------------------------------------
test("22 dot plot: domain, not plotted counts, clamped extreme with a label", () => {
  const peers = pharmaPeers([10, 11, 12, 13, 14, 100]);
  peers.push(rec("NMP", {e1: -1, e2: 2}));
  peers.push(rec("NAP", {e1: null, e2: null, na: {"periods.NTM": "no_consensus"}}));
  const f = rec("F", {pe: 12.5});
  const dp = dotplotModel(f, rowsOf(peers), "pe", ctx(), {});
  assert.deepEqual(dp.extent.map((v) => Number(v.toFixed(6))), [10, 14]);
  assert.ok(dp.domain[0] < 10 && dp.domain[1] > 14);
  assert.deepEqual(dp.notPlotted, {nm: 1, na: 1});
  const pts = dp.lanes[0].points;
  assert.ok(!pts.some((p) => p.ticker === "NMP" || p.ticker === "NAP"));
  const ext = pts.find((p) => p.ticker === "SP6");
  assert.equal(ext.clamped, "hi");
  assert.equal(ext.label, "SP6 100.0");
  assert.equal(Number(ext.x.toFixed(6)), 14);
  assert.ok(pts.some((p) => p.isFocal));
});

const view = (p, focal, patch = {}) => deriveView(p, {...defaultState(p, {focal, engine: ""}), ...patch});
// 27 --------------------------------------------------------------------------------------------
test("27 house style over every generated and catalogued string", () => {
  const names = [];
  for (const pl of [FIX].concat(PAYLOAD ? [PAYLOAD] : [])) for (const c of pl.companies) names.push(c.ticker, c.name);
  const bad = [];
  const check = (s, kind, where) => { const i = lintCopy(s, kind, names); if (i.length) bad.push(`${where}: ${i.join(", ")}: ${s}`); };
  for (const [k, t] of Object.entries(NA_TEXT)) check(t, "sentence", `NA_TEXT.${k}`);
  for (const code of Object.keys(FLAG_SEVERITY)) {
    const ft = flagText({code, params: {as_of: "2025-12-31", days: 3, trading_days: 2, checked_at: "2026-09-20", label: "FY2024",
      source: "prices", run_id: 123, from: "EUR", rate: 1.1378, row_units: ["EUR"], company_currency: "USD", month: 9, line: "equity",
      reason: "A reason.", primary: 1000, alt: 1300, pct: 0.3, primary_basis: "the cover count", alt_basis: "the diluted count",
      n: 2, period: "FY2028", low: 1, high: 2, mean: 1.5, fy1: -0.48, fy2: 9.87, message: "boom"}});
    check(ft.chip, "label", `flag chip ${code}`);
    check(ft.text, "sentence", `flag text ${code}`);
  }
  for (const [k, s] of Object.entries(STATE_COPY)) { check(s.title, "label", `state title ${k}`); check(s.detail, "sentence", `state detail ${k}`); }
  for (const c of COLUMNS) { check(c.label, "label", `column ${c.id}`); check(c.tooltip, "sentence", `tooltip ${c.id}`); }
  for (const c of COMMANDS) check(c.label, "label", `command ${c.id}`);
  const views = [view(FIX, "AZN"), view(FIX, "CRSP")].concat(PAYLOAD ? ["AZN", "LLY", "GILD", "CRSP", "VRTX", "PFE", "BNTX", "KRYS", "ARWR"].map((t) => view(PAYLOAD, t)) : []);
  for (const v of views) {
    check(v.primary.reasonText, "sentence", "primary");
    for (const s of v.states) { check(s.title, "label", `state ${s.id}`); check(s.detail, "sentence", `state ${s.id}`); }
    check(v.dotplot.description, "sentence", "dotplot");
    check(v.bridge.description, "sentence", "bridge");
    for (const it of v.scope.items) check(it.text, "label", "scope");
    for (const sec of v.method.sections) { check(sec.title, "label", "method"); for (const b of sec.body) check(b, "sentence", "method body"); }
  }
  assert.deepEqual(bad, []);
  for (const s of ["Sort by EV/Revenue", "Estimates for FY2", "A 20-F filer", "Trend R² 0.41", "Lead phase Phase 3", "IRA Part D spending", "Open in Forecast tab"]) {
    assert.deepEqual(lintCopy(s, "label"), [], s);
  }
  assert.deepEqual(lintCopy("Peer Set", "label"), ["not sentence case"]);
  assert.deepEqual(lintCopy("Peer Set", "sentence"), []);
  assert.deepEqual(lintCopy("Additionally, this", "sentence"), ["banned: additionally"]);
  assert.deepEqual(lintCopy("a — b", "sentence"), ["em dash"]);
  assert.deepEqual(lintCopy("—", "label"), []);
});

// 28 --------------------------------------------------------------------------------------------
test("28 reduce: identity on no-ops, sorting, exclusions per focal, undo", () => {
  const p = PAYLOAD || FIX;
  const s0 = defaultState(p, {focal: "AZN", engine: "pharma"});
  const noops = [
    {type: "SET_BASIS", basis: s0.basis}, {type: "SET_BASIS", basis: "XXX"}, {type: "SET_CURRENCY", currency: s0.currency},
    {type: "SET_EARNINGS", earnings: s0.earnings}, {type: "SET_PRESET", preset: s0.preset}, {type: "UNPIN_COLUMN", colId: "pe"},
    {type: "REMOVE_FILTER", colId: "pe"}, {type: "CLEAR_FILTERS"}, {type: "CLOSE_DETAIL"}, {type: "CLOSE_METHOD"},
    {type: "CLOSE_OVERLAY"}, {type: "UNDO"}, {type: "EXPIRE_UNDO", now: 1}, {type: "SET_FOCAL", ticker: "AZN"},
    {type: "SET_DOT_METRIC", colId: null}, {type: "SET_PRIMARY", colId: null}, {type: "SET_PRIMARY", colId: "runway_months"},
    {type: "RESET_BRIDGE"}, {type: "RESET_LAYOUT"}, {type: "RESTORE_SYSTEM"}, {type: "DELETE_SET", name: "none"},
    {type: "DELETE_LAYOUT", name: "none"}, {type: "LOAD_LAYOUT", name: "none"}, {type: "LOAD_SET", name: "none"},
    {type: "DELETE_SUBGROUP", name: "none"}, {type: "SET_OUTLIERS", mode: s0.outliers}, {type: "SET_CF_MODE", mode: s0.cfMode},
    {type: "SET_SINGLE_KEYS", on: true}, {type: "SET_COHORTS", ids: []}, {type: "SET_STATS_GROUP", group: "all"},
    {type: "SET_LOWER_TAB", tab: "obs"}, {type: "CLOSE_PEERS"}, {type: "ADOPT_PERSISTED", local: null, session: null},
    {type: "HIDE_COLUMN", colId: "country"}, {type: "ADD_PEER", ticker: "AZN"}, {type: "NOT_AN_ACTION"},
    // Revision 4: the actions of the scatter, "Why?" and Drivers and risks are gone.
    {type: "SET_SCATTER", trend: false}, {type: "TOGGLE_WHY"}, {type: "SET_INSIGHT_TAB", tab: "competition"},
    {type: "SET_NARROW_TAB", tab: "position"}, {type: "SET_LAPTOP_TAB", tab: "position"}, {type: "SET_TEXT_SIZE", delta: -1}, {type: "SORT", colId: "nope"}, {type: "RESIZE_COLUMN", colId: "nope", width: 90},
    {type: "SET_CHART_STRIP", layout: "laptop", value: "bad"}, {type: "SET_NOTE", ticker: "AZN", text: ""},
    {type: "SET_PEER_NOTE", ticker: "PFE", text: ""}, {type: "SET_BRIDGE", patch: {}}, {type: "MOVE_COLUMN", colId: "nope", dir: 1},
  ];
  for (const a of noops) assert.equal(reduce(s0, a, p), s0, a.type);
  const changes = [
    {type: "SET_BASIS", basis: "FY1"}, {type: "CYCLE_BASIS", dir: 1}, {type: "SET_CURRENCY", currency: "EUR"},
    {type: "SET_EARNINGS", earnings: "adjusted"}, {type: "SET_PRESET", preset: "growth"}, {type: "SET_CUSTOM_COLUMNS", ids: ["pe"]},
    {type: "PIN_COLUMN", colId: "pe"}, {type: "RESIZE_COLUMN", colId: "pe", width: 100}, {type: "SORT", colId: "pe"},
    {type: "SET_FILTER", filter: {colId: "pe", op: ">=", value: 10}}, {type: "TOGGLE_EXCLUDE", ticker: "PFE"},
    {type: "SET_OUTLIERS", mode: "exclude"}, {type: "SET_PRIMARY", colId: "ev_ebitda"}, {type: "SET_DOT_METRIC", colId: "ev"},
    {type: "SET_CF_MODE", mode: "premium"}, {type: "CYCLE_DENSITY"},
    {type: "SET_TEXT_SIZE", delta: 1}, {type: "TOGGLE_SUMMARY_ROWS"}, {type: "TOGGLE_SUMMARY_EXPANDED", layout: "laptop"},
    {type: "SET_CHART_STRIP", layout: "laptop", value: "collapsed"}, {type: "SAVE_LAYOUT", name: "Mine", now: 0},
    {type: "SAVE_SET", name: "Obesity", now: 0}, {type: "SET_SUBGROUP", name: "Big", tickers: ["PFE"]},
    {type: "SET_STATS_GROUP", group: "US"}, {type: "SET_COHORTS", ids: ["system"]}, {type: "SET_PEER_NOTE", ticker: "PFE", text: "x"},
    {type: "SET_NOTE", ticker: "AZN", text: "note", now: 0}, {type: "SET_BRIDGE", patch: {stat: "mean"}},
    {type: "SET_SINGLE_KEYS", on: false}, {type: "OPEN_DETAIL", ticker: "PFE"}, {type: "FOCUS_CELL", row: "AZN", col: "pe"},
    {type: "TOGGLE_ROW_EXPANDED", ticker: "PFE"}, {type: "OPEN_METHOD", anchor: "stats"},
    {type: "OPEN_PEERS"}, {type: "OPEN_PEERS", search: true},
    {type: "OPEN_OVERLAY", overlay: "palette"}, {type: "SHOW_COLUMN", colId: "country"},
    {type: "HIDE_COLUMN", colId: "pe"},
  ];
  for (const a of changes) assert.notEqual(reduce(s0, a, p), s0, a.type);
  let s = reduce(s0, {type: "SORT", colId: "pe"}, p);
  assert.deepEqual(s.sort, {colId: "pe", dir: "desc"});
  s = reduce(s, {type: "SORT", colId: "pe"}, p);
  assert.deepEqual(s.sort, {colId: "pe", dir: "asc"});
  s = reduce(s, {type: "SORT", colId: "pe"}, p);
  assert.equal(s.sort, null);
  const peerT = peerSetTickers(p, s0).tickers[0];
  const other = p.companies.find((c) => c.ticker !== "AZN" && c.engine === "pharma").ticker;
  let e = reduce(s0, {type: "TOGGLE_EXCLUDE", ticker: peerT}, p);
  assert.deepEqual(e.excluded, [peerT]);
  e = reduce(e, {type: "SET_FOCAL", ticker: other}, p);
  assert.deepEqual(e.excluded, []);
  e = reduce(e, {type: "SET_FOCAL", ticker: "AZN"}, p);
  assert.deepEqual(e.excluded, [peerT]);
  const d = reduce(s0, {type: "SET_DOT_METRIC", colId: "ev"}, p);
  assert.equal(d.primaryOverride, s0.primaryOverride);
  const sc = reduce({...s0, preset: "core"}, {type: "SHOW_COLUMN", colId: "country"}, p);
  assert.equal(sc.preset, "custom");
  assert.equal(sc.customColumns[sc.customColumns.length - 1], "country");
  assert.ok(sc.customColumns.includes("pe"));
  const rm = reduce(s0, {type: "REMOVE_PEER", ticker: peerT, now: 1000}, p);
  assert.ok(!peerSetTickers(p, rm).tickers.includes(peerT));
  assert.equal(rm.ui.undo.label, `Removed ${peerT} from peers`);
  const un = reduce(rm, {type: "UNDO"}, p);
  assert.ok(peerSetTickers(p, un).tickers.includes(peerT));
  assert.equal(un.ui.undo, null);
  assert.equal(reduce(rm, {type: "EXPIRE_UNDO", now: 1000 + UNDO_MS - 1}, p), rm);
  assert.equal(reduce(rm, {type: "EXPIRE_UNDO", now: 1000 + UNDO_MS}, p).ui.undo, null);
  const pe = persistable(e);
  assert.ok(!("excluded" in pe.local));
  assert.ok(!("ui" in pe.local));
  assert.ok(!("focal" in pe.local));
  assert.deepEqual(pe.session.excluded.AZN, [peerT]);
});

// 29 --------------------------------------------------------------------------------------------
test("29 migrateState: defaults, dropping unknowns, round trip", () => {
  const d = migrateState(null);
  assert.deepEqual(migrateState({version: 99, basis: "FY1"}), d);
  const tickers = FIX.companies.map((c) => c.ticker);
  const raw = {version: 1, basis: "FY1", byEngine: {pharma: {preset: "core", customColumns: ["pe", "bogus"], hidden: ["nope"], pinned: ["pe"], dotMetric: "ev"}},
    peerEdits: {AZN: {added: ["SYNA", "ZZZZ"], removed: [], notes: {SYNA: "x", ZZZZ: "y"}}}, primaryOverride: {pharma: "runway_months", biotech: "ev_revenue"},
    savedSets: {S: {tickers: ["SYNA", "NOPE"], notes: {}, created: "2026-09-29", engine: "pharma"}}};
  const m = migrateState(raw, tickers);
  assert.deepEqual(m.byEngine.pharma.customColumns, ["pe"]);
  assert.deepEqual(m.byEngine.pharma.hidden, []);
  assert.equal(m.byEngine.pharma.dotMetric, "ev");
  assert.deepEqual(m.peerEdits.AZN.added, ["SYNA"]);
  assert.deepEqual(Object.keys(m.peerEdits.AZN.notes), ["SYNA"]);
  assert.deepEqual(m.savedSets.S.tickers, ["SYNA"]);
  assert.equal(m.primaryOverride.pharma, null);
  assert.equal(m.primaryOverride.biotech, "ev_revenue");
  let s = defaultState(FIX, {focal: "AZN", engine: "pharma"}, m);
  s = reduce(s, {type: "SAVE_LAYOUT", name: "L", now: 5}, FIX);
  s = reduce(s, {type: "SET_BRIDGE", patch: {stat: "p25"}}, FIX);
  const local = persistable(s).local;
  assert.deepEqual(migrateState(JSON.parse(JSON.stringify(local)), tickers), local);
  const again = defaultState(FIX, {focal: "AZN", engine: "pharma"}, local);
  assert.equal(again.basis, "FY1");
  assert.deepEqual(again.customColumns, ["pe"]);
});

// 30 --------------------------------------------------------------------------------------------
/** Minimal CSV line parser (quoted fields with doubled quotes). */
function parseCsvLine(line) {
  const out = [];
  let cur = "", q = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (q) {
      if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (ch === '"') q = false;
      else cur += ch;
    } else if (ch === '"') q = true;
    else if (ch === ",") { out.push(cur); cur = ""; }
    else cur += ch;
  }
  out.push(cur);
  return out;
}
test("30 toCSV and toTSV", () => {
  const st = {...defaultState(FIX, {focal: "CRSP", engine: "cellgene"}), preset: "core"};
  const v = deriveView(FIX, st);
  const csv = toCSV(v);
  const lines = csv.trim().split("\n");
  assert.match(lines[0], /^# Comps for CRSP, Cell and gene, clinical, 0, basis NTM, Standardised, USD, generated 2026-09-29T22:40:11Z$/);
  assert.ok(lines[1].startsWith("Company,Ticker,"));
  assert.ok(lines[1].includes("P/E (×, NTM E, calc.)"));
  assert.ok(lines[1].includes("Market cap (USD bn, calc.)"));
  const crsp = parseCsvLine(lines[2]);
  const header = parseCsvLine(lines[1]);
  assert.equal(crsp[header.indexOf("P/E (×, NTM E, calc.)")], "n.m.");
  assert.equal(header.indexOf("PEG (×, NTM E, calc.)"), -1);   // PEG left the core preset (12.7)
  const custom = toCSV(deriveView(FIX, {...st, preset: "custom", customColumns: ["pe", "peg"]})).trim().split("\n");
  assert.equal(parseCsvLine(custom[2])[parseCsvLine(custom[1]).indexOf("PEG (×, NTM E, calc.)")], "n.m.");
  const blank = lines.indexOf("");
  assert.ok(blank > 2);
  assert.ok(parseCsvLine(lines[blank + 1])[0].startsWith("Mean, "));
  assert.match(lines[lines.length - 1], /^# Prices 2026-09-28; FX ECB reference rates, 28 Sep 2026; USD at the ECB/);
  const a = deriveView(FIX, {...defaultState(FIX, {focal: "AZN", engine: "pharma"}), preset: "core"});
  const acsv = toCSV(a).split("\n");
  const ah = parseCsvLine(acsv[1]);
  const arow = parseCsvLine(acsv[2]);
  assert.ok(Math.abs(Number(arow[ah.indexOf("P/E (×, NTM E, calc.)")]) - 166.15 / 10.24611) < 1e-9);
  const evPeers = a.table.rows.find((r) => r.ticker === "AZN");
  assert.ok(evPeers);
  const tsv = toTSV(a);
  assert.ok(!tsv.startsWith("#"));
  assert.ok(tsv.split("\n")[0].startsWith("Company\tTicker"));
  const nullCsv = toCSV(view(payloadOf([AZN(), rec("NOPT", {patch: (r) => { r.street.price_target = null; r.na = {"street.price_target": "no_consensus"}; }})]), "AZN", {preset: "core"}));
  const nl = nullCsv.split("\n"), nh = parseCsvLine(nl[1]);
  const noptRow = parseCsvLine(nl.find((l) => l.startsWith("Synthetic NOPT,")));
  assert.equal(noptRow[nh.indexOf("Street target (%, sourced)")], "");
});

// 31 --------------------------------------------------------------------------------------------
test("31 compareCells puts n.m., nulls and errors last in both directions", () => {
  const cells = [
    {ticker: "A", status: "na", v: null}, {ticker: "B", status: "ok", v: 3}, {ticker: "C", status: "err", v: null},
    {ticker: "D", status: "nm", v: null}, {ticker: "E", status: "ok", v: 9}, {ticker: "F", status: "nb", v: null},
  ];
  const desc = cells.slice().sort((a, b) => compareCells(a, b, "desc")).map((c) => c.ticker);
  const asc = cells.slice().sort((a, b) => compareCells(a, b, "asc")).map((c) => c.ticker);
  assert.deepEqual(desc, ["E", "B", "D", "F", "A", "C"]);
  assert.deepEqual(asc, ["B", "E", "D", "F", "A", "C"]);
});

// 32 --------------------------------------------------------------------------------------------
test("32 keys: normKey, one binding per key, single-key switch", () => {
  assert.equal(normKey({key: "?", shiftKey: true}), "?");
  assert.equal(normKey({key: "+", shiftKey: true}), "+");
  assert.equal(normKey({key: "X", shiftKey: true}), "shift+x");
  assert.equal(normKey({key: "k", metaKey: true}, true), "mod+k");
  assert.equal(normKey({key: "k", ctrlKey: true}, false), "mod+k");
  assert.equal(normKey({key: "k", ctrlKey: true}, true), "k");
  assert.equal(normKey({key: "Escape"}), "esc");
  assert.equal(normKey({key: "ArrowUp"}), "up");
  assert.equal(normKey({key: "Enter", shiftKey: true}), "shift+enter");
  const all = COMMANDS.flatMap((c) => c.keys);
  assert.equal(new Set(all).size, all.length);
  for (const k of all) assert.ok(KEYMAP[k]);
  for (const c of COMMANDS) for (const k of c.keys) assert.equal(KEYMAP[k], c.id);
  for (const c of COMMANDS) assert.ok(!("parent" in c) && c.when !== "parent");
  const on = {singleKeys: true}, off = {singleKeys: false};
  for (const c of COMMANDS.filter((x) => x.keys.length)) {
    for (const k of c.keys) {
      const zone = c.when === "grid" ? "grid" : "page";
      assert.equal(handleKey(on, k, zone), c.id, `${k} on`);
    }
  }
  for (const c of COMMANDS.filter((x) => x.singleKey)) assert.equal(handleKey(off, c.keys[0], "page"), null, c.id);
  assert.equal(handleKey(off, "mod+k", "page"), "palette.open");
  assert.equal(handleKey(off, "/", "page"), null);
  assert.equal(handleKey(off, "esc", "page"), "overlay.close");
  assert.equal(handleKey(off, "mod+z", "page"), "undo");
  assert.equal(handleKey(off, "down", "grid"), "grid.down");
  assert.equal(handleKey(off, "x", "grid"), "peer.exclude");
  assert.equal(handleKey(on, "x", "page"), null);
  assert.equal(handleKey(on, "1", "page"), "preset.1");
});

// Live payload: the six focal companies of the brief derive without a crash.
test("payload: deriveView for AZN, LLY, GILD, CRSP, VRTX and PFE", {skip: !PAYLOAD}, () => {
  for (const t of ["AZN", "LLY", "GILD", "CRSP", "VRTX", "PFE"]) {
    const v = view(PAYLOAD, t);
    assert.equal(v.error, null, t);
    assert.deepEqual(v.sectionErrors, {}, t);
    assert.ok(v.table.rows.length >= 2, t);
    assert.equal(v.focal.ticker, t);
  }
});

test("palette extras are generated, searchable and in house style", () => {
  const v = view(FIX, "AZN");
  const extras = core.paletteExtras(v, v.analysis.state);
  assert.ok(extras.some((e) => e.label === "Go to column P/E"));
  assert.ok(extras.some((e) => e.label === "Set period FY1"));
  assert.ok(extras.some((e) => e.label === "Make CRSP focal"));
  const hits = core.matchCommands("go to col p/e", COMMANDS, extras);
  assert.equal(hits[0].label, "Go to column P/E");
  const names = FIX.companies.flatMap((c) => [c.ticker, c.name]);
  for (const e of extras) assert.deepEqual(lintCopy(e.label, "label", names), [], e.label);
});

// =============================================================================================
// Revision 3 (docs/design/comps-valuation.md, section 12). Numbers follow the list in 12.11.
// =============================================================================================

const {flagMarks, flagTouches, mergeBridge, PRESETS} = core;

// R3.2 -----------------------------------------------------------------------------------------
test("R3.2 presets: nine columns each, the lists of 12.7", () => {
  const want = {
    core: ["market_cap", "ev", "pe", "ev_ebitda", "ev_revenue", "fcf_yield", "price_to_book", "pt_upside", "revenue_growth"],
    growth: ["revenue", "revenue_growth", "revenue_cagr3", "ebitda_growth", "eps_growth", "gross_margin", "operating_margin", "net_margin", "roic"],
    balance: ["market_cap", "net_debt", "net_debt_ebitda", "cash_to_mcap", "runway_months", "beta", "vol_1y", "est_dispersion", "n_estimates"],
    pharma: ["market_cap", "pe", "ev_ebitda", "revenue_growth", "operating_margin", "loe_share_5y", "rd_pct", "late_trials", "pipeline_ps"],
    biotech: ["market_cap", "ev_revenue", "price_to_sales", "mcap_to_cash", "revenue_growth", "runway_months", "lead_phase", "catalysts_12m", "pt_upside"],
    cellgene: ["market_cap", "mcap_to_cash", "runway_months", "lead_phase", "trial_concentration", "late_trials", "catalysts_12m", "vol_1y", "pt_upside"],
  };
  assert.equal(core.MAX_PRESET_COLUMNS, 9);
  assert.deepEqual(PRESETS.map((p) => p.id), ["core", "growth", "balance", "pharma", "biotech", "cellgene", "custom"]);
  for (const p of PRESETS.filter((x) => x.id !== "custom")) {
    assert.equal(p.columns.length, core.MAX_PRESET_COLUMNS, p.id);
    assert.deepEqual(p.columns, want[p.id], p.id);
    for (const c of p.columns) assert.ok(core.COLUMN_BY_ID[c], c);
  }
  assert.deepEqual(PRESETS.find((p) => p.id === "custom").columns, []);
  // The primary column is still inserted when the preset lacks it, and a dropped column is reachable.
  const v = view(payloadOf([rec("F0", {e1: null, e2: null}), ...pharmaPeers([12, 14, 15, 16, 18])]), "F0", {preset: "balance"});
  assert.equal(v.primary.colId, "ev_ebitda");
  assert.equal(v.table.columns.filter((c) => !c.frozen).length, 10);
  assert.ok(v.table.columns.find((c) => c.id === "ev_ebitda").autoPinned);
  const s2 = reduce(defaultState(FIX, {focal: "AZN", engine: "pharma"}), {type: "SHOW_COLUMN", colId: "major_products"}, FIX);
  assert.ok(s2.customColumns.includes("major_products"));
});

// R3.3 -----------------------------------------------------------------------------------------
test("R3.3 flagMarks: a marker only where the flag bears on the printed value", () => {
  const M = (code, col, key, extra = {}) => flagMarks({code, ...extra}, col, key, null);
  const Tch = (code, col, key, extra = {}) => flagTouches({code, ...extra}, col, key, null);
  // stale_price
  assert.ok(M("stale_price", "price", "-") && !M("stale_price", "market_cap", "-"));
  // stale_consensus: forward earnings cells
  for (const [c, k] of [["pe", "NTM"], ["pe", "FY1"], ["peg", "NTM"], ["eps_growth", "NTM"], ["eps_cagr", "NTM"], ["est_dispersion", "FY1"], ["n_estimates", "FY1"]]) {
    assert.ok(M("stale_consensus", c, k), `${c} ${k}`);
  }
  assert.ok(!M("stale_consensus", "pe", "FY0") && !M("stale_consensus", "eps_growth", "FY0"));
  // stale_balance_sheet
  for (const c of ["ev", "net_debt", "price_to_book", "cash_to_mcap", "mcap_to_cash", "roic"]) assert.ok(M("stale_balance_sheet", c, "-"), c);
  assert.ok(!M("stale_balance_sheet", "market_cap", "-"));
  // Row properties: no cell marker, though the logic still sees them.
  assert.ok(Tch("stale_fiscal_year", "revenue", "FY0") && !M("stale_fiscal_year", "revenue", "FY0"));
  assert.ok(Tch("fiscal_year_end", "pe", "FY1") && !M("fiscal_year_end", "pe", "FY1") && !M("fiscal_year_end", "revenue", "FY0"));
  for (const c of core.COLUMNS) assert.ok(!M("source_failed", c.id, "FY0"), c.id);
  // Info flags: none.
  assert.ok(Tch("fx_converted", "revenue", "FY0") && !M("fx_converted", "revenue", "FY0"));
  assert.ok(Tch("market_cap_diluted_route", "market_cap", "-") && !M("market_cap_diluted_route", "market_cap", "-"));
  assert.ok(Tch("cover_count_exception", "market_cap", "-") && !M("cover_count_exception", "market_cap", "-"));
  for (const code of ["ifrs_filer", "non_sec_filer", "no_tagged_addbacks"]) for (const c of core.COLUMNS) assert.ok(!M(code, c.id, "FY0"), `${code} ${c.id}`);
  // currency_mismatch
  for (const c of ["revenue", "net_debt", "ev", "revenue_per_late_trial", "ev_per_late_trial"]) assert.ok(M("currency_mismatch", c, "FY0"), c);
  assert.ok(!M("currency_mismatch", "pe", "NTM"));
  // includes_minorities: the profit line, or the equity line
  assert.ok(M("includes_minorities", "pe", "FY0") && M("includes_minorities", "pe", "LTM") && M("includes_minorities", "net_margin", "FY0"));
  assert.ok(!M("includes_minorities", "pe", "NTM") && !M("includes_minorities", "price_to_book", "-"));
  const eq = {params: {line: "equity"}};
  assert.ok(M("includes_minorities", "price_to_book", "-", eq) && M("includes_minorities", "roic", "FY0", eq) && !M("includes_minorities", "pe", "FY0", eq));
  // stale_shares and market_cap_disagreement: the market cap cell only
  for (const code of ["stale_shares", "market_cap_disagreement"]) {
    assert.ok(M(code, "market_cap", "-"), code);
    for (const c of ["ev", "price_to_sales", "fcf_yield", "price_to_book", "mcap_to_cash", "cash_to_mcap", "ev_revenue", "ev_ebitda", "ev_per_late_trial", "pipeline_to_ev"]) {
      assert.ok(Tch(code, c, "FY0") && !M(code, c, "FY0"), `${code} ${c}`);
    }
    assert.ok(Tch(code, "pe", "FY0") && !M(code, "pe", "FY0"));
  }
  // derived operating income
  for (const code of ["derived_operating_income", "derived_no_addback"]) {
    for (const c of ["operating_margin", "ebitda_margin", "ev_ebitda", "net_debt_ebitda", "roic"]) assert.ok(M(code, c, "FY0"), `${code} ${c}`);
    assert.ok(!M(code, "pe", "NTM") && !M(code, "market_cap", "-"));
  }
  // The cell's own computation raises derived_no_addback on EBITDA growth too, so it marks there.
  assert.ok(M("derived_no_addback", "ebitda_growth", "FY0") && !M("derived_operating_income", "ebitda_growth", "FY0"));
  // no_consensus and eps_sign_change: the cells state the reason themselves
  for (const c of core.COLUMNS) assert.ok(!M("no_consensus", c.id, "NTM") && !M("eps_sign_change", c.id, "NTM"), c.id);
  assert.ok(Tch("eps_sign_change", "pe", "NTM"));
  // thin_estimates by period
  const thin = (per) => ({params: {period: per}});
  assert.ok(M("thin_estimates", "peg", "NTM", thin("FY3")) && M("thin_estimates", "eps_cagr", "NTM", thin("FY3")));
  assert.ok(M("thin_estimates", "eps_growth", "NTM", thin("FY2")) && M("thin_estimates", "pe", "FY2", thin("FY2")) && !M("thin_estimates", "pe", "NTM", thin("FY2")));
  assert.ok(M("thin_estimates", "pe", "FY1", thin("FY1")) && !M("thin_estimates", "pe", "FY2", thin("FY1")));
  // estimate_range_wide: the range cell only
  assert.ok(M("estimate_range_wide", "est_dispersion", "FY1") && Tch("estimate_range_wide", "pe", "NTM") && !M("estimate_range_wide", "pe", "NTM"));
  // guidance_fx_unstated
  assert.ok(M("guidance_fx_unstated", "revenue_growth", "FY1") && M("guidance_fx_unstated", "ev_revenue", "FY1") && !M("guidance_fx_unstated", "revenue_growth", "FY0"));
  // burn_flattered
  assert.ok(M("burn_flattered", "runway_months", "-") && !M("burn_flattered", "cash_to_mcap", "-"));
  // calc_failed: every cell reads the null glyph and is red
  const bad = cell(rec("BAD", {error: "boom"}), "pe", ctx());
  assert.equal(bad.text, "—");
  assert.deepEqual([bad.status, bad.red, bad.marks], ["err", true, ["calc_failed"]]);

  // cell.amber and the tooltip lines follow marks.
  const st = rec("ST", {flags: [{code: "stale_shares", severity: "amber", params: {as_of: "2024-02-01"}}]});
  const mc = cell(st, "market_cap", ctx()), er = cell(st, "ev_revenue", ctx({basis: "FY0"}));
  assert.deepEqual([mc.marks, mc.amber, mc.flagLines.length], [["stale_shares"], true, 1]);
  assert.ok(er.flags.includes("stale_shares"));
  assert.deepEqual([er.marks, er.amber, er.flagLines], [[], false, []]);
  const wide = rec("WD", {flags: [{code: "estimate_range_wide", severity: "amber", params: {low: 1, high: 9, mean: 5}}]});
  assert.equal(cell(wide, "pe", ctx()).amber, false);
  assert.ok(cell(wide, "pe", ctx()).flags.includes("estimate_range_wide"));
  assert.equal(cell(wide, "est_dispersion", ctx()).amber, true);
  const derived = rec("DV", {derived: true, amort: 100});
  const eg = cell(derived, "ebitda_growth", ctx({earnings: "adjusted"}));
  assert.ok(eg.flags.includes("derived_no_addback") && eg.marks.includes("derived_no_addback"));
});

test("R3.3b ticker markers follow the confidence points; the rest lives in the detail panel", () => {
  if (PAYLOAD) {
    const v = view(PAYLOAD, "AZN");
    assert.equal(v.table.rows.length, 18);
    for (const r of v.table.rows) {
      assert.deepEqual(r.tickerFlags, [], r.ticker);
      assert.deepEqual(r.tickerLines, [], r.ticker);
      assert.ok(!("amberFlags" in r) && !("flagLines" in r), r.ticker);
      assert.deepEqual([r.cells.ticker.amber, r.cells.ticker.red, r.cells.ticker.marks], [false, false, []], r.ticker);
    }
    // Amber cells are the derived operating income cells and the market cap cell whose share count is stale.
    const marks = {};
    for (const r of v.table.rows) for (const c of v.table.columns.filter((x) => x.numeric)) {
      const cc = r.cells[c.id];
      assert.equal(cc.amber || cc.red, cc.marks.length > 0, `${r.ticker} ${c.id}`);
      for (const m of cc.marks) marks[`${m}@${c.id}`] = (marks[`${m}@${c.id}`] || 0) + 1;
    }
    assert.deepEqual(Object.keys(marks).sort(), ["derived_operating_income@ev_ebitda", "derived_operating_income@operating_margin",
      "market_cap_disagreement@market_cap", "stale_shares@market_cap"]);
    // The side panel lists every flag of the company with the columns it marks.
    const d = view(PAYLOAD, "AZN", {ui: {...defaultState(PAYLOAD, {focal: "AZN"}).ui, detail: "LLY"}}).detail;
    assert.deepEqual(d.flags.map((f) => f.code).sort(), byT(PAYLOAD, "LLY").flags.map((f) => f.code).sort());
    const dv = d.flags.find((f) => f.code === "derived_operating_income");
    assert.deepEqual(dv.cells, ["EV/EBITDA", "EBITDA margin", "Operating margin", "ROIC", "Net debt / EBITDA"]);
    assert.deepEqual(d.flags.find((f) => f.code === "stale_price").cells, ["Price"]);
    assert.deepEqual(d.flags.find((f) => f.code === "cover_count_exception").cells, []);
    const sev = d.flags.map((f) => ({red: 0, amber: 1, info: 2})[f.severity]);
    assert.deepEqual(sev, sev.slice().sort((a, b) => a - b));
  }
  // A focal with a costing flag on its primary cell carries it.
  const a = AZN();
  a.flags.find((f) => f.code === "estimate_range_wide").params.n = 3;
  a.periods.FY1.eps_n = 3;
  const costing = view(payloadOf([a].concat(pharmaPeers([12, 14, 15.36, 16, 18]))), "AZN");
  assert.deepEqual(costing.table.rows[0].tickerFlags, ["estimate_range_wide"]);
  assert.equal(costing.table.rows[0].tickerLines.length, 1);
  assert.ok(costing.table.rows[0].cells.ticker.amber);
  const calm = view(payloadOf([AZN()].concat(pharmaPeers([12, 14, 15.36, 16, 18]))), "AZN");
  assert.deepEqual(calm.table.rows[0].tickerFlags, []);
  // A peer with derived operating income carries it only while the derived-share penalty is in force.
  const dflag = [{code: "derived_operating_income", severity: "amber", params: {}}];
  const focal = rec("F0", {e1: null, e2: null});
  const peers = (nDerived) => [0, 1, 2, 3, 4].map((i) => rec(`P${i}`, {ebitda: 2500 + 200 * i, ...(i < nDerived ? {derived: true, flags: dflag} : {})}));
  const two = view(payloadOf([focal, ...peers(2)]), "F0");
  assert.equal(two.primary.colId, "ev_ebitda");
  const flagged = two.table.rows.filter((r) => r.tickerFlags.length).map((r) => r.ticker).sort();
  assert.deepEqual(flagged, ["P0", "P1"]);
  assert.deepEqual(two.table.rows.find((r) => r.ticker === "P0").tickerFlags, ["derived_operating_income"]);
  const one = view(payloadOf([focal, ...peers(1)]), "F0");
  assert.deepEqual(one.table.rows.filter((r) => r.tickerFlags.length), []);
  assert.ok(one.table.rows.find((r) => r.ticker === "P0").cells.ev_ebitda.amber);   // the cell marker stays
  // Any row: a failed view source and a failed calculation.
  const failed = rec("SF", {flags: [{code: "source_failed", severity: "amber", params: {source: "consensus_nasdaq", run_id: 123}}]});
  const other = rec("OF", {flags: [{code: "source_failed", severity: "amber", params: {source: "press_ir", run_id: 123}}]});
  const broken = rec("BR", {error: "division by zero"});
  const fv = view(payloadOf([AZN(), failed, other, broken].concat(pharmaPeers([12, 14, 15.36, 16, 18]))), "AZN",
    {peerEdits: {AZN: {added: ["BR"], removed: [], notes: {}}}});
  const row = (t) => fv.table.rows.find((r) => r.ticker === t);
  assert.deepEqual(row("SF").tickerFlags, ["source_failed"]);
  assert.match(row("SF").tickerLines[0], /^Refresh run 123: consensus_nasdaq failed/);
  assert.deepEqual(row("OF").tickerFlags, []);
  assert.deepEqual(row("BR").tickerFlags, ["calc_failed"]);
  assert.ok(row("BR").cells.ticker.red);
});

// R3.10 ----------------------------------------------------------------------------------------
test("R3.10 reducer: one right-side surface, ADOPT_PERSISTED and mergeBridge", () => {
  const p = PAYLOAD || FIX;
  const s0 = defaultState(p, {focal: "AZN", engine: "pharma"});
  assert.deepEqual([s0.ui.peers, s0.ui.peersSearch, "lowerTab" in s0.ui, "insightTab" in s0.ui, "why" in s0.ui],
    [false, false, false, false, false]);
  const surfaces = (s) => [s.ui.detail, s.ui.peers, s.ui.method];
  const peer = peerSetTickers(p, s0).tickers[0];
  let s = reduce(s0, {type: "OPEN_DETAIL", ticker: peer}, p);
  assert.deepEqual(surfaces(s), [peer, false, null]);
  s = reduce(s, {type: "OPEN_PEERS", search: true}, p);
  assert.deepEqual(surfaces(s), [null, true, null]);
  assert.equal(s.ui.peersSearch, true);
  assert.equal(reduce(s, {type: "OPEN_PEERS", search: true}, p), s);
  s = reduce(s, {type: "OPEN_METHOD", anchor: "sources"}, p);
  assert.deepEqual(surfaces(s), [null, false, "sources"]);
  assert.equal(s.ui.peersSearch, false);
  s = reduce(s, {type: "OPEN_PEERS"}, p);
  assert.deepEqual(surfaces(s), [null, true, null]);
  assert.equal(s.ui.peersSearch, false);
  s = reduce(s, {type: "OPEN_DETAIL", ticker: peer}, p);
  assert.deepEqual(surfaces(s), [peer, false, null]);
  s = reduce(s, {type: "OPEN_METHOD"}, p);
  assert.deepEqual(surfaces(s), [null, false, "stats"]);
  s = reduce(reduce(s, {type: "OPEN_PEERS"}, p), {type: "CLOSE_PEERS"}, p);
  assert.deepEqual(surfaces(s), [null, false, null]);
  const open = deriveView(p, reduce(s0, {type: "OPEN_PEERS", search: true}, p));
  assert.deepEqual([open.peers.open, open.peers.search, open.peers.title], [true, true, "Edit peers"]);
  assert.deepEqual([view(p, "AZN").peers.open, view(p, "AZN").peers.search], [false, false]);

  // ADOPT_PERSISTED: what another frame stored replaces the persisted slices; focal, engine, live and ui stay.
  const theirs = reduce(reduce(reduce(reduce(defaultState(p, {focal: peer, engine: "pharma"}),
    {type: "SET_BASIS", basis: "FY0"}, p), {type: "SET_BRIDGE", patch: {stat: "mean"}}, p),
    {type: "SET_PRESET", preset: "growth"}, p), {type: "REMOVE_PEER", ticker: "AZN", now: 0}, p);
  const stored = persistable({...theirs, excludedByFocal: {AZN: [peer]}});
  const mine = reduce(reduce(s0, {type: "OPEN_PEERS"}, p), {type: "OPEN_OVERLAY", overlay: "palette"}, p);
  const adopted = reduce(mine, {type: "ADOPT_PERSISTED", local: stored.local, session: stored.session}, p);
  assert.deepEqual([adopted.focal, adopted.engine, adopted.live], ["AZN", "pharma", true]);
  assert.equal(adopted.ui, mine.ui);
  assert.deepEqual([adopted.basis, adopted.preset], ["FY0", "growth"]);
  assert.deepEqual(adopted.bridge, {[peer]: {stat: "mean"}});
  assert.deepEqual(adopted.peerEdits[peer].removed, ["AZN"]);
  assert.deepEqual(adopted.excluded, [peer]);
  assert.deepEqual(persistable(adopted).local, stored.local);
  // Adopting what this state already holds is the identity, and so is an empty event.
  const own = persistable(mine);
  assert.equal(reduce(mine, {type: "ADOPT_PERSISTED", local: own.local, session: own.session}, p), mine);
  assert.equal(reduce(mine, {type: "ADOPT_PERSISTED"}, p), mine);
  // A session-only event moves the exclusions alone.
  const sess = reduce(mine, {type: "ADOPT_PERSISTED", local: null, session: {excluded: {AZN: [peer, "NOPE"]}}}, p);
  assert.deepEqual([sess.excluded, sess.basis], [[peer], mine.basis]);

  // mergeBridge touches only bridge[focal].
  const blob = {...stored.local, bridge: {LLY: {stat: "p75"}, AZN: {stat: "mean"}}};
  const merged = mergeBridge(blob, "AZN", {colId: "pe", stat: "p25", multipleOverride: null, bogus: 1});
  assert.deepEqual(merged.bridge, {LLY: {stat: "p75"}, AZN: {colId: "pe", stat: "p25"}});
  const rest = (b) => { const o = {...b}; delete o.bridge; return o; };
  assert.deepEqual(rest(merged), rest(blob));
  assert.deepEqual(blob.bridge.AZN, {stat: "mean"});   // the input is not mutated
  assert.deepEqual(mergeBridge(JSON.stringify(blob), "AZN", {stat: "median"}).bridge.AZN, {stat: "median"});
  assert.deepEqual(mergeBridge(blob, "AZN", null).bridge, {LLY: {stat: "p75"}});
  assert.deepEqual(mergeBridge(blob, "AZN", {}).bridge, {LLY: {stat: "p75"}});
  assert.deepEqual(mergeBridge(null, "AZN", {stat: "mean"}), {version: 1, bridge: {AZN: {stat: "mean"}}});
  assert.deepEqual(mergeBridge("not json", "AZN", {stat: "mean"}), {version: 1, bridge: {AZN: {stat: "mean"}}});
  assert.deepEqual(migrateState(mergeBridge(null, "AZN", {stat: "mean"})).bridge, {AZN: {stat: "mean"}});
});

// R3.11 ----------------------------------------------------------------------------------------
test("R3.11 basis chip, view badge, footer, bridge line and the command list", () => {
  const p = PAYLOAD || FIX;
  const basis = (patch) => view(p, "AZN", patch).header.basis;
  assert.deepEqual([basis({}).text, basis({}).nonDefault], ["Basis", false]);
  assert.deepEqual([basis({currency: "EUR"}).text, basis({currency: "EUR"}).nonDefault], ["Basis: EUR", true]);
  assert.equal(basis({currency: "REPORTED"}).text, "Basis: as reported");
  assert.equal(basis({earnings: "adjusted"}).text, "Basis: ex amort.");
  assert.equal(basis({currency: "EUR", earnings: "adjusted"}).text, "Basis: EUR, ex amort.");
  assert.match(basis({}).tooltip, /^USD at the ECB reference rate of 28 Sep 2026/);
  assert.match(basis({currency: "EUR", earnings: "adjusted"}).tooltip, /^EUR at the ECB reference rate.*Earnings ex amort\. and IPR&D: operating income and EBITDA excluding/);
  assert.match(basis({currency: "REPORTED"}).tooltip, /^Each company's filing currency and standard/);
  assert.match(basis({}).tooltip, /Forward earnings: Nasdaq consensus/);
  assert.ok(!/Forward earnings/.test(basis({basis: "FY0"}).tooltip));

  assert.deepEqual(view(p, "AZN").table.viewBadge, {count: 0, lines: [], label: "View"});
  const vb = view(p, "AZN", {statsGroup: "US", outliers: "exclude", cfMode: "percentile", density: "compact", textSize: 14, summaryRows: false}).table.viewBadge;
  assert.deepEqual(vb.lines, ["Statistics over US", "Outliers excluded", "Format: percentile rank", "Compact rows", "Text 14 px", "Summary rows off"]);
  assert.deepEqual([vb.count, vb.label], [6, "View · 6"]);
  assert.deepEqual(view(p, "AZN", {layouts: {Mine: {preset: "core"}}}).table.viewBadge.count, 0);   // layouts never count

  const v = view(p, "AZN");
  assert.equal(v.footer.buttonLabel, "Sources and method");
  assert.equal(v.footer.anchor, "sources");
  assert.match(v.footer.text, /^Prices close 28 Sep 2026 · consensus checked \d+ Sep 2026 · FX ECB 28 Sep 2026 · refresh run 123, partial · saved in this browser only$/);
  assert.equal(v.footer.tone, v.header.dataAsOf.tone);
  const clean = clone(FIX);
  clean.as_of.run.failed_sources = [];
  for (const c of clean.companies) c.flags = c.flags.filter((f) => f.code !== "stale_price");
  assert.equal(view(clean, "AZN").footer.tone, "neutral");
  const stale = clone(clean);
  byT(stale, "AZN").flags.push({code: "stale_price", severity: "amber", params: {as_of: "2026-09-20", trading_days: 6}});
  assert.equal(view(stale, "AZN").footer.tone, "flag");
  const failed = clone(clean);
  failed.as_of.run.failed_sources = [{source: "prices", ticker: "AZN", message: "timeout"}];
  assert.equal(view(failed, "AZN").footer.tone, "flag");
  const bare = clone(clean);
  byT(bare, "AZN").street.consensus_checked_at = null;
  bare.as_of.run = null;
  assert.match(view(bare, "AZN").footer.text, / · no consensus check on file · FX ECB 28 Sep 2026 · no refresh run on file · /);

  if (PAYLOAD) {
    assert.equal(v.bridgeLine.text, "AZN against Big pharma, commercial, 17: peer median P/E (NTM) of 15.4×, 14 of 17 peers with a value.");
    assert.equal(v.bridgeLine.linkLabel, "Change peers or metric in Comps");
    assert.equal(v.bridgeLine.storageLine, "Peer set and inputs are saved in this browser only.");
    const an = view(PAYLOAD, "AZN", {bridge: {AZN: {multipleOverride: 16, stat: "median"}}}).bridgeLine.text;
    assert.equal(an, "AZN against Big pharma, commercial, 17: analyst P/E (NTM) of 16.0×, 14 of 17 peers with a value.");
    const p75 = view(PAYLOAD, "AZN", {bridge: {AZN: {colId: "ev_ebitda", stat: "p75"}}}).bridgeLine.text;
    assert.match(p75, /^AZN against Big pharma, commercial, 17: peer 75th percentile EV\/EBITDA of \d+\.\d×, \d+ of 17 peers with a value\.$/);
    const off = view(PAYLOAD, "AZN", {bridge: {AZN: {colId: "pe", basis: "FY0", metricOverride: -5}}});
    assert.equal(off.bridge.enabled, false);
    assert.equal(off.bridgeLine.text, "AZN against Big pharma, commercial, 17.");
  }

  const ids = COMMANDS.map((c) => c.id);
  for (const id of ["peers.edit", "sources.open"]) {
    assert.ok(ids.includes(id), id);
    assert.deepEqual(core.COMMAND_BY_ID[id].keys, [], id);
  }
  assert.deepEqual(["peers.edit", "sources.open"].map((id) => core.COMMAND_BY_ID[id].label),
    ["Edit peers", "Sources and method"]);
  // Revision 4 (company-scorecard.md 5.2): the palette commands catalysts.open and forecast.open
  // left with Drivers and risks and the KPI strip, "Why?" with the banner, and "Copy summary"
  // with the conclusion it copied.
  for (const id of ["catalysts.open", "forecast.open", "why.toggle", "summary.copy"]) assert.ok(!ids.includes(id), id);
  assert.ok(!ids.includes("bridge.reset"));
  assert.equal(new Set(ids).size, ids.length);
  assert.equal(KEYMAP.a, "peer.add");
  const keys = COMMANDS.flatMap((c) => c.keys);
  assert.equal(new Set(keys).size, keys.length);

  // Palette: the two sections of 12.1, and no link out of the frame (the competition rows left
  // with Drivers and risks).
  const extras = core.paletteExtras(v, v.analysis.state);
  assert.deepEqual(extras.filter((e) => e.group === "Sections" && e.target).map((e) => [e.label, e.target.id]),
    [["Go to section peer position", "charts"], ["Go to section comparable companies", "table"]]);
  assert.ok(!extras.some((e) => /bridge/i.test(e.label)));
  assert.ok(!extras.some((e) => e.link));
  // The constants of 12.0 that stay.
  assert.deepEqual([core.WHOLE_COHORT_MAX, core.MAX_PRESET_COLUMNS], [20, 9]);
  for (const k of ["CATALYST_MIN_PCT", "INSIGHT_ROWS", "CONTEXT_SCHEMA", "GOTO_KEY", "REGULATORY_KINDS"]) assert.ok(!(k in core), k);
  for (const w of ["PoS", "PDUFA", "EMA", "Catalysts"]) assert.ok(core.LINT_ALLOW.includes(w), w);
});

// R3.12 ----------------------------------------------------------------------------------------
test("R3.12 bridge mode: the bridge and its line, nothing else", () => {
  const p = PAYLOAD || FIX;
  const state = defaultState(p, {focal: "AZN", engine: "pharma"});
  const full = deriveView(p, state);
  const b = deriveView(p, state, {mode: "bridge"});
  assert.deepEqual([full.mode, b.mode], ["full", "bridge"]);
  assert.equal(b.error, null);
  assert.deepEqual(b.sectionErrors, {});
  assert.ok(b.bridge && b.bridgeLine && b.focal && b.ctx && b.primary);
  for (const k of ["table", "header", "scope", "dotplot", "peers", "method", "detail", "lineage", "footer"]) {
    assert.equal(b[k], null, k);
  }
  // The same peer set and inputs give the same bridge in both frames.
  assert.deepEqual(b.bridge, full.bridge);
  assert.deepEqual(b.bridgeLine, full.bridgeLine);
  assert.deepEqual(b.primary.candidates, full.primary.candidates);
  // The bridge frame reads a payload with no detail records.
  const lean = clone(p);
  for (const c of lean.companies) delete c.detail;
  const bl = deriveView(lean, state, {mode: "bridge"});
  assert.deepEqual(bl.bridge, full.bridge);
  // Inputs chosen in Comps reach it through the shared state.
  const edited = reduce(reduce(state, {type: "SET_BRIDGE", patch: {stat: "p75"}}, p), {type: "TOGGLE_EXCLUDE", ticker: peerSetTickers(p, state).tickers[0]}, p);
  const be = deriveView(p, edited, {mode: "bridge"});
  assert.equal(be.bridge.stat, "p75");
  assert.deepEqual(be.bridge, deriveView(p, edited).bridge);
  // A disabled bridge: the short line, and the reason as the only state.
  const off = deriveView(p, {...state, bridge: {AZN: {colId: "pe", basis: "FY0", metricOverride: -5}}}, {mode: "bridge"});
  assert.equal(off.bridge.enabled, false);
  assert.match(off.bridgeLine.text, /^AZN against .+\.$/);
  assert.ok(!off.bridgeLine.text.includes(":"));
  assert.deepEqual(off.states.map((s) => s.where), [["bridge"]]);
  assert.equal(off.states[0].detail, off.bridge.reason);
  // Whole-frame errors are the same in both modes.
  assert.equal(deriveView({schema: 2}, state, {mode: "bridge"}).error.title, "This view is out of date");
  assert.equal(deriveView(p, {...state, focal: "NOPE"}, {mode: "bridge"}).error.title, "No record for NOPE");
  assert.equal(deriveView(p, state, {mode: "other"}).mode, "full");
});

// The whole fixture universe derives in both modes and never crashes.
test("R3 payload: every company derives in both modes", {skip: !PAYLOAD}, () => {
  for (const c of PAYLOAD.companies) {
    const v = view(PAYLOAD, c.ticker);
    assert.equal(v.error, null, c.ticker);
    assert.deepEqual(v.sectionErrors, {}, c.ticker);
    assert.ok(v.table.columns.filter((x) => !x.frozen).length <= core.MAX_PRESET_COLUMNS + 1, c.ticker);
    for (const r of v.table.rows) assert.ok(Array.isArray(r.tickerFlags), c.ticker);
    const b = deriveView(PAYLOAD, defaultState(PAYLOAD, {focal: c.ticker, engine: ""}), {mode: "bridge"});
    assert.equal(b.error, null, c.ticker);
    assert.deepEqual(b.sectionErrors, {}, c.ticker);
    assert.ok(b.bridgeLine.text.startsWith(`${c.ticker} against `), c.ticker);
  }
  // Every pharma cohort is taken whole: 17 peers each.
  for (const c of PAYLOAD.companies.filter((x) => x.engine === "pharma")) {
    assert.equal(view(PAYLOAD, c.ticker).peers.n, 17, c.ticker);
  }
});

// ---------------------------------------------------------------------------------------------
// Revision 4: the company scorecard (docs/design/company-scorecard.md 5.2, 6.3, 7.2). The frame
// fixture payload with the scorecard block E1's builder wrote for the 2026-10-01 book.
// ---------------------------------------------------------------------------------------------

const SCORECARD_PATH = path.join(HERE, "../../../backend/tests/fixtures/company_score/sample_scorecard.json");
const SCORECARD = fs.existsSync(SCORECARD_PATH) ? JSON.parse(fs.readFileSync(SCORECARD_PATH, "utf8")) : null;
const SCP = PAYLOAD && SCORECARD ? {...PAYLOAD, scorecard: SCORECARD} : null;
const scState = (focal, actions = [], p = SCP) => {
  let st = defaultState(p, {focal, engine: ""}, null, null);
  for (const a of actions) st = reduce(st, a, p);
  return st;
};
const scView = (focal, actions = [], p = SCP) => core.deriveView(p, scState(focal, actions, p));

test("R4.1 buildScorecard: the cohort's rows in rank order, shaded cells, titles and the context line", {skip: !SCP}, () => {
  const v = scView("AZN");
  assert.deepEqual(v.sectionErrors, {});
  const S = v.scorecard;
  assert.equal(S.state, "ok");
  assert.equal(S.contextText, "Scored against 18 big pharma");
  assert.deepEqual(S.cohort, {id: "big_pharma", label: "Big pharma", noun: "big pharma", n: 18});
  assert.deepEqual(S.columns.map((c) => c.header), ["grow", "prof", "bal.", "pipe", "dur.", "value"]);
  assert.equal(S.columns[0].title, "Growth: revenue growth; revenue growth, 3-year CAGR");
  assert.deepEqual(S.rows.map((r) => r.ticker), SCORECARD.cohorts.big_pharma.ranked);
  const azn = S.rows.find((r) => r.ticker === "AZN");
  assert.deepEqual([azn.rank, azn.rangeText, azn.score, azn.focal, azn.picked, azn.ranked], [7, "2–11", 58, true, true, true]);
  const cell = (r, id) => r.cells.find((c) => c.id === id);
  // 3.2 and 8.3: UP above 50, DOWN below, opacity 0.85 x |s - 50| / 50, the number on hover only.
  assert.deepEqual(pick(cell(azn, "growth"), ["fill", "alpha", "title"]),
    {fill: "up", alpha: 0.459, title: "Growth 77, on 2 of 2 measures; cohort median 48"});
  assert.deepEqual(pick(cell(azn, "profitability"), ["fill", "alpha"]), {fill: "down", alpha: 0.323});
  assert.equal(cell(azn, "value").title, "Value 46, on 2 of 3 measures; cohort median 49");
  for (const r of S.rows) for (const c of r.cells) {
    if (c.missing) { assert.equal(c.text, "·"); assert.equal(c.fill, null); continue; }
    assert.equal(c.fill, c.score > 50 ? "up" : c.score < 50 ? "down" : null, `${r.ticker} ${c.id}`);
    assert.ok(Math.abs(c.alpha - 0.85 * Math.abs(c.score - 50) / 50) < 1e-3, `${r.ticker} ${c.id}`);
  }
  // ROG has no growth pillar: a dot, no fill, and the reason in its title.
  const rog = cell(S.rows.find((r) => r.ticker === "ROG"), "growth");
  assert.equal(rog.missing, true);
  assert.match(rog.title, /^Growth: /);
  // Nothing under the chart for big pharma; the how-to-read line is the server's copy.
  assert.equal(S.notRankedText, null);
  assert.equal(S.notOnChartText, null);
  assert.equal(S.howToRead, SCORECARD.method.text.how_to_read);
  assert.equal(S.compareLabel, "Compare 1");
  assert.equal(S.compareEnabled, false);
  assert.equal(S.compareTip, "Tick two or three companies");
});

function pick(o, keys) { return Object.fromEntries(keys.map((k) => [k, o[k]])); }

test("R4.2 the commercial cohort names the company not ranked and those not on the chart", {skip: !SCP}, () => {
  const S = scView("BNTX").scorecard;
  assert.equal(S.state, "ok");
  assert.equal(S.contextText, SCORECARD.cohorts.commercial.context_text);
  assert.deepEqual(S.columns.map((c) => c.header), ["grow", "prof", "bal.", "pipe", "value"]);
  assert.equal(S.notRankedText, "Not ranked: ADAPY (2 of 4 pillars, a score needs 3).");
  assert.equal(S.notOnChartText, `Not on the chart: ${SCORECARD.cohorts.commercial.not_on_chart.map((x) => x.ticker).join(", ")} (no value measure on file).`);
  const last = S.rows[S.rows.length - 1];
  assert.deepEqual([last.ticker, last.rank, last.ranked, last.reason], ["ADAPY", null, false, "2 of 4 pillars, a score needs 3"]);
  // A clinical company reads its own two pillars and value.
  assert.deepEqual(scView("CRSP").scorecard.columns.map((c) => c.header), ["pipe", "fund", "value"]);
});

test("R4.3 a scorecard that failed or is absent is one state, and the Table view still works", {skip: !SCP}, () => {
  const failed = scView("AZN", [], {...PAYLOAD, scorecard: {schema: 2, error: "TypeError: boom", cohorts: {}, companies: {}}});
  assert.equal(failed.scorecard.state, "error");
  assert.equal(failed.scorecard.errorText, "The scorecard did not load: TypeError: boom. The Table view still works.");
  assert.ok(failed.table && failed.table.rows.length > 0);
  assert.equal(scView("AZN", [], PAYLOAD).scorecard.errorText,
    "The scorecard did not load: no scorecard in the payload. The Table view still works.");
});

test("R4.4 Compare picks: the focal ticked once, a fourth refused, two needed to open", {skip: !SCP}, () => {
  let st = scState("AZN");
  assert.deepEqual(st.ui.compare, ["AZN"]);
  assert.equal(st.ui.view, "scorecard");
  assert.equal(reduce(st, {type: "OPEN_COMPARE"}, SCP), st, "one pick cannot open Compare");
  st = reduce(st, {type: "TOGGLE_COMPARE", ticker: "LLY"}, SCP);
  st = reduce(st, {type: "TOGGLE_COMPARE", ticker: "PFE"}, SCP);
  assert.deepEqual(st.ui.compare, ["AZN", "LLY", "PFE"]);
  assert.equal(reduce(st, {type: "TOGGLE_COMPARE", ticker: "VRTX"}, SCP), st, "a fourth is refused");
  assert.equal(reduce(st, {type: "TOGGLE_COMPARE", ticker: "NOPE"}, SCP), st, "an unknown ticker is ignored");
  st = reduce(st, {type: "OPEN_COMPARE"}, SCP);
  assert.equal(st.ui.compareOpen, true);
  // Unticking below two closes the sheet; the picks stay for the session.
  let s2 = reduce(st, {type: "TOGGLE_COMPARE", ticker: "LLY"}, SCP);
  s2 = reduce(s2, {type: "TOGGLE_COMPARE", ticker: "PFE"}, SCP);
  assert.deepEqual([s2.ui.compare, s2.ui.compareOpen], [["AZN"], false]);
  assert.equal(reduce(st, {type: "CLOSE_COMPARE"}, SCP).ui.compareOpen, false);
  // A new focal company is ticked once, while there is room; unticked, it is not ticked again.
  let s3 = reduce(scState("AZN"), {type: "SET_FOCAL", ticker: "LLY"}, SCP);
  assert.deepEqual(s3.ui.compare, ["AZN", "LLY"]);
  s3 = reduce(s3, {type: "TOGGLE_COMPARE", ticker: "LLY"}, SCP);
  s3 = reduce(s3, {type: "SET_FOCAL", ticker: "AZN"}, SCP);
  s3 = reduce(s3, {type: "SET_FOCAL", ticker: "LLY"}, SCP);
  assert.deepEqual(s3.ui.compare, ["AZN"]);
  // The switch: the Table view closes Compare and the Scorecard view the peer drawer.
  const tv = reduce(st, {type: "SET_VIEW", value: "table"}, SCP);
  assert.deepEqual([tv.ui.view, tv.ui.compareOpen], ["table", false]);
  assert.equal(reduce(tv, {type: "SET_VIEW", value: "nonsense"}, SCP), tv);
  const withPeers = reduce(tv, {type: "OPEN_PEERS"}, SCP);
  assert.equal(reduce(withPeers, {type: "SET_VIEW", value: "scorecard"}, SCP).ui.peers, false);
  // Only the view is kept in the browser; the picks are not.
  const p = persistable(tv);
  assert.equal(p.local.view, "table");
  assert.ok(!("compare" in p.local) && !JSON.stringify(p.session).includes("compare"));
  assert.equal(migrateState({version: 1, view: "table"}).view, "table");
  assert.equal(migrateState({version: 1, view: "chart"}).view, "scorecard");
  assert.equal(defaultState(SCP, {focal: "AZN"}, {version: 1, view: "table"}, null).ui.view, "table");
});

test("R4.5 buildCompare: groups in order, folded until opened, the best marked by direction", {skip: !SCP}, () => {
  const acts = [{type: "TOGGLE_COMPARE", ticker: "PFE"}, {type: "TOGGLE_COMPARE", ticker: "LLY"}, {type: "OPEN_COMPARE"}];
  const v = scView("AZN", acts);
  const C = v.compare;
  assert.ok(C);
  // The open company first, then by rank: LLY 5th, PFE 13th.
  assert.deepEqual(C.columns.map((c) => c.ticker), ["AZN", "LLY", "PFE"]);
  assert.equal(C.mixed, false);
  assert.equal(C.mixedText, null);
  assert.deepEqual(C.groups.map((g) => g.id), ["company", "score", "growth", "profitability", "balance_sheet", "pipeline",
    "durability", "value", "momentum", "positives", "negatives", "deals", "data"]);
  const g = (id) => C.groups.find((x) => x.id === id);
  for (const id of ["growth", "profitability", "balance_sheet", "pipeline", "durability", "value", "momentum", "data"]) {
    assert.equal(g(id).open, false, id);
    assert.equal(g(id).toggle, true, id);
  }
  for (const id of ["company", "score", "positives", "negatives", "deals"]) assert.equal(g(id).open, true, id);
  // Company score: higher is better, LLY 63 is best.
  const sc = g("score").rows[0];
  assert.deepEqual(sc.cells.map((c) => [c.text, c.sub, c.best]),
    [["58", "7th of 18, range 2–11", false], ["63", "5th of 18, range 1–12", true], ["40", "13th of 18, range 4–17", false]]);
  // Metric rows by their own direction: revenue growth higher (LLY), net debt to OCF lower (AZN).
  const row = (gid, mid) => g(gid).rows.find((r) => r.metric === mid);
  assert.deepEqual(row("growth", "rev_growth").cells.map((c) => c.best), [false, true, false]);
  assert.deepEqual(row("balance_sheet", "nd_ocf").cells.map((c) => c.best), [true, false, false]);
  assert.equal(row("growth", "rev_growth").cells[0].sub, "FY2025, 4th best of 17");
  // A figure the data flags is a dot with its reason, never marked.
  const op = row("profitability", "op_margin").cells;
  assert.equal(op[1].text, "·");
  assert.equal(op[1].reason, SCORECARD.method.reasons.derived_operating_income);
  // Opening a group shows its measures; its first row is the pillar score, shaded.
  const opened = scView("AZN", acts.concat([{type: "TOGGLE_COMPARE_ROW", pillar: "growth"}])).compare;
  assert.equal(opened.groups.find((x) => x.id === "growth").open, true);
  const pillarRow = g("growth").rows[0];
  assert.equal(pillarRow.kind, "pillar");
  assert.deepEqual(pillarRow.cells.map((c) => c.text), ["77", "100", "3"]);
  assert.deepEqual(pillarRow.cells.map((c) => c.best), [false, true, false]);
  assert.equal(pillarRow.cells[0].fill, "up");
  // Positives and negatives: the first three of each, as the scorecard words them.
  assert.deepEqual(g("positives").rows[0].cells[0].lines, SCORECARD.companies.AZN.positives.slice(0, 3).map((x) => x.text));
  assert.equal(g("deals").rows[0].cells[0].text, `${SCORECARD.companies.AZN.facts.deals.n} deals on file, newest Sep 2026`);
  // No Compare unless asked for.
  assert.equal(scView("AZN", acts.slice(0, 2)).compare, null);
});

test("R4.6 buildCompare marks ties, nothing with one value, and no score row across cohorts", {skip: !SCP}, () => {
  const sc = JSON.parse(JSON.stringify(SCORECARD));
  // A tie on revenue growth, and only one company with a cash flow margin.
  sc.companies.LLY.pillars.growth.metrics.find((m) => m.id === "rev_growth").value = sc.companies.PFE.pillars.growth.metrics.find((m) => m.id === "rev_growth").value = 0.5;
  for (const t of ["LLY", "PFE"]) {
    const m = sc.companies[t].pillars.profitability.metrics.find((x) => x.id === "fcf_margin");
    Object.assign(m, {value: null, text: null, score: null, place: null, reason: "not_filed"});
  }
  const p = {...PAYLOAD, scorecard: sc};
  const acts = [{type: "TOGGLE_COMPARE", ticker: "PFE"}, {type: "TOGGLE_COMPARE", ticker: "LLY"}, {type: "OPEN_COMPARE"}];
  const C = scView("AZN", acts, p).compare;
  const row = (gid, mid) => C.groups.find((x) => x.id === gid).rows.find((r) => r.metric === mid);
  assert.deepEqual(row("growth", "rev_growth").cells.map((c) => c.best), [false, true, true]);
  assert.deepEqual(row("profitability", "fcf_margin").cells.map((c) => c.best), [false, false, false]);
  // Across cohorts: the score rows are not marked, the mixed line shows, and a measure outside a
  // cohort's list says so.
  const M = scView("AZN", [{type: "TOGGLE_COMPARE", ticker: "CRSP"}, {type: "TOGGLE_COMPARE", ticker: "BNTX"}, {type: "OPEN_COMPARE"}]).compare;
  assert.equal(M.mixed, true);
  assert.equal(M.mixedText, "Scored against different peers. Compare the measures, not the scores.");
  const score = M.groups.find((x) => x.id === "score").rows[0];
  assert.equal(score.marked, false);
  assert.ok(score.cells.every((c) => !c.best));
  assert.ok(M.groups.find((x) => x.id === "growth").rows[0].cells.every((c) => !c.best));
  const crsp = M.columns.findIndex((c) => c.ticker === "CRSP");
  const gcell = M.groups.find((x) => x.id === "growth").rows.find((r) => r.metric === "rev_growth").cells[crsp];
  assert.equal(gcell.reason, "not scored for clinical-stage biotechs");
  assert.ok(M.groups.some((x) => x.id === "funding"), "the union of the cohorts' pillars");
});

test("R4.7 the panel's scorecard blocks: score line, lines, pillars, deals and weights", {skip: !SCP}, () => {
  const d = scView("AZN", [{type: "OPEN_DETAIL", ticker: "AZN"}]).detail;
  assert.ok(!("against" in d), "Against {focal} is gone");
  const S = d.scorecard;
  assert.equal(S.state, "ok");
  assert.equal(S.scoreLine, "58 · 7th of 18 big pharma · 2nd to 11th in 90 of 100 weightings");
  assert.equal(S.sentence, SCORECARD.companies.AZN.sentence);
  assert.equal(S.weightsText, "Equal weights. Under 90 of 100 random weightings the rank stays between 2nd and 11th.");
  assert.deepEqual(S.positives.map((x) => [x.text, x.pillarLabel]), SCORECARD.companies.AZN.positives.map((x) => [x.text,
    SCORECARD.method.pillars[x.pillar].label]));
  assert.deepEqual(S.business.map((p) => p.id), ["growth", "profitability", "balance_sheet", "pipeline", "durability"]);
  assert.deepEqual(S.price.map((p) => p.id), ["value", "momentum"]);
  assert.equal(S.price[0].onText, "on 2 of 3 measures");
  const dur = S.business.find((p) => p.id === "durability");
  assert.equal(dur.note, "4.6 years of exclusivity left");
  assert.equal(S.loeYearsText, "4.6 years of exclusivity left");
  assert.deepEqual(S.exclusivityRows.map((x) => x.text), ["Lynparza exclusivity ends 8 Sep 2027", "Koselugo exclusivity ends 13 Mar 2028"]);
  assert.equal(S.exclusivityRows[0].lead, "5.6% of FY2025 revenue");
  const ev = S.price[0].metrics.find((m) => m.id === "ev_sales");
  assert.equal(ev.line, "4.7× EV to sales, median 4.8×");
  const eps = S.business[0].metrics.find((m) => m.id === "eps_cagr");
  assert.equal(eps.scored, false);
  // Deals: facts, newest first, at most eight, with the chip; the firepower line.
  assert.equal(S.deals.countText, SCORECARD.companies.AZN.facts.deals.count_text);
  assert.equal(S.deals.chip, "From headlines and filings, not reviewed");
  assert.ok(S.deals.rows.length <= 8);
  const dates = S.deals.rows.map((x) => x.date);
  assert.deepEqual(dates, dates.slice().sort().reverse());
  assert.equal(S.deals.rows[0].quote, SCORECARD.companies.AZN.facts.deals.rows[0].quote, "a quote is verbatim");
  assert.equal(S.firepowerText, "Could fund about $19.8bn of deals before net debt reaches three times operating cash flow.");
  // CRSP: the clinical facts and its one positive, no negative.
  const c = scView("CRSP", [{type: "OPEN_DETAIL", ticker: "CRSP"}]).detail.scorecard;
  assert.equal(c.leadPhaseText, "Lead asset in Phase 1/2");
  assert.equal(c.partnerText, "Shares Casgevy, VRTX's marketed drug");
  assert.equal(c.negatives.length, 0);
  assert.equal(c.noNegative, "No measure in the cohort's bottom quarter.");
  // The panel of a company outside the focal cohort reads its own cohort.
  const other = scView("AZN", [{type: "OPEN_DETAIL", ticker: "CRSP"}]).detail.scorecard;
  assert.equal(other.cohortNoun, "clinical-stage biotechs");
});

test("R4.8 full mode derives no conclusion, KPI strip, observations, insight or scatter", {skip: !SCP}, () => {
  const v = scView("AZN");
  for (const k of ["conclusion", "kpis", "observations", "insight", "scatter"]) assert.ok(!(k in v), k);
  for (const k of ["conclusion", "observations", "buildKpis", "scatterModel", "summaryText", "INSIGHT_COPY"]) assert.ok(!(k in core), k);
  assert.ok(v.table && v.dotplot && v.header && v.scorecard);
  assert.equal(v.uiView, "scorecard");
  // The Scorecard view's methodology drawer says how the scorecard is scored, and only that.
  const m = scView("AZN", [{type: "OPEN_METHOD", anchor: "scorecard"}]).method;
  assert.deepEqual(m.sections.map((s) => s.id), ["scorecard"]);
  assert.equal(m.sections[0].title, "How it is scored, each from 0 to 100");
  assert.ok(m.sections[0].body.some((b) => b.startsWith("Cohort: Big pharma, 18 companies")));
  const t = scView("AZN", [{type: "SET_VIEW", value: "table"}, {type: "OPEN_METHOD"}]).method;
  assert.ok(t.sections.some((s) => s.id === "stats") && t.sections.some((s) => s.id === "scorecard"));
  // Every company of the fixture derives with the scorecard and no section error.
  for (const c of PAYLOAD.companies) {
    const x = scView(c.ticker, [{type: "OPEN_DETAIL", ticker: c.ticker}]);
    assert.deepEqual(x.sectionErrors, {}, c.ticker);
    assert.equal(x.scorecard.state, "ok", c.ticker);
    assert.equal(x.detail.scorecard.state, "ok", c.ticker);
  }
});

test("R4.9 house style over the scorecard's fixed copy and every line the frame prints", {skip: !SCP}, () => {
  const bad = [];
  const check = (s, kind, where) => { if (!s) return; const i = lintCopy(s, kind, ["ADAPY", "XLV", "CAGR", "FY0", "EV", "P/E"]); if (i.length) bad.push(`${where}: ${i.join(", ")}: ${s}`); };
  const C = core.SCORECARD_COPY;
  for (const [k, v] of Object.entries(C)) {
    if (typeof v === "string") check(v.replace(/\{\w+\}/g, "X"), /^(views|headings|table)$/.test(k) ? "label" : "sentence", k);
    else for (const [k2, v2] of Object.entries(v)) check(v2, "label", `${k}.${k2}`);
  }
  for (const t of ["AZN", "LLY", "CRSP", "BNTX", "QURE"]) {
    const acts = [{type: "OPEN_DETAIL", ticker: t}, {type: "TOGGLE_COMPARE", ticker: "PFE"}, {type: "TOGGLE_COMPARE", ticker: "CRSP"}, {type: "OPEN_COMPARE"}];
    const v = scView(t, acts);
    const S = v.scorecard;
    for (const x of [S.contextText, S.notRankedText, S.notOnChartText, S.howToRead]) check(x, "sentence", `${t} scorecard`);
    for (const r of S.rows) for (const c of r.cells) check(c.title, "sentence", `${t} cell`);
    const D = v.detail.scorecard;
    for (const x of [D.scoreLine, D.sentence, D.weightsText, D.firepowerText, D.leadPhaseText, D.partnerText, D.deals.countText,
      D.marketCapAltText, D.loeYearsText, D.productCoverageText]) check(x, "sentence", `${t} detail`);
    for (const p of D.business.concat(D.price)) {
      check(p.reasonText, "sentence", `${t} ${p.id}`);
      for (const m of p.metrics) for (const x of [m.reasonText, m.notScoredText, m.line]) check(x, "sentence", `${t} ${m.id}`);
    }
    // Deal quotes are headlines verbatim and are not linted (2.10).
    if (v.compare) for (const g of v.compare.groups) for (const r of g.rows) for (const c of r.cells) {
      for (const x of [c.sub, c.reason].concat(c.lines || [])) check(x, "sentence", `${t} compare ${r.id}`);
    }
  }
  assert.deepEqual(bad, []);
});
