"""The discount rate reads the market, and says which day's market it read.

Every rate in the book was hand-read on one day and written into 382 rows. The row's
own source claimed it was refreshed with the data, and it was not: the ten-year was
4.66% when the book was built and 5.01% seven weeks later. These pin the override that
makes the claim true, and the fallback that keeps an unfetched database working.
"""

import pytest

import assumptions
import company_lines
import db
import forecast
from fetchers import rates_fred


def _db(tmp_path, name="live.db"):
    path = str(tmp_path / name)
    db.init(path)
    rates_fred.clear_cache()
    return path


def _capm(conn, asset_id):
    assumptions.save(conn, asset_id, [
        {"key": k, "value": v, "text_value": None, "source": s}
        for k, v, s in (("risk_free", 0.0466, "hand-read on the day the book was built"),
                        ("erp", 0.0414, "Damodaran, 2026-09-01"),
                        ("beta", 0.69, "computed weekly against the S&P"),
                        ("cost_of_debt", 0.0540, "hand-read on the day"),
                        ("debt_weight", 0.05, "filed debt over debt plus market cap"),
                        ("tax_rate", 0.16, "filed"))])
    conn.commit()


def _rates(path, *rows):
    conn = db.get_connection(path)
    for series, as_of, value in rows:
        conn.execute("INSERT INTO market_rates (series, as_of, value, source)"
                     " VALUES (?, ?, ?, 'fred')", (series, as_of, value))
    conn.commit()
    conn.close()
    rates_fred.clear_cache()


def test_the_seeded_rate_stands_where_nothing_has_been_fetched(tmp_path):
    """Every test database has an empty market_rates, and so does a fresh install.
    The seed is the fallback, not the source, and the book still values without it."""
    path = _db(tmp_path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AMGN', 'Amgen')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Repatha', 1)")
    _capm(conn, 1)
    scalars = assumptions.load(conn, 1)["scalars"]
    conn.close()
    assert scalars["risk_free"] == pytest.approx(0.0466)
    assert scalars["cost_of_debt"] == pytest.approx(0.0540)
    assert "risk_free_as_of" not in scalars
    assert "cost_of_debt_as_of" not in scalars
    # The basis names no fetched series, because none was read. The premium still
    # dates itself, since its own source says when it was struck.
    basis = forecast.wacc(scalars)[1]
    assert "DGS10" not in basis and "BAMLC0A3CAEY" not in basis
    assert basis == "CAPM from components, premium 2026-09-01"
    # No fetched leg, so no "on rates to" clause to mislead anyone.
    assert "on rates to" not in basis


def test_the_fetched_rate_replaces_the_seeded_one_and_dates_itself(tmp_path):
    path = _db(tmp_path, "live2.db")
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AMGN', 'Amgen')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Repatha', 1)")
    _capm(conn, 1)
    conn.close()
    _rates(path, ("DGS10", "2026-09-18", 0.0501),
                 ("BAMLC0A3CAEY", "2026-09-18", 0.0559))

    conn = db.get_connection(path)
    scalars = assumptions.load(conn, 1)["scalars"]
    conn.close()
    assert scalars["risk_free"] == pytest.approx(0.0501)
    assert scalars["risk_free_as_of"] == "2026-09-18"
    assert scalars["risk_free_series"] == "DGS10"
    assert scalars["cost_of_debt"] == pytest.approx(0.0559)
    assert scalars["cost_of_debt_series"] == "BAMLC0A3CAEY"

    rate, basis = forecast.wacc(scalars)
    ke = 0.0501 + 0.69 * 0.0414
    kd = 0.0559 * (1 - 0.16)
    assert rate == pytest.approx(0.95 * ke + 0.05 * kd)
    assert "risk-free DGS10 2026-09-18" in basis
    assert "cost of debt BAMLC0A3CAEY 2026-09-18" in basis


def test_the_premium_is_never_taken_from_a_market_series(tmp_path):
    """It is a published estimate refreshed monthly, not a rate anyone quotes. Nothing
    fetched stands in for it, so no series can silently become the premium."""
    assert "erp" not in assumptions.LIVE_RATES
    assert set(assumptions.LIVE_RATES) == {"risk_free", "cost_of_debt"}


def test_a_leg_the_product_does_not_carry_is_not_invented(tmp_path):
    """A missing row is a gap in the model. Filling it from a market series would
    value a product the engine should be refusing to value."""
    path = _db(tmp_path, "live3.db")
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AMGN', 'Amgen')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Repatha', 1)")
    assumptions.save(conn, 1, [{"key": "beta", "value": 0.69, "text_value": None,
                                "source": "computed"}])
    conn.close()
    _rates(path, ("DGS10", "2026-09-18", 0.0501))

    conn = db.get_connection(path)
    scalars = assumptions.load(conn, 1)["scalars"]
    conn.close()
    assert "risk_free" not in scalars
    assert forecast.wacc(scalars) == (None, None)


def test_a_line_reads_the_same_rate_as_the_product_beside_it(tmp_path):
    """All 58 line rows carry the same CAPM legs. A line discounting at the rate
    somebody typed while the product beside it discounts at the market's would put two
    rates inside one sum of the parts."""
    path = _db(tmp_path, "live4.db")
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'SNY', 'Sanofi')")
    for key, value in (("risk_free", 0.0466), ("cost_of_debt", 0.0540),
                       ("erp", 0.0414), ("beta", 0.69), ("debt_weight", 0.05)):
        conn.execute("INSERT INTO company_lines (company_id, line, scenario, key, value,"
                     " source) VALUES (1, 'Consumer health', 'base', ?, ?, 'seeded')",
                     (key, value))
    conn.commit()
    conn.close()
    _rates(path, ("DGS10", "2026-09-18", 0.0501),
                 ("BAMLC0A3CAEY", "2026-09-18", 0.0559))

    conn = db.get_connection(path)
    line = company_lines.load(conn, 1)[0]
    conn.close()
    assert line["scalars"]["risk_free"] == pytest.approx(0.0501)
    assert line["scalars"]["risk_free_as_of"] == "2026-09-18"
    assert line["scalars"]["cost_of_debt"] == pytest.approx(0.0559)


def test_the_newest_observation_wins_and_the_date_follows_it(tmp_path):
    path = _db(tmp_path, "live5.db")
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AMGN', 'Amgen')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Repatha', 1)")
    _capm(conn, 1)
    conn.close()
    _rates(path, ("DGS10", "2026-09-15", 0.0490), ("DGS10", "2026-09-18", 0.0501))

    conn = db.get_connection(path)
    scalars = assumptions.load(conn, 1)["scalars"]
    conn.close()
    assert scalars["risk_free"] == pytest.approx(0.0501)
    assert scalars["risk_free_as_of"] == "2026-09-18"


def test_a_legs_vintage_is_read_out_of_its_own_source(tmp_path):
    """Read from the source text rather than a column, because the seed CSVs have no
    date column and a value rebuilt from seed must carry the same vintage as one
    restated in place. One string to edit, so the date and the citation cannot drift."""
    assert assumptions.dated("Damodaran implied US equity risk premium, 2026-09-01: "
                             "4.14%") == "2026-09-01"
    assert assumptions.dated("Damodaran US ERP estimate") is None
    assert assumptions.dated(None) is None
    assert assumptions.dated("") is None


def test_the_three_legs_carry_three_different_dates(tmp_path):
    """The whole point of naming vintages. Two legs are the market's on the day they
    were fetched and one is a published estimate refreshed monthly, so a reader
    comparing two discount rates has to be able to see which is which."""
    path = _db(tmp_path, "vintage.db")
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AMGN', 'Amgen')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Repatha', 1)")
    assumptions.save(conn, 1, [
        {"key": k, "value": v, "text_value": None, "source": s}
        for k, v, s in (
            ("risk_free", 0.0466, "FRED DGS10, 2026-08-01"),
            ("erp", 0.0414, "Damodaran implied US equity risk premium, 2026-09-01"),
            ("beta", 0.69, "computed weekly against the S&P"),
            ("cost_of_debt", 0.0540, "FRED BAMLC0A3CAEY, 2026-08-01"),
            ("debt_weight", 0.05, "filed"), ("tax_rate", 0.16, "filed"))])
    conn.commit()
    conn.close()
    _rates(path, ("DGS10", "2026-09-18", 0.0501),
                 ("BAMLC0A3CAEY", "2026-09-18", 0.0559))

    conn = db.get_connection(path)
    scalars = assumptions.load(conn, 1)["scalars"]
    conn.close()
    # The two fetched legs take the fetched date; the premium keeps its own.
    assert scalars["risk_free_as_of"] == "2026-09-18"
    assert scalars["cost_of_debt_as_of"] == "2026-09-18"
    assert scalars["erp_as_of"] == "2026-09-01"
    basis = forecast.wacc(scalars)[1]
    assert "risk-free DGS10 2026-09-18" in basis
    assert "premium 2026-09-01" in basis
    # The freshest fetched date leads, because the UI shows the first clause only.
    assert basis.split(",")[0] == "CAPM from components on rates to 2026-09-18"


def test_the_committed_seeds_carry_a_dated_premium_and_no_round_number():
    """440 rows held 0.05 sourced "Damodaran US ERP estimate". His estimate is not 0.05
    and matches none of his five published variants, so the row named an author and
    did not carry his number."""
    import csv
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "data"
    seen = 0
    for folder in ("assumptions", "company_lines"):
        for path in sorted((root / folder).glob("*.csv")):
            with open(path, encoding="utf-8", newline="") as handle:
                lines = [l for l in handle.read().splitlines()
                         if l.strip() and not l.startswith("#")]
            if not lines:
                continue
            header = next(csv.reader([lines[0]]))
            if "key" not in header:
                continue
            ik, iv, isrc = (header.index("key"), header.index("value"),
                            header.index("source"))
            for line in lines[1:]:
                row = next(csv.reader([line]))
                if len(row) <= ik or row[ik] != "erp":
                    continue
                seen += 1
                assert row[iv] == "0.0414", f"{path.name} still holds {row[iv]}"
                assert assumptions.dated(row[isrc]) == "2026-09-01", path.name
                # The variant is named, so the choice among his five is visible.
                assert "trailing twelve month" in row[isrc], path.name
    assert seen == 519        # 473, then seven Roche Phase 3 seeds, Elahere, Moderna's intismeran, five Lilly Phase 3 seeds, five more Phase 3 seeds (Sanofi, Pfizer, GSK) and thirteen more (GSK, Novartis, Pfizer, Sanofi), then dazodalibep, seltorexant, zenagamtide, BMS-986489, rilvegostomig, cemdisiran, BMS-986353, povorcitinib, XL092, etavopivat, balcinrenone/dapagliflozin, empasiprubart, INCA033989, ziltivekimab, all 2026-09-24
