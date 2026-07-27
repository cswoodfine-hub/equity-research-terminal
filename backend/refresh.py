"""Refresh orchestration.

Creates a refresh_runs row, runs the fetchers for one company or the whole universe,
aggregates their per-source results into the run's detail JSON, and marks the run
complete or partial. Prices run for every company; EDGAR financials run for SEC
filers that have a resolved CIK. Each source honours its own TTL.

A universe refresh runs companies in parallel (fetchers stay sequential within a
company), which is what keeps a full ``scope=all`` to minutes rather than tens of them.
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import env  # noqa: F401  loads the .env before any module reads it

import biologic_loe
import catalysts
import db
import deals
import diff
import pdufa
import trial_mapping
import trial_readouts
from fetchers.adcomm_fedreg import AdCommFetcher
from fetchers.approvals_openfda import ApprovalsOpenFdaFetcher
from fetchers.demand_cms import DemandCmsFetcher
from fetchers.filing_text_edgar import FilingTextEdgarFetcher
from fetchers.exclusivity_orangebook import OrangeBookFetcher
from fetchers.exclusivity_purplebook import PurpleBookFetcher
from fetchers.filings_edgar import FilingsEdgarFetcher
from fetchers.financials_edgar import FinancialsEdgarFetcher
from fetchers.fx_ecb import FxEcbFetcher
from fetchers.labels_dailymed import LabelsDailyMedFetcher
from fetchers.news_fda import NewsFdaFetcher
from fetchers.paragraph_iv_fda import ParagraphIvFetcher
from fetchers.prices import (FiveMinuteBarsFetcher, HourlyBarsFetcher,
                             IntradayPricesFetcher, PricesFetcher)
from fetchers.product_revenue_sec import ProductRevenueFetcher
from fetchers.trials_ctgov import TrialsFetcher

DEFAULT_TICKER = "LLY"

# One worker per company in a universe refresh. Fetchers stay sequential within a
# company, so this also caps concurrent requests per host: 4 workers keeps EDGAR well
# under its 10 requests/second limit.
MAX_WORKERS = int(os.getenv("ER_TOOL_REFRESH_WORKERS", "4"))


def _company_fetchers(company, db_path):
    """Per-company sources: prices, trials, openFDA approvals for everyone; EDGAR
    financials and filings for SEC filers with a CIK."""
    fetchers = [
        PricesFetcher(company["ticker"], db_path),
        IntradayPricesFetcher(company["ticker"], db_path),
        FiveMinuteBarsFetcher(company["ticker"], db_path),
        HourlyBarsFetcher(company["ticker"], db_path),
        TrialsFetcher(company["ticker"], db_path),
        ApprovalsOpenFdaFetcher(company["ticker"], db_path),
        LabelsDailyMedFetcher(company["ticker"], db_path),
    ]
    if company["is_sec_filer"] and company["cik"]:
        fetchers.append(FinancialsEdgarFetcher(company["ticker"], db_path))
        fetchers.append(FilingsEdgarFetcher(company["ticker"], db_path))
        # Runs after the filings fetcher, which populates the 10-K/10-Q rows whose
        # documents this one reads for the risk factors and MD&A text.
        fetchers.append(FilingTextEdgarFetcher(company["ticker"], db_path))
    return fetchers


def _universe_fetchers(db_path):
    """Sources that download one file for the whole universe (LOE weekly, product
    revenue from the SEC bulk data sets which move quarterly, and the ECB daily FX
    reference set that lets the universe view convert to one display currency)."""
    return [OrangeBookFetcher(db_path), PurpleBookFetcher(db_path),
            ProductRevenueFetcher(db_path), FxEcbFetcher(db_path),
            NewsFdaFetcher(db_path), AdCommFetcher(db_path),
            ParagraphIvFetcher(db_path), DemandCmsFetcher(db_path)]


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

    # Bind the trials just fetched to the assets they study, before anything reads the
    # pipeline by product. A compound a company trials but does not sell becomes an
    # unmarketed asset first, so the pipeline reads as programmes rather than loose
    # studies. Both are idempotent, and neither overwrites a curated mapping.
    pipeline_assets = trial_mapping.derive_pipeline_assets(db_path)
    mapped = trial_mapping.map_trials(db_path)
    mapped["pipeline_assets"] = pipeline_assets["created"]
    # Derived readouts run after the trial fetch and before the diff, so a completion
    # date that moved this run is already a catalyst by the time changes are computed.
    readouts = catalysts.derive_readouts(db_path)
    goals = pdufa.extract(db_path)
    # After the filing text is on file, derive a biologic LOE for the valuation from the
    # 12-year floor and any cliff year the 10-K discloses.
    bio_loe = biologic_loe.derive(db_path)
    trial_reads = trial_readouts.extract(db_path)
    deal_reads = deals.extract(db_path)
    changes = diff.detect_changes(db_path, run_id)  # snapshot diff -> changes feed
    status = "partial" if any(r.errors for r in results) else "complete"
    detail = {"ticker": ticker, "sources": [asdict(r) for r in results],
              "readouts": readouts, "pdufa": goals, "biologic_loe": bio_loe,
              "trial_mapping": mapped,
              "trial_readouts": trial_reads, "deals": deal_reads, "changes": changes}
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
    lock = threading.Lock()

    def record(result, label):
        with lock:
            _record_locked(result, label)

    def _record_locked(result, label):
        agg = by_source.setdefault(
            result.source,
            {"source": result.source, "rows_fetched": 0, "errors": [], "notes": [],
             "skipped_ttl": 0, "ran": 0, "elapsed_ms": 0},
        )
        agg["rows_fetched"] += result.rows_fetched
        agg["ran"] += 1
        agg["skipped_ttl"] += 1 if result.skipped_ttl else 0
        agg["elapsed_ms"] += result.elapsed_ms
        agg["errors"].extend(f"{label}: {e}" for e in result.errors)
        agg["notes"].extend(f"{label}: {n}" for n in result.notes)

    # Universe downloads (Orange/Purple Book) run once for the whole universe.
    for fetcher in _universe_fetchers(db_path):
        fetcher.refresh_run_id = run_id
        record(fetcher.run(), fetcher.entity_key)

    # Companies run in parallel; each company's own fetchers stay sequential.
    def run_company(company):
        for fetcher in _company_fetchers(company, db_path):
            fetcher.refresh_run_id = run_id
            record(fetcher.run(), company["ticker"])

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        list(pool.map(run_company, companies))

    # Bind the trials just fetched to the assets they study, before anything reads the
    # pipeline by product. A compound a company trials but does not sell becomes an
    # unmarketed asset first, so the pipeline reads as programmes rather than loose
    # studies. Both are idempotent, and neither overwrites a curated mapping.
    pipeline_assets = trial_mapping.derive_pipeline_assets(db_path)
    mapped = trial_mapping.map_trials(db_path)
    mapped["pipeline_assets"] = pipeline_assets["created"]
    readouts = catalysts.derive_readouts(db_path)
    # PDUFA dates have no free calendar, so they are read out of the 8-K that announces
    # the acceptance. Without an Anthropic key this reports that it did nothing.
    goals = pdufa.extract(db_path)
    bio_loe = biologic_loe.derive(db_path)
    trial_reads = trial_readouts.extract(db_path)
    deal_reads = deals.extract(db_path)
    changes = diff.detect_changes(db_path, run_id)  # snapshot diff -> changes feed
    status = "partial" if any(s["errors"] for s in by_source.values()) else "complete"
    detail = {"scope": "all", "companies": len(companies),
              "sources": list(by_source.values()), "readouts": readouts,
              "trial_mapping": mapped,
              "pdufa": goals, "biologic_loe": bio_loe, "trial_readouts": trial_reads,
              "deals": deal_reads, "changes": changes}
    return _finish_run(db_path, run_id, status, detail)


if __name__ == "__main__":
    import sys

    arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TICKER
    result = run_refresh_all() if arg == "all" else run_refresh(ticker=arg)
    print(json.dumps(result, indent=2))
