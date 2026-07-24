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

import env  # noqa: F401  loads the .env from the repo root, before any module reads it
import asset_revenue as asset_revenue_module
import catalysts as catalysts_module
import comps as comps_module
import db
import financials_view as financials_view_module
import insights as insights_module
import loe as loe_module
import pipeline as pipeline_module
import refresh as refresh_module
import whatchanged as whatchanged_module


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure the schema exists so a fresh checkout can serve immediately.
    db.init()
    yield


app = FastAPI(title="Pharma equity research terminal", version="0.2.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/runs/latest")
def latest_run() -> dict:
    """The most recent refresh run, for the top bar's freshness readout."""
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT id, started_at, finished_at, status FROM refresh_runs"
            " ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"id": None, "started_at": None, "finished_at": None, "status": None}
    return dict(row)


@app.get("/companies")
def list_companies() -> list[dict]:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT ticker, name, primary_exchange, country, reporting_currency,
                   cik, is_sec_filer, is_foreign_private_issuer
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
                "SELECT as_of, close FROM prices WHERE company_id = ? AND interval = '1d'"
                " ORDER BY as_of",
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


@app.get("/companies/{ticker}/intraday")
def company_intraday(ticker: str) -> dict:
    """Fifteen minute bars over the last five sessions.

    Separate from /prices because they are different series, not a subset: the daily
    endpoint must never return an intraday bar as its latest close.
    """
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
                "SELECT as_of, close FROM prices WHERE company_id = ? AND interval = '15m'"
                " ORDER BY as_of",
                (company["id"],),
            )
        ]
    finally:
        conn.close()
    sessions = sorted({p["as_of"][:10] for p in points})
    return {"ticker": ticker, "interval": "15m", "sessions": sessions, "points": points}


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


@app.get("/companies/{ticker}/statements")
def company_statements(
    ticker: str,
    basis: str = Query(default=financials_view_module.QUARTERLY),
    periods: int = Query(default=financials_view_module.DEFAULT_PERIODS),
) -> dict:
    """The income statement, balance sheet, and cash flow for one company.

    ``basis=annual`` gives fiscal years, ``quarterly`` gives the interim periods. All
    three statements come back together so switching between them costs no round trip.
    """
    built = financials_view_module.build_statements(
        None, ticker, basis=basis, limit=max(1, min(periods, 12)))
    if built is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker.upper()}")
    return built


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
    """Approved products, with the protection and revenue known for each.

    The exclusivity join is on the asset, not on the application number: one asset can
    carry several approvals and they all share its protection. Latest expiry wins,
    which is the same definition the LOE cliff uses.
    """
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
                SELECT ap.approval_date, ap.application_number, a.brand_name,
                       a.generic_name, a.modality,
                       (SELECT MAX(e.expiry_date) FROM exclusivities e
                         WHERE e.asset_id = a.id) AS loe,
                       (SELECT e2.protection_type FROM exclusivities e2
                         WHERE e2.asset_id = a.id
                         ORDER BY e2.expiry_date DESC LIMIT 1) AS loe_basis,
                       (SELECT r.value FROM asset_revenue r
                         WHERE r.asset_id = a.id
                         ORDER BY r.fiscal_year DESC LIMIT 1) AS revenue,
                       (SELECT r.unit FROM asset_revenue r
                         WHERE r.asset_id = a.id
                         ORDER BY r.fiscal_year DESC LIMIT 1) AS revenue_unit,
                       (SELECT r.fiscal_year FROM asset_revenue r
                         WHERE r.asset_id = a.id
                         ORDER BY r.fiscal_year DESC LIMIT 1) AS revenue_year
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


@app.get("/companies/{ticker}/revenue")
def company_asset_revenue(ticker: str) -> dict:
    """Product revenue, with the company total the products sit inside.

    The total is what lets the mix show what it cannot attribute. Lilly's tagged
    products come to 50.07bn against 65.18bn reported, and a chart that drew only the
    50.07 would imply the rest does not exist.
    """
    ticker = ticker.upper()
    rows = asset_revenue_module.list_revenue(None, ticker)
    totals = {}
    conn = db.get_connection()
    try:
        for row in conn.execute(
            """
            SELECT f.fiscal_year, f.value, f.unit FROM financials f
              JOIN companies c ON c.id = f.company_id
             WHERE c.ticker = ? AND f.metric = 'Revenues' AND f.period_type = 'FY'
            """,
            (ticker,),
        ):
            totals[row["fiscal_year"]] = {"value": row["value"], "unit": row["unit"]}
    finally:
        conn.close()
    return {"ticker": ticker, "rows": rows, "company_revenue": totals}


class AssetRevenueIn(BaseModel):
    application_number: str
    fiscal_year: int
    value: float
    unit: str = "USD"
    source: Optional[str] = ""
    note: Optional[str] = ""


@app.post("/companies/{ticker}/revenue")
def set_asset_revenue(ticker: str, body: AssetRevenueIn) -> dict:
    try:
        revenue_id = asset_revenue_module.set_revenue(
            None, ticker, body.application_number, body.fiscal_year, body.value,
            body.unit, body.source or "", body.note or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": revenue_id}


@app.delete("/revenue/{revenue_id}")
def remove_asset_revenue(revenue_id: int) -> dict:
    if not asset_revenue_module.delete_revenue(None, revenue_id):
        raise HTTPException(status_code=404, detail=f"revenue {revenue_id} not found")
    return {"deleted": revenue_id}


@app.get("/companies/{ticker}/exposure")
def company_exposure(ticker: str) -> dict:
    """What falls off protection each year, and how much of it carries a revenue figure."""
    built = asset_revenue_module.build_exposure(None, ticker)
    if built is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker.upper()}")
    return built


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
def changes(days: int = Query(default=30),
            ticker: Optional[str] = Query(default=None)) -> list[dict]:
    """The ranked feed. Pass ``ticker`` to narrow it to one company."""
    return whatchanged_module.build_feed(days=days, ticker=ticker)


@app.get("/companies/{ticker}/note")
def company_note(ticker: str, days: int = Query(default=30),
                 refresh: bool = Query(default=False)) -> dict:
    """The morning note for one company.

    Returns the stored note by default; ``refresh=true`` generates a new one. Without
    an ANTHROPIC_API_KEY the note is the rules layer, and ``model`` says so.
    """
    ticker = ticker.upper()
    conn = db.get_connection()
    try:
        if conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone() is None:
            raise HTTPException(status_code=404, detail=f"unknown ticker {ticker}")
    finally:
        conn.close()

    if refresh:
        return insights_module.generate_note(ticker=ticker, days=days)
    note = insights_module.latest_note(ticker=ticker)
    if note is None:
        return {"ticker": ticker, "body": None, "model": None, "generated_at": None,
                "error": None}
    note["error"] = None
    return note


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


@app.post("/catalysts/{catalyst_id}/accept")
def accept_catalyst(catalyst_id: int) -> dict:
    """Promote a derived catalyst to curated, so a later refresh cannot withdraw it."""
    if not catalysts_module.accept_catalyst(None, catalyst_id):
        raise HTTPException(
            status_code=404,
            detail=f"catalyst {catalyst_id} not found, or is already curated")
    return {"accepted": catalyst_id}


@app.post("/refresh")
def refresh(
    ticker: str = Query(default=refresh_module.DEFAULT_TICKER),
    scope: Optional[str] = Query(default=None),
) -> dict:
    """Refresh one company, or the whole universe with ?scope=all."""
    if scope == "all":
        return refresh_module.run_refresh_all()
    return refresh_module.run_refresh(ticker=ticker)
