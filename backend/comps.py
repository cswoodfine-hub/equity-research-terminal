"""Comps table builder.

Assembles per-company comparables from stored financials and the latest price.
Operating ratios (growth, net margin, R&D intensity) are currency-internal and
computed for every filer with data. Valuation ratios (market cap, P/E, EV/sales)
need shares outstanding and a matching price currency, so they resolve only for US
filers; every field is null when an input is missing and nothing is estimated.
"""

from __future__ import annotations

import json

import db


def _pct_change(latest, prior):
    if latest is None or prior in (None, 0):
        return None
    return latest / prior - 1.0


def _ratio(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _fy_values(conn, company_id, metric, limit=1):
    return conn.execute(
        """
        SELECT fiscal_year, value, unit FROM financials
         WHERE company_id = ? AND metric = ? AND period_type = 'FY'
         ORDER BY fiscal_year DESC LIMIT ?
        """,
        (company_id, metric, limit),
    ).fetchall()


def _instant_value(conn, company_id, metric):
    row = conn.execute(
        """
        SELECT value, unit, period_end FROM financials
         WHERE company_id = ? AND metric = ? AND period_type = 'instant'
         ORDER BY period_end DESC LIMIT 1
        """,
        (company_id, metric),
    ).fetchone()
    return row


def _latest_price(conn, company_id):
    return conn.execute(
        "SELECT as_of, close FROM prices WHERE company_id = ? AND interval = '1d'"
        " ORDER BY as_of DESC LIMIT 1",
        (company_id,),
    ).fetchone()


def _price_currency(conn, ticker):
    snap = conn.execute(
        """
        SELECT payload FROM snapshots
         WHERE source = 'prices' AND entity_key = ?
           AND json_extract(payload, '$.currency') IS NOT NULL
         ORDER BY captured_at DESC LIMIT 1
        """,
        (ticker,),
    ).fetchone()
    return json.loads(snap["payload"]).get("currency") if snap else None


def _company_comps(conn, company) -> dict:
    cid, ticker = company["id"], company["ticker"]

    revenues = _fy_values(conn, cid, "Revenues", limit=2)
    revenue = revenues[0]["value"] if revenues else None
    currency = revenues[0]["unit"] if revenues else None
    fiscal_year = revenues[0]["fiscal_year"] if revenues else None
    prior_revenue = revenues[1]["value"] if len(revenues) > 1 else None

    net_income_rows = _fy_values(conn, cid, "NetIncomeLoss")
    net_income = net_income_rows[0]["value"] if net_income_rows else None
    rd_rows = _fy_values(conn, cid, "ResearchAndDevelopmentExpense")
    rd_expense = rd_rows[0]["value"] if rd_rows else None

    shares_row = _instant_value(conn, cid, "SharesOutstanding")
    cash_row = _instant_value(conn, cid, "CashAndEquivalents")
    debt_row = _instant_value(conn, cid, "TotalDebt")
    shares = shares_row["value"] if shares_row else None
    cash = cash_row["value"] if cash_row else None
    total_debt = debt_row["value"] if debt_row else None

    price_row = _latest_price(conn, cid)
    price = price_row["close"] if price_row else None
    price_as_of = price_row["as_of"] if price_row else None
    price_currency = _price_currency(conn, ticker)

    # Valuation needs shares, a price, and price currency matching the financials.
    valuation_ok = (
        shares is not None
        and price is not None
        and currency is not None
        and price_currency == currency
    )
    market_cap = price * shares if valuation_ok else None
    pe = _ratio(market_cap, net_income) if (market_cap and net_income and net_income > 0) else None

    enterprise_value = None
    if market_cap is not None and total_debt is not None and cash is not None:
        enterprise_value = market_cap + total_debt - cash
    ev_sales = _ratio(enterprise_value, revenue)

    return {
        "ticker": ticker,
        "name": company["name"],
        "fiscal_year": fiscal_year,
        "currency": currency,
        "revenue": revenue,
        "revenue_growth": _pct_change(revenue, prior_revenue),
        "net_income": net_income,
        "net_margin": _ratio(net_income, revenue),
        "rd_pct": _ratio(rd_expense, revenue),
        "price": price,
        "price_as_of": price_as_of,
        "market_cap": market_cap,
        "pe": pe,
        "ev_sales": ev_sales,
    }


def build_comps(db_path=None) -> list[dict]:
    conn = db.get_connection(db_path)
    try:
        companies = conn.execute(
            "SELECT id, ticker, name, reporting_currency, is_sec_filer FROM companies ORDER BY ticker"
        ).fetchall()
        return [_company_comps(conn, c) for c in companies]
    finally:
        conn.close()
