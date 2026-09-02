"""An rNPV in the accounts' currency, read against a price quoted in dollars.

Sanofi keeps its books in euro and its depositary share trades in New York at half an
ordinary share. Dividing the euro rNPV by ordinary shares got both of those wrong at
once and put 61 next to a price of 44, a number that looked like an answer and was not
comparable to anything. Two conversions stand between an rNPV and the price, and the
per-share divisor carries both.
"""

import db
import forecast_view

MM = 1e6


def _company(tmp_path, ticker, currency, *, shares, per_adr=None, rate=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = str(tmp_path / f"{ticker}.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name, reporting_currency)"
                 " VALUES (1, ?, ?, ?)", (ticker, ticker, currency))
    conn.execute(
        "INSERT INTO financials (company_id, period_end, period_type, metric, value,"
        " unit, fiscal_year, fiscal_period) VALUES (1, '2025-12-31', 'FY',"
        " 'WeightedAverageDilutedShares', ?, 'shares', 2025, 'FY')", (shares,))
    # A fresh database already carries the shipped ratios and rates, so the test states
    # its own rather than adding to them.
    conn.execute("DELETE FROM adr_ratios WHERE ticker = ?", (ticker,))
    conn.execute("DELETE FROM fx_rates WHERE base = ?", (currency,))
    if per_adr is not None:
        conn.execute("INSERT INTO adr_ratios (ticker, ordinary_per_adr) VALUES (?, ?)",
                     (ticker, per_adr))
    if rate is not None:
        conn.execute("INSERT INTO fx_rates (base, quote, rate, as_of)"
                     " VALUES (?, 'USD', ?, '2026-09-01')", (currency, rate))
    conn.commit()
    return conn


def test_a_dollar_filer_divides_by_its_own_shares(tmp_path):
    conn = _company(tmp_path / "usd", "VRTX", "USD", shares=258e6)
    assert forecast_view._diluted_shares(conn, 1) == 258e6


def test_a_euro_rnpv_is_read_against_the_dollar_price(tmp_path):
    """Sanofi: 1,219mm ordinary shares, two to the ADS, euro worth 1.159 dollars. An
    rNPV of 74,881mm euro is 35.59 dollars a share, not 61.41 euro of nothing."""
    conn = _company(tmp_path / "eur", "SNY", "EUR",
                    shares=1_219_427_096, per_adr=0.5, rate=1.159)
    divisor = forecast_view._diluted_shares(conn, 1)
    assert round(74_881 * MM / divisor, 2) == 35.59


def test_the_depositary_ratio_runs_both_ways(tmp_path):
    """GSK's ADS is two ordinary shares and AstraZeneca's is half of one, so the same
    mistake overstates one company and understates the other."""
    gsk = forecast_view._diluted_shares(
        _company(tmp_path / "gbp", "GSK", "GBP",
                 shares=4_315_445_026, per_adr=2.0, rate=1.0), 1)
    azn = forecast_view._diluted_shares(
        _company(tmp_path / "azn", "AZN", "USD",
                 shares=1_564_678_899, per_adr=0.5), 1)
    assert round(gsk) == 2_157_722_513
    assert round(azn) == 3_129_357_798


def test_a_rate_that_is_not_on_file_gives_no_per_share_figure(tmp_path):
    """An rNPV in kroner divided by shares is not a figure in dollars, and printing it
    beside a dollar price would be worse than printing nothing."""
    conn = _company(tmp_path / "dkk", "NVO", "DKK", shares=4_447_850_630, per_adr=1.0)
    assert forecast_view._diluted_shares(conn, 1) is None
