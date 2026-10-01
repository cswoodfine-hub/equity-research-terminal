"""The company scorecard (backend/company_score.py, docs/design/company-scorecard.md).

Pure functions on their own data, then ``score()`` on the saved book of 2026-10-01
(``fixtures/company_score/book_2026-10-01.json``: the 70 records of GET /comps/valuation
trimmed to the fields it reads, plus the captured book inputs), which must give the spec's
worked examples (2.14), its big pharma table (2.15) and Appendix B exactly. Never the real
book, bar the one guard at the end, which takes the ``book`` fixture.
"""

from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import company_score as cs

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "company_score"
TODAY = dt.date(2026, 10, 1)


@pytest.fixture(scope="module")
def saved():
    """The saved book of 2026-10-01 (conftest's ``book`` is the live one)."""
    return json.loads((FIXTURES / "book_2026-10-01.json").read_text())


@pytest.fixture(scope="module")
def out(saved):
    return cs.score(saved["records"], saved["inputs"], saved["today"])


@pytest.fixture(scope="module")
def deal_rows():
    return json.loads((FIXTURES / "deals_rows.json").read_text())


def _metric(company: dict, metric: str) -> dict:
    for pillar in company["pillars"].values():
        for entry in pillar["metrics"]:
            if entry["id"] == metric:
                return entry
    for entry in company["facts"]["other_metrics"]:
        if entry["id"] == metric:
            return entry
    raise KeyError(metric)


# --- synthetic records ----------------------------------------------------------------------
def _rec(ticker, engine="pharma", stage="commercial", revenue=10_000.0, growth=0.05,
         op=None, fcf=None, net_debt=0.0, debt=1_000.0, cash=1_000.0, late=5, rel=0.0,
         mcap=50_000.0, runway=None, flags=(), compounds=None, conc=0.2, ev=None, na=None):
    na = dict(na or {})
    if runway is None:
        na["risk.runway_months"] = "not_burning"
    return {
        "ticker": ticker, "name": f"{ticker} Inc.", "engine": engine, "stage": stage,
        "filer": {"annual_form": "10-K"},
        "periods": {"FY0": {"label": "FY2025", "period_end": "2025-12-31",
                            "revenue_usd_m": revenue, "operating_income_usd_m": op,
                            "fcf_usd_m": fcf},
                    "FYm3": {"label": "FY2022"}, "FY1": {"label": "FY2026", "eps": None},
                    "FY2": {"label": "FY2027", "eps": None}, "FY3": {"label": "FY2028"},
                    "NTM": {"eps": None}},
        "growth": {"revenue_fy": growth, "revenue_cagr3": None, "eps_street_cagr": None,
                   "bases": {"revenue_fy": [revenue, revenue / (1 + growth)]}},
        "ev": {"net_debt_usd_m": net_debt, "total_debt_usd_m": debt, "cash_usd_m": cash,
               "ev_usd_m": ev if ev is not None else mcap + net_debt},
        "market": {"price": 100.0, "market_cap_usd_m": mcap, "market_cap_basis": "shares_outstanding"},
        "risk": {"runway_months": runway},
        "healthcare": {"trial_concentration": conc},
        "detail": {"pipeline": {"compounds": compounds if compounds is not None else
                                {"Phase 2": 2, "Phase 3": late}},
                   "relative": {"1y": {"relative_pct": rel, "covers_window": True},
                                "3m": {"relative_pct": rel, "covers_window": True}}},
        "na": na, "flags": [dict(f) for f in flags],
    }


def _inp(ocf=2_000.0, pretax=None, share=None, share_reason=None):
    return {"ocf_usd_m": ocf, "pretax_usd_m": pretax, "share_change": share,
            "share_change_reason": share_reason, "product_rows": [], "fresh": None,
            "approvals": [], "partner_marketed": [], "deals": []}


# --- percentile and pull --------------------------------------------------------------------
def test_percentile_is_mid_rank_with_ties_and_excludes_the_company():
    assert cs.percentile(5, [1, 2, 3, 4]) == 100.0
    assert cs.percentile(1, [2, 3, 4, 5]) == 0.0
    assert cs.percentile(3, [1, 3, 5, 7]) == pytest.approx(100 * (1 + 0.5) / 4)
    assert cs.percentile(3, []) is None


def test_lower_is_better_is_flipped(out):
    azn = out["companies"]["AZN"]
    # EV to sales 4.7x, 9th best of 18: 52.9 after the flip.
    assert _metric(azn, "ev_sales")["score"] == 52.9
    vrtx = out["companies"]["VRTX"]
    assert _metric(vrtx, "top_product")["score"] == 0.0     # the highest share, the worst


def test_pull_toward_the_middle():
    assert cs.pull(80.0, 2, 2) == 80.0                       # every metric: w = 1
    assert cs.pull(90.0, 1, 2) == pytest.approx(50 + 40 * 0.75)
    assert cs.pull(90.0, 1, 3) == pytest.approx(50 + 40 * 2 / 3)
    assert cs.pull(None, 0, 3) is None
    assert cs.pull(70.0, 0, 3) is None


# --- the coverage rule ----------------------------------------------------------------------
def test_coverage_rule_and_a_pillar_leaving_the_list():
    # Six big pharma: two thirds is 4. Operating margin held by 3 is not scored; pre-tax and
    # free cash flow margins are not filed at all, so profitability leaves the list.
    recs = [_rec(f"P{i}", growth=0.01 * i, op=(1_000.0 * i if i < 3 else None),
                 net_debt=100.0 * i, late=i) for i in range(6)]
    res = cs.score(recs, {r["ticker"]: _inp() for r in recs}, TODAY)
    cohort = res["cohorts"]["big_pharma"]
    ids = [p["id"] for p in cohort["pillars"]]
    assert "profitability" not in ids and "durability" not in ids
    ns = {x["metric"]: x for x in cohort["not_scored"]}
    assert ns["op_margin"]["have"] == 3 and ns["op_margin"]["of"] == 6
    assert ns["op_margin"]["text"] == "Not scored: 3 of 6 in the cohort have it"
    assert "profitability" not in res["companies"]["P1"]["pillars"]


def test_two_distinct_levels_are_not_scored():
    recs = [_rec(f"P{i}", growth=0.01 * i, late=(3 if i % 2 else 7)) for i in range(6)]
    res = cs.score(recs, {r["ticker"]: _inp() for r in recs}, TODAY)
    ns = {x["metric"] for x in res["cohorts"]["big_pharma"]["not_scored"]}
    assert "late_compounds" in ns and "late_per_rev" in ns       # one revenue: two levels
    assert "rev_growth" not in ns


def test_big_pharma_coverage_on_the_book(out):
    cohort = out["cohorts"]["big_pharma"]
    assert cohort["not_scored"] == [{"metric": "eps_cagr", "pillar": "growth", "have": 11,
                                     "of": 18, "text": "Not scored: 11 of 18 in the cohort have it"}]
    commercial = {p["id"]: p["metrics"] for p in out["cohorts"]["commercial"]["pillars"]}
    assert commercial == {"growth": ["rev_growth"],
                          "profitability": ["op_margin", "pretax_margin", "fcf_margin"],
                          "balance_sheet": ["runway"], "pipeline": ["late_compounds"],
                          "value": ["mcap_sales"], "momentum": ["rel_1y", "rel_3m"]}


# --- floors and missing data ----------------------------------------------------------------
def test_floors_give_the_right_reason():
    rec = _rec("SMALL", revenue=50.0)
    v = cs.metric_values(rec, _inp(), TODAY)
    assert v["rev_growth"] == (None, "below_revenue_floor")
    assert v["ev_sales"] == (None, "below_revenue_floor")
    assert v["late_per_rev"] == (None, "below_revenue_floor")
    rec = _rec("TINYBASE", revenue=200.0)
    rec["growth"]["bases"]["revenue_fy"] = [200.0, 5.0]
    assert cs.metric_values(rec, _inp(), TODAY)["rev_growth"] == (None, "growth_not_meaningful")


def test_small_revenue_margins_rank_last_tied_and_print_their_revenue(out):
    for t in ("ABEO", "AUTL", "QURE"):
        entry = _metric(out["companies"][t], "pretax_margin")
        assert entry["place"] == "joint worst"
        assert entry["note"].endswith("too little to compare margins")
    abeo = out["companies"]["ABEO"]
    assert _metric(abeo, "pretax_margin")["note"] == (
        "$5.8m of revenue in FY2025, too little to compare margins")
    assert _metric(abeo, "pretax_margin")["value"] > 10          # 1,225%: kept, ranked last


def test_no_debt_line_is_never_nil_debt():
    rec = _rec("NODEBT", debt=None, na={"ev.total_debt_usd_m": "no_debt_line"})
    v = cs.metric_values(rec, _inp(), TODAY)
    assert v["nd_ocf"] == (None, "no_debt_line")
    assert v["net_cash_rev"] == (None, "no_debt_line")


def test_not_burning_ranks_above_every_burner_and_ties(out):
    entries = {t: _metric(out["companies"][t], "runway")
               for t in out["cohorts"]["commercial"]["ranked"]}
    non = [e for e in entries.values() if e["text"] == "not burning cash"]
    burners = [e for e in entries.values() if e["score"] is not None and e["text"] != "not burning cash"]
    assert len(non) == 11
    assert len({e["score"] for e in non}) == 1
    assert all(e["value"] is None and e["reason"] is None for e in non)
    assert min(e["score"] for e in non) > max(e["score"] for e in burners)
    assert non[0]["place"] == "joint best"


def test_a_negative_free_cash_flow_yield_is_null():
    v = cs.metric_values(_rec("BURN", fcf=-10.0), _inp(), TODAY)
    assert v["fcf_yield"] == (None, "fcf_negative")
    assert v["fcf_margin"][0] == pytest.approx(-0.001)


# --- flags ----------------------------------------------------------------------------------
def test_every_amber_code_is_handled(saved):
    assert cs.unknown_amber_flags(saved["records"]) == []
    stray = _rec("X", flags=[{"code": "brand_new_flag", "field": "x", "severity": "amber"}])
    assert cs.unknown_amber_flags([stray]) == ["brand_new_flag"]


def test_derived_operating_income_nulls_only_the_operating_margin(out):
    lly = out["companies"]["LLY"]
    assert _metric(lly, "op_margin")["reason"] == "derived_operating_income"
    assert _metric(lly, "op_margin")["value"] is None
    assert _metric(lly, "pretax_margin")["text"] == "39.5%"


def test_market_cap_disagreement_nulls_nothing():
    flag = {"code": "market_cap_disagreement", "field": "market.market_cap_usd_m",
            "severity": "amber"}
    base = cs.metric_values(_rec("A", fcf=500.0), _inp(), TODAY)
    flagged = cs.metric_values(_rec("A", fcf=500.0, flags=[flag]), _inp(), TODAY)
    assert base == flagged


def test_estimate_flags_reach_by_field():
    rec = _rec("E", flags=[{"code": "thin_estimates", "field": "periods.FY3", "severity": "amber"}])
    rec["growth"]["eps_street_cagr"] = 0.1
    rec["growth"]["bases"]["eps_street_cagr"] = [5.0, 7.0]
    rec["periods"]["NTM"]["eps"] = 5.0
    rec["periods"]["FY1"]["eps"], rec["periods"]["FY2"]["eps"] = 5.0, 6.0
    v = cs.metric_values(rec, _inp(), TODAY)
    assert v["eps_cagr"] == (None, "thin_estimates")
    assert v["pe_ntm"] == (20.0, None)
    rec["flags"][0]["field"] = "periods.FY1"
    assert cs.metric_values(rec, _inp(), TODAY)["pe_ntm"] == (None, "thin_estimates")


# --- share count change ---------------------------------------------------------------------
def test_share_change_on_the_book(saved):
    for t in ("ABEO", "IONS", "ALNY"):
        assert saved["inputs"][t]["share_change"] is None
        assert saved["inputs"][t]["share_change_reason"] == "dilution_basis_changed"


def test_share_change_rules():
    q = [("2026-06-30", 120.0), ("2025-06-30", 100.0), ("2026-03-31", 118.0)]
    assert cs.share_change(q, [], {}) == (pytest.approx(0.2), None, ["2025-06-30", "2026-06-30"])
    loss_to_profit = {"Q": {"2026-06-30": 5.0, "2025-06-30": -3.0}}
    assert cs.share_change(q, [], loss_to_profit)[1] == "dilution_basis_changed"
    assert cs.share_change([("2026-06-30", 40.0), ("2025-06-30", 100.0)], [], {})[1] == "share_split"
    assert cs.share_change([("2026-06-30", 2500.0), ("2025-06-30", 100.0)], [], {})[1] == "share_scale"
    fy = [("2025-12-31", 110.0), ("2024-12-31", 100.0)]
    assert cs.share_change([], fy, {})[0] == pytest.approx(0.1)
    assert cs.share_change([], [], {}) == (None, "not_filed", None)


# --- product rows and the product gate ------------------------------------------------------
def test_product_rows_count_an_exact_duplicate_once():
    rows = [{"asset_id": 102, "fiscal_year": 2025, "period": "FY", "value": 10.31e9, "unit": "USD"},
            {"asset_id": 6972, "fiscal_year": 2025, "period": "FY", "value": 10.31e9, "unit": "USD"},
            {"asset_id": 7, "fiscal_year": 2025, "period": "FY", "value": 1.0e9, "unit": "USD"},
            {"asset_id": 7, "fiscal_year": 2024, "period": "FY", "value": 9.0e9, "unit": "USD"},
            {"asset_id": 8, "fiscal_year": 2025, "period": "Q2", "value": 3.0e9, "unit": "USD"}]
    kept = cs.product_rows(rows, 2025)
    assert [r["asset_id"] for r in kept] == [102, 7]


def test_product_gate_on_the_book(out):
    assert _metric(out["companies"]["VRTX"], "top_product")["text"] == "86%"
    bayn = out["companies"]["BAYN"]
    assert _metric(bayn, "top_product")["reason"] == "partial_product_revenue"
    assert _metric(bayn, "top_product")["reason_text"] == (
        "Product revenue on file covers 17% of revenue, outside 60% to 110%")
    jnj = out["companies"]["JNJ"]
    assert jnj["facts"]["product_coverage"] == pytest.approx(0.64, abs=0.01)
    assert _metric(jnj, "top_product")["value"] is not None


def test_a_pillar_emptied_by_a_parametrised_code_carries_the_filled_text(out):
    """Key insights prints the pillar's reason where its bar would be, so the pillar fills
    the company's figure as its metrics do: BAYN's durability read "covers {c}%"."""
    pillar = out["companies"]["BAYN"]["pillars"]["durability"]
    assert pillar["score"] is None and pillar["reason"] == "partial_product_revenue"
    assert pillar["reason_text"] == (
        "Product revenue on file covers 17% of revenue, outside 60% to 110%")
    for t, company in out["companies"].items():
        for pid, p in company["pillars"].items():
            texts = [p.get("reason_text")] + [m.get("reason_text") for m in p["metrics"]]
            assert not any("{" in x for x in texts if x), (t, pid, texts)


def test_eps_growth_from_a_depressed_year_is_null(out):
    entry = _metric(out["companies"]["MRK"], "eps_cagr")
    assert entry["reason"] == "eps_base_depressed" and entry["value"] is None


def test_freshness_anchored_on_the_revenue_year(out):
    assert _metric(out["companies"]["NVO"], "fresh_share")["text"] == "27%"
    assert _metric(out["companies"]["VRTX"], "fresh_share")["text"] == "9%"
    lnth = out["companies"]["LNTH"]
    assert _metric(lnth, "fresh_share")["reason"] == "inferred_dates"


def test_loe_years():
    rows = [{"asset_id": 1, "usd_m": 300.0}, {"asset_id": 2, "usd_m": 100.0},
            {"asset_id": 3, "usd_m": 100.0}]
    loe = {1: {"date": "2030-10-01"}, 2: {"date": "2020-01-01"}}
    years, why = cs.loe_years(rows, loe, TODAY)
    assert why is None
    assert years == pytest.approx(300 * (1461 / 365.25) / 400)   # the past date counts 0
    years, why = cs.loe_years(rows, {3: {"date": "2030-01-01"}}, TODAY)
    assert (years, why) == (None, "under_half_dated")


# --- company score and rank -----------------------------------------------------------------
def test_a_company_below_the_pillar_minimum_is_not_ranked(out):
    adapy = out["companies"]["ADAPY"]
    assert adapy["score"] is None and adapy["rank"] is None and adapy["chart"] is None
    assert adapy["reason"] == "too_few_pillars"
    assert adapy["reason_text"] == "2 of 4 pillars, a score needs 3"
    assert adapy["sentence"] == "ADAPY is not scored: 2 of 4 pillars have data, and a score needs 3."
    commercial = out["cohorts"]["commercial"]
    assert commercial["not_ranked"] == [{"ticker": "ADAPY", "reason": "2 of 4 pillars, a score needs 3",
                                         "code": "too_few_pillars"}]
    assert "ADAPY" not in commercial["ranked"]
    assert out["companies"]["INCY"]["ranked_of"] == 21


def test_equal_scores_break_by_ticker():
    recs = [_rec(t, growth=0.05, late=5, net_debt=100.0) for t in ("ZZZ", "AAA", "MMM")]
    recs += [_rec(f"Q{i}", growth=0.01 * i, late=i, net_debt=10.0 * i) for i in range(3)]
    res = cs.score(recs, {r["ticker"]: _inp() for r in recs}, TODAY, draws=50)
    ranked = res["cohorts"]["big_pharma"]["ranked"]
    tied = [t for t in ranked if t in ("AAA", "MMM", "ZZZ")]
    assert tied == ["AAA", "MMM", "ZZZ"]


def test_not_on_chart_without_a_value_measure(out):
    assert {x["ticker"] for x in out["cohorts"]["commercial"]["not_on_chart"]} == {"ABEO", "AUTL", "QURE"}
    assert out["companies"]["ABEO"]["chart"] is None
    assert out["companies"]["AZN"]["chart"] == {"x": 58.1, "y": 45.75, "size": 49.3, "complete": True}
    assert out["companies"]["ROG"]["chart"]["complete"] is False


# --- the rank range -------------------------------------------------------------------------
def _rank_range_reference(metric_scores, spec, ranked, seed, draws, level=90):
    """The reference script's loop (work-keep/proto/r2/score.py), kept here to pin the
    vectorised version to it bit for bit."""
    rng = random.Random(seed)
    biz = [p for p, _ms in spec]
    sp = dict(spec)
    out = {t: [] for t in ranked}
    for _ in range(draws):
        wm = {p: {m: rng.gammavariate(1.0, 1.0) for m in sp[p]} for p in biz}
        wp = {p: rng.gammavariate(1.0, 1.0) for p in biz}
        sc = {}
        for t in ranked:
            num = den = 0.0
            k = 0
            for p in biz:
                got = [(wm[p][m], metric_scores[t][m]) for m in sp[p] if m in metric_scores[t]]
                if not got:
                    continue
                raw = sum(w * x for w, x in got) / sum(w for w, _ in got)
                num += wp[p] * cs.pull(raw, len(got), len(sp[p]))
                den += wp[p]
                k += 1
            sc[t] = cs.pull(num / den, k, len(biz)) if den else 50.0
        for i, t in enumerate(sorted(ranked, key=lambda t: (-sc[t], t))):
            out[t].append(i + 1)
    tail = (100 - level) / 200
    res = {}
    for t in ranked:
        d = sorted(out[t])
        res[t] = [d[int(tail * len(d))], d[min(len(d) - 1, int((1 - tail) * len(d)))]]
    return res


def test_rank_range_matches_the_reference_loop(out):
    # The cohorts' own pillar lists and ranked sets, with random metric scores and gaps.
    for cohort in ("big_pharma", "clinical"):
        spec = [(p["id"], p["metrics"]) for p in out["cohorts"][cohort]["pillars"]
                if cs.PILLARS[p["id"]]["kind"] == "business"]
        ranked = out["cohorts"][cohort]["ranked"]
        rng = random.Random(7)
        scores = {t: {m: rng.uniform(0, 100) for _p, ms in spec for m in ms if rng.random() > 0.15}
                  for t in ranked}
        for seed in (1, 20261001):
            assert cs.rank_range(scores, spec, ranked, seed=seed, draws=300) == \
                _rank_range_reference(scores, spec, ranked, seed, 300)


def test_rank_range_is_deterministic_and_holds_the_ranked_set(out):
    spec = [("growth", ["a", "b"]), ("pipeline", ["c"])]
    scores = {"T1": {"a": 90, "b": 80, "c": 70}, "T2": {"a": 50, "b": 60, "c": 40},
              "T3": {"a": 10, "c": 95}}
    first = cs.rank_range(scores, spec, ["T1", "T2", "T3"], seed=3, draws=200)
    assert first == cs.rank_range(scores, spec, ["T1", "T2", "T3"], seed=3, draws=200)
    assert set(first) == {"T1", "T2", "T3"}
    assert all(1 <= lo <= hi <= 3 for lo, hi in first.values())
    # A company with no score never enters a draw: ADAPY has no range, and the commercial
    # ranges stop at 21, the ranked count.
    assert out["companies"]["ADAPY"]["rank_range"] is None
    assert max(out["companies"][t]["rank_range"][1] for t in out["cohorts"]["commercial"]["ranked"]) <= 21


def test_a_company_leading_every_metric_ranges_one_to_one():
    recs = [_rec(f"S{i}", growth=0.01 * i, late=i, net_debt=1000.0 - 100 * i, rel=0.01 * i,
                 op=100.0 * (i + 1), fcf=50.0 * (i + 1)) for i in range(6)]
    res = cs.score(recs, {r["ticker"]: _inp(ocf=1000.0, pretax=80.0 * (i + 1))
                          for i, r in enumerate(recs)}, TODAY)
    assert res["companies"]["S5"]["rank"] == 1
    assert res["companies"]["S5"]["rank_range"] == [1, 1]
    assert res["companies"]["S5"]["range_text"] == "1"


# --- positives and negatives ----------------------------------------------------------------
def test_lines_come_from_business_pillars_at_most_one_each(out):
    for t, company in out["companies"].items():
        for key in ("positives", "negatives"):
            pillars = [x["pillar"] for x in company[key]]
            assert len(pillars) == len(set(pillars)), (t, key)
            assert all(cs.PILLARS[p]["kind"] == "business" for p in pillars)
            strengths = [x["strength"] for x in company[key]]
            assert strengths == sorted(strengths, reverse=True)
    total_pos = sum(len(c["positives"]) for c in out["companies"].values())
    total_neg = sum(len(c["negatives"]) for c in out["companies"].values())
    assert (total_pos, total_neg) == (70, 100)
    assert not out["companies"]["IONS"]["positives"] and not out["companies"]["IONS"]["negatives"]
    assert not out["companies"]["SRPT"]["positives"] and not out["companies"]["SRPT"]["negatives"]


def test_thresholds_and_the_natural_zero_rule(out):
    for company in out["companies"].values():
        for x in company["positives"]:
            assert x["strength"] >= cs.POSITIVE_AT - 50
            entry = _metric(company, x["metric"])
            if x["metric"] in cs.ABOVE_ZERO:
                assert entry["value"] > 0
            if x["metric"] in cs.BELOW_ZERO:
                assert entry["value"] < 0
        for x in company["negatives"]:
            assert x["strength"] >= 25


def test_absolute_rules(out):
    lines = {t: [x["text"] for x in c["negatives"]] for t, c in out["companies"].items()}
    assert "23 months of cash runway, under two years" in lines["WVE"]
    assert not any("cash runway, under two years" in x for x in lines["STOK"])     # 23.9 shows 24
    assert "Net debt of 4.0× operating cash flow, above 3×" in lines["BMRN"]
    # PFE's leverage is above 3x but its balance sheet already has a ranked negative.
    assert not any(x.endswith("above 3×") for x in lines["PFE"])
    assert "86% of FY2025 revenue from Trikafta, worst of 17 big pharma" in lines["VRTX"]


def test_a_partner_on_a_marketed_drug_has_no_pipeline_line(out):
    crsp = out["companies"]["CRSP"]
    assert crsp["facts"]["partner_on"] == {"brand": "Casgevy", "owner": "VRTX",
                                           "text": "Shares Casgevy, VRTX's marketed drug"}
    assert all(x["pillar"] != "pipeline" for x in crsp["positives"] + crsp["negatives"])
    assert [x["text"] for x in crsp["positives"]] == [
        "77 months of cash runway, 2nd best of 28 clinical-stage biotechs"]
    assert crsp["negatives"] == []


def test_places_and_plurals():
    def place(v, pool, better="higher"):
        return cs._place(v, pool, better)
    assert place(10, [10, 5, 1]) == ("best", 3)
    assert place(1, [10, 5, 1]) == ("worst", 3)
    assert place(5, [10, 5, 5, 1, 0]) == ("joint 2nd best", 5)
    assert place(1, [10, 5, 1], better="lower") == ("best", 3)
    rec = _rec("ONE")
    assert cs._phrase("late_compounds", 1, rec, {}) == "1 late-stage compound"
    assert cs._phrase("late_compounds", 4, rec, {}) == "4 late-stage compounds"
    assert cs._phrase("mid_late_compounds", 1, rec, {}) == "1 compound in Phase 2 or later"
    assert cs._phrase("nd_ocf", -3.8, rec, {}) == "Net cash of 3.8× operating cash flow"
    assert cs._phrase("net_cash_rev", -0.7, rec, {}) == "Net debt of 0.7× revenue"
    assert cs._phrase("top_product", 0.86, rec, {"top_name": "Trikafta (Copackaged)"}) == \
        "86% of FY2025 revenue from Trikafta"


# --- the deal gate --------------------------------------------------------------------------
def _gated(deal_rows, ticker):
    d = deal_rows["companies"][ticker]
    return cs.gate_deals(d["rows"], d["company"], deal_rows["today"])


def _parties(deal_rows, ticker):
    return {r["counterparty"] for r in _gated(deal_rows, ticker)}


def test_gate_gsk(deal_rows):
    kept = _gated(deal_rows, "GSK")
    assert len(kept) == 7
    parties = {r["counterparty"] for r in kept}
    assert not parties & {"Massachusetts", "US-based", "SBP Group", "ADS"}
    sino = [r for r in kept if r["counterparty"].startswith("Sino")]
    assert len(sino) == 1 and sino[0]["route"] == "filing"   # the news row merged into it


@pytest.mark.parametrize("ticker,dropped", [("NVS", "U.S"), ("ROG", "Biz"), ("MRK", "Firm"),
                                            ("BIIB", "Waltham"), ("LLY", "CAR-T")])
def test_gate_drops_non_names(deal_rows, ticker, dropped):
    assert dropped in {r["counterparty"] for r in deal_rows["companies"][ticker]["rows"]}
    assert dropped not in _parties(deal_rows, ticker)


@pytest.mark.parametrize("ticker,word", [("MRK", "verona"), ("MRK", "terns"),
                                         ("BIIB", "apellis"), ("LLY", "orna")])
def test_gate_counts_a_repeated_deal_once(deal_rows, ticker, word):
    assert sum(word in r["counterparty"].lower() for r in _gated(deal_rows, ticker)) == 1


def test_gate_drops_vendors_and_keeps_real_deals(deal_rows):
    assert not _parties(deal_rows, "BMY") & {"Microsoft", "NVIDIA", "Anthropic", "Nvidia's"}
    assert not _parties(deal_rows, "NVO") & {"Pocketpills", "Hims", "OpenAI", "Amazon", "Anthropic",
                                             "Microsoft Quantum Co"}
    azn = _gated(deal_rows, "AZN")
    assert sum("CSPC" in r["counterparty"] for r in azn) == 2    # June 2025 and July 2026
    assert len(azn) == 6
    assert _gated(deal_rows, "BEAM") == []                      # the Bio Palette termination
    assert _parties(deal_rows, "CRSP") == {"Eli Lilly"}
    assert _gated(deal_rows, "IOVA") == []
    assert len(_gated(deal_rows, "LLY")) == 15
    assert len(_gated(deal_rows, "VRTX")) == 2


def test_gate_rows_are_newest_first_and_capped(deal_rows, out):
    kept = _gated(deal_rows, "LLY")
    assert [r["date"] for r in kept] == sorted((r["date"] for r in kept), reverse=True)
    assert all(len(r["quote"]) <= cs.QUOTE_MAX for r in kept)
    deals = out["companies"]["LLY"]["facts"]["deals"]
    assert deals["n"] == 15 and len(deals["rows"]) == cs.DEAL_LIST_MAX
    assert deals["count_text"] == "15 deals on file in 24 months"
    assert set(deals["rows"][0]) == {"date", "type", "route", "quote", "url"}
    assert out["companies"]["WVE"]["facts"]["deals"]["count_text"] == "No deal on file in 24 months."
    assert out["companies"]["CRSP"]["facts"]["deals"]["count_text"] == "1 deal on file in 24 months"


def test_firepower(out):
    azn = out["companies"]["AZN"]["facts"]
    assert azn["firepower_usd_m"] == 3 * 14575 - 23903
    assert azn["firepower_text"] == ("Could fund about $19.8bn of deals before net debt reaches "
                                     "three times operating cash flow.")
    assert out["companies"]["CRSP"]["facts"]["firepower_usd_m"] is None


# --- the sentence and the worked examples ---------------------------------------------------
SENTENCES = {
    "AZN": "AZN scores 58, 7th of 18 big pharma, range 2–11. Strongest on growth and pipeline, weakest on profitability.",
    "LLY": "LLY scores 63, 5th of 18 big pharma, range 1–12. Strongest on growth and pipeline, weakest on balance sheet.",
    "PFE": "PFE scores 40, 13th of 18 big pharma, range 4–17. Strongest on pipeline and durability, weakest on growth and balance sheet.",
    "VRTX": "VRTX scores 72, 1st of 18 big pharma, range 1–10. Strongest on balance sheet and growth.",
    "CRSP": "CRSP scores 59, 10th of 30 clinical-stage biotechs, range 2–23. Strongest on funding, weakest on pipeline.",
}


def test_sentences(out):
    for t, text in SENTENCES.items():
        assert out["companies"][t]["sentence"] == text
    assert max(len(c["sentence"].split()) for c in out["companies"].values()) <= 30


def test_the_sentence_drops_the_second_strongest_then_the_second_weakest():
    res = {"score_raw": 50.0, "rank": 12, "ranked_of": 30, "range_text": "1–30", "k": 4, "K": 4,
           "need": 3, "pillar_raw": {"growth": 90, "profitability": 80, "balance_sheet": 10,
                                     "pipeline": 20}}
    # The head is 8 words plus the noun; the full tail 11, less the second strongest 9, less
    # the second weakest too 7.
    short = cs._sentence("T", res, " ".join(["w"] * 5))
    assert short.endswith("Strongest on growth and profitability, weakest on balance sheet and pipeline.")
    one = cs._sentence("T", res, " ".join(["w"] * 12))
    assert one.endswith(" Strongest on growth, weakest on balance sheet and pipeline.")
    assert len(one.split()) <= 30
    two = cs._sentence("T", res, " ".join(["w"] * 14))
    assert two.endswith(" Strongest on growth, weakest on balance sheet.")
    assert len(two.split()) <= 30


# 2.14: (ticker, metric) -> (value text, metric score, place, n); None score = not scored
WORKED = {
    "AZN": {"rev_growth": ("8.6%", 81.2, "4th best", 17), "rev_cagr3": ("9.8%", 73.3, "5th best", 16),
            "op_margin": ("23.4%", 18.2, "3rd worst", 12), "pretax_margin": ("21.1%", 31.2, "6th worst", 17),
            "fcf_margin": ("20.0%", 43.8, "8th worst", 17), "nd_ocf": ("1.6×", 56.2, "8th best", 17),
            "net_cash_rev": ("−0.4×", 52.9, "9th best", 18), "late_compounds": ("23", 94.1, "2nd best", 18),
            "late_per_rev": ("3.9", 82.4, "4th best", 18), "fresh_share": ("7%", 18.8, "4th worst", 17),
            "loe_years": ("4.6 years", 56.2, "8th best", 17), "top_product": ("14%", 68.8, "6th best", 17),
            "ev_sales": ("4.7×", 52.9, "9th best", 18), "fcf_yield": ("4.7%", 37.5, "7th worst", 17),
            "rel_1y": ("−18 points", 11.8, "3rd worst", 18), "rel_3m": ("−21 points", 5.9, "2nd worst", 18)},
    "LLY": {"rev_growth": ("44.7%", 100.0, "best", 17), "rev_cagr3": ("31.7%", 100.0, "best", 16),
            "eps_cagr": ("23.3%", None, "best", 11), "pretax_margin": ("39.5%", 93.8, "2nd best", 17),
            "fcf_margin": ("13.8%", 6.2, "2nd worst", 17), "nd_ocf": ("2.7×", 37.5, "7th worst", 17),
            "net_cash_rev": ("−0.7×", 23.5, "5th worst", 18), "late_compounds": ("13", 70.6, "6th best", 18),
            "late_per_rev": ("2.0", 41.2, "8th worst", 18), "fresh_share": ("68%", 100.0, "best", 17),
            "loe_years": ("7.7 years", 87.5, "3rd best", 17), "top_product": ("35%", 37.5, "7th worst", 17),
            "pe_ntm": ("26.2×", 7.7, "2nd worst", 14), "ev_sales": ("16.7×", 0.0, "worst", 18),
            "fcf_yield": ("0.9%", 0.0, "worst", 17), "rel_1y": ("+29 points", 82.4, "4th best", 18),
            "rel_3m": ("−8 points", 35.3, "7th worst", 18)},
    "PFE": {"rev_growth": ("−1.6%", 6.2, "2nd worst", 17), "rev_cagr3": ("−14.8%", 0.0, "worst", 16),
            "eps_cagr": ("−6.6%", None, "2nd worst", 11), "pretax_margin": ("12.0%", 12.5, "3rd worst", 17),
            "fcf_margin": ("14.5%", 12.5, "3rd worst", 17), "nd_ocf": ("4.7×", 6.2, "2nd worst", 17),
            "net_cash_rev": ("−0.9×", 11.8, "3rd worst", 18), "late_compounds": ("27", 100.0, "best", 18),
            "late_per_rev": ("4.3", 94.1, "2nd best", 18), "fresh_share": ("21%", 87.5, "3rd best", 17),
            "loe_years": ("5.3 years", 68.8, "6th best", 17), "top_product": ("13%", 81.2, "4th best", 17),
            "pe_ntm": ("9.7×", 76.9, "4th best", 14), "ev_sales": ("3.5×", 76.5, "5th best", 18),
            "fcf_yield": ("5.5%", 62.5, "7th best", 17), "rel_1y": ("−7 points", 35.3, "7th worst", 18),
            "rel_3m": ("+13 points", 100.0, "best", 18)},
    "VRTX": {"rev_growth": ("8.9%", 87.5, "3rd best", 17), "rev_cagr3": ("10.4%", 80.0, "4th best", 16),
             "op_margin": ("34.8%", 90.9, "2nd best", 12), "pretax_margin": ("38.7%", 87.5, "3rd best", 17),
             "fcf_margin": ("26.6%", 68.8, "6th best", 17), "nd_ocf": ("−3.8×", 100.0, "best", 17),
             "net_cash_rev": ("1.1×", 100.0, "best", 18), "late_compounds": ("4", 8.8, "joint 2nd worst", 18),
             "late_per_rev": ("3.3", 76.5, "5th best", 18), "fresh_share": ("9%", 43.8, "8th worst", 17),
             "loe_years": ("11.4 years", 100.0, "best", 17), "top_product": ("86%", 0.0, "worst", 17),
             "pe_ntm": ("29.4×", 0.0, "worst", 14), "ev_sales": ("10.0×", 5.9, "2nd worst", 18),
             "fcf_yield": ("2.4%", 6.2, "2nd worst", 17), "rel_1y": ("+6 points", 47.1, "9th worst", 18),
             "rel_3m": ("−2 points", 58.8, "8th best", 18)},
    "CRSP": {"mid_late_compounds": ("0", 15.5, "joint worst", 30), "trial_conc": ("67%", 50.0, "joint 15th best", 30),
             "runway": ("77 months", 96.3, "2nd best", 28), "share_change": ("+10.8%", 74.1, "8th best", 28),
             "mcap_cash": ("2.3×", 44.8, "14th worst", 30), "rel_1y": ("−38 points", 51.7, "15th best", 30),
             "rel_3m": ("−11 points", 82.8, "6th best", 30)},
}
WORKED_NULLS = {("AZN", "eps_cagr"): "estimate_range_wide", ("AZN", "pe_ntm"): "estimate_range_wide",
                ("LLY", "op_margin"): "derived_operating_income",
                ("PFE", "op_margin"): "derived_operating_income",
                ("VRTX", "eps_cagr"): "thin_estimates"}
WORKED_HEAD = {"AZN": (58, 7, [2, 11], 46, 9), "LLY": (63, 5, [1, 12], 3, 59),
               "PFE": (40, 13, [4, 17], 72, 68), "VRTX": (72, 1, [1, 10], 4, 53),
               "CRSP": (59, 10, [2, 23], 45, 67)}
WORKED_LINES = {
    "AZN": (["23 late-stage compounds, 2nd best of 18 big pharma",
             "8.6% revenue growth in FY2025, 4th best of 17 big pharma"],
            ["23.4% operating margin in FY2025, 3rd worst of 12 big pharma",
             "7% of FY2025 product revenue from drugs approved since 2021, 4th worst of 17 big pharma"]),
    "LLY": (["44.7% revenue growth in FY2025, best of 17 big pharma",
             "68% of FY2025 product revenue from drugs approved since 2021, best of 17 big pharma",
             "39.5% pre-tax margin in FY2025, 2nd best of 17 big pharma",
             "7.7 years of exclusivity left on FY2025 product revenue, 3rd best of 17 big pharma"],
            ["13.8% free cash flow margin in FY2025, 2nd worst of 17 big pharma",
             "Net debt of 0.7× revenue, 5th worst of 18 big pharma"]),
    "PFE": (["27 late-stage compounds, best of 18 big pharma",
             "13% of FY2025 revenue from Eliquis, 4th best of 17 big pharma"],
            ["−14.8% a year revenue growth, FY2022 to FY2025, worst of 16 big pharma",
             "Net debt of 4.7× operating cash flow, 2nd worst of 17 big pharma",
             "14.5% free cash flow margin in FY2025, 3rd worst of 17 big pharma"]),
    "VRTX": (["Net cash of 1.1× revenue, best of 18 big pharma",
              "11.4 years of exclusivity left on FY2025 product revenue, best of 17 big pharma",
              "34.8% operating margin in FY2025, 2nd best of 12 big pharma",
              "8.9% revenue growth in FY2025, 3rd best of 17 big pharma",
              "3.3 late-stage compounds per $10bn of revenue, 5th best of 18 big pharma"],
             ["86% of FY2025 revenue from Trikafta, worst of 17 big pharma",
              "4 late-stage compounds, joint 2nd worst of 18 big pharma"]),
    "CRSP": (["77 months of cash runway, 2nd best of 28 clinical-stage biotechs"], []),
}


@pytest.mark.parametrize("ticker", sorted(WORKED))
def test_worked_examples(out, ticker):
    company = out["companies"][ticker]
    score, rank, rng, value, momentum = WORKED_HEAD[ticker]
    assert (company["score"], company["rank"], company["rank_range"], company["value"],
            company["momentum"]) == (score, rank, rng, value, momentum)
    for metric, (text, mscore, place, n) in WORKED[ticker].items():
        entry = _metric(company, metric)
        assert (entry["text"], entry["score"], entry["place"], entry["n"]) == (text, mscore, place, n), metric
    for (t, metric), code in WORKED_NULLS.items():
        if t == ticker:
            entry = _metric(company, metric)
            assert entry["value"] is None and entry["reason"] == code
    positives, negatives = WORKED_LINES[ticker]
    assert [x["text"] for x in company["positives"]] == positives
    assert [x["text"] for x in company["negatives"]] == negatives


def test_worked_example_facts(out):
    azn = out["companies"]["AZN"]
    assert azn["facts"]["multiple"] == {"metric": "ev_sales", "value": 4.7081, "text": "4.7×",
                                        "label": "EV to sales", "median": 4.7626,
                                        "median_text": "4.8×"}
    assert [(x["asset"], x["date"], x["share_text"]) for x in azn["exclusivity_losses"]] == [
        ("Lynparza", "2027-09-08", "5.6%"), ("Koselugo", "2028-03-13", "1.1%")]
    assert azn["pillars"]["durability"]["note"] == "4.6 years of exclusivity left"
    lly = out["companies"]["LLY"]["facts"]["multiple"]
    assert (lly["text"], lly["label"], lly["median_text"]) == ("26.2×", "P/E NTM", "15.1×")
    crsp = out["companies"]["CRSP"]["facts"]
    assert (crsp["multiple"]["text"], crsp["multiple"]["label"], crsp["multiple"]["median_text"]) == (
        "2.3×", "Market cap to cash", "2.1×")
    assert crsp["lead_phase"]["text"] == "Lead asset in Phase 1/2"
    assert out["companies"]["ARWR"]["facts"]["lead_phase"]["text"] == \
        "Lead asset marketed: Redemplo, approved Nov 2025"
    assert out["companies"]["RVMD"]["facts"]["lead_phase"]["text"] == \
        "Lead asset marketed: Rasonque, approved Aug 2026"
    assert out["companies"]["WVE"]["facts"]["lead_phase"]["text"] == "Lead asset in Phase 2"


# 2.15 and Appendix B: rank, range, ticker, score, then the pillars in the cohort's order
# ("·" a pillar with no data), value and momentum.
BIG_PHARMA = """
1 1-10 VRTX 72 84 82 100 43 50 4 53
2 1-6 NVS 69 68 76 76 69 56 59 18
3 1-11 REGN 65 39 72 94 68 50 50 74
4 2-11 NVO 65 78 77 76 52 41 65 0
5 1-12 LLY 63 100 50 31 71 62 3 59
6 1-11 ROG 61 · 56 74 59 56 48 41
7 2-11 AZN 58 77 31 55 65 62 46 9
8 5-13 JNJ 54 52 64 73 28 53 17 62
9 4-13 GSK 50 42 34 61 53 62 87 24
10 3-16 AMGN 47 90 51 6 47 44 24 79
11 6-16 SNY 46 51 18 82 40 41 96 18
12 5-17 GILD 42 32 81 31 16 50 41 74
13 4-17 PFE 40 3 17 9 94 75 72 68
14 7-17 ABBV 39 48 43 15 21 66 27 38
15 9-17 BIIB 37 19 36 27 57 44 62 76
16 10-17 MRK 36 29 44 30 61 12 26 88
17 10-17 BMY 35 13 50 49 41 25 92 68
18 17-18 BAYN 11 12 0 21 6 · 86 53
"""
COMMERCIAL = """
1 1-9 INCY 75 47 81 72 100 71 79
2 2-7 NBIX 73 53 76 72 90 65 40
3 1-8 ALNY 72 87 62 72 67 29 19
4 2-6 ARGX 71 · 77 72 67 24 71
5 1-12 BNTX 69 · 43 72 95 41 55
6 1-13 UTHR 65 27 96 72 67 53 48
7 1-15 KRYS 63 67 97 72 17 12 67
8 3-15 EXEL 62 20 88 72 67 59 79
9 7-13 BMRN 59 33 65 72 67 82 64
10 1-14 AXSM 59 93 46 · 40 18 52
11 8-16 LNTH 54 13 65 72 67 76 71
12 3-17 RGNX 51 100 26 11 67 88 17
13 8-15 IONS 50 60 35 39 67 35 17
14 5-16 LEGN 50 80 53 · 17 47 17
15 11-15 SRPT 49 40 44 72 40 94 48
16 11-19 IOVA 32 73 17 22 17 6 98
17 12-21 MRNA 30 0 19 · 67 0 98
18 13-21 ATRA 24 7 66 6 17 100 17
19 16-19 QURE 20 · 5 33 17 · 2
20 18-20 ABEO 19 · 5 28 17 · 38
21 19-21 AUTL 15 · 5 17 17 · 76
· · ADAPY · · · 0 17 · 29
"""
CLINICAL = """
1 1-3 ARWR 87 91 82 10 81
2 2-8 ARCT 79 82 76 62 67
3 3-10 DYN 75 82 68 28 53
4 1-21 BEAM 72 58 87 48 47
5 2-18 ALLO 68 77 59 83 71
6 5-12 RVMD 67 59 76 0 95
7 2-19 FATE 67 71 63 72 83
8 3-14 GPCR 65 57 72 17 34
9 4-18 NTLA 62 82 43 31 22
10 2-23 CRSP 59 33 85 45 67
11 6-17 VKTX 58 52 65 3 72
12 10-15 WVE 58 65 52 66 7
13 6-21 SLDB 58 72 43 59 41
14 6-20 TSHA 56 38 74 24 67
15 4-20 RCKT 56 77 35 100 29
16 11-22 STOK 49 38 59 21 53
17 11-22 CAPR 48 38 57 41 41
18 6-25 VYGR 47 43 52 90 17
19 5-24 KYTX 47 66 28 52 62
20 4-25 ALT 47 38 56 93 60
21 16-27 SANA 34 33 35 14 55
22 14-29 PRME 33 43 22 7 38
23 16-30 CABA 31 49 13 76 29
24 19-27 PEPG 31 38 24 79 55
25 13-29 CRBU 29 16 43 86 26
26 18-28 KRRO 27 16 37 97 24
27 21-28 EDIT 26 16 35 69 36
28 16-30 IPSC 26 16 35 34 67
29 20-29 VOR 25 38 12 38 47
30 27-30 SGMOQ 14 16 11 55 50
"""


def _num_or_none(cell):
    return None if cell == "·" else int(cell)


@pytest.mark.parametrize("cohort,table", [("big_pharma", BIG_PHARMA), ("commercial", COMMERCIAL),
                                          ("clinical", CLINICAL)])
def test_cohort_tables(out, cohort, table):
    pillars = [p["id"] for p in out["cohorts"][cohort]["pillars"]]
    rows = [line.split() for line in table.strip().splitlines()]
    ranked = [r[2] for r in rows if r[0] != "·"]
    assert out["cohorts"][cohort]["ranked"] == ranked
    assert out["cohorts"][cohort]["n"] == len(rows)
    for r in rows:
        company = out["companies"][r[2]]
        rank = _num_or_none(r[0])
        rng = None if r[1] == "·" else [int(x) for x in r[1].split("-")]
        assert (company["rank"], company["rank_range"], company["score"]) == \
            (rank, rng, _num_or_none(r[3])), r[2]
        got = [company["pillars"][p]["score"] for p in pillars]
        assert got == [_num_or_none(x) for x in r[4:]], r[2]


def test_cohort_medians(out):
    assert out["cohorts"]["big_pharma"]["medians"] == {
        "score": 49, "growth": 48, "profitability": 50, "balance_sheet": 52, "pipeline": 52,
        "durability": 50, "value": 49, "momentum": 56}
    assert out["cohorts"]["big_pharma"]["metric_medians"]["pe_ntm"] == pytest.approx(15.11, abs=0.01)
    assert out["cohorts"]["big_pharma"]["context_text"] == "Scored against 18 big pharma"


# --- the payload ----------------------------------------------------------------------------
def test_every_reason_code_has_a_text():
    sample = json.loads((FIXTURES / "sample_scorecard.json").read_text())
    codes = set()
    for company in sample["companies"].values():
        codes.add(company["reason"])
        for pillar in company["pillars"].values():
            codes.add(pillar["reason"])
            codes.update(e["reason"] for e in pillar["metrics"])
        codes.update(e["reason"] for e in company["facts"]["other_metrics"])
    codes.discard(None)
    assert codes <= set(cs.REASONS)
    assert codes <= set(sample["method"]["reasons"])


def test_the_sample_is_strict_json_and_under_350_kb():
    sample = json.loads((FIXTURES / "sample_scorecard.json").read_text())
    body = json.dumps(sample, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    assert len(body.encode()) < 350_000
    assert sample["schema"] == cs.SCHEMA and sample["error"] is None
    assert set(sample) >= {"schema", "generated_at", "today", "error", "method", "cohorts", "companies"}
    assert len(sample["companies"]) == 70


def test_build_returns_an_error_rather_than_raising(tmp_path):
    missing = tmp_path / "no" / "such" / "dir" / "book.db"
    payload = {"companies": [_rec("A")], "fx": {"usd_per_unit": {"USD": 1.0}}}
    res = cs.build(payload, db_path=missing, today=TODAY)
    assert res["error"] and res["companies"] == {} and res["cohorts"] == {}
    assert res["schema"] == cs.SCHEMA


def test_the_route_skips_the_cache_when_the_scorecard_failed(monkeypatch):
    import comps_valuation
    import main
    import response_cache
    monkeypatch.setattr(comps_valuation, "build", lambda: {"complete": True, "companies": []})
    monkeypatch.setattr(cs, "build", lambda payload: {"schema": 2, "error": "TypeError: boom",
                                                      "companies": {}})
    response = TestClient(main.app).get("/comps/valuation")
    assert response.status_code == 200
    assert response.json()["scorecard"]["error"] == "TypeError: boom"
    assert response.headers.get(response_cache.SKIP) == "1"
    monkeypatch.setattr(cs, "build", lambda payload: {"schema": 2, "error": None, "companies": {}})
    assert TestClient(main.app).get("/comps/valuation").headers.get(response_cache.SKIP) is None


# --- the book guard -------------------------------------------------------------------------
def test_book_guard(book):
    """Against the built book (run it on a .backup copy through ER_TOOL_DB): every company
    in exactly one cohort, every listed metric scored or named, and at least 15 of 18 big
    pharma ranked. Skipped, by conftest's ``book``, where no book is built."""
    import comps_valuation
    payload = comps_valuation.build()
    sc = cs.build(payload)
    assert sc["error"] is None
    tickers = [r["ticker"] for r in payload["companies"]]
    members = [t for c in sc["cohorts"].values() for t in c["ranked"]] + \
        [x["ticker"] for c in sc["cohorts"].values() for x in c["not_ranked"]]
    assert sorted(members) == sorted(tickers)
    assert sum(c["n"] for c in sc["cohorts"].values()) == len(tickers)
    for cid, cohort in sc["cohorts"].items():
        scored = {m for p in cohort["pillars"] for m in p["metrics"]}
        named = {x["metric"] for x in cohort["not_scored"]}
        listed = {m for _p, ms in cs.LISTS[cid] for m in ms}
        assert listed == scored | named and not scored & named
    assert len(sc["cohorts"]["big_pharma"]["ranked"]) >= 15
    json.dumps(sc, allow_nan=False)


def test_book_inputs_on_a_small_book(tmp_path):
    """The reads of 5.1 against a book built here: the duplicate product row is counted
    once (asset_revenue.fy_product_rows, which freshness now reads through too), FY0 cash
    flow and pre-tax income, the share count change and the deal gate."""
    import asset_revenue
    import db
    path = tmp_path / "small.db"
    db.init(path)
    conn = db.get_connection(path)
    try:
        conn.execute("INSERT INTO companies (ticker, name) VALUES ('TT', 'Tee Therapeutics Inc.')")
        cid = conn.execute("SELECT id FROM companies WHERE ticker = 'TT'").fetchone()[0]
        ids = []
        for brand in ("Trikafta", "Trikafta (Copackaged)", "Older"):
            ids.append(conn.execute("INSERT INTO assets (owner_company_id, brand_name, is_marketed)"
                                    " VALUES (?, ?, 1)", (cid, brand)).lastrowid)
        for asset_id, value in zip(ids, (10.31e9, 10.31e9, 1.0e9)):
            conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit)"
                         " VALUES (?, 2025, 'FY', ?, 'USD')", (asset_id, value))
        rows = [("CashFlowOperating", "FY", "2025-12-31", 4.0e9),
                ("IncomeBeforeTax", "FY", "2025-12-31", 3.0e9),
                ("WeightedAverageDilutedShares", "Q", "2026-06-30", 260e6),
                ("WeightedAverageDilutedShares", "Q", "2025-06-30", 250e6),
                ("NetIncomeLoss", "Q", "2026-06-30", 1.0e9),
                ("NetIncomeLoss", "Q", "2025-06-30", 0.8e9)]
        for metric, kind, end, value in rows:
            conn.execute("INSERT INTO financials (company_id, period_end, period_type, metric,"
                         " value, unit) VALUES (?, ?, ?, ?, ?, 'USD')", (cid, end, kind, metric, value))
        deals = [("0001", "licensing", "WuXi Biologics", "2026-02-12",
                  "An exclusive global license agreement with WuXi Biologics"),
                 (None, "acquisition", "Foo Bio", "2026-03-01", "Tee Therapeutics stock is a buy"),
                 (None, "acquisition", "Massachusetts", "2026-04-01",
                  "Tee Therapeutics acquires Massachusetts site"),
                 ("0002", "licensing", "Old Partner", "2023-01-01", "A licence of 2023")]
        for accession, kind, party, day, quote in deals:
            conn.execute("INSERT INTO deals (accession, company_id, deal_type, counterparty,"
                         " event_date, quote) VALUES (?, ?, ?, ?, ?, ?)",
                         (accession, cid, kind, party, day, quote))
        conn.commit()
        assert [r["asset_id"] for r in asset_revenue.fy_product_rows(conn, cid, 2025)] == [ids[0], ids[2]]
        rec = _rec("TT", engine="biotech", revenue=11_310.0)
        got = cs.book_inputs(conn, [rec], {"USD": 1.0}, TODAY)["TT"]
    finally:
        conn.close()
    assert [r["name"] for r in got["product_rows"]] == ["Trikafta", "Older"]
    assert got["ocf_usd_m"] == 4000.0 and got["pretax_usd_m"] == 3000.0
    assert got["share_change"] == pytest.approx(0.04)
    assert got["share_change_basis"] == ["2025-06-30", "2026-06-30"]
    assert [d["counterparty"] for d in got["deals"]] == ["WuXi Biologics"]
    v = cs.metric_values(rec, got, TODAY)
    assert v["top_product"][0] == pytest.approx(10_310 / 11_310)
