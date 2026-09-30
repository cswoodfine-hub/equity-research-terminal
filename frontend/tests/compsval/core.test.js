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
test("17 defaultPeers: cap, pools, reasons and warnings", () => {
  const focal = rec("F0", {});
  const many = Array.from({length: 20}, (_, i) => rec(`M${i}`, {}));
  const d = defaultPeers(focal, [focal].concat(many));
  assert.equal(d.tickers.length, 15);
  assert.ok(d.tickers.every((t) => d.pools[t] === "A"));
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
    const dp = defaultPeers(byT(PAYLOAD, "AZN"), PAYLOAD.companies);
    assert.ok(dp.tickers.length <= 15);
    assert.ok(dp.tickers.every((t) => byT(PAYLOAD, t).engine === "pharma" && byT(PAYLOAD, t).stage === "commercial"));
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
    {type: "SET_LOWER_TAB", tab: "bridge"}, {type: "SET_NARROW_TAB", tab: "position"}, {type: "SET_LAPTOP_TAB", tab: "position"},
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
    {type: "SET_LOWER_TAB", tab: "obs"}, {type: "OPEN_OVERLAY", overlay: "palette"}, {type: "SHOW_COLUMN", colId: "country"},
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
  assert.equal(crsp[header.indexOf("PEG (×, NTM E, calc.)")], "n.m.");
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
