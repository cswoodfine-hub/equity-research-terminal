"""FastAPI app: health, company list, price history, and refresh.

The frontend is a thin client over these JSON endpoints. Phase 2 wires the prices
source end to end for one company; the refresh endpoint runs the real fetcher.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

import comps as comps_module
import db
import pipeline as pipeline_module
import refresh as refresh_module

try:  # optional local .env, mirrors seed.py
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure the schema exists so a fresh checkout can serve immediately.
    db.init()
    yield


app = FastAPI(title="Pharma equity research terminal", version="0.2.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/companies")
def list_companies() -> list[dict]:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT ticker, name, primary_exchange, country, reporting_currency,
                   cik, is_sec_filer
              FROM companies
             ORDER BY ticker
            """
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


@app.get("/companies/{ticker}/prices")
def company_prices(ticker: str) -> dict:
    ticker = ticker.upper()
    conn = db.get_connection()
    try:
        company = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (ticker,)
        ).fetchone()
        if company is None:
            raise HTTPException(status_code=404, detail=f"unknown ticker {ticker}")

        points = [
            dict(r)
            for r in conn.execute(
                "SELECT as_of, close FROM prices WHERE company_id = ? ORDER BY as_of",
                (company["id"],),
            )
        ]
        snap = conn.execute(
            """
            SELECT payload FROM snapshots
             WHERE source = 'prices' AND entity_key = ?
               AND json_extract(payload, '$.currency') IS NOT NULL
             ORDER BY captured_at DESC LIMIT 1
            """,
            (ticker,),
        ).fetchone()
        last_fetch_at = conn.execute(
            """
            SELECT MAX(captured_at) FROM snapshots
             WHERE source = 'prices' AND entity_key = ?
               AND json_extract(payload, '$.fetch_kind') = 'live'
            """,
            (ticker,),
        ).fetchone()[0]
    finally:
        conn.close()

    meta = json.loads(snap["payload"]) if snap else {}
    latest = None
    if points:
        latest = {
            "as_of": points[-1]["as_of"],
            "close": points[-1]["close"],
            "market_cap": meta.get("market_cap"),  # null this phase
        }
    return {
        "ticker": ticker,
        "currency": meta.get("currency"),
        "latest": latest,
        "points": points,
        "last_fetch_at": last_fetch_at,
    }


@app.get("/companies/{ticker}/financials")
def company_financials(ticker: str) -> dict:
    ticker = ticker.upper()
    conn = db.get_connection()
    try:
        company = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (ticker,)
        ).fetchone()
        if company is None:
            raise HTTPException(status_code=404, detail=f"unknown ticker {ticker}")
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT metric, period_end, period_type, value, unit, fiscal_year
                  FROM financials
                 WHERE company_id = ?
                 ORDER BY metric, period_end
                """,
                (company["id"],),
            )
        ]
    finally:
        conn.close()
    return {"ticker": ticker, "rows": rows}


@app.get("/comps")
def comps() -> list[dict]:
    return comps_module.build_comps()


@app.get("/pipeline")
def pipeline() -> list[dict]:
    return pipeline_module.build_pipeline()


@app.get("/companies/{ticker}/trials")
def company_trials(ticker: str, phase: Optional[str] = Query(default=None)) -> dict:
    rows = pipeline_module.trials_for(None, ticker, phase)
    if rows is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker.upper()}")
    return {"ticker": ticker.upper(), "phase": phase, "trials": rows}


@app.post("/refresh")
def refresh(
    ticker: str = Query(default=refresh_module.DEFAULT_TICKER),
    scope: Optional[str] = Query(default=None),
) -> dict:
    """Refresh one company, or the whole universe with ?scope=all."""
    if scope == "all":
        return refresh_module.run_refresh_all()
    return refresh_module.run_refresh(ticker=ticker)
