"""The Forecast tab's board adds up what the valuation holds and values nothing."""

import pathlib

import pytest

import forecast_board as B

BACKEND = pathlib.Path(__file__).resolve().parent.parent


def _row(revenue, ebit, fcff):
    return {"revenue": revenue, "cogs": revenue * 0.2, "sga": revenue * 0.2,
            "rd": revenue * 0.1, "other": 0.0, "ebit": ebit, "tax": ebit * 0.2,
            "fcff": fcff}


def _verdict():
    return {"ok": True, "name": "Test Co", "close": 20.0, "diluted_shares": 100e6,
            "modelled": [
                {"asset_id": 1, "name": "Onsale", "is_marketed": True, "pos": 1.0,
                 "per_share": 6.0, "years": [2026, 2027],
                 "pnl_share": [_row(100.0, 50.0, 40.0), _row(110.0, 55.0, 44.0)]},
                {"asset_id": 2, "name": "Pipeline", "is_marketed": False, "pos": 0.5,
                 "per_share": 2.0, "years": [2027],
                 "pnl_share": [_row(40.0, 20.0, 16.0)]},
                {"asset_id": 3, "name": "Placeholder", "is_marketed": False, "pos": 0.5,
                 "per_share": 1.0, "years": [2027], "counted": False,
                 "pnl_share": [_row(500.0, 250.0, 200.0)]}],
            "streams": [{"line": "Other", "years": [2026, 2027], "per_share": 1.0,
                         "pnl_share": [_row(10.0, 5.0, 4.0), _row(10.0, 5.0, 4.0)]}],
            "placeholders": [{"asset_id": 3}]}


def _with_launches():
    """The same company with launches the model assumes: 20 of revenue in 2027 at a 50%
    margin before a 20% tax, 6 of it spent on the plant its growth takes."""
    verdict = _verdict()
    verdict["sotp"] = {"future": {
        "value": 9.0, "ratios": {"cogs": 0.2, "sga": 0.2, "rd": 0.1, "other": 0.0,
                                 "tax": 0.2},
        "flows": [{"year": 2026, "revenue": 0.0, "fcff": 0.0, "growth_investment": 0.0},
                  {"year": 2027, "revenue": 20.0, "fcff": 2.0, "growth_investment": 6.0}]}}
    return verdict


def test_the_company_is_the_sum_of_its_counted_parts_at_their_odds():
    parts = B._parts(_verdict())
    weighted = B.total(parts, "revenue", True)
    success = B.total(parts, "revenue", False)
    assert weighted == {2026: 110.0, 2027: 110.0 + 10.0 + 40.0 * 0.5}
    assert success == {2026: 110.0, 2027: 110.0 + 10.0 + 40.0}
    # the placeholder is carried and never counted
    assert any(p["name"] == "Placeholder" and not p["counted"] for p in parts)
    assert B.total(parts, "revenue", False, "pipeline") == {2027: 40.0}


def test_added_revenue_is_never_negative_and_starts_from_what_is_sold_today():
    assert B.added({2026: 110.0, 2027: 100.0, 2028: 130.0}, opening=100.0) == {
        2026: 10.0, 2027: 0.0, 2028: 30.0}
    assert B.added({2026: 110.0}, opening=None) == {2026: 0.0}


def test_capex_is_upkeep_on_revenue_plus_new_plant_on_added_revenue():
    parts = B._parts(_verdict())
    rule = {"upkeep_rate": 0.03, "growth_rate": 0.3}
    case = B._case(parts, True, opening=100.0, share=0.5, rule=rule)
    revenue = case["company"]["revenue"]
    assert case["company"]["capex"][2026] == pytest.approx(0.03 * 110.0 + 0.3 * 10.0)
    assert case["company"]["capex"][2027] == pytest.approx(
        0.03 * revenue[2027] + 0.3 * (revenue[2027] - 110.0))
    # new plant is the capex share of the growth charge the valuation takes
    assert case["company"]["capex"][2027] - 0.03 * revenue[2027] == pytest.approx(
        0.3 / 0.5 * case["company"]["growth_investment"][2027])
    # the growth charge comes off the company's cash flow, as it comes off its value
    assert case["company"]["free_cash_flow"][2026] == pytest.approx(44.0 - 0.5 * 10.0)


def test_the_launches_the_model_assumes_are_a_group_of_their_own():
    """They are in the value, so they are in the path: a group beside the named assets,
    the same on both bases, with their own plant charge taken off the company's cash."""
    parts = B._parts(_with_launches())
    assumed = next(p for p in parts if p["kind"] == "assumed")
    row = assumed["rows"][1]
    assert row["ebit"] == pytest.approx(20.0 * 0.5)
    assert row["tax"] == pytest.approx(10.0 * 0.2)
    assert row["fcff"] == pytest.approx(10.0 - 2.0)          # before its plant
    for weighted in (True, False):
        case = B._case(parts, weighted, opening=100.0, share=0.5,
                       rule={"upkeep_rate": None, "growth_rate": None})
        assert case["groups"]["assumed"]["revenue"] == {2026: 0.0, 2027: 20.0}
        company = case["company"]
        assert company["revenue"][2027] == pytest.approx(
            sum(case["groups"][g]["revenue"].get(2027, 0.0) for g in B.GROUPS))
        book_growth = B.added(B.total([p for p in parts if p["kind"] != "assumed"],
                                      "revenue", weighted), 100.0)[2027]
        assert company["growth_investment"][2027] == pytest.approx(0.5 * book_growth + 6.0)
        assert company["free_cash_flow"][2027] == pytest.approx(
            sum(case["groups"][g]["free_cash_flow"].get(2027, 0.0) for g in B.GROUPS)
            - company["growth_investment"][2027])


def test_a_company_with_only_assumed_launches_has_no_board():
    verdict = _with_launches()
    verdict["modelled"], verdict["streams"] = [], []
    assert B.build(None, None, "TEST", verdict)["ok"] is False


def test_the_rows_are_paired_with_the_valuation_window_not_the_model_window():
    """A product launched since the valuation year has a model that opens before it and
    P&L rows only for the window. Paired with the model's years, Casgevy's cash flow was
    drawn two years early and Vertex's forecast opened in 2024."""
    verdict = _verdict()
    verdict["modelled"][0].update(years=[2024, 2025, 2026, 2027], dcf_years=[2026, 2027])
    parts = B._parts(verdict)
    assert parts[0]["years"] == [2026, 2027]
    assert B.total(parts, "revenue", True)[2026] == 110.0
    assert 2024 not in B.total(parts, "revenue", True)


def _tail(loe, in_base=False):
    return {"end": 2027, "growth": 0.0, "year1_pct": 0.5, "decay_pct": 0.2,
            "late_decay_pct": None, "late_from_year": None, "parts": [[1.0, loe, in_base]]}


def test_a_part_is_carried_past_its_model_on_the_path_its_terminal_value_takes():
    """Every line of the final year moves with the revenue, which is the stream the
    terminal multiple discounts; a part with no terminal value earns nothing past it."""
    import forecast
    verdict = _verdict()
    verdict["modelled"][0]["terminal_tail"] = _tail(2029)
    parts = B._parts(verdict)
    onsale, pipeline = parts[0], parts[1]
    B.carry(onsale, 2032)
    B.carry(pipeline, 2032)
    assert onsale["years"] == list(range(2026, 2033)) and onsale["modelled"] == 2
    path = forecast.terminal_path(0.0, 2027, 2029, False, 0.5, 0.2, None, None,
                                  list(range(2028, 2033)))
    for year, row in zip(onsale["years"][2:], onsale["rows"][2:]):
        assert row["revenue"] == pytest.approx(110.0 * path[year])
        assert row["fcff"] == pytest.approx(44.0 * path[year])
    assert onsale["rows"][2]["revenue"] == pytest.approx(110.0)       # flat to its cliff
    assert onsale["rows"][-1]["revenue"] < 0.5 * 110.0                # and then down it
    assert pipeline["years"] == [2027]                                # no tail, no carry
    # the growth charge is laid on the modelled years alone, as the valuation lays it
    assert B.total(parts, "revenue", True, modelled=True).get(2030) is None
    assert B.total(parts, "revenue", True)[2030] == pytest.approx(110.0 * path[2030])


def test_the_horizon_passes_the_last_cliff_that_matters_and_no_further():
    verdict = _verdict()
    parts = B._parts(verdict)
    assert B.horizon(parts, 2026) == 2035                     # no cliff: ten years
    verdict["modelled"][0]["loe_year"] = 2039
    assert B.horizon(B._parts(verdict), 2026) == 2042         # three years past it
    verdict["modelled"][0]["loe_year"] = 2070
    assert B.horizon(B._parts(verdict), 2026) == 2050         # never more than 25 years
    verdict["modelled"][0].update(loe_year=2030, per_share=600.0)
    verdict["modelled"][1].update(loe_year=2045, per_share=2.0)   # under 1% of the value
    assert B.horizon(B._parts(verdict), 2026) == 2035


def test_capex_with_no_rule_is_none_not_nil():
    parts = B._parts(_verdict())
    case = B._case(parts, True, opening=100.0, share=0.5,
                   rule={"upkeep_rate": None, "growth_rate": None})
    assert case["company"]["capex"] is None


def test_the_board_is_a_view_beside_the_value():
    for name in ("forecast", "assumptions", "forecast_view", "company_score", "breakpoints",
                 "fair_value"):
        assert "import forecast_board" not in (BACKEND / f"{name}.py").read_text(), name


def test_the_live_board_reconciles_with_the_sum_of_the_parts(book):
    """Its value split adds to the equity a share, and its revenue to the sum of the
    assets' own, for a company the book carries.

    Skipped, with the reason, where no built database is on file."""
    import forecast_view as V
    row = book.execute("SELECT 1 FROM companies WHERE ticker = 'AMGN'").fetchone()
    if row is None:
        pytest.skip("no AMGN in this book")
    verdict = V.company_verdict(None, "AMGN")
    if not (verdict or {}).get("ok"):
        pytest.skip("no AMGN verdict in this book")
    board = B.build(book, None, "AMGN", verdict)
    assert board["ok"]
    split = sum(x["per_share"] for x in board["value"]["source"])
    assert split == pytest.approx(board["value"]["equity_per_share"], abs=0.01)
    for basis in ("weighted", "success"):
        company = board[basis]["company"]["revenue"]
        groups = board[basis]["groups"]
        for year in board["years"]["forecast"]:
            assert company[year] == pytest.approx(
                sum(groups[k]["revenue"].get(year, 0.0) for k in B.GROUPS))
            cash = board[basis]["company"]
            assert cash["free_cash_flow"][year] == pytest.approx(
                sum(groups[k]["free_cash_flow"].get(year, 0.0) for k in B.GROUPS)
                - cash["growth_investment"][year])
