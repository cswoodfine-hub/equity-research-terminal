"""The odds the price pays for on one readout, and the two ways the inversion goes wrong.

The naive version divided the company's whole gap by one asset's leg and read thirty-seven
for Lilly. The fixed version takes the rest of the company out first, reports only where
one gate carries the company, and says whether a disagreement is about odds or payoff.
"""

import datetime as dt

import db
import gate_odds


def test_the_rest_of_the_company_comes_out_before_the_gate_is_inverted():
    """Viking as recorded on 2026-10-25: VK2735 is worth 19.64 a share today, 30.84 if it
    passes and nil if it fails, the book is 20.82 and the price 24.40. The book's own
    odds are 64% and the price pays for 75%."""
    got = gate_odds.invert(price=24.40, fair_value=20.822, per_share_now=19.635,
                           per_share_success=30.844, per_share_failure=0.0)
    assert abs(got["p_book"] - 0.6366) < 1e-3
    assert abs(got["p_mkt"] - 0.7527) < 1e-3
    assert got["regime"] == "odds"
    assert got["share"] > 1.0                  # the gate is the company, and then some


def test_a_price_above_the_success_leg_is_a_payoff_disagreement_not_an_odds_one():
    """NewAmsterdam: the price exceeds the asset's full-success value plus the rest of
    the company, so no probability explains it and the readout cannot settle it."""
    got = gate_odds.invert(price=19.71, fair_value=10.978, per_share_now=3.73,
                           per_share_success=6.757, per_share_failure=0.0)
    assert got["p_mkt"] > 1.0
    assert got["regime"] == "payoff above success"


def test_a_gate_that_swings_a_sliver_of_its_company_is_not_reported(tmp_path):
    """Lilly's retatrutide swings 4.6% of Lilly. Attributing Lilly's gap to it reads
    thirty-seven, which is the arithmetic refusing, and the view refuses first."""
    path = _book(tmp_path, price=1273.5, fair_value=474.5, now=20.0, success=42.0, failure=0.0)
    out = gate_odds.build(path, today=dt.date(2026, 11, 7))
    assert out["rows"] == [] and "fifth" in out["reason"]


def test_a_gate_whose_date_has_passed_is_marked_rather_than_read_as_live(tmp_path):
    path = _book(tmp_path, price=24.4, fair_value=20.822, now=19.635, success=30.844,
                 failure=0.0, due="2026-11-01")
    row = gate_odds.build(path, today=dt.date(2026, 11, 7))["rows"][0]
    assert row["due_passed"] is True
    assert row["regime"] == "odds"


def _book(tmp_path, price, fair_value, now, success, failure, due="2027-07-01"):
    path = str(tmp_path / "g.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AAA', 'AAA')")
    conn.execute(
        "INSERT INTO model_calls (as_of, ticker, cohort, price, price_date, fair_value)"
        " VALUES ('2026-10-25', 'AAA', 'biotech', ?, '2026-10-24', ?)", (price, fair_value))
    conn.execute(
        "INSERT INTO gate_calls (as_of, ticker, asset_name, expected_date, per_share_now,"
        " per_share_success, per_share_failure, price)"
        " VALUES ('2026-10-25', 'AAA', 'X', ?, ?, ?, ?, ?)",
        (due, now, success, failure, price))
    conn.commit()
    conn.close()
    return path
