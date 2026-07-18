"""parse_companyfacts runs against saved EDGAR fixtures, no network.

Locks the tag-drift behaviour (LLY's recent R&D lives under the excluding-acquired
concept) and the us-gaap vs ifrs-full / currency handling.
"""

import json
from pathlib import Path

import pytest

from fetchers.financials_edgar import parse_companyfacts

FIXTURES = Path(__file__).parent / "fixtures"


def _facts(name):
    return json.loads((FIXTURES / name).read_text())


def test_parse_lly_us_gaap():
    r = parse_companyfacts(_facts("companyfacts_lly.json"))

    assert r["currency"] == "USD"
    assert r["fy_end"] == "2025-12-31"
    assert r["annual"]["Revenues"][2025]["val"] == 65179000000
    assert r["annual"]["NetIncomeLoss"][2025]["val"] == 20640000000
    assert r["shares"]["val"] == 941741406
    assert r["cash"] == 7268000000
    assert r["total_debt"] == 42503000000


def test_jnj_rd_prefers_the_excluding_concept_when_both_reach_the_latest_year():
    """Regression: JNJ tags acquired in-process R&D under the plain concept.

    Both concepts reach FY2025, so the reaches-the-latest-year rule cannot separate
    them and the plain tag used to win with 0.11bn against 14.66bn of real spend.
    """
    r = parse_companyfacts(_facts("companyfacts_jnj.json"))
    rd = r["annual"]["ResearchAndDevelopmentExpense"]

    assert rd[2025]["val"] == 14_665_000_000
    assert rd[2025]["val"] != 110_000_000        # the in-process component alone
    # Every year lands in the same order of magnitude, which the old pick did not.
    assert all(v["val"] > 5e9 for v in rd.values())


def test_lly_rd_uses_latest_concept_not_stale_tag():
    r = parse_companyfacts(_facts("companyfacts_lly.json"))
    rd = r["annual"]["ResearchAndDevelopmentExpense"]
    # Canonical ResearchAndDevelopmentExpense stops at FY2022 (7.19B); the parser must
    # pick ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost, which reaches 2025.
    assert 2025 in rd
    assert rd[2025]["val"] == 13337000000
    assert rd[2025]["val"] != 7190800000


def test_parse_nvo_ifrs_dkk_no_shares():
    r = parse_companyfacts(_facts("companyfacts_nvo.json"))

    assert r["currency"] == "DKK"
    assert r["annual"]["Revenues"][2025]["val"] == 309064000000
    assert r["annual"]["NetIncomeLoss"][2025]["val"] == 102434000000  # ifrs ProfitLoss
    assert r["shares"] is None  # foreign 20-F filers lack dei shares outstanding
    assert r["cash"] is None
    assert r["total_debt"] is None


def test_empty_payload_is_safe():
    r = parse_companyfacts({"facts": {}})
    assert r["currency"] is None
    assert r["annual"]["Revenues"] == {}
    assert r["shares"] is None


def _annual(start, end, val, form="20-F"):
    return {"start": start, "end": end, "val": val, "form": form, "filed": "2026-02-01"}


def _instant(end, val, form="10-K"):
    return {"end": end, "val": val, "form": form, "filed": "2026-02-01"}


def test_revenue_falls_back_to_sale_of_goods():
    # Novartis / Sanofi report net sales under RevenueFromSaleOfGoods, not Revenue.
    payload = {"facts": {"ifrs-full": {"RevenueFromSaleOfGoods": {
        "units": {"EUR": [_annual("2025-01-01", "2025-12-31", 43626000000)]}}}}}
    r = parse_companyfacts(payload)
    assert r["currency"] == "EUR"
    assert r["annual"]["Revenues"][2025]["val"] == 43626000000


def test_total_debt_falls_back_to_long_term_debt():
    # ABBV lacks the combined and split debt tags but has LongTermDebt at the FY end.
    payload = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_annual("2025-01-01", "2025-12-31", 61200000000, "10-K")]}},
        "LongTermDebt": {"units": {"USD": [_instant("2025-12-31", 64503000000)]}},
    }}}
    r = parse_companyfacts(payload)
    assert r["total_debt"] == 64503000000


def test_cash_falls_back_to_restricted_inclusive_tag():
    payload = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_annual("2025-01-01", "2025-12-31", 29400000000, "10-K")]}},
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": {
            "units": {"USD": [_instant("2025-12-31", 7564000000)]}},
    }}}
    r = parse_companyfacts(payload)
    assert r["cash"] == 7564000000


def test_lly_rd_extends_back_through_the_agreeing_older_concept():
    """Regression: LLY R&D 2020 read as no data.

    Lilly moved R&D from the plain concept to the excluding-acquired one in 2021.
    Picking one concept and discarding the other lost every year before 2021, even
    though EDGAR holds them. The two agree exactly in 2021 and 2022, which is what
    makes the older series safe to extend the newer one with.
    """
    r = parse_companyfacts(_facts("companyfacts_lly.json"))
    rd = r["annual"]["ResearchAndDevelopmentExpense"]

    assert 2020 in rd, "2020 R&D is in EDGAR and must not be dropped"
    # The fixture is an older snapshot than the live API, which now restates 2020 to
    # 5.9821bn. Both are about 6bn; the point is that the year is present at all.
    assert rd[2020]["val"] == 5_976_300_000
    assert rd[2025]["val"] == 13_337_000_000      # the newer concept still wins the tail


def test_jnj_conflicting_rd_concepts_are_not_merged():
    """The agreement check is what stops JNJ's in-process tag polluting the series."""
    r = parse_companyfacts(_facts("companyfacts_jnj.json"))
    rd = r["annual"]["ResearchAndDevelopmentExpense"]

    # Both concepts report 2022-2025 and differ by orders of magnitude, so the plain
    # one must contribute nothing at all.
    assert all(v["val"] > 5e9 for v in rd.values())
    assert rd[2025]["val"] == 14_665_000_000
