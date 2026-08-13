"""The street feed: FMP's annual analyst estimates, kept as revisions.

The fixture is built from the field names FMP's ``stable/analyst-estimates`` response
documents rather than captured from a live call, because this checkout has no key. When
one lands, replace it with the real payload and this file will say whether the shapes
still agree.

Two behaviours matter more than the mapping. A figure that has not moved does not earn a
row, so the table holds the street's changes of mind rather than a daily photocopy. And
without a key the fetcher never runs at all: the registry gates on it, so an unkeyed
checkout does not spend seventy fetchers reporting that they have nothing to read.
"""

import datetime as dt
import json
import pathlib

import db
import refresh
from fetchers.consensus_fmp import ConsensusFmpFetcher

FIXTURE = json.loads(
    (pathlib.Path(__file__).parent / "fixtures"
     / "fmp_analyst_estimates_vrtx.json").read_text())


def _seed(tmp_path):
    path = str(tmp_path / "f.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'VRTX', 'Vertex')")
    conn.commit()
    conn.close()
    return path


def _raw(records=FIXTURE):
    return {"company": {"id": 1, "ticker": "VRTX", "us_adr_ticker": None},
            "records": records}


def _rows(path):
    conn = db.get_connection(path)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM consensus_estimates ORDER BY period, metric, as_of")]
    finally:
        conn.close()


def test_a_record_becomes_one_row_per_metric_with_its_year(tmp_path):
    fetcher = ConsensusFmpFetcher("VRTX", _seed(tmp_path))
    rows = fetcher.normalise(_raw())
    revenue = next(r for r in rows if r["period"] == "FY2026"
                   and r["metric"] == "Revenue")
    assert (revenue["value"], revenue["low"], revenue["high"]) == (
        12650000000.0, 12400000000, 12900000000)
    assert revenue["note"] == "27 analysts" and revenue["currency"] == "USD"
    eps = next(r for r in rows if r["period"] == "FY2027" and r["metric"] == "EPS")
    assert eps["value"] == 17.5


def test_a_metric_the_feed_leaves_empty_is_absent_rather_than_zero(tmp_path):
    fetcher = ConsensusFmpFetcher("VRTX", _seed(tmp_path))
    rows = fetcher.normalise(_raw())
    assert not [r for r in rows if r["period"] == "FY2028" and r["metric"] == "Revenue"]
    assert [r for r in rows if r["period"] == "FY2028" and r["metric"] == "EPS"]


def test_only_a_changed_figure_earns_a_row(tmp_path):
    path = _seed(tmp_path)
    fetcher = ConsensusFmpFetcher("VRTX", path)
    rows = fetcher.normalise(_raw())
    first = fetcher.upsert(rows)
    assert first.rows_fetched == len(rows)
    # The same numbers again are not a revision.
    assert fetcher.upsert(rows).rows_fetched == 0
    assert len(_rows(path)) == len(rows)


def test_a_revision_is_written_beside_the_figure_it_replaces(tmp_path):
    path = _seed(tmp_path)
    fetcher = ConsensusFmpFetcher("VRTX", path)
    fetcher.upsert(fetcher.normalise(_raw()))
    conn = db.get_connection(path)
    conn.execute("UPDATE consensus_estimates SET as_of = '2026-01-05'")
    conn.commit()
    conn.close()

    moved = json.loads(json.dumps(FIXTURE))
    moved[1]["revenueAvg"] = 12900000000
    written = fetcher.upsert(fetcher.normalise(_raw(moved)))
    assert written.rows_fetched == 1
    history = [r for r in _rows(path)
               if r["period"] == "FY2026" and r["metric"] == "Revenue"]
    assert [r["value"] for r in history] == [12650000000.0, 12900000000.0]
    assert history[-1]["as_of"] == dt.date.today().isoformat()


def test_without_a_key_the_fetcher_reports_rather_than_writes(tmp_path):
    path = _seed(tmp_path)
    fetcher = ConsensusFmpFetcher("VRTX", path)
    assert fetcher.normalise(_raw(None)) == []
    result = fetcher.upsert([])
    assert result.rows_fetched == 0 and result.errors == []
    assert "no FMP key" in result.notes[0]
    assert _rows(path) == []


def test_the_registry_runs_this_fetcher_only_where_a_key_exists(tmp_path, monkeypatch):
    path = _seed(tmp_path)
    company = {"ticker": "VRTX", "ir_rss_url": None, "ir_news_url": None,
               "is_sec_filer": 0, "cik": None}

    monkeypatch.setenv("FMP_API_KEY", "")
    assert not [f for f in refresh._company_fetchers(company, path)
                if isinstance(f, ConsensusFmpFetcher)]

    monkeypatch.setenv("FMP_API_KEY", "a-key")
    assert [f for f in refresh._company_fetchers(company, path)
            if isinstance(f, ConsensusFmpFetcher)]
