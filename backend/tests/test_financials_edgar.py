"""parse_companyfacts runs against saved EDGAR fixtures, no network.

Locks the tag-drift behaviour (LLY's recent R&D lives under the excluding-acquired
concept) and the us-gaap vs ifrs-full / currency handling.
"""

from fetchers import financials_edgar as fe
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
    assert r["cash"] == 26464000000                # ifrs-full CashAndCashEquivalents
    # The debt ladder is us-gaap only, so an IFRS filer has no total debt and its EV is
    # left null rather than being built from an incomplete balance sheet.
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


# --- a concept the filer stopped using --------------------------------------------------

def _fy(end, val):
    return {(end, "FY"): {"val": val, "unit": "USD", "end": end, "period_type": "FY"}}


def test_a_tag_handover_extends_the_history():
    """ASC 606 moved revenue from SalesRevenueGoodsNet to the contract concept on a date.
    JNJ tagged the old one to 2017 and the new one from 2018, and they never overlap, so
    the agreement test refuses the older series and the history starts in 2018."""
    old = {**_fy("2016-01-03", 71890e6), **_fy("2017-12-31", 76450e6)}
    new = {**_fy("2018-12-30", 81581e6), **_fy("2019-12-29", 82059e6)}
    assert fe._continues(old, new)


def test_a_gap_of_years_is_not_a_handover():
    old = _fy("2013-12-29", 71312e6)
    new = _fy("2018-12-30", 81581e6)
    assert not fe._continues(old, new)


def test_a_different_quantity_is_not_a_handover():
    """The dates can line up and the line still measure something else. JNJ's plain R&D
    concept holds acquired in-process R&D alone and is two orders of magnitude smaller."""
    old = _fy("2017-12-31", 500e6)
    new = _fy("2018-12-30", 81581e6)
    assert not fe._continues(old, new)


def test_an_overlapping_series_is_left_to_the_agreement_test():
    """Sharing a year is what the agreement test is for, and it checks the values."""
    old = {**_fy("2017-12-31", 76450e6), **_fy("2018-12-30", 81581e6)}
    new = _fy("2018-12-30", 81581e6)
    assert not fe._continues(old, new)


def test_the_history_reaches_back_far_enough_for_a_cycle():
    """Seven years is one cycle. A growth line has to be long enough to show a patent
    cliff and what replaced it."""
    assert fe.MAX_FISCAL_YEARS >= 16


def test_interest_paid_is_read_where_the_filer_books_it():
    """US GAAP interest paid is operating; an IFRS filer's operating choice lands on the
    same line and its financing choice on its own, so a filer with nothing to add back
    is told apart from one with nothing on file."""
    from fetchers.financials_edgar import parse_statements
    us = parse_statements({"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_annual("2025-01-01", "2025-12-31", 62579000000, "10-K")]}},
        "InterestPaidNet": {"units": {"USD": [_annual("2025-01-01", "2025-12-31", 2739000000, "10-K")]}},
    }}})
    got = us["lines"]["InterestPaidOperating"]["periods"]
    assert [e["val"] for e in got.values()] == [2739000000]
    assert "InterestPaidFinancing" not in us["lines"] or not us["lines"]["InterestPaidFinancing"]["periods"]
    ifrs = parse_statements({"facts": {"ifrs-full": {
        "Revenue": {"units": {"GBP": [_annual("2025-01-01", "2025-12-31", 32667000000, "20-F")]}},
        "InterestPaidClassifiedAsFinancingActivities": {"units": {"GBP": [
            _annual("2025-01-01", "2025-12-31", 679000000, "20-F")]}},
    }}})
    assert [e["val"] for e in ifrs["lines"]["InterestPaidFinancing"]["periods"].values()] == [679000000]
    assert not (ifrs["lines"].get("InterestPaidOperating") or {}).get("periods")


def test_rd_before_the_excluding_concept_is_plain_rd_less_tagged_in_process_rd():
    """Vertex's plain R&D includes acquired in-process R&D; less the tagged amount it
    reconciles to the excluding concept in 2020 and 2021, so 2017 to 2019 read the same
    way. A year with no in-process tag is not filled."""
    from fetchers.financials_edgar import parse_statements
    def usd(rows):
        return {"units": {"USD": [_annual(f"{y}-01-01", f"{y}-12-31", v, "10-K") for y, v in rows]}}
    payload = {"facts": {"us-gaap": {
        "Revenues": usd([(2025, 12001.3e6)]),
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost": usd([(2020, 1644.9e6), (2021, 1937.8e6), (2025, 3909.5e6)]),
        "ResearchAndDevelopmentExpense": usd([(2016, 1047.7e6), (2017, 1324.6e6), (2018, 1416.5e6), (2020, 1829.5e6), (2021, 3051.1e6)]),
        "ResearchAndDevelopmentInProcess": usd([(2017, 160.0e6), (2018, 0.0), (2020, 184.6e6), (2021, 1113.3e6)]),
    }}}
    periods = parse_statements(payload)["lines"]["ResearchAndDevelopmentExpense"]["periods"]
    by_year = {int(end[:4]): e for (end, kind), e in periods.items() if kind == "FY"}
    assert by_year[2017]["val"] == pytest.approx(1164.6e6) and by_year[2018]["val"] == pytest.approx(1416.5e6)
    assert "in-process" in by_year[2017]["concept"] and 2016 not in by_year
    assert by_year[2020]["val"] == pytest.approx(1644.9e6)


def test_the_rd_fill_is_refused_where_the_tags_do_not_reconcile():
    """Gilead's 2018 plain R&D sits $1,098mm above its excluding figure against a tagged
    in-process nil, so nothing earlier is filled."""
    from fetchers.financials_edgar import parse_statements
    def usd(rows):
        return {"units": {"USD": [_annual(f"{y}-01-01", f"{y}-12-31", v, "10-K") for y, v in rows]}}
    payload = {"facts": {"us-gaap": {
        "Revenues": usd([(2025, 29e9)]),
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost": usd([(2018, 3920e6), (2025, 5799e6)]),
        "ResearchAndDevelopmentExpense": usd([(2016, 5098e6), (2017, 3734e6), (2018, 5018e6)]),
        "ResearchAndDevelopmentInProcess": usd([(2017, 0.0), (2018, 0.0)]),
    }}}
    periods = parse_statements(payload)["lines"]["ResearchAndDevelopmentExpense"]["periods"]
    assert sorted(int(end[:4]) for end, kind in periods if kind == "FY") == [2018, 2025]


def _usd_years(rows):
    return {"units": {"USD": [_annual(f"{y}-01-01", f"{y}-12-31", v, "10-K") for y, v in rows]}}


def test_rd_expensing_acquired_in_process_rd_inside_it_is_read_net_of_it():
    """Merck tags plain R&D only, and $11,409mm of acquired in-process R&D written off in
    2023 inside its $30,531mm. The net line takes it out; a year with nothing tagged is
    the line as filed."""
    from fetchers.financials_edgar import parse_statements
    payload = {"facts": {"us-gaap": {
        "Revenues": _usd_years([(2025, 65011e6)]),
        "ResearchAndDevelopmentExpense": _usd_years([(2022, 13548e6), (2023, 30531e6), (2025, 15789e6)]),
        "ResearchAndDevelopmentAssetAcquiredOtherThanThroughBusinessCombinationWrittenOff":
            _usd_years([(2022, 0.0), (2023, 11409e6)]),
    }}}
    lines = parse_statements(payload)["lines"]
    net = {int(end[:4]): e for (end, kind), e in lines["ResearchLessExpensedIprd"]["periods"].items()}
    assert net[2023]["val"] == pytest.approx(19122e6) and "less expensed" in net[2023]["concept"]
    assert net[2022]["val"] == pytest.approx(13548e6) and net[2025]["val"] == pytest.approx(15789e6)
    filed = {int(end[:4]): e for (end, kind), e in lines["ResearchAndDevelopmentExpense"]["periods"].items() if kind == "FY"}
    assert filed[2023]["val"] == pytest.approx(30531e6)


def test_a_filer_presenting_in_process_rd_on_its_own_line_is_not_netted_twice():
    """Lilly's plain and excluding R&D agree in 2021 against $970mm tagged in-process, so
    its tagged amounts sit outside R&D and its plain years are not netted."""
    from fetchers.financials_edgar import parse_statements
    payload = {"facts": {"us-gaap": {
        "Revenues": _usd_years([(2025, 65179e6)]),
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost": _usd_years([(2021, 6931e6), (2025, 13337e6)]),
        "ResearchAndDevelopmentExpense": _usd_years([(2019, 5595e6), (2020, 5976e6), (2021, 6931e6)]),
        "ResearchAndDevelopmentAssetAcquiredOtherThanThroughBusinessCombinationWrittenOff":
            _usd_years([(2020, 500e6), (2021, 970e6)]),
    }}}
    net = {int(end[:4]): e["val"] for (end, kind), e in
           parse_statements(payload)["lines"]["ResearchLessExpensedIprd"]["periods"].items()}
    assert net[2020] == pytest.approx(5976e6) and net[2021] == pytest.approx(6931e6)
