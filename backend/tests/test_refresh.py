"""Refresh pipeline test with the Yahoo fetch monkeypatched to a fixture. No network."""

import json
from pathlib import Path

import db
import refresh
import seed
from fetchers.approvals_openfda import ApprovalsOpenFdaFetcher
from fetchers.deals_news import DealsNewsFetcher
from fetchers.exclusivity_orangebook import OrangeBookFetcher
from fetchers.exclusivity_purplebook import PurpleBookFetcher
from fetchers.prices import IntradayPricesFetcher, PricesFetcher
from fetchers.ndc_marketing import NdcMarketingFetcher
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
    monkeypatch.setattr(DealsNewsFetcher, "fetch",
                        lambda self: {"feeds": {}, "companies": [], "errors": []})
    # The NDC register is the one fetcher this test still reached the network for, and
    # openFDA rate-limits it: the run came back partial on an HTTP 429 that has nothing
    # to do with what the test asserts.
    monkeypatch.setattr(NdcMarketingFetcher, "fetch", lambda self: {"results": []})

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
    monkeypatch.setattr(DealsNewsFetcher, "fetch",
                        lambda self: {"feeds": {}, "companies": [], "errors": []})
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


def test_a_forced_run_ignores_the_ttl(tmp_path):
    """A rebuilt database carries snapshots saying every source was fetched today,
    while the data those fetches produced is not in the export. A scheduled run that
    honoured that would publish a database with almost nothing in it, which is what
    happened: five runs finished 'complete' in forty seconds each."""
    from fetchers.base import BaseFetcher

    class Probe(BaseFetcher):
        source = "probe"
        ttl_seconds = 86_400

        @property
        def entity_key(self):
            return "universe"

        def fetch(self):
            return []

        def normalise(self, raw):
            return []

        def snapshot(self, rows):
            pass

        def upsert(self, rows):
            pass

        def _snapshot_cache(self):
            pass

        def _last_live_fetch_at(self):        # as if history had just been restored
            import datetime as dt
            return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    probe = Probe(str(tmp_path / "t.db"))
    assert probe._within_ttl() is True         # an ordinary run would skip
    probe.force = True
    assert probe._within_ttl() is False        # a scheduled run fetches


def test_the_scheduled_job_runs_with_no_arguments(monkeypatch):
    """The default refresh callable is invoked with no arguments when the database is
    the default one, which is every scheduled run. A callable that required a path
    raised TypeError inside the catch-all and the job exited 2 in eighteen seconds."""
    import refresh as refresh_module
    import scheduled_refresh

    seen = {}

    def fake_run_refresh_all(db_path=None, force=False):
        seen["db_path"], seen["force"] = db_path, force
        return {"id": 1, "status": "complete", "detail": {"changes": {}}}

    monkeypatch.setattr(refresh_module, "run_refresh_all", fake_run_refresh_all)
    monkeypatch.setattr(scheduled_refresh, "LOCK_FILE",
                        scheduled_refresh.LOCK_FILE.parent / "test.lock")
    assert scheduled_refresh.run() == 0
    assert seen == {"db_path": None, "force": True}
