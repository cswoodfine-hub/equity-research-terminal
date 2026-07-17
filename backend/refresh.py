"""Refresh orchestration.

Creates a refresh_runs row, runs the fetchers for a company, aggregates their
per-source results into the run's detail JSON, and marks the run complete or
partial. Phase 2 runs the prices fetcher for one ticker; later phases add more
fetchers to the list without changing this shape.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import db
from fetchers.prices import PricesFetcher

DEFAULT_TICKER = "LLY"


def run_refresh(db_path=None, ticker: str = DEFAULT_TICKER) -> dict:
    ticker = ticker.upper()
    db.init(db_path)  # ensure schema exists

    conn = db.get_connection(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO refresh_runs (started_at, status) VALUES (datetime('now'), 'running')"
        )
        run_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    fetchers = [PricesFetcher(ticker, db_path)]
    for fetcher in fetchers:
        fetcher.refresh_run_id = run_id
    results = [fetcher.run() for fetcher in fetchers]

    has_errors = any(r.errors for r in results)
    status = "partial" if has_errors else "complete"
    detail = {"ticker": ticker, "sources": [asdict(r) for r in results]}

    conn = db.get_connection(db_path)
    try:
        conn.execute(
            """
            UPDATE refresh_runs
               SET finished_at = datetime('now'), status = ?, detail = ?
             WHERE id = ?
            """,
            (status, json.dumps(detail), run_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, started_at, finished_at, status, detail FROM refresh_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()

    out = dict(row)
    out["detail"] = detail  # return parsed detail for convenience
    return out


if __name__ == "__main__":
    import sys

    result = run_refresh(ticker=sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TICKER)
    print(json.dumps(result, indent=2))
