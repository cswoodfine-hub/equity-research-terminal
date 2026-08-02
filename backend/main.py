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
import annotations as annotations_module
import asof as asof_module
import backtest as backtest_module
import asset_revenue as asset_revenue_module
import catalyst_grid as catalyst_grid_module
import catalysts as catalysts_module
import cashflow as cashflow_module
import comps as comps_module
import db
import deals as deals_module
import demand as demand_module
import filing_diff as filing_diff_module
import trial_readouts as trial_readouts_module
import valuation as valuation_module
import financials_view as financials_view_module
import insights as insights_module
import themes_view as themes_view_module
import brief as brief_module
import runway as runway_module
import productivity as productivity_module
import engines as engines_module
import headlines as headlines_module
import marketmap as marketmap_module
import labels as labels_module
import fx as fx_module
import loe as loe_module
import product_areas
import therapeutic_areas
import pipeline as pipeline_module
import product_profile as product_profile_module
import refresh as refresh_module
import regulatory as regulatory_module
import screen as screen_module
import slippage as slippage_module
import tearsheet as tearsheet_module
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
        # Two facts the company page needs before it can decide what to show. Stage is
        # whether the company sells anything, read from inventory and cost of revenue.
        # Engine is which of the three cohorts it is read on, which decides the tabs: a
        # 6m-revenue gene therapy developer and AbbVie cannot answer the same questions,
        # and offering both the same tabs is what left them half empty.
        homes = engines_module.home()
        out = []
        for row in rows:
            entry = dict(row)
            company = conn.execute(
                "SELECT id FROM companies WHERE ticker = ?", (entry["ticker"],)).fetchone()
            entry["stage"] = runway_module.stage(conn, company["id"])
            entry["engine"] = homes.get(entry["ticker"])
            out.append(entry)
    finally:
        conn.close()
    return out


@app.get("/companies/{ticker}/prices")
def company_prices(ticker: str, interval: str = Query(default="1d")) -> dict:
    """Daily OHLC by default, or an intraday bar size for the trading chart. 5m and 60m
    read the intraday_bars cache (a rolling window); anything else is the 5y daily series.
    The 15m/30m and 4H views are resampled on the frontend from the 5m and 60m bases."""
    ticker = ticker.upper()
    conn = db.get_connection()
    try:
        company = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (ticker,)
        ).fetchone()
        if company is None:
            raise HTTPException(status_code=404, detail=f"unknown ticker {ticker}")

        if interval in ("5m", "60m"):
            points = [
                dict(r)
                for r in conn.execute(
                    "SELECT as_of, open, high, low, close, volume FROM intraday_bars"
                    " WHERE company_id = ? AND interval = ? ORDER BY as_of",
                    (company["id"], interval),
                )
            ]
        else:
            interval = "1d"
            points = [
                dict(r)
                for r in conn.execute(
                    "SELECT as_of, open, high, low, close, volume FROM prices"
                    " WHERE company_id = ? AND interval = '1d' ORDER BY as_of",
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
        "interval": interval,
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


@app.get("/companies/{ticker}/cashflow")
def company_cashflow(ticker: str) -> dict:
    """Cash generation and leverage: free cash flow and its margin, cash conversion,
    net debt and net debt to EBITDA, each null when one of its inputs is missing."""
    built = cashflow_module.build_cashflow(None, ticker)
    if built is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker.upper()}")
    return built


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


@app.get("/comps/trend")
def comps_trend() -> dict:
    """Per-company revenue growth and net margin over the last few fiscal years, on one
    shared set of year labels, for the multi-company comparison chart."""
    return comps_module.comps_trend()


@app.get("/pipeline")
def pipeline() -> list[dict]:
    return pipeline_module.build_pipeline()


@app.get("/companies/{ticker}/trials")
def company_trials(ticker: str, phase: Optional[str] = Query(default=None)) -> dict:
    rows = pipeline_module.trials_for(None, ticker, phase)
    if rows is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker.upper()}")
    return {"ticker": ticker.upper(), "phase": phase, "trials": rows}


@app.get("/companies/{ticker}/programmes")
def company_programmes(ticker: str) -> dict:
    """Compounds the company is trialling but does not yet sell, each with the studies
    behind it, the furthest phase reached and the next readout due."""
    rows = pipeline_module.programmes(None, ticker)
    if rows is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker.upper()}")
    return {"ticker": ticker.upper(), "programmes": rows}


@app.get("/loe")
def loe() -> dict:
    return loe_module.build_loe()


@app.get("/companies/{ticker}/exclusivities")
def company_exclusivities(ticker: str) -> dict:
    rows = loe_module.loe_detail(None, ticker)
    if rows is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker.upper()}")
    # The area travels here too: a CBER cell or gene therapy has no drugsfda approval,
    # so this list is the only place the portfolio view meets it.
    areas = product_areas.areas_for(None, [r.get("asset_id") for r in rows])
    for row in rows:
        row["area"] = areas.get(row.get("asset_id"))
    return {"ticker": ticker.upper(), "assets": rows}


@app.get("/companies/{ticker}/filing-text")
def company_filing_text(ticker: str) -> dict:
    """Risk factors and MD&A of the latest filings, diffed against the prior of the same
    form, with the passages that were added. Empty until a filing has a prior to compare
    against, which for a foreign 20-F filer is never, since their layout differs."""
    rows = filing_diff_module.company_filing_diff(None, ticker)
    if rows is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker.upper()}")
    return {"ticker": ticker.upper(), "sections": rows}


@app.get("/companies/{ticker}/valuation")
def company_valuation(ticker: str, rate: float = Query(default=valuation_module.DISCOUNT_RATE)) -> dict:
    """A protected-revenue NPV per marketed product and a company total.

    Each product's latest reported revenue is held flat and discounted over the years
    left to its LOE. A scaffold, not a model: post-LOE generic revenue is zero, the rate
    is one number, and a product missing revenue or an LOE date is listed unvalued."""
    built = valuation_module.company_valuation(None, ticker, rate)
    if built is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker.upper()}")
    return built


@app.get("/companies/{ticker}/deals")
def company_deals(ticker: str) -> dict:
    """Recent M&A, licensing and collaboration deals read from the filings that announced
    them, one per counterparty with the value where the filing stated it and the area."""
    return {"ticker": ticker.upper(), "deals": deals_module.recent(None, ticker)}


@app.get("/companies/{ticker}/readouts")
def company_readouts(ticker: str) -> dict:
    """Signed Phase 2 and Phase 3 trial readouts classified from the filings that
    announced them: the drug, the phase, the sign, and the sentence that carried it."""
    return {"ticker": ticker.upper(), "readouts": trial_readouts_module.recent(None, ticker)}


@app.get("/companies/{ticker}/demand")
def company_demand(ticker: str) -> dict:
    """Medicare Part D and Part B demand per marketed drug, matched by brand.

    Real-world US volume the revenue line cannot show: spending, claims and distinct
    beneficiaries, latest year with the year before for direction. Sorted by spending."""
    rows = demand_module.company_demand(None, ticker)
    if rows is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker.upper()}")
    return {"ticker": ticker.upper(), "drugs": rows}


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
                SELECT a.id AS asset_id, ap.approval_date, ap.application_number,
                       a.brand_name, a.generic_name, a.modality,
                       (SELECT MAX(e.expiry_date) FROM exclusivities e
                         WHERE e.asset_id = a.id) AS loe_max,
                       (SELECT MIN(e.expiry_date) FROM exclusivities e
                         WHERE e.asset_id = a.id) AS loe_earliest,
                       (SELECT MAX(e.expiry_date) FROM exclusivities e
                         WHERE e.asset_id = a.id AND e.patent_kind = 'substance')
                         AS substance_max,
                       (SELECT MIN(e.expiry_date) FROM exclusivities e
                         WHERE e.asset_id = a.id AND e.patent_kind = 'substance')
                         AS substance_earliest,
                       (SELECT MAX(e.expiry_date) FROM exclusivities e
                         WHERE e.asset_id = a.id AND e.patent_kind = 'use')
                         AS use_max,
                       (SELECT e2.protection_type FROM exclusivities e2
                         WHERE e2.asset_id = a.id
                         ORDER BY e2.expiry_date DESC LIMIT 1) AS loe_basis,
                       (SELECT b.loe_year FROM biologic_loe b
                         WHERE b.asset_id = a.id) AS bio_floor_year,
                       (SELECT r.value FROM asset_revenue r
                         WHERE r.asset_id = a.id AND r.period = 'FY'
                         ORDER BY r.fiscal_year DESC LIMIT 1) AS revenue,
                       (SELECT r.unit FROM asset_revenue r
                         WHERE r.asset_id = a.id AND r.period = 'FY'
                         ORDER BY r.fiscal_year DESC LIMIT 1) AS revenue_unit,
                       (SELECT r.fiscal_year FROM asset_revenue r
                         WHERE r.asset_id = a.id AND r.period = 'FY'
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
    # Merge the biologic 12-year floor into the latest expiry, the same rule loe_detail
    # uses, so the two views agree; keep the earliest expiry for the patent range.
    rates = fx_module.latest_usd_rates(None)
    # The disease each product treats, resolved from the label that states it, in one
    # place for every view that shows an area.
    areas = product_areas.areas_for(None, [r["asset_id"] for r in rows])
    for r in rows:
        r["area"] = areas.get(r["asset_id"])
        r["loe"], r["loe_basis"] = loe_module.effective(
            r.pop("loe_max"), r["loe_basis"], r.pop("bio_floor_year"),
            r.get("substance_max"))
        # The window is the molecule patents where the book flags them, since that is
        # what a generic has to wait out.
        r["loe_earliest"] = r.pop("substance_earliest") or r["loe_earliest"]
        # Popped first and read after: reading it inside the conditional after the pop
        # is a KeyError the moment a product actually has a use patent.
        use_max = r.pop("use_max", None)
        r["use_patent_year"] = int(use_max[:4]) if use_max else None
        r.pop("substance_max", None)
        # Same rule as the mix: a card's revenue is shown in dollars whatever the filer
        # reports in, with the filed figure kept beside it.
        r["reported_revenue"], r["reported_unit"] = r.get("revenue"), r.get("revenue_unit")
        if r.get("revenue_unit") and r["revenue_unit"] != "USD":
            r["revenue"] = fx_module.to_usd(r.get("revenue"), r["revenue_unit"], rates)
            r["revenue_unit"] = "USD" if r["revenue"] is not None else r["reported_unit"]
    return {"ticker": ticker, "approvals": rows}


@app.get("/companies/{ticker}/product/{asset_id}")
def company_product_profile(ticker: str, asset_id: int) -> dict:
    """One product's fact profile: approval, revenue, LOE, CMS demand, labels and patent
    challenges from the sourced tables, plus the curated market-size, peak-sales and
    competitor fields the analyst keeps by hand."""
    profile = product_profile_module.product_profile(None, ticker, asset_id)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail=f"no product {asset_id} for {ticker.upper()}")
    return profile


class ProductNotesIn(BaseModel):
    market_size: Optional[str] = None
    peak_sales: Optional[str] = None
    competitors: Optional[str] = None
    thesis: Optional[str] = None


@app.post("/companies/{ticker}/product/{asset_id}/notes")
def save_product_notes(ticker: str, asset_id: int, body: ProductNotesIn) -> dict:
    """Store the curated fields for one product. The ticker scopes the asset so a note
    cannot be written against another company's product by id alone."""
    if product_profile_module.product_profile(None, ticker, asset_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"no product {asset_id} for {ticker.upper()}")
    product_profile_module.save_notes(None, asset_id, body.model_dump())
    return {"asset_id": asset_id, "saved": True}


@app.get("/companies/{ticker}/revenue")
def company_asset_revenue(ticker: str) -> dict:
    """Product revenue, with the company total the products sit inside.

    The total is what lets the mix show what it cannot attribute. Lilly's tagged
    products come to 50.07bn against 65.18bn reported, and a chart that drew only the
    50.07 would imply the rest does not exist.
    """
    ticker = ticker.upper()
    rows = asset_revenue_module.list_revenue(None, ticker)
    # The area travels with the revenue, so the mix can be cut by disease without
    # depending on the approvals list: Jardiance earns revenue under Lilly and is
    # approved to Boehringer, so it appears here and not there.
    areas = product_areas.areas_for(None, [r.get("asset_id") for r in rows])
    for row in rows:
        row["area"] = areas.get(row.get("asset_id"))
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
    # Product revenue is filed in the company's own currency, so Novo's Ozempic reads
    # 127bn against a Lilly product's 22bn and the mix is drawn on two scales at once.
    # Converted here, at the read, so every view of a product's revenue is in dollars
    # and the filed figure stays beside it. No rate means no converted value, never a
    # figure counted at par.
    rates = fx_module.latest_usd_rates(None)
    for row in rows:
        row["reported_value"], row["reported_unit"] = row.get("value"), row.get("unit")
        if row.get("unit") and row["unit"] != "USD":
            row["value"] = fx_module.to_usd(row.get("value"), row["unit"], rates)
            row["unit"] = "USD" if row["value"] is not None else row["reported_unit"]
    for year, total in totals.items():
        total["reported_value"], total["reported_unit"] = total["value"], total["unit"]
        if total.get("unit") and total["unit"] != "USD":
            total["value"] = fx_module.to_usd(total["value"], total["unit"], rates)
            total["unit"] = "USD" if total["value"] is not None else total["reported_unit"]
    return {"ticker": ticker, "rows": rows, "company_revenue": totals,
            "fx_as_of": rates.get("as_of")}


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


@app.get("/companies/{ticker}/revenue-at-risk")
def company_revenue_at_risk(ticker: str) -> dict:
    """The exposure cliff as shares of tagged product revenue, with the unpriced
    band carried as counts rather than imputed values."""
    built = asset_revenue_module.build_revenue_at_risk(None, ticker)
    if built is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker.upper()}")
    return built


@app.get("/revenue-at-risk")
def universe_revenue_at_risk() -> dict:
    """Universe view, in shares only: no FX source exists here, so absolute
    figures in mixed currencies are never stacked."""
    return asset_revenue_module.build_universe_at_risk()


@app.get("/slippage")
def slippage(ticker: Optional[str] = Query(default=None)) -> dict:
    """Per-trial completion-date moves accumulated from our own snapshot history."""
    return slippage_module.build(ticker=ticker)


@app.get("/label-changes")
def label_changes(ticker: Optional[str] = Query(default=None),
                  days: int = Query(default=365)) -> dict:
    """Detected label revisions across the universe, or one company: new
    indications and widened populations from DailyMed, ranked to the top of the feed."""
    return {"changes": labels_module.list_label_changes(None, ticker, days),
            "current": labels_module.current_labels(None, ticker)}


@app.get("/companies/{ticker}/label-changes")
def company_label_changes(ticker: str, days: int = Query(default=365)) -> dict:
    ticker = ticker.upper()
    return {"ticker": ticker,
            "changes": labels_module.list_label_changes(None, ticker, days),
            "current": labels_module.current_labels(None, ticker),
            "supplements": labels_module.list_supplements(None, ticker)}


@app.get("/companies/{ticker}/supplements")
def company_supplements(ticker: str) -> dict:
    """Approved efficacy supplements for one company, US CDER only."""
    return {"ticker": ticker.upper(),
            "supplements": labels_module.list_supplements(None, ticker.upper())}


@app.get("/catalyst-grid")
def catalyst_grid(months: int = Query(default=18)) -> dict:
    """Every company against the coming months; uncurated PDUFA cells flagged."""
    return catalyst_grid_module.build(months=max(1, min(months, 36)))


@app.get("/screen")
def screen() -> list[dict]:
    """The comps universe with derived analyst columns; missing inputs are null."""
    return screen_module.build_screen()


@app.get("/price-grid")
def price_grid(days: int = Query(default=90)) -> list[dict]:
    """Recent closes for all companies in one payload, for the universe grid."""
    return comps_module.price_grid(days=max(5, min(days, 1900)))


@app.get("/as-of")
def as_of(date: str = Query(...)) -> dict:
    """Read-only reconstruction of tracked state at a past date, from snapshots."""
    built = asof_module.state_at(None, date)
    if built is None:
        raise HTTPException(status_code=400, detail=f"not an ISO date: {date}")
    return built


class AnnotationIn(BaseModel):
    ticker: str
    entity_type: str
    entity_id: Optional[str] = None
    body: str


@app.get("/annotations")
def list_annotations(ticker: Optional[str] = Query(default=None),
                     entity_type: Optional[str] = Query(default=None),
                     entity_id: Optional[str] = Query(default=None)) -> list[dict]:
    return annotations_module.list_annotations(None, ticker, entity_type, entity_id)


@app.post("/annotations")
def create_annotation(body: AnnotationIn) -> dict:
    try:
        annotation_id = annotations_module.add(
            None, body.ticker, body.entity_type, body.entity_id, body.body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": annotation_id}


@app.delete("/annotations/{annotation_id}")
def remove_annotation(annotation_id: int) -> dict:
    if not annotations_module.delete(None, annotation_id):
        raise HTTPException(status_code=404,
                            detail=f"annotation {annotation_id} not found")
    return {"deleted": annotation_id}


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


@app.get("/engines")
def engines_board() -> dict:
    """The three engines, each with the live headline and distribution from its cohort."""
    return engines_module.build()


@app.get("/engines/catalogue")
def engines_catalogue() -> dict:
    """The three engines by name. What the front door needs and nothing else."""
    return {"engines": engines_module.catalogue()}


@app.get("/engines/{engine}/tickers")
def engine_tickers(engine: str) -> list[str]:
    """The companies one engine covers. An unknown engine returns the whole universe."""
    return engines_module.tickers_for(engine=engine)


@app.get("/headlines")
def headline_items(engine: Optional[str] = None, days: int = headlines_module.LOOKBACK_DAYS,
                   limit: int = headlines_module.LIMIT) -> list[dict]:
    """The few things worth knowing on an engine, ranked by materiality not recency."""
    tickers = (engines_module.tickers_for(engine=engine)
               if engine in engines_module.ENGINES else None)
    return headlines_module.build(tickers=tickers, days=days, limit=limit)


@app.get("/marketmap")
def market_map(engine: Optional[str] = None,
               days: int = marketmap_module.WINDOW_DAYS) -> dict:
    """Every company on an engine as a box, sized by what that engine runs on."""
    return marketmap_module.build(engine=engine, days=days)


@app.get("/lookahead")
def lookahead_items(engine: Optional[str] = None,
                    days: int = headlines_module.AHEAD_DAYS) -> list[dict]:
    """What is dated inside the window on an engine, soonest first."""
    tickers = (engines_module.tickers_for(engine=engine)
               if engine in engines_module.ENGINES else None)
    return headlines_module.ahead(tickers=tickers, days=days)


@app.get("/engines/home")
def engine_home() -> dict:
    """{ticker: engine} for every company, so a caller can place one without the cards."""
    return engines_module.home()


@app.get("/productivity/scorecard")
def productivity_scorecard() -> dict:
    """Each company on a research axis and a commercial one, plus who cannot be placed.

    Both axes are weighted z-scores against the companies on the chart, so zero is the
    average of those peers rather than any absolute standard.
    """
    return {"placed": productivity_module.scorecard(),
            "gaps": productivity_module.scorecard_gaps()}


@app.get("/productivity")
def productivity_panel() -> list[dict]:
    """R&D productivity for the commercial-stage names.

    Portfolio freshness leads: the share of product revenue from drugs approved in the
    last five years. Spend per approval is reported beside it as the reference point
    rather than the answer, since the research in the window did not buy the approvals
    in it. Where the revenue behind a company cannot be attributed to dated drugs the
    share is refused and the reason is given.
    """
    return productivity_module.build()


@app.get("/runway")
def runway_all(stage: Optional[str] = Query(default="clinical")) -> list[dict]:
    """Cash runway for the clinical-stage cohort, shortest first.

    Months at the current burn, which is what the filings support. It is not a forecast:
    companies raise, cut and partner, and the number moves the day they do.
    """
    return runway_module.build(stage_filter=stage or None)


@app.get("/companies/{ticker}/runway")
def runway_one(ticker: str) -> dict:
    row = runway_module.for_company(ticker=ticker.upper())
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker}")
    return row


@app.get("/themes")
def themes_overview(days: int = Query(default=90)) -> dict:
    """The universe along the modality axis, with how far that axis reaches.

    Coverage travels with the counts on purpose. The counts are floors: an asset named
    only by a code number states nothing about itself in any free source, so a company
    can run programmes in a theme without appearing in its count.
    """
    return {"themes": themes_view_module.build(days=days),
            "coverage": themes_view_module.coverage()}


@app.get("/themes/{theme}")
def theme_detail(theme: str, days: int = Query(default=90)) -> dict:
    """Every programme carrying one theme, with the phrase each tag was read from."""
    return themes_view_module.detail(theme, days=days)


@app.get("/themes/{theme}/brief")
def theme_brief(theme: str) -> dict:
    """The stored thematic brief, or an empty body when none has been written."""
    return brief_module.latest(theme=theme) or {"theme": theme, "body": "", "model": None}


@app.post("/themes/{theme}/brief")
def write_theme_brief(theme: str, days: int = Query(default=90)) -> dict:
    """Write a brief for one theme. Without a model key this is the rules layer, and
    ``model`` says which it was."""
    return brief_module.generate(theme=theme, days=days)


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


@app.get("/regulatory-news")
def regulatory_news(days: int = Query(default=120)) -> dict:
    """Recent FDA announcement items across the universe, matched company first.

    From the FDA press, drug and safety feeds. An item that named no tracked company
    is kept too, so the announcement layer is complete rather than pre-filtered."""
    conn = db.get_connection()
    try:
        rows = [dict(r) for r in conn.execute(
            """
            SELECT n.source, n.title, n.url, n.published_at, c.ticker
              FROM news n LEFT JOIN companies c ON c.id = n.company_id
             WHERE n.source LIKE 'fda_%'
               AND (n.published_at IS NULL OR n.published_at >= date('now', ?))
             ORDER BY n.published_at DESC, n.id DESC LIMIT 80
            """,
            (f"-{int(days)} days",),
        )]
    finally:
        conn.close()
    return {"news": rows}


@app.get("/regulatory")
def regulatory_stream(days: int = Query(default=120)) -> dict:
    """Advisory committee meetings and FDA announcement feeds as one timeline: scheduled
    panel votes ahead, announcements behind, each tagged by kind and by company where the
    item names a covered one."""
    return regulatory_module.build(None, days=days)


@app.get("/backtest")
def backtest() -> dict:
    """Whether the change signals led price moves: abnormal forward return and hit rate
    by change type, over the stored history. Small by construction on a young install."""
    return backtest_module.build()


@app.get("/adcomm-calendar")
def adcomm_calendar(days: int = Query(default=270)) -> dict:
    """Upcoming FDA advisory committee meetings, matched company first.

    The whole scheduled calendar across sponsors, from the Federal Register. A meeting
    that binds to a tracked company carries its ticker and is also a catalyst; the rest
    are agency context, kept rather than dropped."""
    conn = db.get_connection()
    try:
        rows = [dict(r) for r in conn.execute(
            """
            SELECT m.meeting_date, m.committee, m.application_label, m.sponsor,
                   m.product, m.url, c.ticker
              FROM adcomm_meetings m LEFT JOIN companies c ON c.id = m.company_id
             WHERE m.meeting_date >= date('now')
               AND m.meeting_date <= date('now', ?)
             ORDER BY (c.ticker IS NULL), m.meeting_date
            """,
            (f"+{int(days)} days",),
        )]
    finally:
        conn.close()
    return {"meetings": rows}


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


@app.post("/companies/{ticker}/tearsheet")
def make_tearsheet(ticker: str) -> dict:
    """Write a one-page print-styled tearsheet to exports/ and return its path."""
    try:
        path = tearsheet_module.build(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ticker": ticker.upper(), "path": str(path), "filename": path.name}


@app.post("/refresh")
def refresh(
    ticker: str = Query(default=refresh_module.DEFAULT_TICKER),
    scope: Optional[str] = Query(default=None),
) -> dict:
    """Refresh one company, or the whole universe with ?scope=all."""
    if scope == "all":
        return refresh_module.run_refresh_all()
    return refresh_module.run_refresh(ticker=ticker)
