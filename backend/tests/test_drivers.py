"""Drivers and risks (company-scorecard.md 1.5, 5.4): one ranked list for two tabs.

Catalysts prints all of it and Key insights prints the first three Drivers as Next, so the
order is the thing to get right. The fixtures are the live comps-context answers and
change feeds for AZN, LLY and CRSP of 2026-10-01; the exclusivity rows are the scorecard's
for AZN and LLY as section 6.1 and 1.5 state them.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "frontend"))

import drivers as D  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TODAY = "2026-10-01"
BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")
STARTS_WITH_NUMBER = re.compile(r"^\$?\d")


def _load(name):
    return json.loads((FIXTURES / "drivers" / name).read_text())


@pytest.fixture(scope="module")
def ctx():
    return {t: _load(f"ctx_{t}.json") for t in ("AZN", "LLY", "CRSP")}


@pytest.fixture(scope="module")
def feed():
    return {t: _load(f"feed_{t}.json") for t in ("AZN", "LLY", "CRSP")}


# The scorecard's exclusivity losses (6.1 for AZN, 1.5 for LLY).
SCORECARD = {
    "AZN": {"ticker": "AZN", "exclusivity_losses": [
        {"asset": "Lynparza", "date": "2027-09-08", "share_of_revenue": 0.056,
         "basis": "drug substance patent"},
        {"asset": "Koselugo", "date": "2028-03-13", "share_of_revenue": 0.011,
         "basis": "drug substance patent"}]},
    "LLY": {"ticker": "LLY", "exclusivity_losses": [
        {"asset": "Trulicity", "date": "2027-12-31", "share_of_revenue": 0.066,
         "basis": "drug substance patent"}]},
    "CRSP": {"ticker": "CRSP", "exclusivity_losses": []},
}


def _event(ident, date, *, asset_id=None, name=None, marketed=False, kind="data readout",
           phase="Phase 3", conf=None, value=None, stake=None, indication=None):
    """One comps-context catalyst item, shaped as the API sends it."""
    precision = "month" if len(date) == 7 else "day"
    return {
        "id": ident, "date": date, "date_precision": precision,
        "date_confidence": conf or ("month" if precision == "month" else "estimated"),
        "kind": kind, "regulatory": kind in D.REGULATORY_KINDS, "phase": phase,
        "asset": ({"id": asset_id, "name": name, "is_marketed": marketed}
                  if asset_id is not None else None),
        "indication": {"id": 1, "name": indication} if indication else None,
        "title": f"{phase}, a study", "nct_id": None, "source_url": None, "is_curated": False,
        "stake": stake,
        "asset_value": ({"per_share": value * 100, "pct_of_price": value, "pos": 0.5,
                         "counted": True} if value is not None else None),
        "na": {},
    }


def _context(items, ticker="ZZZ", competition=None):
    return {"schema": 1, "ticker": ticker, "today": TODAY,
            "window": {"from": TODAY, "to": "2027-10-01"}, "complete": True,
            "price": {"close": 100.0, "as_of": "2026-09-30"},
            "catalysts": {"total": len(items), "sent": len(items), "items": items},
            "competition": competition or {"covered": False, "reason": "not_big_pharma",
                                           "indications": []}}


# --- rank_events ---------------------------------------------------------------------
def test_azn_drivers_lead_with_elecoglipron_then_dated_readouts(ctx):
    rows = D.rank_events(ctx["AZN"])
    assert [r["asset"] for r in rows[:4]] == ["Elecoglipron", "Truqap", "Saphnelo", "Enhertu"]
    assert rows[0]["line"] == "$4.68  Elecoglipron · Phase 3 readout · obesity · est. Jun 2027"
    assert rows[1]["line"] == "est. Oct 2026  Truqap · Phase 3 readout · breast neoplasms"
    assert len(rows) == 25
    assert D.drivers_basis(len(rows)) == "25 assets in 12 months"


def test_lly_drivers_lead_with_retatrutide_then_zepbound_and_foundayo(ctx):
    rows = D.rank_events(ctx["LLY"])
    assert [r["asset"] for r in rows[:3]] == ["Retatrutide", "Zepbound", "Foundayo"]
    # A month the registry gives without a day prints as the month, with no "est.".
    assert rows[0]["line"] == "$33.51  Retatrutide · Phase 3 readout · obesity · Nov 2026"
    assert rows[0]["estimated"] is False
    assert rows[1]["lead"] == "Nov 2026"


def test_one_row_per_asset(ctx):
    for t in ("AZN", "LLY"):
        rows = D.rank_events(ctx[t])
        ids = [r["asset_id"] for r in rows if r["asset_id"] is not None]
        assert len(ids) == len(set(ids))
        # Every event is either a row or counted in its asset's "more".
        assert sum(1 + r["more"] for r in rows) == len(ctx[t]["catalysts"]["items"])
    saphnelo = next(r for r in D.rank_events(ctx["AZN"]) if r["asset"] == "Saphnelo")
    assert saphnelo["more"] == 2 and saphnelo["date"] == "2026-11-02"


def test_crsp_has_no_driver(ctx):
    assert D.rank_events(ctx["CRSP"]) == []


def test_a_valued_readout_under_one_percent_ranks_by_date():
    items = [
        _event(1, "2027-03-01", asset_id=10, name="Small", value=0.005),   # $0.50, 0.5%
        _event(2, "2026-11-01", asset_id=20, name="Marketed", marketed=True, value=0.04),
        _event(3, "2027-06-01", asset_id=30, name="Big", value=0.03),
        _event(4, "2027-05-01", asset_id=40, name="Bigger", value=0.06),
    ]
    rows = D.rank_events(_context(items))
    assert [r["asset"] for r in rows] == ["Bigger", "Big", "Marketed", "Small"]
    assert [r["tier"] for r in rows] == [2, 2, 3, 3]
    small = rows[3]
    assert small["per_share"] is None and small["lead"] == "est. Mar 2027"
    assert rows[0]["lead"] == "$6.00" and rows[0]["model"] is True


def test_a_marketed_drug_leads_with_its_month(ctx):
    truqap = next(r for r in D.rank_events(ctx["AZN"]) if r["asset"] == "Truqap")
    assert truqap["per_share"] is None and truqap["model"] is False
    assert truqap["lead"] == "est. Oct 2026"
    assert truqap["date"] == "2026-10-31"      # a day on file, printed to its month


def test_est_marks_estimated_dates_and_never_a_month_only_date(ctx):
    for r in D.rank_events(ctx["AZN"]) + D.rank_events(ctx["LLY"]):
        if r["precision"] == "month":
            assert "est." not in r["line"] and r["estimated"] is False
        if r["estimated"]:
            assert r["date_text"].startswith("est. ")


def test_a_stated_day_prints_whole():
    item = _event(1, "2027-02-14", asset_id=1, name="Drug", kind="PDUFA", phase=None,
                  conf="confirmed")
    row = D.rank_events(_context([item]))[0]
    assert row["lead"] == "14 Feb 2027" and row["estimated"] is False
    assert row["text"] == "Drug · PDUFA date"


def test_tiers_stake_then_regulatory_then_valued_then_late_then_rest():
    stake_small = {"per_share": -1.5, "pct_of_price": 0.015}
    stake_big = {"per_share": 4.0, "pct_of_price": 0.04}
    items = [
        _event(1, "2026-10-05", asset_id=1, name="Early", phase="Phase 2"),
        _event(2, "2026-10-06", asset_id=2, name="Late", marketed=True),
        _event(3, "2027-01-01", asset_id=3, name="Valued", value=0.02),
        _event(4, "2027-02-01", asset_id=4, name="Filed", kind="PDUFA", phase=None,
               conf="confirmed"),
        _event(5, "2026-12-01", asset_id=5, name="Filed early", kind="PDUFA", phase=None,
               conf="confirmed", value=0.05),
        _event(6, "2027-04-01", asset_id=6, name="Stake small", stake=stake_small),
        _event(7, "2027-05-01", asset_id=7, name="Stake big", stake=stake_big),
    ]
    rows = D.rank_events(_context(items))
    assert [r["asset"] for r in rows] == ["Stake big", "Stake small", "Filed early", "Filed",
                                          "Valued", "Late", "Early"]
    assert rows[1]["lead"] == "$1.50"          # a stake prints its size, unsigned
    # A regulatory date on an unapproved asset decides its value, so it leads with it.
    assert rows[2]["lead"] == "$5.00" and rows[2]["text"].endswith("1 Dec 2026")
    assert rows[3]["lead"] == "1 Feb 2027"


def test_ties_inside_a_tier_go_by_date_then_id():
    items = [_event(9, "2026-11", asset_id=1, name="B", marketed=True),
             _event(3, "2026-11", asset_id=2, name="A", marketed=True),
             _event(5, "2026-11-02", asset_id=3, name="C", marketed=True)]
    assert [r["asset"] for r in D.rank_events(_context(items))] == ["A", "B", "C"]


def test_an_unusable_context_gives_no_driver():
    assert D.rank_events(None) == []
    assert D.rank_events({"schema": 2, "catalysts": {"items": []}}) == []
    assert D.rank_events({"error": "timeout"}) == []
    assert D.context_error({"error": "timeout"}) == "timeout"


def test_indication_prose_keeps_acronyms_and_eponyms():
    assert D.indication_prose("Pulmonary Disease, Chronic Obstructive") == \
        "chronic obstructive pulmonary disease"
    assert D.indication_prose("Leukemia, Lymphocytic, Chronic, B-Cell") == \
        "B-cell chronic lymphocytic leukemia"
    assert D.indication_prose("Alzheimer Disease") == "Alzheimer disease"
    assert D.indication_prose("Diabetes Mellitus, Type 1") == "type 1 diabetes mellitus"
    assert D.indication_title("Obesity") == "Obesity"


# --- risks ---------------------------------------------------------------------------
def test_azn_risks_are_two_losses_two_slips_and_the_obesity_pool(ctx, feed):
    rows = D.risks(SCORECARD["AZN"], ctx["AZN"], feed["AZN"], TODAY)
    assert [r["kind"] for r in rows] == ["exclusivity", "exclusivity", "slip", "slip", "pool"]
    assert [r["line"] for r in rows] == [
        "5.6% of revenue  Lynparza exclusivity ends 8 Sep 2027",
        "1.1% of revenue  Koselugo exclusivity ends 13 Mar 2028",
        "241 days  NCT06455449 readout slips to Jan 2028",
        "364 days  NCT06921785 readout slips to Mar 2030",
        "73% kept  Obesity: 2 candidates in a 19-drug pool (model)",
    ]
    assert [r["model"] for r in rows] == [False, False, False, False, True]


def test_lly_risks_hold_trulicity_and_the_obesity_pool(ctx, feed):
    rows = D.risks(SCORECARD["LLY"], ctx["LLY"], feed["LLY"], TODAY)
    assert rows[0]["line"] == "6.6% of revenue  Trulicity exclusivity ends 31 Dec 2027"
    # LLY's slips in the feed are all rated medium: none is a Phase 3 readout slip.
    assert [r["kind"] for r in rows] == ["exclusivity", "pool"]


def test_crsp_has_no_risk(ctx, feed):
    assert D.risks(SCORECARD["CRSP"], ctx["CRSP"], feed["CRSP"], TODAY) == []
    s = D.section("CRSP", ctx["CRSP"], SCORECARD["CRSP"], feed["CRSP"], TODAY)
    assert s["state"] == "empty"
    assert s["message"] == "No dated event or exclusivity loss on file for CRSP."


def test_every_risk_is_under_fifteen_words_and_starts_with_a_number(ctx, feed):
    for t in ("AZN", "LLY", "CRSP"):
        for r in D.risks(SCORECARD[t], ctx[t], feed[t], TODAY):
            assert len(r["line"].split()) < 15, r["line"]
            assert STARTS_WITH_NUMBER.match(r["line"]), r["line"]


def test_slips_need_a_high_rating_ninety_days_and_a_recent_detection():
    def slip(nct, old, new, days, when, sig="high"):
        return {"kind": "change", "change_type": "date_slip", "significance": sig,
                "ticker": "ZZZ", "date": when, "detected_at": when,
                "headline": f"ZZZ trial {nct}: primary completion slips {old} -> {new}",
                "reason": f"slipped {days}d"}
    feed = [
        slip("NCT00000001", "2027-01-01", "2027-03-01", 59, "2026-09-30 08:00:00"),   # short
        slip("NCT00000002", "2027-01-01", "2028-01-01", 365, "2026-09-29 08:00:00", "medium"),
        slip("NCT00000003", "2027-01-01", "2028-01-01", 365, "2026-06-01 08:00:00"),  # old
        slip("NCT00000004", "2027-01-01", "2027-06-01", 151, "2026-09-20 08:00:00"),
        slip("NCT00000005", "2027-01-01", "2027-12-01", 334, "2026-09-20 09:00:00"),
        slip("NCT00000006", "2027-01-01", "2028-06-01", 517, "2026-09-10 08:00:00"),
        slip("NCT00000004", "2026-06-01", "2027-01-01", 214, "2026-09-01 08:00:00"),  # earlier
        {"kind": "change", "change_type": "status_change", "significance": "high",
         "headline": "ZZZ trial NCT00000009: status Recruiting -> Completed"},
    ]
    rows = D.slip_rows(feed, TODAY, "ZZZ")
    # Newest day first, the longer slip first on a shared day, one row per trial, two at most.
    assert [r["nct_id"] for r in rows] == ["NCT00000005", "NCT00000004"]
    assert rows[0]["line"] == "334 days  NCT00000005 readout slips to Dec 2027"
    assert rows[1]["days"] == 151


def test_a_slip_without_days_in_its_reason_is_measured_from_the_headline():
    item = {"change_type": "date_slip", "significance": "high", "detected_at": "2026-09-30",
            "headline": "trial NCT00000007: primary completion slips 2027-01-15 -> 2027-07-15",
            "reason": "completion slipped"}
    rows = D.slip_rows([item], TODAY)
    assert rows[0]["days"] == 181 and rows[0]["text"].endswith("Jul 2027")


def test_exclusivity_rows_keep_the_next_24_months_in_date_order():
    company = {"ticker": "ZZZ", "exclusivity_losses": [
        {"asset": "Late", "date": "2028-10-02", "share_of_revenue": 0.2},      # past 24 months
        {"asset": "Gone", "date": "2026-09-30", "share_of_revenue": 0.2},      # already past
        {"asset": "Second (Copackaged)", "date": "2027-05-01", "share_of_revenue": 0.0004},
        {"asset": "First", "date": "2027-01-10", "share_of_revenue": None},
    ]}
    rows = D.exclusivity_rows(company, TODAY)
    assert [r["line"] for r in rows] == [
        "10 Jan 2027  First exclusivity ends",
        "0.04% of revenue  Second exclusivity ends 1 May 2027",
    ]
    assert D.exclusivity_rows(None, TODAY) == []


def _pool_row(name, keeps, pct, claimants, pooled, crowded=True):
    return {"indication": {"id": 7, "name": name}, "value": {"pct_of_price": pct},
            "pool": {"patients": 1e6, "claimants": pooled, "pooled_claimants": pooled,
                     "companies": 3},
            "crowding": {"uncrowded_share": 1.2, "crowded_share": 1.0} if crowded else None,
            "company_pool": {"keeps": keeps, "claimants": claimants, "rank": 2,
                             "of_companies": 3, "share_of_claims": 0.2}}


def test_pools_follow_the_core_js_rule():
    comp = {"covered": True, "indications": [
        _pool_row("Obesity", 0.95, 0.10, 2, 19),                           # keeps over 90%
        _pool_row("Asthma", 0.50, 0.01, 2, 5),                             # under 2% of price
        _pool_row("Psoriasis", 0.50, 0.05, 2, 5, crowded=False),           # no crowding
        _pool_row("Arthritis, Rheumatoid", 0.899, 0.03, 1, 18),
        _pool_row("Pulmonary Disease, Chronic Obstructive, Severe Early-Onset", 0.6, 0.03, 3, 8),
    ]}
    rows = D.pool_rows({"competition": comp})
    assert [r["line"] for r in rows] == [
        "90% kept  Rheumatoid arthritis: 1 candidate in an 18-drug pool (model)",
        "60% kept  Severe early-onset chronic obstructive pulmonary…: 3 candidates in an "
        "8-drug pool (model)",
    ]
    assert all(r["words"] < 15 for r in rows)


def test_at_most_five_risks():
    company = {"ticker": "ZZZ", "exclusivity_losses": [
        {"asset": f"Drug {i}", "date": f"2027-0{i}-01", "share_of_revenue": 0.01 * i}
        for i in range(1, 8)]}
    rows = D.risks(company, None, [], TODAY)
    assert len(rows) == 5 and rows[0]["asset"] == "Drug 1"
    # The next loss, then the largest four, by date; the two smallest fold.
    assert [r["asset"] for r in rows] == ["Drug 1", "Drug 4", "Drug 5", "Drug 6", "Drug 7"]
    shown, folded = D.risk_parts(company, None, [], TODAY)
    assert shown == rows and [r["asset"] for r in folded] == ["Drug 2", "Drug 3"]


def test_an_exclusivity_row_prints_the_payloads_share_text():
    """share_of_revenue is rounded to four places in the payload, so formatting it again
    can land a tenth off the strip and the panel, which print share_text."""
    company = {"ticker": "PFE", "exclusivity_losses": [
        {"asset": "Adcetris", "date": "2026-12-31", "share_of_revenue": 0.0145,
         "share_text": "1.4%"},
        {"asset": "Kovaltry", "date": "2027-03-16", "share_of_revenue": 0.0135,
         "share_text": "1.3%"},
        {"asset": "Older", "date": "2027-06-01", "share_of_revenue": 0.0145}]}
    rows = D.exclusivity_rows(company, TODAY)
    assert [r["lead"] for r in rows] == ["1.4% of revenue", "1.3% of revenue",
                                         D._pct_share(0.0145) + " of revenue"]
    assert rows[0]["line"] == "1.4% of revenue  Adcetris exclusivity ends 31 Dec 2026"
    assert rows[0]["share_text"] == "1.4%"


# PFE's exclusivity losses of the next 24 months on the 2026-10-01 book, as the scorecard
# sends them, and its one Phase 3 slip rated high.
PFE_LOSSES = [
    ("Bosulif", "2026-11-23", 0.0098, "1.0%"), ("Vyndaqel", "2026-12-31", 0.102, "10.2%"),
    ("Adcetris", "2026-12-31", 0.0145, "1.4%"), ("Ibrance", "2027-12-31", 0.0659, "6.6%"),
    ("Xtandi", "2027-12-31", 0.0351, "3.5%"), ("Eliquis", "2028-04-01", 0.1272, "12.7%")]
PFE_SLIP = {"kind": "change", "change_type": "date_slip", "significance": "high",
            "ticker": "PFE", "date": "2026-09-20", "detected_at": "2026-09-20 08:00:00",
            "headline": "PFE trial NCT05895786: primary completion slips 2027-07-31 -> "
                        "2030-07-31", "reason": "slipped 1096d"}


def test_risks_keep_the_next_loss_and_the_largest_when_slips_need_room():
    """The five-row cap by date dropped PFE's Eliquis at 12.7% of revenue and the slip the
    Key insights page names. Now the next loss stays (the strip names it), the largest
    fill the room the slips and pools leave, and every row still prints by date."""
    company = {"ticker": "PFE", "exclusivity_losses": [
        {"asset": a, "date": d, "share_of_revenue": s, "share_text": t, "fy": "FY2025"}
        for a, d, s, t in PFE_LOSSES]}
    shown, folded = D.risk_parts(company, None, [PFE_SLIP], TODAY)
    assert [r["line"] for r in shown] == [
        "1.0% of revenue  Bosulif exclusivity ends 23 Nov 2026",
        "10.2% of revenue  Vyndaqel exclusivity ends 31 Dec 2026",
        "6.6% of revenue  Ibrance exclusivity ends 31 Dec 2027",
        "12.7% of revenue  Eliquis exclusivity ends 1 Apr 2028",
        "1,096 days  NCT05895786 readout slips to Jul 2030",
    ]
    assert [r["asset"] for r in folded] == ["Adcetris", "Xtandi"]
    # Two slips and a pool leave exclusivity its floor of three: next, then the two largest.
    pools = {"competition": {"covered": True, "indications": [
        _pool_row("Obesity", 0.7, 0.05, 2, 19)]}}
    slip2 = dict(PFE_SLIP, headline=PFE_SLIP["headline"].replace("NCT05895786", "NCT05895787"))
    shown, folded = D.risk_parts(company, pools, [PFE_SLIP, slip2], TODAY)
    assert [r.get("asset") or r["kind"] for r in shown] == [
        "Bosulif", "Vyndaqel", "Eliquis", "slip", "slip"]
    assert [r.get("asset") or r["kind"] for r in folded] == [
        "Adcetris", "Ibrance", "Xtandi", "pool"]
    s = D.section("PFE", pools, company, [PFE_SLIP, slip2], TODAY)
    assert s["risks"]["more_label"] == "Show 4 more" and s["risks"]["more"] == folded
    assert D.section("AZN", None, SCORECARD["AZN"], [], TODAY)["risks"]["more"] == []


def test_an_asset_name_drops_its_brackets():
    """8.2: "Trikafta (Copackaged)" prints "Trikafta", as the lines and the strip print it."""
    item = _event(1, "2027-02-01", asset_id=1, name="Trikafta (Copackaged)", marketed=True,
                  indication="Cystic Fibrosis")
    row = D.rank_events(_context([item]))[0]
    assert row["asset"] == "Trikafta"
    assert row["text"] == "Trikafta · Phase 3 readout · cystic fibrosis"


# --- the section ---------------------------------------------------------------------
def test_section_shows_five_drivers_and_folds_the_rest(ctx, feed):
    s = D.section("AZN", ctx["AZN"], SCORECARD["AZN"], feed["AZN"], TODAY)
    assert s["title"] == "Drivers and risks"
    assert s["basis"] == "events in 12 months, exclusivity losses in 24 · model output marked"
    assert s["state"] == "ok" and s["message"] is None
    assert [r["asset"] for r in s["drivers"]["shown"]] == [
        "Elecoglipron", "Truqap", "Saphnelo", "Enhertu", "Fasenra"]
    assert len(s["drivers"]["more"]) == 20 and s["drivers"]["more_label"] == "Show 20 more"
    assert s["drivers"]["basis"] == "25 assets in 12 months"
    assert len(s["risks"]["rows"]) == 5


def test_section_reads_risks_when_the_context_failed(feed):
    s = D.section("AZN", {"error": "timed out"}, SCORECARD["AZN"], feed["AZN"], TODAY)
    assert s["state"] == "ok" and s["drivers"]["rows"] == []
    assert s["message"] == "The events for AZN did not load: timed out."
    assert len(s["risks"]["rows"]) == 4             # no pools without the context
    s = D.section("CRSP", None, None, [], TODAY)
    assert s["state"] == "error"


def test_next_on_key_insights_is_the_head_of_the_same_list(ctx):
    """Key insights prints rank_events(context)[:3]; the Catalysts list starts with them."""
    s = D.section("AZN", ctx["AZN"], SCORECARD["AZN"], [], TODAY)
    assert s["drivers"]["shown"][:3] == D.rank_events(ctx["AZN"])[:3]


def test_the_ranking_does_not_mutate_the_payload(ctx):
    before = copy.deepcopy(ctx["AZN"])
    D.rank_events(ctx["AZN"])
    D.risks(SCORECARD["AZN"], ctx["AZN"], [], TODAY)
    assert ctx["AZN"] == before


# --- house style ---------------------------------------------------------------------
def test_copy_keeps_house_style(ctx, feed):
    texts = [D.SECTION_TITLE, D.SECTION_BASIS, D.DRIVERS_TITLE, D.RISKS_TITLE, D.EMPTY,
             D.CONTEXT_FAILED, D.more_label(3), D.drivers_basis(1)]
    for t in ("AZN", "LLY", "CRSP"):
        texts += [r["line"] for r in D.rank_events(ctx[t])]
        texts += [r["line"] for r in D.risks(SCORECARD[t], ctx[t], feed[t], TODAY)]
    for text in texts:
        assert "\u2014" not in text, text
        low = text.lower()
        assert not any(re.search(rf"\b{w}", low) for w in BANNED), text
    assert D.drivers_basis(1) == "1 asset in 12 months"


# --- the scorecard contract ------------------------------------------------------------
SAMPLE = FIXTURES / "company_score" / "sample_scorecard.json"


@pytest.mark.skipif(not SAMPLE.exists(), reason="E1's sample scorecard is not written yet")
def test_risks_read_the_sample_scorecard():
    sample = json.loads(SAMPLE.read_text())
    block = sample.get("scorecard", sample)
    today = block.get("today") or TODAY
    seen = 0
    for ticker, company in (block.get("companies") or {}).items():
        losses = company.get("exclusivity_losses") or []
        rows = D.exclusivity_rows(company, today)
        assert len(rows) <= len(losses)
        for r in rows:
            assert STARTS_WITH_NUMBER.match(r["line"]) and r["words"] < 15
        if losses and rows:
            first = min(losses, key=lambda x: x["date"])
            assert rows[0]["asset"] == D.product_name(first["asset"])
            seen += 1
    assert seen >= 1
