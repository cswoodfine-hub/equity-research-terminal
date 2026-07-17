"""Refresh orchestration.

Creates a refresh_runs row, runs the fetchers for one company or the whole universe,
aggregates their per-source results into the run's detail JSON, and marks the run
complete or partial. Prices run for every company; EDGAR financials run for SEC
filers that have a resolved CIK. Each source honours its own TTL.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import db
from fetchers.financials_edgar import FinancialsEdgarFetcher
from fetchers.prices import PricesFetcher

DEFAULT_TICKER = "LLY"


def _company_fetchers(company, db_path):
    """Prices for everyone; EDGAR financials for SEC filers with a CIK."""
    fetchers = [PricesFetcher(company["ticker"], db_path)]
    if company["is_sec_filer"] and company["cik"]:
        fetchers.append(FinancialsEdgarFetcher(company["ticker"], db_path))
    return fetchers


def _start_run(db_path) -> int:
    conn = db.get_connection(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO refresh_runs (started_at, status) VALUES (datetime('now'), 'running')"
        )
        run_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return run_id


def _finish_run(db_path, run_id: int, status: str, detail: dict) -> dict:
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
    out["detail"] = detail
    return out


def run_refresh(db_path=None, ticker: str = DEFAULT_TICKER) -> dict:
    ticker = ticker.upper()
    db.init(db_path)
    run_id = _start_run(db_path)

    conn = db.get_connection(db_path)
    try:
        company = conn.execute(
            "SELECT ticker, cik, is_sec_filer FROM companies WHERE ticker = ?", (ticker,)
        ).fetchone()
    finally:
        conn.close()

    if company is None:
        detail = {"ticker": ticker, "sources": [], "errors": [f"unknown ticker {ticker}"]}
        return _finish_run(db_path, run_id, "partial", detail)

    fetchers = _company_fetchers(company, db_path)
    for fetcher in fetchers:
        fetcher.refresh_run_id = run_id
    results = [fetcher.run() for fetcher in fetchers]

    status = "partial" if any(r.errors for r in results) else "complete"
    detail = {"ticker": ticker, "sources": [asdict(r) for r in results]}
    return _finish_run(db_path, run_id, status, detail)


def run_refresh_all(db_path=None) -> dict:
    """Refresh the whole universe: prices for all, financials for SEC filers."""
    db.init(db_path)
    run_id = _start_run(db_path)

    conn = db.get_connection(db_path)
    try:
        companies = conn.execute(
            "SELECT ticker, cik, is_sec_filer FROM companies ORDER BY ticker"
        ).fetchall()
    finally:
        conn.close()

    by_source: dict[str, dict] = {}
    for company in companies:
        for fetcher in _company_fetchers(company, db_path):
            fetcher.refresh_run_id = run_id
            result = fetcher.run()
            agg = by_source.setdefault(
                result.source,
                {"source": result.source, "rows_fetched": 0, "errors": [],
                 "skipped_ttl": 0, "ran": 0, "elapsed_ms": 0},
            )
            agg["rows_fetched"] += result.rows_fetched
            agg["ran"] += 1
            agg["skipped_ttl"] += 1 if result.skipped_ttl else 0
            agg["elapsed_ms"] += result.elapsed_ms
            agg["errors"].extend(f"{company['ticker']}: {e}" for e in result.errors)

    status = "partial" if any(s["errors"] for s in by_source.values()) else "complete"
    detail = {"scope": "all", "companies": len(companies), "sources": list(by_source.values())}
    return _finish_run(db_path, run_id, status, detail)


if __name__ == "__main__":
    import sys

    arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TICKER
    result = run_refresh_all() if arg == "all" else run_refresh(ticker=arg)
    print(json.dumps(result, indent=2))
