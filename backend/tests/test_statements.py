"""Period classification and the statement line map, against saved EDGAR fixtures.

No network. The fixtures are trimmed copies of real company facts, rebuilt by
tools/refresh_fixtures.py.
"""

import json
from pathlib import Path

import statements
from fetchers.financials_edgar import (
    parse_statements,
    pick_kind_series,
    total_debt_series,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _facts(name):
    return json.loads((FIXTURES / name).read_text())


def _entry(start, end, form="10-Q"):
    return {"start": start, "end": end, "form": form, "val": 1, "filed": "2026-05-01"}


# --- period classification ----------------------------------------------
def test_classify_full_year_allows_a_52_week_filer():
    # JNJ's fiscal 2025 is 364 days and ends on a Sunday, not on 31 December.
    assert statements.classify_period(
        _entry("2024-12-30", "2025-12-28", "10-K")) == ("2025-12-28", statements.FY)


def test_classify_separates_a_quarter_from_a_cumulative_span():
    assert statements.classify_period(_entry("2026-01-01", "2026-03-31")) == (
        "2026-03-31", statements.Q)
    assert statements.classify_period(_entry("2025-01-01", "2025-06-30")) == (
        "2025-06-30", statements.YTD)
    assert statements.classify_period(_entry("2025-01-01", "2025-09-30")) == (
        "2025-09-30", statements.YTD)


def test_classify_instant_has_no_start():
    assert statements.classify_period({"end": "2026-03-31", "form": "10-Q", "val": 1}) == (
        "2026-03-31", statements.INSTANT)


def test_classify_drops_a_span_that_fits_no_bucket():
    # A two month stub period is not a quarter and must not be presented as one.
    assert statements.classify_period(_entry("2026-01-01", "2026-02-28")) is None


def test_classify_ignores_forms_we_do_not_read():
    assert statements.classify_period(_entry("2026-01-01", "2026-03-31", "S-1")) is None


def test_duration_label_names_the_months_covered():
    assert statements.duration_label(_entry("2025-01-01", "2025-09-30")) == "9M"
    assert statements.duration_label(_entry("2025-01-01", "2025-03-31")) == "3M"
    assert statements.duration_label({"end": "2025-03-31"}) is None


# --- the line map against real payloads ----------------------------------
def test_lly_quarters_reach_the_latest_10q():
    parsed = parse_statements(_facts("companyfacts_lly.json"))
    revenue = parsed["lines"]["Revenues"]["periods"]
    assert revenue[("2026-03-31", statements.Q)]["val"] == 19_799_000_000


def test_gross_profit_is_absent_for_a_filer_that_never_tags_it():
    """Lilly does not tag GrossProfit. The line must be missing, not zero.

    The API derives it from revenue less cost of sales and flags it; what must never
    happen is a stored value the company did not publish.
    """
    parsed = parse_statements(_facts("companyfacts_lly.json"))
    assert "GrossProfit" not in parsed["lines"]

    jnj = parse_statements(_facts("companyfacts_jnj.json"))
    assert jnj["lines"]["GrossProfit"]["periods"], "JNJ does tag it"


def test_capex_resolves_through_a_different_concept_per_filer():
    # Lilly tags PaymentsToAcquireOtherPropertyPlantAndEquipment, JNJ the plain one.
    for name in ("lly", "jnj"):
        parsed = parse_statements(_facts(f"companyfacts_{name}.json"))
        assert parsed["lines"]["CapitalExpenditure"]["periods"], name


def test_nvo_is_annual_only():
    """A 20-F filer tags no interim periods, which is a state the UI has to show."""
    parsed = parse_statements(_facts("companyfacts_nvo.json"))
    kinds = {kind for line in parsed["lines"].values() for _, kind in line["periods"]}
    assert statements.FY in kinds
    assert statements.Q not in kinds and statements.YTD not in kinds


def test_eps_keeps_its_own_unit_not_the_reporting_currency():
    parsed = parse_statements(_facts("companyfacts_nvo.json"))
    assert parsed["currency"] == "DKK"
    assert parsed["lines"]["EarningsPerShareDiluted"]["unit"] == "DKK/shares"


# --- the debt ladder ------------------------------------------------------
def test_total_debt_reconciles_the_split_ladder_to_the_combined_tag():
    """Regression: total debt stepped 1.6bn every fourth quarter.

    Lilly tags the combined amount at year ends only and the split at every quarter.
    Resolving each date independently picked whichever was present, so the series read
    as a debt raise each December and a paydown each March. Adding DebtCurrent to the
    ladder makes the split reconcile exactly, and the agreement check keeps the two
    bases from being mixed when they do not.
    """
    facts = _facts("companyfacts_lly.json")["facts"]
    series = total_debt_series(facts)
    assert series["2025-12-31"]["val"] == 42_503_000_000   # what the combined tag says
    _, combined = pick_kind_series(
        facts, [("us-gaap", "DebtLongtermAndShorttermCombinedAmount")],
        statements.INSTANT)
    assert combined[("2025-12-31", statements.INSTANT)]["val"] == 42_503_000_000

    # And the quarters either side are on the same basis, so the series is continuous.
    for end in ("2025-09-30", "2026-03-31"):
        assert series[end]["concept"].startswith("LongTermDebtNoncurrent")


def test_total_debt_skips_a_date_where_the_current_portion_is_untagged():
    """Adding zero for a missing current portion would read as a paydown."""
    facts = {"us-gaap": {
        "LongTermDebtNoncurrent": {"units": {"USD": [
            {"end": "2025-12-31", "val": 40e9, "form": "10-K", "filed": "2026-02-01"},
            {"end": "2026-03-31", "val": 39e9, "form": "10-Q", "filed": "2026-05-01"},
        ]}},
        "DebtCurrent": {"units": {"USD": [
            {"end": "2025-12-31", "val": 2e9, "form": "10-K", "filed": "2026-02-01"},
        ]}},
    }}
    series = total_debt_series(facts)
    assert series["2025-12-31"]["val"] == 42e9
    assert "2026-03-31" not in series


def test_every_line_key_is_unique_and_maps_back():
    keys = [line.key for line in statements.LINES]
    assert len(keys) == len(set(keys))
    assert all(statements.LINES_BY_KEY[key].key == key for key in keys)


def test_reference_lines_are_stored_but_never_drawn():
    """They answer a question about the statements rather than appearing on one, so the
    fetcher walks them and the three statement views do not."""
    drawn = {line.key for statement in statements.STATEMENTS
             for line in statements.lines_for(statement)}
    assert "ResearchExcludingAcquiredIprd" in statements.LINES_BY_KEY
    assert "ResearchExcludingAcquiredIprd" not in drawn


def test_derived_lines_reference_lines_that_exist():
    for line in statements.LINES:
        if not line.derived:
            continue
        left, op, right = line.derived
        assert op == "-"
        assert left in statements.LINES_BY_KEY and right in statements.LINES_BY_KEY
