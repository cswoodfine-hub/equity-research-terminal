"""From revenue to cash: the figure built from the three statements.

Lives here so ``cd backend && pytest -q`` stays the one test command. Figures synthetic.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "frontend"))

import business  # noqa: E402


def _cells(*values):
    return [{"value": v, "derived": False} for v in values]


def _statements(quarterly=True):
    """Newest first, as the endpoint returns it: three quarters and the year before."""
    ends = ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31"]
    income = {"periods": [{"period_end": e, "label": l, "period_type": "Q", "months": "3M"}
                          for e, l in zip(ends, ("Q3 26", "Q2 26", "Q1 26", "Q4 25"))],
              "lines": [
                  {"key": "Revenues", "cells": _cells(100e9, 90e9, 80e9, 70e9)},
                  {"key": "CostOfRevenue", "cells": _cells(20e9, 18e9, 16e9, 14e9)},
                  {"key": "ResearchAndDevelopmentExpense", "cells": _cells(25e9, 22e9, 20e9, 18e9)},
                  {"key": "SellingGeneralAndAdministrative", "cells": _cells(15e9, 14e9, 13e9, 12e9)},
                  {"key": "NetIncomeLoss", "cells": _cells(30e9, 27e9, 24e9, -5e9)}]}
    kinds = ((("YTD", "9M"), ("YTD", "6M"), ("Q", "3M"), ("FY", "12M")) if quarterly
             else (("FY", "12M"),) * 4)
    cash = {"periods": [{"period_end": e, "period_type": k, "months": m}
                        for e, (k, m) in zip(ends, kinds)],
            "lines": [
                {"key": "CashFlowOperating", "cells": _cells(60e9, 35e9, 15e9, 50e9)},
                {"key": "CapitalExpenditure", "cells": _cells(9e9, 5e9, 2e9, 8e9)},
                {"key": "AcquisitionsNet", "cells": _cells(6e9, 6e9, None, 1e9)},
                {"key": "AcquiredIprd", "cells": _cells(3e9, 1e9, 1e9, None)},
                {"key": "ShareRepurchases", "cells": _cells(4e9, 2e9, 1e9, 3e9)},
                {"key": "DividendsPaid", "cells": _cells(6e9, 4e9, 2e9, 7e9)}]}
    balance = {"periods": [{"period_end": e, "period_type": "instant"} for e in ends],
               "lines": [{"key": "NetDebt", "cells": _cells(40e9, 38e9, 36e9, None)}]}
    return {"income": income, "cashflow": cash, "balance": balance}


def test_a_quarters_cash_is_the_year_to_date_less_the_one_before_it():
    rows = {r["label"]: r for r in business.prepare(_statements())["periods"]}
    # Nine months less six, six less three, and a first quarter is itself.
    assert rows["Q3 26"]["cfo"] == 25e9 and rows["Q2 26"]["cfo"] == 20e9
    assert rows["Q1 26"]["cfo"] == 15e9
    # The full year has no nine month figure before it in the window: left empty, not
    # printed as a quarter the size of a year.
    assert rows["Q4 25"]["cfo"] is None
    assert rows["Q3 26"]["capex"] == 4e9 and rows["Q3 26"]["dividends"] == 2e9


def test_a_gap_in_the_year_to_date_chain_leaves_the_quarter_empty_not_guessed():
    periods = [{"period_type": "YTD", "months": "9M"}, {"period_type": "YTD", "months": "6M"},
               {"period_type": "Q", "months": "3M"}]
    assert business.discrete([27.0, None, 5.0], periods) == [None, None, 5.0]
    # A neighbour that is not the period three months shorter is not subtracted.
    jump = [{"period_type": "YTD", "months": "9M"}, {"period_type": "Q", "months": "3M"}]
    assert business.discrete([27.0, 5.0], jump) == [None, 5.0]


def test_on_an_annual_basis_every_figure_is_already_its_own_period():
    rows = business.prepare(_statements(quarterly=False))["periods"]
    assert [r["cfo"] for r in rows] == [50e9, 15e9, 35e9, 60e9]


def test_the_remainder_is_what_revenue_left_after_the_named_costs_and_net_income():
    rows = {r["label"]: r for r in business.prepare(_statements())["periods"]}
    latest = rows["Q3 26"]
    # Neither operating income nor income before tax on this filer, so there is nothing
    # to split the remainder at.
    assert latest["other"] == 100e9 - 20e9 - 25e9 - 15e9 - 30e9
    assert latest["opex_other"] is None and latest["pretax_other"] is None
    assert latest["gross"] == 80e9
    # Businesses bought and programmes bought are one use of cash.
    assert latest["acquisitions"] == (6e9 - 6e9) + (3e9 - 1e9)
    assert rows["Q4 25"]["net_debt"] is None and latest["net_debt"] == 40e9
    # Oldest first, so time runs left to right.
    assert [r["label"] for r in business.prepare(_statements())["periods"]] == [
        "Q4 25", "Q1 26", "Q2 26", "Q3 26"]


def _with_operating_income():
    statements = _statements()
    statements["income"]["lines"].append(
        {"key": "OperatingIncomeLoss", "cells": _cells(36e9, 33e9, 29e9, -4e9)})
    return statements


def test_the_remainder_is_split_at_operating_income_where_the_filer_tags_it():
    """One remainder called "Tax and other" held a 4.5bn operating charge in a Vertex
    quarter whose tax was 0.2bn. Above operating income it is an operating cost with no
    line of its own, and is named as that; below it, tax, interest and the rest."""
    data = business.prepare(_with_operating_income())
    rows = {r["label"]: r for r in data["periods"]}
    latest = rows["Q3 26"]
    assert latest["opex_other"] == 100e9 - 20e9 - 25e9 - 15e9 - 36e9
    assert latest["other"] == 36e9 - 30e9
    # The two together are the one remainder there was: nothing is added or lost.
    assert latest["opex_other"] + latest["other"] == 100e9 - 20e9 - 25e9 - 15e9 - 30e9
    # The loss quarter: 30bn spent in operations that no named line carries, and 1bn
    # below the line.
    assert rows["Q4 25"]["opex_other"] == 70e9 - 14e9 - 18e9 - 12e9 + 4e9
    assert rows["Q4 25"]["other"] == -4e9 + 5e9

    drawn = business.render(data, "USD", "income")
    block = f'fill="{business.TK.RULE_STRONG}" fill-opacity="1.0"'
    # A segment in each of the four periods, and its name beside the latest.
    assert drawn.count(block) == 5
    assert ">Other operating<" in drawn and ">Tax and other<" in drawn
    assert ">Operating income<" in drawn and ">36.00<" in drawn
    # With no operating income on file no such segment is drawn, in any period.
    assert business.render(business.prepare(_statements()), "USD", "income").count(block) == 0


def test_a_filer_with_no_operating_income_is_split_at_income_before_tax():
    """Lilly, Merck, Pfizer, J&J, Bristol and Biogen tag no operating income. Their upper
    remainder stops at income before tax, holds the interest too, and says less."""
    statements = _statements()
    statements["income"]["lines"].append(
        {"key": "IncomeBeforeTax", "cells": _cells(35e9, 32e9, 28e9, -5e9)})
    data = business.prepare(statements)
    latest = data["periods"][-1]
    assert latest["pretax_other"] == 100e9 - 20e9 - 25e9 - 15e9 - 35e9
    assert latest["other"] == 35e9 - 30e9 and latest["opex_other"] is None
    drawn = business.render(data, "USD", "income")
    assert ">Other costs<" in drawn and ">Income before tax<" in drawn
    assert ">Other operating<" not in drawn and ">Operating income<" not in drawn
    # Where both are tagged, operating income is the line, as the finer of the two.
    statements["income"]["lines"].append(
        {"key": "OperatingIncomeLoss", "cells": _cells(36e9, 33e9, 29e9, -4e9)})
    both = business.prepare(statements)["periods"][-1]
    assert both["opex_other"] == 4e9 and both["pretax_other"] is None
    assert both["other"] == 36e9 - 30e9


def test_a_gain_in_operations_draws_no_segment_and_is_still_printed():
    statements = _with_operating_income()
    # Operating income above what the named costs leave: a gain booked in operations.
    statements["income"]["lines"][-1]["cells"] = _cells(45e9, 33e9, 29e9, -4e9)
    data = business.prepare(statements)
    latest = data["periods"][-1]
    assert latest["opex_other"] == -5e9 and latest["other"] == 15e9
    drawn = business.render(data, "USD", "income")
    block = f'fill="{business.TK.RULE_STRONG}" fill-opacity="1.0"'
    assert drawn.count(block) == 3            # the three other periods, none beside the latest
    assert f">{business.MINUS}5.00<" in drawn  # the period's readout still says it


def _data():
    return business.prepare(_statements(), [
        {"period_end": "2026-09-30", "revenue_growth": 0.25, "net_margin": 0.30},
        {"period_end": "2026-06-30", "revenue_growth": 0.20, "net_margin": 0.30}])


def test_one_view_is_drawn_at_a_time_and_each_names_only_its_own_lines():
    income = business.render(_data(), "USD", "income")
    assert income.startswith("<svg") and "INCOME · USD BN" in income
    for label in ("Revenue", "Cost of sales", "R&amp;D", "SG&amp;A", "Tax and other",
                  "Net income"):
        assert label in income
    assert ">100.00<" in income and ">30.00<" in income
    # Nothing of the other two views is on it.
    assert "CASH ·" not in income and "Buybacks" not in income and "NET DEBT" not in income
    # The loss quarter has no green on its stack; the three profitable ones each do.
    assert income.count(f'fill="{business.TK.UP}"/>') == 3

    cash = business.render(_data(), "USD", "cash")
    for label in ("CASH · USD BN", "Cash from operations", "Capital expenditure",
                  "Buybacks", "Dividends", "NET DEBT"):
        assert label in cash
    assert "INCOME ·" not in cash and "Cost of sales" not in cash
    # Net debt is printed for the three periods it exists for, never as a nought.
    assert cash.count(">40.0<") >= 1 and ">0.0<" not in cash

    rates = business.render(_data(), "USD", "rates")
    assert "GROWTH ON A YEAR AND NET MARGIN" in rates and ">+25.0%<" in rates
    assert "INCOME ·" not in rates and "CASH ·" not in rates


def test_the_first_view_is_the_default_and_it_is_the_income_view():
    assert business.render(_data(), "USD") == business.render(_data(), "USD", "income")
    assert [key for key, _label in business.VIEWS] == ["income", "rates", "cash"]


def test_too_little_to_draw_is_no_figure():
    assert business.render({"periods": [], "unit": "", "divisor": 1.0}) == ""
    one = _statements()
    for line in one["income"]["lines"]:
        if line["key"] == "Revenues":
            line["cells"] = _cells(100e9, None, None, None)
    assert business.render(business.prepare(one)) == ""
    # With no growth series passed, margin is still net income over revenue, so the
    # view draws on that alone.
    assert "Net margin" in business.render(business.prepare(_statements()), "USD", "rates")
    # A view with nothing behind it is no figure, not an empty frame.
    no_cash = _statements()
    no_cash["cashflow"]["lines"] = []
    assert business.render(business.prepare(no_cash), "USD", "cash") == ""


def _named(statements):
    """Labels and units, as the endpoint carries them on each line."""
    names = {"Revenues": ("Revenue", "USD"), "NetIncomeLoss": ("Net income", "USD"),
             "CashFlowOperating": ("Cash from operations", "USD"),
             "NetDebt": ("Net debt", "USD")}
    for statement in statements.values():
        for line in statement["lines"]:
            line["label"], line["unit"] = names.get(line["key"], (line["key"], "USD"))
    return statements


def test_every_line_with_two_figures_is_offered_under_its_statements_name():
    options = dict(business.line_options(_named(_statements())))
    assert options["income:Revenues"] == "Income statement: Revenue"
    assert options["balance:NetDebt"] == "Balance sheet: Net debt"
    assert options["cashflow:CashFlowOperating"] == "Cash flow: Cash from operations"
    thin = _named(_statements())
    thin["income"]["lines"][0]["cells"] = _cells(100e9, None, None, None)
    assert "income:Revenues" not in dict(business.line_options(thin))


def test_a_line_on_its_own_prints_each_figure_and_reads_against_a_year_before():
    statements = _named(_statements())
    svg = business.render_line(statements, "income:Revenues", "USD")
    assert "INCOME STATEMENT · REVENUE · USD BN" in svg
    for figure in (">100.00<", ">90.00<", ">80.00<", ">70.00<"):
        assert figure in svg
    # A loss stands below the line with a true minus, and is not a column of nought.
    loss = business.render_line(statements, "income:NetIncomeLoss", "USD")
    assert f">{business.MINUS}5.00<" in loss
    # A quarter's cash is its own, named by its quarter, and the figure says how.
    cash = business.render_line(statements, "cashflow:CashFlowOperating", "USD")
    assert ">25.00<" in cash and ">Q3 26<" in cash and ">60.00<" not in cash
    assert "each quarter from year-to-date" in cash
    # A missing level is no column: three figures printed, not four.
    debt = business.render_line(statements, "balance:NetDebt", "USD")
    assert debt.count("<rect") == 3
    assert business.render_line(statements, "income:NoSuchLine") == ""


def test_a_round_step_puts_about_three_lines_under_the_top():
    assert business._step(24.4) == 10 and business._step(65.0) == 25.0
    assert business._step(309.0) == 250.0 or business._step(309.0) == 200.0
    assert business._step(0.9) in (0.25, 0.5) and business._step(0) == 1.0
