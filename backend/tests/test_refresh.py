"""Refresh pipeline test with the Yahoo fetch monkeypatched to a fixture. No network."""

import json
from pathlib import Path

import db
import refresh
import seed
from fetchers.prices import PricesFetcher

FIXTURE = Path(__file__).parent / "fixtures" / "yahoo_chart_lly.json"


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
    # Return the fixture instead of hitting Yahoo; keeps the test offline.
    monkeypatch.setattr(PricesFetcher, "fetch", lambda self: payload)

    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)

    # First refresh: live fetch populates prices and writes a live snapshot.
    first = refresh.run_refresh(db_file, "LLY")
    assert first["status"] == "complete"
    src = first["detail"]["sources"][0]
    assert src["rows_fetched"] == 124
    assert src["skipped_ttl"] is False

    conn = db.get_connection(db_file)
    try:
        assert conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0] == 124
        assert _snapshot_kind_counts(conn, "LLY") == {"live": 1}
    finally:
        conn.close()

    # Second refresh within the TTL: skipped, no new rows, a cache snapshot added.
    second = refresh.run_refresh(db_file, "LLY")
    src2 = second["detail"]["sources"][0]
    assert src2["skipped_ttl"] is True
    assert src2["rows_fetched"] == 0

    conn = db.get_connection(db_file)
    try:
        assert conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0] == 124
        assert _snapshot_kind_counts(conn, "LLY") == {"live": 1, "cache": 1}
    finally:
        conn.close()
