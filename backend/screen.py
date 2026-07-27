"""Screen: the comps universe with derived analyst columns.

Every column is computed from data already stored, and every column with a
missing input is null rather than a computed placeholder. The denominator for
revenue per Phase 3 trial is the count of lead-sponsored Phase 3 and Phase 2/3
trials, and it is named for trials because asset mapping is not populated;
calling trials assets would overstate what the number is.
"""

from __future__ import annotations

import datetime as dt

import asset_revenue
import comps
import db
import fx
import pipeline

_LATE_PHASES = ("Phase 3", "Phase 2/3")
_TTM_TOLERANCE_DAYS = 21


def _ttm_change(conn, company_id: int) -> float | None:
    """Trailing 12-month price change from stored daily closes, or null when the
    history does not reach back a year within tolerance."""
    latest = conn.execute(
        "SELECT as_of, close FROM prices WHERE company_id = ? AND interval = '1d'"
        " ORDER BY as_of DESC LIMIT 1", (company_id,)).fetchone()
    if not latest or not latest["close"]:
        return None
    target = (dt.date.fromisoformat(latest["as_of"][:10])
              - dt.timedelta(days=365)).isoformat()
    year_ago = conn.execute(
        """
        SELECT as_of, close FROM prices
         WHERE company_id = ? AND interval = '1d' AND as_of <= ?
         ORDER BY as_of DESC LIMIT 1
        """,
        (company_id, target),
    ).fetchone()
    if not year_ago or not year_ago["close"]:
        return None
    gap = abs((dt.date.fromisoformat(target[:10])
               - dt.date.fromisoformat(year_ago["as_of"][:10])).days)
    if gap > _TTM_TOLERANCE_DAYS:
        return None
    return latest["close"] / year_ago["close"] - 1.0


def _catalysts_12m(conn, company_id: int) -> int:
    return conn.execute(
        """
        SELECT COUNT(*) FROM catalysts
         WHERE company_id = ? AND status = 'pending'
           AND expected_date >= date('now')
           AND expected_date <= date('now', '+365 days')
        """,
        (company_id,),
    ).fetchone()[0]


def build_screen(db_path=None) -> list[dict]:
    base = {row["ticker"]: row for row in comps.build_comps(db_path)}
    late_counts = {row["ticker"]: sum(row["phases"].get(p, 0) for p in _LATE_PHASES)
                   for row in pipeline.build_pipeline(db_path)}

    conn = db.get_connection(db_path)
    try:
        companies = conn.execute(
            "SELECT id, ticker FROM companies ORDER BY ticker").fetchall()
        extras = {}
        for company in companies:
            extras[company["ticker"]] = {
                "ttm_price_change": _ttm_change(conn, company["id"]),
                "catalysts_12m": _catalysts_12m(conn, company["id"]),
            }
    finally:
        conn.close()

    # A comps table compares companies, so its absolutes have to be in one currency.
    # Novo files 309bn DKK and Sanofi 43.6bn EUR; ranked in a column beside dollars they
    # were nonsense. Ratios are currency-internal and are left as filed. A currency with
    # no stored rate converts to None rather than being counted at par, and the reporting
    # currency travels with the row so a converted figure is never taken for a filed one.
    rates = fx.latest_usd_rates(db_path)

    out = []
    for ticker, row in base.items():
        at_risk = asset_revenue.build_revenue_at_risk(db_path, ticker)
        late = late_counts.get(ticker, 0)
        reported = row.get("revenue")
        currency = row["currency"]
        revenue = (reported if currency == "USD"
                   else fx.to_usd(reported, currency, rates))
        out.append({
            "ticker": ticker,
            "name": row["name"],
            "currency": currency,
            "reported_revenue": reported,
            "fx_as_of": (rates.get("as_of")
                         if currency and currency != "USD" else None),
            "revenue": revenue,
            "revenue_growth": row["revenue_growth"],
            "net_margin": row["net_margin"],
            "rd_pct": row["rd_pct"],
            "late_trials": late,
            # Revenue over zero trials is undefined, not infinite and not zero.
            "revenue_per_late_trial": (revenue / late
                                       if revenue is not None and late else None),
            "loe_share_5y": at_risk["share_5y"] if at_risk else None,
            "loe_unpriced_5y": (sum(
                count for year, count in at_risk["unpriced_by_year"].items()
                if year != "later" and int(year) <= at_risk["years"][4])
                if at_risk and len(at_risk["years"]) > 4 else None),
            "catalysts_12m": extras[ticker]["catalysts_12m"],
            "ttm_price_change": extras[ticker]["ttm_price_change"],
        })
    return out
