"""The consensus layer: reported, guidance, street and mine read off one table.

Two rules carry the whole module. Revisions accumulate as rows and the reader takes the
newest per source, so the history stays queryable without ever being shown by accident.
And a curated seed is insert-only, so a live revision beats the file it started from.
"""

import consensus
import db


def _seed(tmp_path, ticker="VRTX", currency="USD"):
    path = str(tmp_path / "c.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name, reporting_currency)"
                 " VALUES (1, ?, 'Vertex', ?)", (ticker, currency))
    conn.commit()
    return path, conn


def _estimate(conn, **kw):
    row = {"company_id": 1, "metric": "Revenue", "period": "FY2026", "value": None,
           "low": None, "high": None, "currency": "USD", "source": "fmp",
           "as_of": "2026-01-01", "note": None}
    row.update(kw)
    conn.execute(
        """INSERT INTO consensus_estimates (company_id, metric, period, value, low,
               high, currency, source, as_of, note)
           VALUES (:company_id, :metric, :period, :value, :low, :high, :currency,
                   :source, :as_of, :note)""", row)
    conn.commit()


def test_the_reader_takes_the_newest_revision_and_keeps_the_older_one(tmp_path):
    path, conn = _seed(tmp_path)
    _estimate(conn, value=12.0e9, as_of="2026-01-01")
    _estimate(conn, value=12.6e9, as_of="2026-04-01")
    latest = consensus.latest(conn, 1)
    assert [row["value"] for row in latest] == [12.6e9]
    # The revision is still on file; only the reader is opinionated about which shows.
    stored = conn.execute("SELECT COUNT(*) FROM consensus_estimates").fetchone()[0]
    assert stored == 2
    conn.close()


def test_each_source_keeps_its_own_newest_row(tmp_path):
    path, conn = _seed(tmp_path)
    _estimate(conn, value=12.6e9, source="fmp", as_of="2026-04-01")
    _estimate(conn, value=13.1e9, source="guidance", as_of="2026-02-01")
    by_source = {row["source"]: row["value"] for row in consensus.latest(conn, 1)}
    assert by_source == {"fmp": 12.6e9, "guidance": 13.1e9}
    conn.close()


def test_street_view_puts_the_sources_side_by_side(tmp_path):
    path, conn = _seed(tmp_path)
    _estimate(conn, value=12.6e9, source="fmp", as_of="2026-04-01")
    _estimate(conn, value=13.1e9, low=13.0e9, high=13.2e9, source="guidance",
              as_of="2026-02-01", note="we expect revenue of 13.0 to 13.2 billion")
    conn.close()
    view = consensus.street_view(path, "VRTX")
    row = next(r for r in view["rows"] if r["period"] == "FY2026")
    assert row["street"]["value"] == 12.6e9
    assert row["guidance"]["value"] == 13.1e9
    assert row["guidance"]["note"].startswith("we expect revenue")
    # Guidance above street, stated as the delta an analyst would quote.
    assert abs(row["guidance_vs_street"] - (13.1 / 12.6 - 1.0)) < 1e-9


def test_a_filers_own_currency_travels_with_a_usd_conversion(tmp_path):
    path, conn = _seed(tmp_path, ticker="NVO", currency="DKK")
    conn.execute("INSERT INTO financials (company_id, metric, period_type,"
                 " fiscal_year, period_end, value, unit) VALUES"
                 " (1, 'Revenues', 'FY', 2025, '2025-12-31', 309064000000.0, 'DKK')")
    conn.execute("INSERT INTO fx_rates (base, quote, rate, as_of)"
                 " VALUES ('DKK', 'USD', 0.15, '2026-08-01')")
    _estimate(conn, company_id=1, period="FY2026", value=8.0, high=14.0, low=2.0,
              metric="RevenueGrowth", currency=None, source="guidance",
              as_of="2026-08-06", note="sales growth of 2 to 14 percent")
    conn.close()
    view = consensus.street_view(path, "NVO")
    reported = next(r for r in view["rows"]
                    if r["period"] == "FY2025" and r["reported"])["reported"]
    assert reported["unit"] == "DKK"
    assert abs(reported["usd_value"] - 309064000000.0 * 0.15) < 1.0
    # Growth is its own metric rather than an amount derived off a base the company
    # never used, so nothing tries to convert it.
    growth = next(r for r in view["rows"] if r["metric"] == "RevenueGrowth")
    assert growth["guidance"]["low"] == 2.0 and growth["guidance"]["high"] == 14.0


def test_mine_is_absent_without_a_forecast_and_names_its_assets_with_one(tmp_path):
    path, conn = _seed(tmp_path)
    _estimate(conn, value=12.6e9, source="fmp", as_of="2026-04-01")
    conn.close()
    view = consensus.street_view(path, "VRTX")
    assert view["mine_lines"] == []
    assert all(row["mine"] is None for row in view["rows"])


def test_an_unknown_ticker_is_none_rather_than_an_empty_view(tmp_path):
    path, _conn = _seed(tmp_path)
    _conn.close()
    assert consensus.street_view(path, "ZZZZ") is None


def test_seeds_load_once_and_never_overwrite_a_live_revision(tmp_path):
    path, conn = _seed(tmp_path)
    directory = tmp_path / "seeds"
    directory.mkdir()
    (directory / "manual.csv").write_text(
        "# a comment line the loader skips\n"
        "ticker,metric,period,value,low,high,currency,source,as_of,note\n"
        "VRTX,Revenue,FY2026,12050000000,11900000000,12200000000,USD,manual,"
        "2026-08-11,desk note\n"
        "ZZZZ,Revenue,FY2026,1,,,USD,manual,2026-08-11,unknown ticker\n",
        encoding="utf-8")
    first = consensus.load_seeds(conn, directory)
    assert first == {"written": 1, "skipped": 1}
    # Re-running writes nothing: the row is already there, and the file is a starting
    # point rather than a source of truth.
    assert consensus.load_seeds(conn, directory)["written"] == 0
    _estimate(conn, value=12.4e9, source="manual", as_of="2026-08-20")
    consensus.load_seeds(conn, directory)
    row = next(r for r in consensus.latest(conn, 1) if r["source"] == "manual")
    assert row["value"] == 12.4e9
    conn.close()


def test_a_missing_seed_directory_is_not_an_error(tmp_path):
    path, conn = _seed(tmp_path)
    assert consensus.load_seeds(conn, tmp_path / "nothing") == {"written": 0,
                                                                "skipped": 0}
    conn.close()
