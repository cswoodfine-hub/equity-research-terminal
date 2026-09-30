// Tests for frontend/components/compsval/core.js (spec docs/design/comps-valuation.md, 10.2).
// Run: node --test "*.test.js" from this folder.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

import * as core from "../../components/compsval/core.js";

const {
  quantile, median, mean, summarize, percentileRank, quartileSide, premium, isInLine, fences, outlierClass, ols,
  multipleDirection, cell, companyType, isPreRevenue, primaryMetric, relevance, defaultPeers, mixedModels,
  peerStats, bridge, scatterModel, dotplotModel, observations, deriveView, defaultState, reduce, persistable,
  migrateState, toCSV, toTSV, compareCells, normKey, handleKey, KEYMAP, COMMANDS, lintCopy, NA_TEXT, STATE_COPY,
  flagText, COLUMNS, FLAG_SEVERITY, UNDO_MS, PREMIUM_METRICS, peerSetTickers, metricAvailability,
} = core;

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIX = JSON.parse(fs.readFileSync(path.join(HERE, "fixture_min.json"), "utf8"));
const PAYLOAD_PATH = path.join(HERE, "fixture_payload.json");
const PAYLOAD = fs.existsSync(PAYLOAD_PATH) ? JSON.parse(fs.readFileSync(PAYLOAD_PATH, "utf8")) : null;
// Focal contexts of GET /companies/{ticker}/comps-context (section 12.2), keyed by ticker: the
// reference bodies for AZN, LLY, NVO, VKTX, CRSP, BAYN, AMGN and VRTX on the 2026-09-29 book.
const CONTEXTS = JSON.parse(fs.readFileSync(path.join(HERE, "fixture_context.json"), "utf8"));

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

// 3 ---------------------------------------------------------------------------------------------
test("3 quartileSide agrees with the p75 row, not the mid-rank percentile", () => {
  const peers = [1, 2, 3, 4, 5, 6, 7, 8];
  assert.equal(quantile(peers, 0.75), 6.25);
  assert.equal(percentileRank(6.1, peers), 75);
  assert.notEqual(quartileSide(6.1, peers), "top");
  assert.equal(quartileSide(6.25, peers), "top");
  assert.equal(quartileSide(1, peers), "bottom");
  assert.equal(quartileSide(9, [1, 2, 3, 4]), null);
});

// 4 ---------------------------------------------------------------------------------------------
test("4 isInLine rounds to whole percents", () => {
  assert.equal(isInLine(0.044), true);
  assert.equal(isInLine(0.045), false);
  assert.equal(isInLine(-0.049), false);
  assert.equal(isInLine(null), false);
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

// 6 ---------------------------------------------------------------------------------------------
test("6 ols recovers an exact line and needs 5 points", () => {
  const pts = [0, 1, 2, 3, 4].map((x) => ({x, y: 2 + 3 * x}));
  const fit = ols(pts);
  assert.ok(Math.abs(fit.slope - 3) < 1e-12 && Math.abs(fit.intercept - 2) < 1e-12);
  assert.equal(fit.r2, 1);
  assert.equal(fit.n, 5);
  assert.equal(ols(pts.slice(0, 4)), null);
  assert.equal(ols([1, 1, 1, 1, 1].map((x, i) => ({x, y: i}))), null);
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
    assert.match(v.conclusion.headline, /the median of 14 big pharma peers, 15\.4×\.$/);
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
  assert.equal(b.conclusion.headline, a.conclusion.headline);
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

// 21 --------------------------------------------------------------------------------------------
test("21 scatterModel regions, median fallback, direction words, disabled", () => {
  const xs = [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35];
  const peers = xs.map((x, i) => rec(`S${i}`, {g: x, pe: 10 + 50 * x}));
  const focalAt = (x, rel) => rec("F", {g: x, pe: (10 + 50 * x) * (1 + rel)});
  const reg = (x, rel) => scatterModel(focalAt(x, rel), rowsOf(peers), "revenue_growth", "pe", ctx()).region.id;
  assert.equal(reg(0.3, 0.3), "above_better");
  assert.equal(reg(0.05, 0.3), "above_worse");
  assert.equal(reg(0.3, -0.3), "below_better");
  assert.equal(reg(0.05, -0.3), "below_worse");
  assert.equal(reg(0.2, 0.05), "near");
  const neg = [0.0, 0.05, 0.1, 0.15, 0.2, 0.25].map((x, i) => rec(`N${i}`, {g: x, pe: 20 - 50 * x}));
  const fm = scatterModel(rec("F", {g: 0.6, pe: 12}), rowsOf(neg), "revenue_growth", "pe", ctx());
  assert.equal(fm.reference, "median");
  assert.match(fm.interpretation, /the peer trend gives no usable value/);
  const loePeers = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6].map((l, i) => rec(`L${i}`, {pe: 10 + 10 * l, hc: {loe_share_5y: l}}));
  const lf = scatterModel(rec("F", {pe: 30, hc: {loe_share_5y: 0.05}}), rowsOf(loePeers), "loe_share_5y", "pe", ctx());
  assert.match(lf.region.label, /better than median/);
  const few = scatterModel(focalAt(0.2, 0.1), rowsOf(peers.slice(0, 2)), "revenue_growth", "pe", ctx());
  assert.match(few.disabledReason, /^Only 2 peers have both revenue growth and P\/E; at least 3 are needed\.$/);
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

// 23 --------------------------------------------------------------------------------------------
test("23 observations: quartile rules, severity, suppression, own copy", () => {
  const four = [0.01, 0.02, 0.03, 0.04].map((g, i) => rec(`O${i}`, {g}));
  const focal = rec("F", {g: 0.2});
  assert.ok(!observations(focal, rowsOf(four), ctx()).premium.some((o) => o.id === "growth_top"));
  const five = four.concat([rec("O4", {g: 0.05})]);
  assert.ok(observations(focal, rowsOf(five), ctx()).premium.some((o) => o.id === "growth_top"));
  const eight = [1, 2, 3, 4, 5, 6, 7, 8].map((g, i) => rec(`Q${i}`, {g: g / 100}));
  const at61 = observations(rec("F", {g: 0.061}), rowsOf(eight), ctx());
  assert.ok(!at61.premium.some((o) => o.id === "growth_top"));
  const clin = rec("CL", {stage: "clinical", rev: null, runway: 10});
  const rs = observations(clin, rowsOf(five), ctx()).discount.find((o) => o.id === "runway_short");
  assert.equal(rs.severity, "red");
  const margins = [0.1, 0.12, 0.14, 0.16, 0.18].map((m, i) => rec(`M${i}`, {op: 10000 * m}));
  const lly = rec("LLY_LIKE", {op: 4560, derived: true,
    flags: [{code: "derived_operating_income", field: "periods.FY0.operating_income_usd_m", severity: "amber", params: {}}]});
  const lo = observations(lly, rowsOf(margins), ctx());
  assert.ok(!lo.premium.some((o) => o.id === "margin_top"));
  assert.ok(lo.suppressed.some((s) => s.id === "margin_top"));
  const thin = observations(rec("TH", {n1: 2}), rowsOf(five), ctx()).discount.find((o) => o.id === "estimates_thin");
  assert.equal(thin.long, "Only 2 analysts cover FY1 EPS.");
  const disp = [0.1, 0.12, 0.14, 0.16, 0.18].map((d, i) => rec(`D${i}`, {disp: d}));
  const wide = observations(rec("W", {disp: 0.4}), rowsOf(disp), ctx()).discount.find((o) => o.id === "estimates_wide");
  assert.match(wide.long, /^Analyst EPS estimates span 40% of the mean, wider than most peers \(median 14%\)\.$/);
  assert.equal(observations(focal, rowsOf(five), ctx()).notAssessed.length, 2);
});

// 24 --------------------------------------------------------------------------------------------
const view = (p, focal, patch = {}) => deriveView(p, {...defaultState(p, {focal, engine: ""}), ...patch});
test("24 conclusion templates", () => {
  const ok = view(payloadOf([AZN()].concat(pharmaPeers([12, 14, 15.36, 16, 18]))), "AZN");
  assert.equal(ok.header.peerSet.full, "Big pharma, commercial, 5");
  assert.equal(ok.conclusion.state, "ok");
  assert.equal(ok.conclusion.headline, "AZN trades at 16.2× P/E (NTM), a 6% premium to the median of 5 big pharma peers, 15.4×.");
  assert.deepEqual(ok.conclusion.token, {text: "+6%", caption: "premium to median", dir: "up"});
  assert.match(ok.conclusion.support, /^Alongside the premium, AZN has /);
  assert.ok(!/associated with/.test(ok.conclusion.support));
  assert.equal(ok.conclusion.label, "System-generated summary from the table below. It states associations, not causes.");
  assert.equal(ok.conclusion.labelShort, "System-generated");
  assert.ok(!("tone" in ok.conclusion.token));

  const inl = view(payloadOf([AZN()].concat(pharmaPeers([14, 15, 16, 17, 18]))), "AZN");
  assert.equal(inl.conclusion.headline, "AZN trades at 16.2× P/E (NTM), in line with the median of 5 big pharma peers, 16.0× (+1%).");
  assert.equal(inl.conclusion.token.caption, "in line with median");
  assert.equal(inl.conclusion.token.dir, null);

  const fcfPeers = [6000, 8000, 10000, 12000, 14000].map((fcf, i) => rec(`FY${i}`, {pe: 15, fcf}));
  const fcf = view(payloadOf([AZN()].concat(fcfPeers)), "AZN", {primaryOverride: {pharma: "fcf_yield"}});
  assert.equal(fcf.conclusion.headline, "AZN's FCF yield of 4.5% (FY2025) sits against a median of 5.0% for 5 big pharma peers: a 10% premium on this measure.");

  const low = view(payloadOf([AZN()].concat(pharmaPeers([12, 14, 16], {nd: null, rev: 50}))), "AZN");
  assert.equal(low.conclusion.state, "low_confidence");
  assert.equal(low.conclusion.headline, "AZN trades at 16.2× P/E (NTM). Only 3 peers have a value, so no premium or discount is stated.");
  assert.ok(!/%/.test(low.conclusion.headline));
  assert.equal(low.conclusion.bar, "flag");
  assert.ok(low.conclusion.chips.some((c) => c.text === "Low confidence"));

  const few = view(payloadOf([AZN()].concat([rec("K1", {rev: 50, nd: null, pe: 20}), rec("K2", {rev: 50, nd: null, e1: -1, e2: -1})])), "AZN");
  assert.equal(few.conclusion.state, "too_few");
  assert.equal(few.conclusion.headline, "AZN trades at 16.2× P/E (NTM). One peer has a value, so there is no comparison.");
  assert.equal(few.conclusion.support, "Widen the set to adjacent subsectors, or add peers with A.");

  const nocash = rec("NC", {engine: "cellgene", stage: "clinical", rev: null, cash: null, e1: -1, e2: -1,
    patch: (r) => { r.ev.cash_usd_m = null; r.na = {"ev.cash_usd_m": "no_cash"}; }});
  const clinPeers = [1.5, 1.9, 2.07, 2.5, 3.0].map((m, i) => rec(`CG${i}`, {engine: "cellgene", stage: "clinical", rev: null, cash: 2000, mcap: 2000 * m, e1: -2, e2: -1.5, phase: "Phase 2", runway: 20 + 5 * i}));
  const nm = view(payloadOf([nocash].concat(clinPeers)), "NC");
  assert.equal(nm.conclusion.state, "no_multiple");
  assert.equal(nm.conclusion.headline, "No valuation multiple has both a value for NC and 2 or more peer values.");

  const p = payloadOf([AZN()].concat(pharmaPeers([12, 14, 15.36, 16, 18])));
  let st = defaultState(p, {focal: "AZN", engine: ""});
  for (const t of ["SP1", "SP2", "SP3", "SP4", "SP5"]) st = reduce(st, {type: "REMOVE_PEER", ticker: t, now: 0}, p);
  const none = deriveView(p, st);
  assert.equal(none.conclusion.state, "no_peers");
  assert.equal(none.conclusion.headline, "No peers are selected, so there is no comparison.");

  const clin = view(payloadOf([CRSP()].concat(clinPeers)), "CRSP");
  assert.equal(clin.conclusion.headline, "CRSP trades at 2.2× market cap to cash (30 Jun 2026), a 7% premium to the median of 5 clinical cell and gene peers, 2.1×.");
  assert.match(clin.conclusion.support, /^Enterprise value is \$3\.5bn, and cash runway is 77 months on trailing burn\./);

  // Tested association: revenue growth and P/E rise together across these peers.
  const assocPeers = [0.0, 0.02, 0.04, 0.06, 0.08].map((g, i) => rec(`AS${i}`, {g, pe: 10 + 40 * g}));
  const assoc = view(payloadOf([AZN()].concat(assocPeers)), "AZN", {scatter: {x: "revenue_growth", y: "pe", size: "market_cap", trend: true, colorBy: "none", logY: false}});
  assert.match(assoc.conclusion.support, /^The premium is associated with revenue growth in the top quartile of peers/);
  assert.match(assoc.conclusion.supportShort, /^Associated with revenue growth top quartile \(R² 1\.00\)$/);

  // A model observation never enters the support.
  const modelPeers = pharmaPeers([12, 14, 15.36, 16, 18]).map((r) => { r.model = {state: "modelled", pipeline_rnpv_usd_m: 100}; return r; });
  const mv = view(payloadOf([AZN()].concat(modelPeers)), "AZN");
  assert.ok(mv.observations.premium.some((o) => o.id === "pipeline_value"));
  assert.ok(!/modelled pipeline/i.test(mv.conclusion.support));
  assert.ok(!/model/i.test(mv.conclusion.supportShort));

  // Every headline and short support within the limits, for every fixture company.
  const all = [FIX].concat(PAYLOAD ? [PAYLOAD] : []);
  for (const pl of all) {
    for (const c of pl.companies) {
      const v = view(pl, c.ticker);
      assert.equal(v.error, null, c.ticker);
      assert.ok(v.conclusion.headline.length <= 160, `${c.ticker}: ${v.conclusion.headline}`);
      assert.ok(v.conclusion.supportShort.length <= 90, `${c.ticker}: ${v.conclusion.supportShort}`);
      assert.ok(v.conclusion.lookNext.text.length <= 60, `${c.ticker}: ${v.conclusion.lookNext.text}`);
      assert.deepEqual(v.sectionErrors, {}, c.ticker);
    }
  }
});

// 25 --------------------------------------------------------------------------------------------
test("25 confidence: AZN high on the live payload, penalties elsewhere, bar colour", {skip: !PAYLOAD}, () => {
  const azn = view(PAYLOAD, "AZN");
  assert.equal(azn.primary.colId, "pe");
  assert.equal(azn.conclusion.confidence.score, 2);
  assert.equal(azn.conclusion.confidence.level, "high");
  assert.ok(!azn.conclusion.confidence.reasons.some((r) => /IFRS|estimate/i.test(r)));
  assert.equal(azn.conclusion.bar, "active");
  const gild = view(PAYLOAD, "GILD");
  assert.equal(gild.primary.colId, "ev_ebitda");
  assert.ok(gild.conclusion.confidence.reasons.some((r) => /Peers mix IFRS and US GAAP filers, and EV\/EBITDA uses filed figures/.test(r)));
  assert.ok(gild.conclusion.confidence.reasons.some((r) => /peer EBITDA figures are derived and may be overstated/.test(r)));
  assert.equal(gild.conclusion.bar, "flag");
});
test("25b confidence: a padded set costs the appropriate-peer point and turns the bar amber", () => {
  const bf = rec("BF", {engine: "biotech", pe: 20});
  const poolA = [18, 20, 22].map((pe, i) => rec(`BA${i}`, {engine: "biotech", pe}));
  const poolB = [0, 1].map((i) => rec(`BB${i}`, {engine: "biotech", stage: "clinical", rev: null, price: 1, shares: 5, g: null, e1: -1, e2: -1}));
  const v = view(payloadOf([bf, ...poolA, ...poolB]), "BF");
  assert.equal(v.analysis.def.warning, "padded");
  assert.ok(v.conclusion.chips.some((c) => c.text === "Weak peer set"));
  assert.ok(v.conclusion.confidence.reasons.includes("Only 3 of 5 peers score 40 or more on relevance"));
  assert.equal(v.conclusion.bar, "flag");
  assert.ok(v.peers.weak && /added below relevance 40/.test(v.peers.weak.title));
});

// 26 --------------------------------------------------------------------------------------------
test("26 lookNext: a costing flag on the primary cell first, else the strongest observation", () => {
  const a = AZN();
  a.flags.find((f) => f.code === "estimate_range_wide").params.n = 3;
  a.periods.FY1.eps_n = 3;
  const v = view(payloadOf([a].concat(pharmaPeers([12, 14, 15.36, 16, 18]))), "AZN");
  assert.equal(v.conclusion.lookNext.text, "Check AZN's P/E data: wide estimate range");
  assert.deepEqual(v.conclusion.lookNext.target, {kind: "cell", colId: "pe", ticker: "AZN"});
  const w = view(payloadOf([AZN()].concat(pharmaPeers([12, 14, 15.36, 16, 18]))), "AZN");
  const strongest = w.observations.premium.concat(w.observations.discount).filter((o) => o.provenance !== "M")
    .sort((x, y) => y.strength - x.strength)[0];
  assert.equal(w.conclusion.lookNext.text, strongest.tag);
  assert.ok(w.conclusion.lookNext.text.length <= 60);
});

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
    const c = v.conclusion;
    check(c.headline, "sentence", "headline"); check(c.support, "sentence", "support");
    check(c.supportShort, "label", "supportShort"); check(c.label, "sentence", "label"); check(c.labelShort, "label", "labelShort");
    check(c.lookNext.text, "label", "lookNext");
    for (const ch of c.chips) { check(ch.text, "label", "chip"); check(ch.tooltip, "sentence", "chip tooltip"); }
    for (const g of c.why.groups) { check(g.title, "label", "why title"); for (const it of g.items) check(it.text, "sentence", "why item"); }
    for (const o of v.observations.premium.concat(v.observations.discount)) {
      check(o.long, "sentence", `obs ${o.id}`); check(o.short, "sentence", `obs short ${o.id}`); check(o.tag, "label", `obs tag ${o.id}`);
    }
    for (const t of v.observations.notAssessed) check(t, "sentence", "not assessed");
    for (const k of v.kpis) { check(k.label, "label", `kpi ${k.id}`); check(k.tooltip, "sentence", `kpi tooltip ${k.id}`); check(k.period, "label", `kpi period ${k.id}`); }
    for (const s of v.states) { check(s.title, "label", `state ${s.id}`); check(s.detail, "sentence", `state ${s.id}`); }
    check(v.scatter.interpretation, "sentence", "scatter"); check(v.dotplot.description, "sentence", "dotplot");
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
    {type: "SET_LOWER_TAB", tab: "obs"}, {type: "SET_INSIGHT_TAB", tab: "catalysts"}, {type: "SET_INSIGHT_TAB", tab: "bridge"},
    {type: "CLOSE_PEERS"}, {type: "ADOPT_PERSISTED", local: null, session: null},
    {type: "SET_NARROW_TAB", tab: "position"}, {type: "SET_LAPTOP_TAB", tab: "position"},
    {type: "HIDE_COLUMN", colId: "country"}, {type: "ADD_PEER", ticker: "AZN"}, {type: "NOT_AN_ACTION"},
    {type: "SET_SCATTER"}, {type: "SET_TEXT_SIZE", delta: -1}, {type: "SORT", colId: "nope"}, {type: "RESIZE_COLUMN", colId: "nope", width: 90},
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
    {type: "SET_SCATTER", trend: false}, {type: "SET_CF_MODE", mode: "premium"}, {type: "CYCLE_DENSITY"},
    {type: "SET_TEXT_SIZE", delta: 1}, {type: "TOGGLE_SUMMARY_ROWS"}, {type: "TOGGLE_SUMMARY_EXPANDED", layout: "laptop"},
    {type: "SET_CHART_STRIP", layout: "laptop", value: "collapsed"}, {type: "SAVE_LAYOUT", name: "Mine", now: 0},
    {type: "SAVE_SET", name: "Obesity", now: 0}, {type: "SET_SUBGROUP", name: "Big", tickers: ["PFE"]},
    {type: "SET_STATS_GROUP", group: "US"}, {type: "SET_COHORTS", ids: ["system"]}, {type: "SET_PEER_NOTE", ticker: "PFE", text: "x"},
    {type: "SET_NOTE", ticker: "AZN", text: "note", now: 0}, {type: "SET_BRIDGE", patch: {stat: "mean"}},
    {type: "SET_SINGLE_KEYS", on: false}, {type: "OPEN_DETAIL", ticker: "PFE"}, {type: "FOCUS_CELL", row: "AZN", col: "pe"},
    {type: "TOGGLE_ROW_EXPANDED", ticker: "PFE"}, {type: "TOGGLE_WHY"}, {type: "OPEN_METHOD", anchor: "confidence"},
    {type: "SET_INSIGHT_TAB", tab: "competition"}, {type: "OPEN_PEERS"}, {type: "OPEN_PEERS", search: true},
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
    assert.equal(v.kpis.length, 6, t);
    assert.ok(v.table.rows.length >= 2, t);
    assert.ok(v.conclusion.headline.startsWith(t), t);
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

const {flagMarks, flagTouches, indicationTitle, indicationProse, mergeBridge, CONTEXT_NA_TEXT, PRESETS} = core;
const viewCtx = (p, focal, context, patch = {}) => deriveView(p, {...defaultState(p, {focal, engine: ""}), ...patch}, {context});
const ctxOf = (t) => clone(CONTEXTS[t]);
const itemIds = (list) => list.map((i) => i.id);

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
  assert.ok(costing.conclusion.confidence.points.some((p) => p.points === -1 && /FY1 EPS estimates run/.test(p.text)));
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
  assert.ok(two.conclusion.confidence.reasons.some((r) => /2 of 5 peer EBITDA figures are derived/.test(r)));
  const flagged = two.table.rows.filter((r) => r.tickerFlags.length).map((r) => r.ticker).sort();
  assert.deepEqual(flagged, ["P0", "P1"]);
  assert.deepEqual(two.table.rows.find((r) => r.ticker === "P0").tickerFlags, ["derived_operating_income"]);
  const one = view(payloadOf([focal, ...peers(1)]), "F0");
  assert.ok(!one.conclusion.confidence.reasons.some((r) => /derived/.test(r)));
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

// R3.4 -----------------------------------------------------------------------------------------
test("R3.4 insight.state: pending, error, ok; the pending view keeps the metric items", {skip: !PAYLOAD}, () => {
  const none = viewCtx(PAYLOAD, "AZN", null);
  assert.equal(none.insight.state, "pending");
  assert.equal(none.insight.ticker, "AZN");
  assert.equal(none.insight.message.title, "Loading catalysts and competition for AZN");
  assert.equal(none.insight.message.detail, "They arrive with the page once the company changes.");
  assert.equal(none.insight.message.severity, "info");
  assert.deepEqual([none.insight.catalysts.state, none.insight.competition.state], ["pending", "pending"]);
  assert.deepEqual([none.insight.catalysts.rows, none.insight.competition.rows], [[], []]);
  assert.equal(none.insight.catalysts.empty, none.insight.message);
  // The metric-linked observations are client data and show at once.
  assert.deepEqual(itemIds(none.insight.valuation.premium), itemIds(none.observations.premium));
  assert.deepEqual(itemIds(none.insight.valuation.discount), itemIds(none.observations.discount));
  assert.ok(none.insight.valuation.premium.length > 0);
  for (const it of none.insight.valuation.premium.concat(none.insight.valuation.discount)) {
    assert.equal(it.kind, "metric");
    assert.equal(it.link.kind, "column");
    assert.equal(it.linkLabel, core.COLUMN_BY_ID[it.link.colId].label);
    assert.deepEqual(it.chips.map((c) => c.text), it.provenance === "M" ? ["Model output"] : []);
  }
  assert.deepEqual(none.insight.valuation.notAssessed.slice(0, 2), none.observations.notAssessed);
  // Another company's context is never shown.
  const other = viewCtx(PAYLOAD, "AZN", ctxOf("LLY"));
  assert.equal(other.insight.state, "pending");
  assert.deepEqual(other.insight.competition.rows, []);
  assert.deepEqual(deriveView(PAYLOAD, defaultState(PAYLOAD, {focal: "AZN"})).insight.state, "pending");
  // Error context, and a schema this view does not read.
  const err = viewCtx(PAYLOAD, "AZN", {ticker: "AZN", error: "HTTP 500"});
  assert.equal(err.insight.state, "error");
  assert.equal(err.insight.message.title, "Catalysts and competition did not load");
  assert.equal(err.insight.message.detail, "The API did not answer /companies/AZN/comps-context (HTTP 500). Reload with the reload button.");
  assert.equal(err.insight.message.severity, "amber");
  assert.deepEqual([err.insight.catalysts.state, err.insight.competition.state], ["error", "error"]);
  const old = viewCtx(PAYLOAD, "AZN", {...ctxOf("AZN"), schema: 2});
  assert.equal(old.insight.state, "error");
  assert.equal(old.insight.message.title, "This view is out of date");
  assert.match(old.insight.message.detail, /reads data schema 1 and the API sent 2/);
  // A good context.
  const ok = viewCtx(PAYLOAD, "AZN", ctxOf("AZN"));
  assert.deepEqual([ok.insight.state, ok.insight.message, ok.insight.notice], ["ok", null, null]);
  assert.deepEqual([ok.insight.catalysts.state, ok.insight.competition.state], ["ok", "ok"]);
  assert.deepEqual(ok.sectionErrors, {});
  // The model not yet computed: one line above both groups.
  const cold = viewCtx(PAYLOAD, "AZN", {...ctxOf("AZN"), complete: false, incomplete_reason: "model_not_computed"});
  assert.equal(cold.insight.notice, "The model value has not been computed yet. Reload in a minute.");
  // The banner never reads the context: support, the short support and "Look next" are the same.
  for (const k of ["headline", "support", "supportShort"]) assert.equal(ok.conclusion[k], none.conclusion[k], k);
  assert.deepEqual(ok.conclusion.lookNext, none.conclusion.lookNext);
  assert.deepEqual(ok.observations, none.observations);
});

// R3.5 -----------------------------------------------------------------------------------------
test("R3.5 side rules: the four context rules, their thresholds and exact sentences", {skip: !PAYLOAD}, () => {
  const azn = viewCtx(PAYLOAD, "AZN", ctxOf("AZN")).insight;
  const rationed = azn.valuation.discount.find((i) => i.id === "pool_rationed:367");
  assert.equal(rationed.text, "73% of their own forecast is what AZN's 2 modelled obesity candidates keep once 19 modelled drugs share one pool of 107.6m patients. Model output.");
  assert.deepEqual([rationed.kind, rationed.side, rationed.tag, rationed.strength, rationed.severity, rationed.provenance, rationed.twoSided],
    ["competition", "discount", "shared patient pool (model)", 50, "amber", "M", false]);
  assert.deepEqual(rationed.link, {kind: "indication", indicationId: 367, name: "Obesity"});
  assert.equal(rationed.linkLabel, "Obesity, landscape");
  assert.deepEqual(rationed.chips.map((c) => c.text), ["Model output"]);
  assert.ok(!azn.valuation.discount.concat(azn.valuation.premium).some((i) => i.kind === "catalyst"));   // Elecoglipron is 2.8% of price
  assert.ok(!azn.valuation.premium.some((i) => i.kind === "competition"));
  // Order in a side list: metric items by strength, then the catalyst item, then competition items.
  const kinds = azn.valuation.discount.map((i) => i.kind);
  assert.deepEqual(kinds, kinds.slice().sort((a, b) => ["metric", "catalyst", "competition"].indexOf(a) - ["metric", "catalyst", "competition"].indexOf(b)));
  const metric = azn.valuation.discount.filter((i) => i.kind === "metric").map((i) => i.strength);
  assert.deepEqual(metric, metric.slice().sort((a, b) => b - a));

  const lly = viewCtx(PAYLOAD, "LLY", ctxOf("LLY")).insight;
  assert.equal(lly.valuation.discount.find((i) => i.id === "pool_rationed:367").text,
    "73% of their own forecast is what LLY's 4 modelled obesity candidates keep once 19 modelled drugs share one pool of 107.6m patients. Model output.");
  assert.ok(!itemIds(lly.valuation.premium).some((id) => id.startsWith("pool_lead")));   // 23%, second of nine
  assert.ok(!lly.valuation.discount.some((i) => i.kind === "catalyst"));                  // Retatrutide is 2.9% of price

  const nvo = viewCtx(PAYLOAD, "NVO", ctxOf("NVO")).insight;
  const lead = nvo.valuation.premium.find((i) => i.id === "pool_lead:367");
  assert.equal(lead.text, "26% of the patients the modelled drugs start in obesity go to NVO's 4 candidates, the largest share of 9 companies. Model output.");
  assert.deepEqual([lead.side, lead.tag, lead.severity, lead.provenance], ["premium", "largest share of a shared pool (model)", "info", "M"]);
  assert.ok(itemIds(nvo.valuation.discount).includes("pool_rationed:367"));
  assert.equal(nvo.competition.rows[0].side, "both");

  const vk = viewCtx(PAYLOAD, "VKTX", ctxOf("VKTX"));
  const cv = vk.insight.valuation.discount.find((i) => i.id === "catalyst_value");
  assert.equal(cv.text, "72.9% of the price, $24.09 a share, is the risk-adjusted value the model carries for VK2735, whose Phase 3 readout is due around 1 Jul 2027. The outcome can move it either way. Model output.");
  assert.deepEqual([cv.kind, cv.side, cv.twoSided, cv.tag, cv.severity, cv.provenance, cv.strength],
    ["catalyst", "discount", true, "pipeline value on one event (model)", "amber", "M", 50]);
  assert.deepEqual(cv.link, {kind: "tab", tab: "Catalysts"});
  assert.equal(cv.linkLabel, "Catalysts tab");
  assert.deepEqual(cv.chips.map((c) => c.text), ["Model output", "Two-sided"]);
  assert.deepEqual(Object.keys(cv).sort(), Object.keys(rationed).sort());   // one item shape
  // The specific statement replaces the count in the panel; the banner's observations keep it.
  assert.ok(itemIds(vk.observations.discount).includes("binary_catalysts"));
  assert.ok(!itemIds(vk.insight.valuation.discount).includes("binary_catalysts"));
  assert.ok(itemIds(viewCtx(PAYLOAD, "VKTX", null).insight.valuation.discount).includes("binary_catalysts"));
  assert.equal(vk.insight.catalysts.rows[0].side, "discount");

  const amgn = viewCtx(PAYLOAD, "AMGN", ctxOf("AMGN")).insight;
  assert.equal(amgn.valuation.discount.find((i) => i.id === "catalyst_value").text,
    "5.4% of the price, $22.67 a share, is the risk-adjusted value the model carries for Maridebart Cafraglutide, whose Phase 3 readout is due around 21 Jan 2027. The outcome can move it either way. Model output.");
  assert.equal(amgn.valuation.discount.find((i) => i.id === "pool_rationed:367").text,
    "73% of its own forecast is what AMGN's 1 modelled obesity candidate keeps once 19 modelled drugs share one pool of 107.6m patients. Model output.");

  // A stake is the stronger statement: 5% fires, 4.9% does not, and it replaces the value rule.
  const staked = (pct) => {
    const c = ctxOf("VKTX");
    c.catalysts.items = [{...c.catalysts.items[0], id: 900, date: "2027-11-14", asset: {id: 371, name: "Casgevy", is_marketed: true},
      asset_value: null, stake: {per_share: -4.204132, pct_of_price: pct, pos_now: 0.8075, pos_success: 0.95, pos_failure: 0.4, economics_share: 0.4},
      na: {}}];
    c.catalysts.total = 1;
    return viewCtx(PAYLOAD, "VKTX", c).insight;
  };
  const s5 = staked(0.05);
  const cs = s5.valuation.discount.find((i) => i.id === "catalyst_stake");
  assert.equal(cs.text, "5.0% of the price, $4.20 a share, separates success from failure at the Casgevy Phase 3 readout due around 14 Nov 2027. The outcome can move the value either way. Model output.");
  assert.deepEqual([cs.tag, cs.twoSided, cs.side], ["binary catalyst in 12 months (model)", true, "discount"]);
  assert.ok(!itemIds(s5.valuation.discount).includes("catalyst_value") && !itemIds(s5.valuation.discount).includes("binary_catalysts"));
  assert.equal(s5.catalysts.rows[0].modelText, "at stake $4.20 a share, 5.0% of price");
  assert.deepEqual([s5.catalysts.rows[0].tier, s5.catalysts.rows[0].modelKind, s5.catalysts.rows[0].naText], [0, "stake", null]);
  const s49 = staked(0.049);
  assert.ok(!s49.valuation.discount.some((i) => i.kind === "catalyst"));
  assert.ok(itemIds(s49.valuation.discount).includes("binary_catalysts"));
  const both = ctxOf("VKTX");
  both.catalysts.items[1] = {...both.catalysts.items[1], stake: {per_share: 3.3, pct_of_price: 0.1}};
  assert.deepEqual(itemIds(viewCtx(PAYLOAD, "VKTX", both).insight.valuation.discount).filter((id) => id.startsWith("catalyst")), ["catalyst_stake"]);

  // The value rule reads only a regulatory event or a late-phase readout on an unapproved, counted asset.
  const vary = (patch) => {
    const c = ctxOf("VKTX");
    c.catalysts.items = c.catalysts.items.map((it) => ({...it, ...patch(it)}));
    return itemIds(viewCtx(PAYLOAD, "VKTX", c).insight.valuation.discount);
  };
  assert.ok(!vary(() => ({phase: "Phase 2"})).includes("catalyst_value"));
  assert.ok(!vary((it) => ({asset: {...it.asset, is_marketed: true}})).includes("catalyst_value"));
  assert.ok(!vary((it) => ({asset_value: {...it.asset_value, counted: false}})).includes("catalyst_value"));
  assert.ok(!vary((it) => ({asset_value: {...it.asset_value, pct_of_price: 0.0499}})).includes("catalyst_value"));
  assert.ok(vary(() => ({phase: "Phase 2/3"})).includes("catalyst_value"));
  assert.ok(vary(() => ({phase: null, kind: "PDUFA", regulatory: true})).includes("catalyst_value"));

  // Pool rules at their thresholds.
  const pool = (patch) => {
    const c = ctxOf("NVO");
    patch(c.competition.indications[0]);
    const i = viewCtx(PAYLOAD, "NVO", c).insight;
    return itemIds(i.valuation.premium.concat(i.valuation.discount)).filter((id) => id.startsWith("pool_"));
  };
  assert.deepEqual(pool(() => {}), ["pool_lead:367", "pool_rationed:367"]);
  assert.deepEqual(pool((r) => { r.company_pool.keeps = 0.9; }), ["pool_lead:367", "pool_rationed:367"]);
  assert.deepEqual(pool((r) => { r.company_pool.keeps = 0.901; }), ["pool_lead:367"]);
  assert.deepEqual(pool((r) => { r.company_pool.share_of_claims = 0.249; }), ["pool_rationed:367"]);
  assert.deepEqual(pool((r) => { r.company_pool.rank = 2; }), ["pool_rationed:367"]);
  assert.deepEqual(pool((r) => { r.company_pool.of_companies = 2; }), ["pool_rationed:367"]);
  assert.deepEqual(pool((r) => { r.value.pct_of_price = 0.0199; }), []);
  assert.deepEqual(pool((r) => { r.value.pct_of_price = 0.02; }), ["pool_lead:367", "pool_rationed:367"]);
  assert.deepEqual(pool((r) => { r.crowding = null; r.company_pool = null; r.na = {crowding: "flow_pool"}; }), []);
  // Rival counts never take a side.
  for (const t of ["AZN", "LLY", "NVO", "AMGN", "VRTX"]) {
    const i = viewCtx(PAYLOAD, t, ctxOf(t)).insight;
    for (const r of i.competition.rows) if (!r.shareText) assert.equal(r.side, null, `${t} ${r.name}`);
  }
});

// R3.6 -----------------------------------------------------------------------------------------
test("R3.6 catalyst rows: one per asset, the tier order, dates and model cells", {skip: !PAYLOAD}, () => {
  const c = viewCtx(PAYLOAD, "AZN", ctxOf("AZN")).insight.catalysts;
  assert.equal(c.title, "Catalysts ahead");
  assert.equal(c.countText, "36 in 12 months, 24 assets");
  assert.equal(c.rows.length, 24);
  assert.deepEqual(c.link, {kind: "tab", tab: "Catalysts"});
  assert.equal(c.linkLabel, "Open the Catalysts tab");
  assert.equal(c.note, "Dates marked est. come from trial records. A catalyst is two-sided: it can raise or lower the value. Value figures are model output.");
  const assets = c.rows.map((r) => r.assetId);
  assert.equal(new Set(assets).size, assets.length);
  assert.deepEqual(c.rows.slice(0, 5).map((r) => r.label), ["Elecoglipron: Phase 3 readout", "AZD0780: Phase 3 readout",
    "Balcinrenone/dapagliflozin: Phase 3 readout", "Imfinzi: Phase 3 readout", "Datroway: Phase 3 readout"]);
  assert.deepEqual(c.rows.slice(0, 5).map((r) => r.dateShort), ["4 Jun 2027", "4 Jan 2027", "16 Apr 2027", "30 Sep 2026", "30 Sep 2026"]);
  assert.deepEqual(c.rows.slice(0, 5).map((r) => r.indicationText), ["Obesity", null, "Heart failure", "Hepatocellular carcinoma", "Non-small-cell lung carcinoma"]);
  assert.deepEqual(c.rows.slice(0, 5).map((r) => r.moreText), [null, "and 1 more for this asset", null, "and 3 more for this asset", "and 2 more for this asset"]);
  assert.deepEqual(c.rows.slice(0, 5).map((r) => r.tier), [2, 2, 2, 3, 3]);
  const tiers = c.rows.map((r) => r.tier);
  assert.deepEqual(tiers, tiers.slice().sort((a, b) => a - b));
  const [elec, azd, , imfinzi] = c.rows;
  assert.deepEqual([elec.id, elec.assetId, elec.dateIso, elec.estimated, elec.dateText], ["cat-1109", 1744, "2027-06-04", true, "around 4 Jun 2027"]);
  assert.equal(elec.modelText, "$4.73 a share, 2.8% of price, PoS 55%");
  assert.equal(elec.modelKind, "asset_value");
  assert.equal(elec.naText, CONTEXT_NA_TEXT.no_outcome_legs);
  assert.deepEqual(elec.chips.map((x) => x.text), ["Two-sided", "Model output", "Derived, estimated date"]);
  assert.equal(elec.chips[2].tone, "flag");
  assert.equal(elec.sourceUrl, "https://clinicaltrials.gov/study/NCT07775404");
  assert.deepEqual(elec.tooltip.slice(1), ["Source: NCT07775404", "The date is the trial's estimated primary completion."]);
  assert.match(elec.tooltip[0], /^Phase 3, A Study to Investigate the Efficacy and Safety of Elecoglipron/);
  assert.deepEqual(elec.link, {kind: "tab", tab: "Catalysts"});
  assert.equal(elec.side, null);
  assert.equal(azd.modelText, "$0.87 a share, 0.5% of price, PoS 56%");
  assert.equal(azd.indicationNa, CONTEXT_NA_TEXT.no_indication_link);
  // A marketed product: the model states no value for the readout.
  assert.deepEqual([imfinzi.modelText, imfinzi.modelKind], [null, null]);
  assert.equal(imfinzi.naText, "Marketed product. The model states no value for this readout.");
  assert.deepEqual(imfinzi.chips.map((x) => x.text), ["Two-sided", "Derived, estimated date"]);
  // Inside tier 2 the order is the share of price, largest first.
  const t2 = c.rows.filter((r) => r.tier === 2).map((r) => Number(/([\d.]+)% of price/.exec(r.modelText.replace("under ", ""))[1]));
  assert.deepEqual(t2, t2.slice().sort((a, b) => b - a));
  assert.equal(c.rows[2].modelText, "$0.05 a share, under 0.1% of price, PoS 48%");

  // LLY: month dates.
  const l = viewCtx(PAYLOAD, "LLY", ctxOf("LLY")).insight.catalysts;
  assert.equal(l.countText, "33 in 12 months, 16 assets");
  const ret = l.rows[0];
  assert.deepEqual([ret.label, ret.dateShort, ret.dateText, ret.estimated, ret.indicationText, ret.modelText, ret.moreText],
    ["Retatrutide: Phase 3 readout", "Oct 2026", "in Oct 2026", true, "Type 2 diabetes mellitus", "$33.78 a share, 2.9% of price, PoS 88%", "and 3 more for this asset"]);

  // The date forms, the event words and the tier of each kind.
  const base = ctxOf("VKTX").catalysts.items[0];
  const one = (patch) => {
    const x = ctxOf("VKTX");
    x.catalysts.items = [{...base, ...patch}];
    x.catalysts.total = 1;
    return viewCtx(PAYLOAD, "VKTX", x).insight.catalysts.rows[0];
  };
  const pdufa = one({id: 1, date: "2027-02-01", date_confidence: "confirmed", kind: "PDUFA", regulatory: true, phase: null, is_curated: true});
  assert.deepEqual([pdufa.label, pdufa.dateShort, pdufa.dateText, pdufa.estimated, pdufa.tier], ["VK2735: PDUFA date", "1 Feb 2027", "on 1 Feb 2027", false, 1]);
  assert.deepEqual(pdufa.chips.map((x) => x.text), ["Two-sided", "Model output", "Curated"]);
  assert.ok(!pdufa.tooltip.includes("The date is the trial's estimated primary completion."));
  const stated = one({date_confidence: "stated", kind: "regulatory decision", regulatory: true});
  assert.deepEqual([stated.label, stated.dateText, stated.estimated], ["VK2735: regulatory decision", "on 1 Jul 2027", false]);
  const q = one({date: "2026-10", date_precision: "quarter", date_confidence: "quarter"});
  assert.deepEqual([q.dateShort, q.dateText, q.estimated], ["Q4 2026", "in Q4 2026", true]);
  const h = one({date: "2027-03", date_precision: "half", date_confidence: "half"});
  assert.deepEqual([h.dateShort, h.dateText], ["H1 2027", "in H1 2027"]);
  assert.equal(one({date: "2027-09-30", date_precision: "half", date_confidence: "half"}).dateShort, "H2 2027");
  assert.equal(one({kind: "AdCom", regulatory: true}).label, "VK2735: advisory committee");
  assert.equal(one({kind: "EMA decision", regulatory: true}).label, "VK2735: EMA decision");
  assert.equal(one({phase: null}).label, "VK2735: data readout");
  assert.equal(one({kind: "Investor day", regulatory: false}).label, "VK2735: investor day");
  assert.equal(one({phase: "Phase 2"}).tier, 4);
  assert.equal(one({asset_value: null, na: {stake: "not_modelled", asset_value: "not_modelled"}}).tier, 3);
  assert.equal(one({asset_value: null, na: {stake: "not_modelled", asset_value: "not_modelled"}}).naText, CONTEXT_NA_TEXT.not_modelled);
  // No asset: the title, cut at 60 characters, and a row of its own.
  const orphan = one({asset: null, asset_value: null, title: "Phase 3, a study with a very long title that runs well past the sixty character cut", na: {asset: "no_asset", stake: "no_asset"}});
  assert.ok(orphan.label.length <= 60 && orphan.label.endsWith("…"));
  assert.deepEqual([orphan.assetId, orphan.naText], [null, CONTEXT_NA_TEXT.no_asset]);
  // Regulatory events rank ahead of any readout without a stake.
  const mixed = ctxOf("VKTX");
  mixed.catalysts.items.push({...base, id: 999, date: "2027-09-01", kind: "PDUFA", regulatory: true, date_confidence: "confirmed",
    asset: {id: 77, name: "Other", is_marketed: false}, asset_value: null, na: {stake: "not_modelled", asset_value: "not_modelled"}});
  mixed.catalysts.total = 3;
  const mr = viewCtx(PAYLOAD, "VKTX", mixed).insight.catalysts;
  assert.deepEqual(mr.rows.map((r) => [r.label, r.tier]), [["Other: PDUFA date", 1], ["VK2735: Phase 3 readout", 2]]);
  assert.equal(mr.countText, "3 in 12 months, 2 assets");

  // No catalysts: the empty state with the window.
  const crsp = viewCtx(PAYLOAD, "CRSP", ctxOf("CRSP")).insight.catalysts;
  assert.equal(crsp.state, "empty");
  assert.deepEqual(crsp.rows, []);
  assert.equal(crsp.empty.title, "No dated catalysts in the next 12 months");
  assert.equal(crsp.empty.detail, "No pending catalyst for CRSP is dated between 29 Sep 2026 and 29 Sep 2027. The Catalysts tab lists later events.");
});

// R3.7 -----------------------------------------------------------------------------------------
test("R3.7 competition rows: value, counts, pool, share, reasons and the uncovered states", {skip: !PAYLOAD}, () => {
  const g = viewCtx(PAYLOAD, "AZN", ctxOf("AZN")).insight.competition;
  assert.equal(g.title, "Competition by indication");
  assert.equal(g.countText, "5 of 19 valued indications");
  assert.deepEqual(g.columns, ["Indication", "AZN value, $ a share · of price", "Own / rivals", "Pool claimed → supplied", "AZN share"]);
  assert.equal(g.linkLabel, "Open Comps, Indications");
  assert.deepEqual(g.link, g.rows[0].link);
  assert.equal(g.lead, null);
  assert.equal(g.note, "Rivals are big pharma candidates that are marketed or in Phase 2 or later. Value counts each modelled asset in the indication the model sizes it in, else in its lead indication. Pool figures are model output and leave out marketed products valued off reported revenue.");
  assert.deepEqual(g.rows.map((r) => r.name), ["Non-small-cell lung carcinoma", "Breast neoplasms", "Asthma", "Obesity", "Chronic obstructive pulmonary disease"]);
  assert.deepEqual(g.rows.map((r) => r.valueText), ["$21.33 · 12.8%", "$14.32 · 8.6%", "$9.84 · 5.9%", "$8.52 · 5.1%", "$6.83 · 4.1%"]);
  const ob = g.rows[3];
  assert.deepEqual([ob.id, ob.indicationId, ob.name, ob.storedName], ["ind-367", 367, "Obesity", "Obesity"]);
  assert.equal(ob.valueText, "$8.52 · 5.1%");
  assert.equal(ob.ownText, "3 own: 2 Phase 3, 1 Phase 2");
  assert.equal(ob.rivalsText, "29 rivals from 8 companies: 4 marketed, 12 Phase 3, 13 Phase 2");
  assert.equal(ob.poolText, "58% → 42%");
  assert.equal(ob.shareText, "12%, 4th of 9");
  assert.deepEqual([ob.valueNa, ob.poolNa, ob.shareNa], [null, null, null]);
  assert.deepEqual(ob.own, {n: 3, marketed: 0, phase3: 2, phase2: 1, other: 0});
  assert.deepEqual(ob.rivals, {n: 29, marketed: 4, phase3: 12, phase2: 13, other: 0, companies: 8});
  assert.deepEqual([ob.side, ob.provenance], ["discount", "M"]);
  assert.deepEqual(ob.link, {kind: "indication", indicationId: 367, name: "Obesity"});
  assert.deepEqual(ob.tooltip, ["Stored as Obesity.",
    "One population under 4 names: Obesity; Overweight; Weight Loss; Obesity, Morbid.",
    "19 modelled drugs from 9 companies claim 58% of 107.6m patients at the 2054 peak. Counted once, the pool supplies 42%.",
    "AZN's 2 keep 73% of their own forecasts and 5% of the pool.",
    "Elecoglipron: Phase 3, $4.73 a share.", "AZD6234: Phase 3, $3.80 a share.", "Pramlintide: Phase 2, no modelled value counted here."]);
  // Each pool reason is worded, and a share is stated only for a standing pool that is shared.
  assert.deepEqual([g.rows[0].poolText, g.rows[0].poolNa, g.rows[0].shareText, g.rows[0].shareNa], [null, CONTEXT_NA_TEXT.flow_pool, null, CONTEXT_NA_TEXT.flow_pool]);
  assert.equal(g.rows[1].poolNa, CONTEXT_NA_TEXT.claims_exceed_pool);
  assert.deepEqual([g.rows[2].poolText, g.rows[2].shareText, g.rows[2].shareNa], ["5% → 5%", null, "AZN has no modelled drug in the shared pool."]);
  assert.equal(g.rows[0].storedName, "Carcinoma, Non-Small-Cell Lung");
  assert.equal(g.rows[0].ownText, "13 own: 6 marketed, 6 Phase 3, 1 Phase 2");
  assert.equal(g.rows[1].rivalsText, "60 rivals from 13 companies: 21 marketed, 21 Phase 3, 16 Phase 2, 2 earlier");
  const l = viewCtx(PAYLOAD, "LLY", ctxOf("LLY")).insight.competition;
  assert.equal(l.countText, "5 of 22 valued indications");
  assert.deepEqual([l.rows[0].valueText, l.rows[0].shareText], ["$294.31 · 24.8%", "23%, 2nd of 9"]);
  assert.equal(l.rows[3].poolNa, CONTEXT_NA_TEXT.no_pool);
  assert.equal(l.rows[4].poolNa, CONTEXT_NA_TEXT.single_claimant);
  assert.equal(l.rows[4].name, "B-cell chronic lymphocytic leukemia");
  const tiny = ctxOf("AZN");
  tiny.competition.indications[3].crowding = null;
  tiny.competition.indications[3].company_pool = null;
  tiny.competition.indications[3].na = {crowding: "share_under_1pct"};
  assert.equal(viewCtx(PAYLOAD, "AZN", tiny).insight.competition.rows[3].poolNa, CONTEXT_NA_TEXT.share_under_1pct);
  const vr = viewCtx(PAYLOAD, "VRTX", ctxOf("VRTX")).insight.competition;
  assert.equal(vr.rows[2].rivalsText, "0 rivals");
  assert.equal(vr.rows[3].rivalsText, "5 rivals from 4 companies: 4 Phase 3, 1 earlier");

  // Not covered: outside the big pharma engine.
  const crsp = viewCtx(PAYLOAD, "CRSP", ctxOf("CRSP")).insight;
  assert.deepEqual([crsp.state, crsp.competition.state, crsp.competition.link], ["ok", "not_covered", null]);
  assert.deepEqual(crsp.competition.rows, []);
  assert.equal(crsp.competition.empty.title, "Competition by indication is not covered for CRSP");
  assert.equal(crsp.competition.empty.detail, "The indication landscape and the pool model cover the 18 big pharma companies. CRSP is read on the Cell and gene engine, so no rival counts or pool shares are stated.");
  assert.deepEqual(crsp.valuation.premium.concat(crsp.valuation.discount).filter((i) => i.kind !== "metric"), []);
  // No model: ranked by contest, every value null with its reason.
  const bayn = viewCtx(PAYLOAD, "BAYN", ctxOf("BAYN")).insight.competition;
  assert.equal(bayn.state, "ok");
  assert.equal(bayn.countText, "5 of 7 indications, by contest");
  assert.equal(bayn.lead, "No modelled value for BAYN, so indications are ordered by how many companies contest them.");
  assert.equal(bayn.rows[0].name, "Heart failure");
  for (const r of bayn.rows) assert.deepEqual([r.valueText, r.valueNa, r.side], [null, "No forecast model for this company.", null], r.name);
  assert.deepEqual([bayn.rows[0].provenance, bayn.rows[1].provenance, bayn.rows[1].poolText], ["S", "M", "20% → 18%"]);
  // A modelled company whose values are still being computed is not called unmodelled.
  const cold = ctxOf("AZN");
  cold.complete = false; cold.model = {state: "not_computed", assets: 0}; cold.competition.ranked_by = "contest";
  for (const r of cold.competition.indications) { r.value = {per_share: null, pct_of_price: null, assets: 0}; r.na = {...r.na, value: "model_not_computed"}; }
  const cv = viewCtx(PAYLOAD, "AZN", cold).insight;
  assert.equal(cv.competition.lead, "Model values are not computed yet, so indications are ordered by how many companies contest them.");
  assert.equal(cv.competition.rows[0].valueNa, CONTEXT_NA_TEXT.model_not_computed);
  assert.equal(cv.notice, CONTEXT_NA_TEXT.model_not_computed);
  assert.ok(!cv.valuation.discount.some((i) => i.kind === "competition"));   // no value, so no pool item
  // A big pharma company in no landscape entry.
  const empty = ctxOf("BAYN");
  empty.competition = {covered: false, reason: "no_indications", ranked_by: null, total: 0, valued: 0, indications: []};
  const e = viewCtx(PAYLOAD, "BAYN", empty).insight.competition;
  assert.deepEqual([e.state, e.empty.title, e.empty.detail], ["empty", "No indication to compare for BAYN",
    "No BAYN candidate that is marketed or in Phase 2 or later is linked to an indication in the landscape."]);
  // A value with no price on file keeps the money and says nothing of the share.
  const np = ctxOf("AZN");
  np.competition.indications[3].value.pct_of_price = null;
  const npv = viewCtx(PAYLOAD, "AZN", np).insight;
  assert.equal(npv.competition.rows[3].valueText, "$8.52");
  assert.ok(!itemIds(npv.valuation.discount).includes("pool_rationed:367"));
});

// R3.8 -----------------------------------------------------------------------------------------
test("R3.8 indicationTitle and indicationProse", () => {
  const cases = [["Carcinoma, Non-Small-Cell Lung", "Non-small-cell lung carcinoma"], ["Breast Neoplasms", "Breast neoplasms"],
    ["Asthma", "Asthma"], ["Obesity", "Obesity"], ["Pulmonary Disease, Chronic Obstructive", "Chronic obstructive pulmonary disease"],
    ["Diabetes Mellitus, Type 2", "Type 2 diabetes mellitus"], ["Arthritis, Juvenile", "Juvenile arthritis"],
    ["Leukemia, Lymphocytic, Chronic, B-Cell", "B-cell chronic lymphocytic leukemia"], ["beta-Thalassemia", "Beta-thalassemia"]];
  for (const [stored, title] of cases) assert.equal(indicationTitle(stored), title, stored);
  assert.equal(indicationProse("Obesity"), "obesity");
  assert.equal(indicationProse("Pulmonary Disease, Chronic Obstructive"), "chronic obstructive pulmonary disease");
  assert.equal(indicationProse("Carcinoma, Non-Small-Cell Lung"), "non-small-cell lung carcinoma");
  // Acronyms, single letters and proper names keep their capitals in prose.
  assert.equal(indicationProse("Alzheimer Disease"), "Alzheimer disease");
  assert.equal(indicationProse("Lymphoma, Non-Hodgkin"), "non-Hodgkin lymphoma");
  assert.equal(indicationProse("HIV Infections"), "HIV infections");
  assert.equal(indicationProse("Hepatitis B, Chronic"), "chronic hepatitis B");
  assert.equal(indicationProse("Sjogren's Syndrome"), "Sjogren's syndrome");
  assert.equal(indicationTitle(""), "");
  assert.equal(indicationTitle(null), "");
  assert.equal(core.fmtPatients(107592242), "107.6m");
  assert.equal(core.fmtPatients(644112), "644k");
  assert.equal(core.fmtPatients(2197800), "2.2m");
  assert.equal(core.fmtPatients(812), "812");
  assert.equal(core.fmtPatients(null), "—");
});

// R3.9 -----------------------------------------------------------------------------------------
test("R3.9 house style over every revision 3 string", {skip: !PAYLOAD}, () => {
  const names = PAYLOAD.companies.flatMap((c) => [c.ticker, c.name]);
  const bad = [];
  const check = (s, kind, where, extra = []) => {
    if (s == null) return;
    const i = lintCopy(s, kind, names.concat(extra));
    if (i.length) bad.push(`${where}: ${i.join(", ")}: ${s}`);
  };
  for (const [k, t] of Object.entries(CONTEXT_NA_TEXT)) check(t, "sentence", `CONTEXT_NA_TEXT.${k}`);
  assert.deepEqual(Object.keys(CONTEXT_NA_TEXT), ["no_asset", "no_price", "not_modelled", "model_not_computed", "no_outcome_legs", "not_in_stakes",
    "no_indication_link", "no_attributed_asset", "no_pool", "single_claimant", "flow_pool", "claims_exceed_pool", "share_under_1pct", "no_claimant"]);
  for (const [k, t] of Object.entries(core.INSIGHT_COPY)) check(t, /Title|Link|Heading|Tag$/.test(k) ? "label" : "sentence", `INSIGHT_COPY.${k}`);
  for (const c of COMMANDS) check(c.label, "label", `command ${c.id}`);
  const lintView = (v, t) => {
    const I = v.insight;
    const assetNames = ((CONTEXTS[t] || {}).catalysts || {items: []}).items.map((it) => it.asset && it.asset.name).filter(Boolean);
    if (I.message) { check(I.message.title, "label", `${t} message`); check(I.message.detail, "sentence", `${t} message`); }
    check(I.notice, "sentence", `${t} notice`);
    for (const it of I.valuation.premium.concat(I.valuation.discount)) {
      check(it.text, "sentence", `${t} item ${it.id}`); check(it.tag, "label", `${t} tag ${it.id}`);
      check(it.linkLabel, "label", `${t} linkLabel ${it.id}`);
      for (const ch of it.chips) { check(ch.text, "label", "chip"); check(ch.tooltip, "sentence", "chip tooltip"); }
    }
    for (const s of I.valuation.notAssessed) check(s, "sentence", `${t} not assessed`);
    for (const k of ["premiumHeading", "discountHeading"]) check(I.valuation[k], "label", k);
    check(I.valuation.emptyText, "sentence", "empty side");
    for (const g of [I.catalysts, I.competition]) {
      check(g.title, "label", `${t} title`); check(g.countText, "label", `${t} count`); check(g.note, "sentence", `${t} note`);
      check(g.linkLabel, "label", `${t} group link`);
      if (g.empty) { check(g.empty.title, "label", `${t} empty`); check(g.empty.detail, "sentence", `${t} empty`); }
    }
    check(I.competition.lead, "sentence", `${t} lead`);
    for (const h of I.competition.columns) check(h, "label", `${t} column heading`);
    for (const r of I.catalysts.rows) {
      check(r.label, "sentence", `${t} row label`); check(r.dateShort, "label", "date"); check(r.dateText, "sentence", "date");
      check(r.indicationText, "sentence", "indication"); check(r.moreText, "sentence", "more"); check(r.modelText, "label", "model", assetNames);
      check(r.naText, "sentence", "na"); check(r.indicationNa, "sentence", "na");
      for (const ch of r.chips) { check(ch.text, "label", "chip"); check(ch.tooltip, "sentence", "chip tooltip"); }
      for (const s of r.tooltip) check(s, "sentence", "row tooltip");
    }
    for (const r of I.competition.rows) {
      check(r.name, "sentence", `${t} name`);
      for (const k of ["valueText", "ownText", "rivalsText", "poolText", "shareText"]) check(r[k], "label", `${t} ${k}`);
      for (const k of ["valueNa", "poolNa", "shareNa"]) check(r[k], "sentence", `${t} ${k}`);
      for (const s of r.tooltip) check(s, "sentence", "row tooltip");
    }
    check(v.footer.text, "sentence", `${t} footer`); check(v.footer.buttonLabel, "label", "footer button");
    check(v.header.basis.text, "label", `${t} basis`); check(v.header.basis.tooltip, "sentence", `${t} basis tooltip`);
    check(v.header.peerSet.tooltip, "sentence", `${t} peer set tooltip`);
    check(v.bridgeLine.text, "sentence", `${t} bridge line`); check(v.bridgeLine.linkLabel, "label", "bridge link");
    check(v.bridgeLine.storageLine, "sentence", "bridge storage line");
    check(v.kpis[5].tooltip, "sentence", `${t} kpi 6`);
    check(v.peers.title, "label", "peer drawer title");
    for (const s of v.table.viewBadge.lines) check(s, "label", `${t} view badge`);
    check(v.table.viewBadge.label, "label", "view badge label");
    for (const r of v.table.rows) for (const s of r.tickerLines) check(s, "sentence", "ticker line");
    for (const s of v.states) { check(s.title, "label", `${t} state ${s.id}`); check(s.detail, "sentence", `${t} state ${s.id}`); }
    for (const e of core.paletteExtras(v, v.analysis.state)) check(e.label, "label", `palette ${e.id}`, I.competition.rows.map((r) => r.name));
  };
  for (const t of Object.keys(CONTEXTS)) lintView(viewCtx(PAYLOAD, t, ctxOf(t)), t);
  lintView(viewCtx(PAYLOAD, "AZN", null), "AZN pending");
  lintView(viewCtx(PAYLOAD, "AZN", {ticker: "AZN", error: "HTTP 500"}), "AZN error");
  lintView(viewCtx(PAYLOAD, "AZN", {...ctxOf("AZN"), complete: false}), "AZN cold");
  lintView(viewCtx(PAYLOAD, "AZN", ctxOf("AZN"), {currency: "EUR", earnings: "adjusted", cfMode: "percentile", density: "compact", textSize: 14,
    summaryRows: false, outliers: "exclude", statsGroup: "US"}), "AZN settings");
  lintView(viewCtx(PAYLOAD, "AZN", ctxOf("AZN"), {currency: "REPORTED"}), "AZN reported");
  assert.deepEqual(bad, []);
  // The exact sentences of 12.3, and the words of the specification's own lint list.
  for (const s of ["PoS 55%", "PDUFA date", "EMA decision", "Open the Catalysts tab", "Catalysts tab"]) assert.deepEqual(lintCopy(s, "label"), [], s);
});

// R3.10 ----------------------------------------------------------------------------------------
test("R3.10 reducer: one right-side surface, the insight tab, ADOPT_PERSISTED and mergeBridge", () => {
  const p = PAYLOAD || FIX;
  const s0 = defaultState(p, {focal: "AZN", engine: "pharma"});
  assert.deepEqual([s0.ui.peers, s0.ui.peersSearch, s0.ui.insightTab, "lowerTab" in s0.ui], [false, false, "catalysts", false]);
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
  assert.equal(reduce(s0, {type: "SET_INSIGHT_TAB", tab: "competition"}, p).ui.insightTab, "competition");

  // ADOPT_PERSISTED: what another frame stored replaces the persisted slices; focal, engine, live and ui stay.
  const theirs = reduce(reduce(reduce(reduce(defaultState(p, {focal: peer, engine: "pharma"}),
    {type: "SET_BASIS", basis: "FY0"}, p), {type: "SET_BRIDGE", patch: {stat: "mean"}}, p),
    {type: "SET_PRESET", preset: "growth"}, p), {type: "REMOVE_PEER", ticker: "AZN", now: 0}, p);
  const stored = persistable({...theirs, excludedByFocal: {AZN: [peer]}});
  const mine = reduce(reduce(s0, {type: "OPEN_PEERS"}, p), {type: "TOGGLE_WHY"}, p);
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
test("R3.11 basis chip, view badge, footer, bridge line, KPI 6 link and the command list", () => {
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

  assert.deepEqual(v.kpis.map((k) => k.link), [null, null, null, null, null, {kind: "tab", tab: "Forecast"}]);
  assert.equal(v.kpis[5].id, "implied");
  assert.equal(v.kpis[5].tooltip, "From the peer-multiple bridge on the Forecast tab, with its inputs. Click to open it. Per-share figures are in USD, the quote currency.");
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
  for (const id of ["peers.edit", "sources.open", "forecast.open", "catalysts.open"]) {
    assert.ok(ids.includes(id), id);
    assert.deepEqual(core.COMMAND_BY_ID[id].keys, [], id);
  }
  assert.deepEqual(["peers.edit", "sources.open", "forecast.open", "catalysts.open"].map((id) => core.COMMAND_BY_ID[id].label),
    ["Edit peers", "Sources and method", "Open the peer-multiple value on the Forecast tab", "Open the Catalysts tab"]);
  assert.ok(!ids.includes("bridge.reset"));
  assert.equal(new Set(ids).size, ids.length);
  assert.equal(KEYMAP.a, "peer.add");
  const keys = COMMANDS.flatMap((c) => c.keys);
  assert.equal(new Set(keys).size, keys.length);

  // Palette: the three sections of 12.1 and one entry per competition row.
  const extras = core.paletteExtras(v, v.analysis.state);
  assert.deepEqual(extras.filter((e) => e.group === "Sections" && e.target).map((e) => [e.label, e.target.id]),
    [["Go to section drivers and risks", "obs"], ["Go to section peer position", "charts"], ["Go to section comparable companies", "table"]]);
  assert.ok(!extras.some((e) => /bridge/i.test(e.label)));
  if (PAYLOAD) {
    const vc = viewCtx(PAYLOAD, "AZN", ctxOf("AZN"));
    const ind = core.paletteExtras(vc, vc.analysis.state).filter((e) => e.link);
    assert.deepEqual(ind.map((e) => e.label), ["Open Comps, Indications: Non-small-cell lung carcinoma", "Open Comps, Indications: Breast neoplasms",
      "Open Comps, Indications: Asthma", "Open Comps, Indications: Obesity", "Open Comps, Indications: Chronic obstructive pulmonary disease"]);
    assert.deepEqual(ind[3].link, {kind: "indication", indicationId: 367, name: "Obesity"});
    assert.equal(core.matchCommands("indications obesity", COMMANDS, ind)[0].label, "Open Comps, Indications: Obesity");
  }
  // The constants of 12.0.
  assert.deepEqual([core.CATALYST_MIN_PCT, core.POOL_KEEP_MAX, core.POOL_LEAD_MIN_SHARE, core.POOL_LEAD_MIN_COMPANIES, core.COMPETITION_MIN_PCT,
    core.INSIGHT_ROWS, core.WHOLE_COHORT_MAX, core.MAX_PRESET_COLUMNS, core.CONTEXT_SCHEMA, core.GOTO_KEY],
    [0.05, 0.90, 0.25, 3, 0.02, 5, 20, 9, 1, "er.compsval.goto"]);
  assert.deepEqual(core.REGULATORY_KINDS, ["PDUFA", "regulatory decision", "AdCom", "EMA decision"]);
  assert.deepEqual(core.LATE_PHASES, ["Phase 3", "Phase 2/3"]);
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
  for (const k of ["insight", "table", "header", "conclusion", "scope", "dotplot", "scatter", "observations", "peers", "method", "detail", "lineage", "footer"]) {
    assert.equal(b[k], null, k);
  }
  assert.deepEqual(b.kpis, []);
  // The same peer set and inputs give the same bridge in both frames.
  assert.deepEqual(b.bridge, full.bridge);
  assert.deepEqual(b.bridgeLine, full.bridgeLine);
  assert.deepEqual(b.primary.candidates, full.primary.candidates);
  // The bridge frame reads a payload with no detail records, and the context is not read.
  const lean = clone(p);
  for (const c of lean.companies) delete c.detail;
  const bl = deriveView(lean, state, {mode: "bridge", context: CONTEXTS.AZN});
  assert.deepEqual(bl.bridge, full.bridge);
  assert.equal(bl.insight, null);
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

// The whole fixture universe derives with its context, or without one, and never crashes.
test("R3 payload: every company derives in both modes; the reference contexts give their insight", {skip: !PAYLOAD}, () => {
  for (const c of PAYLOAD.companies) {
    const v = viewCtx(PAYLOAD, c.ticker, CONTEXTS[c.ticker] ? ctxOf(c.ticker) : null);
    assert.equal(v.error, null, c.ticker);
    assert.deepEqual(v.sectionErrors, {}, c.ticker);
    assert.equal(v.insight.state, CONTEXTS[c.ticker] ? "ok" : "pending", c.ticker);
    assert.equal(v.kpis.length, 6, c.ticker);
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
