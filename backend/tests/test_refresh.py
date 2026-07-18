"""Refresh pipeline test with the Yahoo fetch monkeypatched to a fixture. No network."""

import json
from pathlib import Path

import db
import refresh
import seed
from fetchers.approvals_openfda import ApprovalsOpenFdaFetcher
from fetchers.exclusivity_orangebook import OrangeBookFetcher
from fetchers.exclusivity_purplebook import PurpleBookFetcher
from fetchers.prices import IntradayPricesFetcher, PricesFetcher
from fetchers.trials_ctgov import TrialsFetcher

FIXTURE = Path(__file__).parent / "fixtures" / "yahoo_chart_lly.json"


def _prices_source(run):
    return next(s for s in run["detail"]["sources"] if s["source"] == "prices")


def _snapshot_kind_counts(conn, ticker):
    rows = conn.execute(
        """
        SELECT json_extract(payload, '$.fetch_kind') AS kind, COUNT(*) AS n
          FROM snapshots
         WHERE source = 'prices' AND entity_key = ?
         GROUP BY kind
        """,
        (ticker,),
    ).fetchall()
    return {r["kind"]: r["n"] for r in rows}


def test_refresh_populates_then_skips_within_ttl(tmp_path, monkeypatch):
    payload = json.loads(FIXTURE.read_text())
    # Return fixtures instead of hitting the network; keeps the test offline. The
    # refresh also runs the trials fetcher, so stub it with an empty result.
    monkeypatch.setattr(PricesFetcher, "fetch", lambda self: payload)
    monkeypatch.setattr(IntradayPricesFetcher, "fetch", lambda self: payload)
    monkeypatch.setattr(TrialsFetcher, "fetch", lambda self: {"studies": []})
    monkeypatch.setattr(ApprovalsOpenFdaFetcher, "fetch", lambda self: {"results": []})

    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)

    # First refresh: live fetch populates prices and writes a live snapshot.
    first = refresh.run_refresh(db_file, "LLY")
    assert first["status"] == "complete"
    src = _prices_source(first)
    assert src["rows_fetched"] == 124
    assert src["skipped_ttl"] is False

    conn = db.get_connection(db_file)
    try:
        # Scoped to the daily series: the intraday fetcher writes its own bars,
        # and the two must never be counted or charted together.
        assert conn.execute(
            "SELECT COUNT(*) FROM prices WHERE interval = '1d'"
        ).fetchone()[0] == 124
        assert _snapshot_kind_counts(conn, "LLY") == {"live": 1}
    finally:
        conn.close()

    # Second refresh within the TTL: skipped, no new rows, a cache snapshot added.
    second = refresh.run_refresh(db_file, "LLY")
    src2 = _prices_source(second)
    assert src2["skipped_ttl"] is True
    assert src2["rows_fetched"] == 0

    conn = db.get_connection(db_file)
    try:
        # Scoped to the daily series: the intraday fetcher writes its own bars,
        # and the two must never be counted or charted together.
        assert conn.execute(
            "SELECT COUNT(*) FROM prices WHERE interval = '1d'"
        ).fetchone()[0] == 124
        assert _snapshot_kind_counts(conn, "LLY") == {"live": 1, "cache": 1}
    finally:
        conn.close()


def test_refresh_all_runs_companies_in_parallel_without_losing_results(tmp_path,
                                                                      monkeypatch):
    """The thread pool must aggregate exactly once per company, not lose or double."""
    payload = json.loads(FIXTURE.read_text())
    monkeypatch.setattr(PricesFetcher, "fetch", lambda self: payload)
    monkeypatch.setattr(IntradayPricesFetcher, "fetch", lambda self: payload)
    monkeypatch.setattr(TrialsFetcher, "fetch", lambda self: {"studies": []})
    monkeypatch.setattr(ApprovalsOpenFdaFetcher, "fetch", lambda self: {"results": []})
    monkeypatch.setattr(OrangeBookFetcher, "fetch",
                        lambda self: {"products": "", "patents": "", "exclusivity": ""})
    monkeypatch.setattr(PurpleBookFetcher, "fetch", lambda self: {"csvs": []})

    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)

    conn = db.get_connection(db_file)
    try:
        n_companies = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    finally:
        conn.close()

    run = refresh.run_refresh_all(db_file)
    prices = _prices_source(run)
    # Every company ran exactly once and every row landed.
    assert prices["ran"] == n_companies
    assert prices["rows_fetched"] == 124 * n_companies
    assert prices["errors"] == []

    conn = db.get_connection(db_file)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM prices WHERE interval = '1d'"
        ).fetchone()[0] == 124 * n_companies
    finally:
        conn.close()
