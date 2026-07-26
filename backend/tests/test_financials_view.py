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
    assert all(p["revenue_growth"] is not None for p in trend)
    assert all(p["net_margin"] is not None for p in trend)


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
    assert annual[0]["revenue_growth"] is not None   # starts with growth, not a gap
    assert annual[0]["net_margin"] is not None
    assert annual[-1]["revenue_growth"] is not None


def test_trend_matches_a_52_week_filers_shifting_quarter_end(loaded):
    trend = financials_view.build_statements(loaded, "JNJ", basis="quarterly")["trend"]
    assert all(p["revenue_growth"] is not None for p in trend[1:])


def test_prior_period_rejects_a_date_more_than_a_fortnight_out():
    series = {("2025-01-31", statements.Q): 1.0, ("2026-03-31", statements.Q): 2.0}
    assert financials_view._prior_period(series, ("2026-03-31", statements.Q)) is None


def test_prior_period_takes_the_nearest_candidate():
    series = {("2025-03-29", statements.Q): 1.0, ("2025-04-04", statements.Q): 2.0,
              ("2026-03-31", statements.Q): 3.0}
    assert financials_view._prior_period(
        series, ("2026-03-31", statements.Q)) == ("2025-03-29", statements.Q)
