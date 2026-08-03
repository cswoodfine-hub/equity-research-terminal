"""build_statements over a seeded DB, no network.

Financials load through the real fetcher with the EDGAR call monkeypatched to fixtures,
so the view is tested on rows the parser actually produces.
"""

import json
from pathlib import Path

import pytest

import db
import financials_view
import seed
import statements
from fetchers.financials_edgar import FinancialsEdgarFetcher

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def loaded(tmp_path, monkeypatch):
    facts = {t: json.loads((FIXTURES / f"companyfacts_{t.lower()}.json").read_text())
             for t in ("LLY", "JNJ", "NVO")}
    monkeypatch.setattr(FinancialsEdgarFetcher, "fetch", lambda self: facts[self.ticker])
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    for ticker in facts:
        FinancialsEdgarFetcher(ticker, db_file).run()
    return db_file


def _line(built, statement, key):
    return next(l for l in built["statements"][statement]["lines"] if l["key"] == key)


def _labels(built, statement):
    return [p["label"] for p in built["statements"][statement]["periods"]]


def test_unknown_ticker_is_none(loaded):
    assert financials_view.build_statements(loaded, "NOPE") is None


def test_quarterly_income_is_labelled_by_fiscal_quarter(loaded):
    built = financials_view.build_statements(loaded, "LLY", basis="quarterly")
    assert _labels(built, "income")[:3] == ["Q1 26", "Q4 25", "Q3 25"]
    assert built["currency"] == "USD"
    assert built["has_interim"] is True


def test_fourth_quarter_is_the_year_less_the_nine_months(loaded):
    """Q4 is never tagged, so it is the reported year minus the reported nine months."""
    built = financials_view.build_statements(loaded, "LLY", basis="quarterly")
    revenue = _line(built, "income", "Revenues")
    q4 = revenue["cells"][_labels(built, "income").index("Q4 25")]

    assert q4["derived"] is True
    assert q4["value"] == pytest.approx(65_179_000_000 - 45_887_000_000, rel=1e-6)


def test_fourth_quarter_is_not_derived_for_per_share_lines(loaded):
    """Regression guard: EPS does not add up across quarters.

    Full year EPS less nine month EPS is not the fourth quarter's EPS, because the
    share count moves between periods. The cell must stay empty rather than carry a
    number no filer published.
    """
    built = financials_view.build_statements(loaded, "LLY", basis="quarterly")
    index = _labels(built, "income").index("Q4 25")

    for key in ("EarningsPerShareDiluted", "WeightedAverageDilutedShares"):
        assert _line(built, "income", key)["cells"][index]["value"] is None, key
    # The same column does resolve for the flow lines either side of it.
    assert _line(built, "income", "NetIncomeLoss")["cells"][index]["value"] is not None


def test_gross_profit_is_derived_for_lly_and_reported_for_jnj(loaded):
    lly = financials_view.build_statements(loaded, "LLY", basis="annual")
    jnj = financials_view.build_statements(loaded, "JNJ", basis="annual")

    assert all(c["derived"] for c in _line(lly, "income", "GrossProfit")["cells"]
               if c["value"] is not None)
    assert not any(c["derived"] for c in _line(jnj, "income", "GrossProfit")["cells"]
                   if c["value"] is not None)


def test_derived_subtotal_is_dropped_when_an_input_is_missing(loaded):
    """Novo tags no us-gaap debt, so net debt has nothing to subtract from."""
    built = financials_view.build_statements(loaded, "NVO", basis="annual")
    keys = [line["key"] for line in built["statements"]["balance"]["lines"]]
    assert "NetDebt" not in keys
    assert "CashAndEquivalents" in keys      # the input that does resolve is still shown


def test_free_cash_flow_is_operations_less_capex(loaded):
    built = financials_view.build_statements(loaded, "LLY", basis="annual")
    index = _labels(built, "cashflow").index("FY25")
    operations = _line(built, "cashflow", "CashFlowOperating")["cells"][index]["value"]
    capex = _line(built, "cashflow", "CapitalExpenditure")["cells"][index]["value"]
    fcf = _line(built, "cashflow", "FreeCashFlow")["cells"][index]

    assert fcf["derived"] is True
    assert fcf["value"] == pytest.approx(operations - capex)


def test_cash_flow_quarterly_columns_are_cumulative(loaded):
    """A 10-Q reports cash flow from the year start, so the columns run 3M, 6M, 9M, FY."""
    built = financials_view.build_statements(loaded, "LLY", basis="quarterly")
    assert _labels(built, "cashflow")[:4] == ["Q1 26", "FY25", "9M 25", "6M 25"]

    index = _labels(built, "cashflow").index("9M 25")
    operations = _line(built, "cashflow", "CashFlowOperating")["cells"][index]
    assert operations["value"] == 13_588_400_000       # January to September, as filed


def test_annual_balance_sheet_only_shows_fiscal_year_ends(loaded):
    built = financials_view.build_statements(loaded, "LLY", basis="annual")
    assert _labels(built, "balance")[:2] == ["Dec 25", "Dec 24"]

    quarterly = financials_view.build_statements(loaded, "LLY", basis="quarterly")
    assert _labels(quarterly, "balance")[:2] == ["Mar 26", "Dec 25"]


def test_annual_only_filer_reports_no_interim(loaded):
    built = financials_view.build_statements(loaded, "NVO", basis="quarterly")
    assert built["has_interim"] is False
    assert built["statements"]["income"]["periods"] == []


def test_snapshot_compares_the_same_quarter_a_year_earlier(loaded):
    built = financials_view.build_statements(loaded, "LLY")
    snapshot = built["snapshot"]

    assert snapshot["label"] == "Q1 26"
    assert snapshot["revenue"] == 19_799_000_000
    assert snapshot["revenue_growth"] == pytest.approx(19_799_000_000 / 12_729_000_000 - 1)
    assert snapshot["net_margin"] == pytest.approx(7_396_000_000 / 19_799_000_000)
    assert snapshot["eps_diluted"] == 8.26


def test_snapshot_matches_a_52_week_filers_shifting_period_end(loaded):
    """JNJ's quarters end on a Sunday, so last year's is a day or two off the date."""
    snapshot = financials_view.build_statements(loaded, "JNJ")["snapshot"]
    assert snapshot["revenue_growth"] is not None


def test_a_line_no_filer_tags_is_absent_rather_than_zero(loaded):
    # Nobody in the universe tags OperatingIncomeLoss on a US filing any more.
    built = financials_view.build_statements(loaded, "LLY", basis="annual")
    keys = [line["key"] for line in built["statements"]["income"]["lines"]]
    assert "OperatingIncomeLoss" not in keys

    # The IFRS filer does tag it, under its own concept.
    nvo = financials_view.build_statements(loaded, "NVO", basis="annual")
    nvo_keys = [line["key"] for line in nvo["statements"]["income"]["lines"]]
    assert "OperatingIncomeLoss" in nvo_keys


def test_period_labels_cover_each_period_type():
    label = financials_view._period_label
    assert label("2025-12-31", statements.FY, "12M", 12) == "FY25"
    assert label("2026-03-31", statements.Q, "3M", 12) == "Q1 26"
    assert label("2025-06-30", statements.YTD, "6M", 12) == "6M 25"
    assert label("2026-03-31", statements.INSTANT, None, 12) == "Mar 26"
    # A June year end: September is the first quarter of the next fiscal year.
    assert label("2025-09-30", statements.Q, "3M", 6) == "Q1 26"


# --- growth against margin -----------------------------------------------
def test_trend_pairs_growth_with_margin_per_quarter(loaded):
    trend = financials_view.build_statements(loaded, "LLY", basis="quarterly")["trend"]

    assert [p["label"] for p in trend][-3:] == ["Q3 25", "Q4 25", "Q1 26"]
    latest = trend[-1]
    assert latest["revenue_growth"] == pytest.approx(19_799_000_000 / 12_729_000_000 - 1)
    assert latest["net_margin"] == pytest.approx(7_396_000_000 / 19_799_000_000)


def test_trend_has_no_hole_where_a_fourth_quarter_belongs(loaded):
    """The series is what makes the panel readable, so a missing Q4 would break it.

    Nobody tags Q4, so without the fill the line would jump Q3 to the next Q1 and the
    bars would show a gap every fourth column.
    """
    trend = financials_view.build_statements(loaded, "LLY", basis="quarterly")["trend"]
    labels = [p["label"] for p in trend]

    assert "Q4 25" in labels and "Q4 24" in labels
    assert all(p["net_margin"] is not None for p in trend)
    # Growth wherever a year-earlier quarter exists to divide by, which is every quarter
    # but the first four: the trend now runs the whole stored history rather than the
    # last nine points, so it begins where the data begins and nothing precedes it.
    assert all(p["revenue_growth"] is not None for p in trend[4:])
    fourths = [p for p in trend[4:] if p["label"].startswith("Q4")]
    assert fourths and all(p["revenue_growth"] is not None for p in fourths)


def test_trend_growth_compares_the_same_quarter_not_the_one_before(loaded):
    """Seasonality is not a trend. Q1 against Q4 would read as a collapse every year."""
    trend = {p["label"]: p for p in
             financials_view.build_statements(loaded, "LLY", basis="quarterly")["trend"]}
    # Q1 25 revenue is below Q4 24, and above Q1 24. Only the year-on-year pair is positive.
    assert trend["Q1 25"]["revenue_growth"] > 0


def test_trend_follows_the_basis(loaded):
    annual = financials_view.build_statements(loaded, "LLY", basis="annual")["trend"]
    assert [p["label"] for p in annual][-2:] == ["FY24", "FY25"]


def test_the_extra_stored_year_gives_the_oldest_shown_year_its_growth(loaded):
    """A fiscal year beyond the shown window is kept as the base the oldest shown year's
    year-over-year growth divides by, so the growth and margin lines start together rather
    than the growth line missing its first year. Growth still comes only from a genuinely
    adjacent prior (see _prior_period), never whatever happens to be nearest."""
    annual = financials_view.build_statements(loaded, "NVO", basis="annual")["trend"]
    # The oldest year on file has nothing before it to divide by. Every year after it
    # does, including the one that used to be the oldest shown before the window opened
    # onto the whole history.
    assert annual[0]["revenue_growth"] is None
    assert all(p["revenue_growth"] is not None for p in annual[1:])
    assert annual[0]["net_margin"] is not None
    assert annual[-1]["revenue_growth"] is not None


def test_trend_matches_a_52_week_filers_shifting_quarter_end(loaded):
    trend = financials_view.build_statements(loaded, "JNJ", basis="quarterly")["trend"]
    # A 52/53 week filer moves its quarter end by a day or two a year, so the year-ago
    # match is by nearest date rather than by exact one. Every quarter whose own year-ago
    # quarter is in the series finds it; the ones without are the quarters a refused
    # fourth-quarter derivation left out, and they read as gaps rather than as figures.
    present = {p["label"] for p in trend}

    def year_before(label):
        quarter, year = label.split()
        return f"{quarter} {int(year) - 1:02d}"

    for point in trend:
        if year_before(point["label"]) in present:
            assert point["revenue_growth"] is not None, point["label"]


def test_prior_period_rejects_a_date_more_than_a_fortnight_out():
    series = {("2025-01-31", statements.Q): 1.0, ("2026-03-31", statements.Q): 2.0}
    assert financials_view._prior_period(series, ("2026-03-31", statements.Q)) is None


def test_prior_period_takes_the_nearest_candidate():
    series = {("2025-03-29", statements.Q): 1.0, ("2025-04-04", statements.Q): 2.0,
              ("2026-03-31", statements.Q): 3.0}
    assert financials_view._prior_period(
        series, ("2026-03-31", statements.Q)) == ("2025-03-29", statements.Q)


# --- 52/53 week calendars ---------------------------------------------------
# A filer on a 52/53 week year closes its periods on a fixed weekday, so a period end
# wanders either side of the month boundary. Every date here is a real one.

@pytest.mark.parametrize("period_end, expected", [
    # Johnson & Johnson. The third quarter of 2017 closed on 1 October and the second of
    # 2018 on 1 July; read by calendar month both land a quarter late.
    ("2017-10-01", "Q3 17"),
    ("2018-07-01", "Q2 18"),
    ("2023-10-01", "Q3 23"),
    # And the ordinary cases still read as themselves.
    ("2017-12-31", "Q4 17"),
    ("2026-06-28", "Q2 26"),
    ("2025-09-30", "Q3 25"),
])
def test_a_quarter_is_labelled_by_the_month_it_closes_nearest(period_end, expected):
    assert financials_view._period_label(
        period_end, statements.Q, "3M", 12) == expected


@pytest.mark.parametrize("period_end, expected", [
    # Johnson & Johnson's fiscal 2011 closed on 1 January 2012 and its 2016 on
    # 1 January 2017. Taken from the calendar year each collided with the year after it.
    ("2012-01-01", "FY11"),
    ("2017-01-01", "FY16"),
    ("2023-01-01", "FY22"),
    ("2012-12-30", "FY12"),
    ("2025-12-28", "FY25"),
])
def test_a_year_is_labelled_by_the_year_it_closes_nearest(period_end, expected):
    assert financials_view._period_label(
        period_end, statements.FY, "12M", 12) == expected


def test_a_balance_date_snaps_the_same_way():
    assert financials_view._period_label(
        "2023-01-01", statements.INSTANT, None, 12) == "Dec 22"


def test_a_filer_whose_year_does_not_end_in_december_is_unaffected():
    """The snap is about the day of the month, not the month, so a June year end still
    counts its quarters from July."""
    assert financials_view._period_label(
        "2025-09-30", statements.Q, "3M", 6) == "Q1 26"


def test_two_dates_a_day_apart_are_one_period():
    """Exelixis carries its June 2016 quarter at 36.3m under 2016-06-30 and again, to
    the cent, under 2016-07-01. The later date wins, being the more recent filing's
    view of where the quarter ended."""
    collapsed = financials_view.collapse_adjacent({
        ("2016-06-30", statements.Q): 36.3,
        ("2016-07-01", statements.Q): 36.3,
        ("2016-09-30", statements.Q): 62.2,
    })
    assert list(collapsed) == [("2016-07-01", statements.Q),
                               ("2016-09-30", statements.Q)]


def test_two_real_periods_are_never_collapsed():
    """Consecutive quarters are three months apart and a year is twelve. Only a date
    that has moved by a day or two is the same period seen twice."""
    series = {("2025-03-31", statements.Q): 1.0,
              ("2025-06-30", statements.Q): 2.0,
              ("2025-09-30", statements.Q): 3.0}
    assert financials_view.collapse_adjacent(series) == series


def test_a_quarter_and_a_year_ending_the_same_day_both_survive():
    """A fourth quarter and its fiscal year close on the same date and are different
    facts. The collapse is within one period type, never across two."""
    series = {("2025-12-31", statements.Q): 25.0,
              ("2025-12-31", statements.FY): 100.0}
    assert financials_view.collapse_adjacent(series) == series


# --- A derived fourth quarter, and when not to derive one -------------------
# Q4 = full year minus nine months. Exact arithmetic, and exact only while both figures
# describe the same company.

def _pair(fy_revenue, ytd_revenue, quarters):
    """A revenue series shaped like one year: three quarters, a nine month, a full year."""
    series = {("2021-10-03", statements.YTD): ytd_revenue,
              ("2022-01-02", statements.FY): fy_revenue}
    for end, value in zip(("2021-04-04", "2021-07-04", "2021-10-03"), quarters):
        series[(end, statements.Q)] = value
    return ({"Revenues": series},
            ("2022-01-02", statements.FY), ("2021-10-03", statements.YTD))


def test_a_restated_year_is_not_subtracted_from_an_unrestated_nine_months():
    """Johnson & Johnson's fiscal 2021, the case this guard exists for. The year is on
    file restated for the Kenvue separation at 78.74bn and the nine months as reported
    with consumer health still in it at 68.97bn, which subtract to a fourth quarter of
    9.77bn against three quarters averaging 23.0. The real figure was 24.8."""
    by_metric, fy, ytd = _pair(78.74e9, 68.97e9, (22.32e9, 23.31e9, 23.34e9))
    assert financials_view._q4_reconciles(by_metric, fy, ytd) is False


def test_an_ordinary_year_still_derives_its_fourth_quarter():
    """The same company a year earlier, where both figures are the same basis."""
    by_metric, fy, ytd = _pair(82.58e9, 60.11e9, (20.69e9, 18.34e9, 21.08e9))
    assert financials_view._q4_reconciles(by_metric, fy, ytd) is True


def test_a_milestone_landing_in_the_fourth_quarter_is_kept():
    """Beam's fourth quarter of 2023 is fifteen times its average because a licence fee
    landed in it, and Moderna's of 2020 is seven times because that is when the vaccine
    shipped. A company whose revenue arrives in lumps has no expectation to violate."""
    by_metric, fy, ytd = _pair(0.38e9, 0.06e9, (0.02e9, 0.02e9, 0.02e9))
    assert financials_view._q4_reconciles(by_metric, fy, ytd) is True


def test_lumpy_quarters_are_never_judged():
    """Three quarters that disagree with each other cannot predict a fourth."""
    by_metric, fy, ytd = _pair(30e9, 28e9, (16e9, 8e9, 4e9))
    assert financials_view._q4_reconciles(by_metric, fy, ytd) is True


def test_a_negative_quarter_is_refused_at_any_size():
    """No company sells a negative amount in three months. Intellia and Voyager both
    have a year that subtracts below zero, and neither is near the size the rest of the
    test applies at."""
    by_metric, fy, ytd = _pair(0.040e9, 0.041e9, (0.013e9, 0.014e9, 0.014e9))
    assert financials_view._q4_reconciles(by_metric, fy, ytd) is False


def test_a_year_with_no_revenue_on_file_is_derived_as_before():
    """A developer's lines are losses and cash burn, where a wide swing is the business.
    There is nothing to reconcile against and nothing is refused."""
    assert financials_view._q4_reconciles(
        {}, ("2022-01-02", statements.FY), ("2021-10-03", statements.YTD)) is True


def test_the_refused_quarter_is_a_gap_not_a_wrong_number(loaded):
    """What a refusal looks like downstream: the column has no revenue rather than a
    figure the company never reported."""
    q4 = ("2022-01-02", statements.Q)
    by_metric = {"Revenues": _pair(78.74e9, 68.97e9,
                                   (22.32e9, 23.31e9, 23.34e9))[0]["Revenues"]}
    values, filled = financials_view._fill_fourth_quarters(
        by_metric, {q4: (("2022-01-02", statements.FY),
                         ("2021-10-03", statements.YTD))})
    assert q4 not in values["Revenues"]
    assert ("Revenues", q4) not in filled
