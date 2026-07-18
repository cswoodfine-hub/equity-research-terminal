"""FastAPI app: health, company list, price history, and refresh.

The frontend is a thin client over these JSON endpoints. Phase 2 wires the prices
source end to end for one company; the refresh endpoint runs the real fetcher.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

import catalysts as catalysts_module
import comps as comps_module
import db
import loe as loe_module
import pipeline as pipeline_module
import refresh as refresh_module
import whatchanged as whatchanged_module

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


@app.get("/loe")
def loe() -> dict:
    return loe_module.build_loe()


@app.get("/companies/{ticker}/exclusivities")
def company_exclusivities(ticker: str) -> dict:
    rows = loe_module.loe_detail(None, ticker)
    if rows is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker.upper()}")
    return {"ticker": ticker.upper(), "assets": rows}


@app.get("/companies/{ticker}/approvals")
def company_approvals(ticker: str) -> dict:
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
                SELECT ap.approval_date, ap.application_number, a.brand_name, a.modality
                  FROM approvals ap JOIN assets a ON ap.asset_id = a.id
                 WHERE a.owner_company_id = ?
                 ORDER BY ap.approval_date DESC
                """,
                (company["id"],),
            )
        ]
    finally:
        conn.close()
    return {"ticker": ticker, "approvals": rows}


def _company_rows(ticker, query):
    ticker = ticker.upper()
    conn = db.get_connection()
    try:
        company = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (ticker,)
        ).fetchone()
        if company is None:
            raise HTTPException(status_code=404, detail=f"unknown ticker {ticker}")
        return ticker, [dict(r) for r in conn.execute(query, (company["id"],))]
    finally:
        conn.close()


@app.get("/changes")
def changes(days: int = Query(default=30)) -> list[dict]:
    return whatchanged_module.build_feed(days=days)


@app.get("/companies/{ticker}/filings")
def company_filings(ticker: str) -> dict:
    ticker, rows = _company_rows(
        ticker,
        """
        SELECT form_type, filed_date, accession, title, url FROM filings
         WHERE company_id = ? ORDER BY filed_date DESC LIMIT 60
        """,
    )
    return {"ticker": ticker, "filings": rows}


@app.get("/companies/{ticker}/news")
def company_news(ticker: str) -> dict:
    ticker, rows = _company_rows(
        ticker,
        """
        SELECT source, title, url, published_at FROM news
         WHERE company_id = ? ORDER BY published_at DESC LIMIT 60
        """,
    )
    return {"ticker": ticker, "news": rows}


@app.get("/catalysts")
def catalysts(within_days: int = Query(default=90),
              ticker: Optional[str] = Query(default=None)) -> list[dict]:
    return catalysts_module.list_catalysts(within_days=within_days, ticker=ticker)


class CatalystIn(BaseModel):
    ticker: str
    catalyst_type: str
    expected_date: str
    title: str
    description: Optional[str] = None


@app.post("/catalysts")
def create_catalyst(body: CatalystIn) -> dict:
    try:
        catalyst_id = catalysts_module.add_catalyst(
            None, body.ticker, body.catalyst_type, body.expected_date, body.title,
            body.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": catalyst_id}


@app.delete("/catalysts/{catalyst_id}")
def remove_catalyst(catalyst_id: int) -> dict:
    if not catalysts_module.delete_catalyst(None, catalyst_id):
        raise HTTPException(status_code=404, detail=f"catalyst {catalyst_id} not found")
    return {"deleted": catalyst_id}


@app.post("/refresh")
def refresh(
    ticker: str = Query(default=refresh_module.DEFAULT_TICKER),
    scope: Optional[str] = Query(default=None),
) -> dict:
    """Refresh one company, or the whole universe with ?scope=all."""
    if scope == "all":
        return refresh_module.run_refresh_all()
    return refresh_module.run_refresh(ticker=ticker)
