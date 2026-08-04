"""Comps table builder.

Assembles per-company comparables from stored financials and the latest price.
Operating ratios (growth, net margin, R&D intensity) are currency-internal and
computed for every filer with data. Valuation ratios (market cap, P/E, EV/sales)
need shares outstanding and a matching price currency, so they resolve only for US
filers; every field is null when an input is missing and nothing is estimated.
"""

from __future__ import annotations

import json

import datetime as dt

import db
import fx
from financials_view import _nearest_month_end


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


def _adr_ratio(conn, ticker):
    """Ordinary shares per ADS for a company listed here through a depositary, or None."""
    row = conn.execute(
        "SELECT ordinary_per_adr FROM adr_ratios WHERE ticker = ?", (ticker,)).fetchone()
    return row["ordinary_per_adr"] if row and row["ordinary_per_adr"] else None


def _market_cap(price, price_currency, shares, currency, adr_ratio):
    """Market cap in the reporting currency, or None when it cannot be had honestly.

    Two routes. A company quoted in the currency it reports in multiplies directly. A
    foreign issuer quoted here through a depositary is quoted in dollars per ADS while
    its share count is ordinary shares, so the ADS price is first divided by the shares
    each ADS represents; that lands in dollars without needing a rate, because the
    depositary quote already is dollars.

    Without a ratio the depositary route returns nothing. The direct route used to be
    reached by any company whose reporting currency happened to be dollars, which let
    AstraZeneca multiply an ADS price by an ordinary share count and report half the
    company with nothing to show it was wrong.
    """
    if price is None or shares is None:
        return None
    if adr_ratio:
        return price * shares / adr_ratio if price_currency == "USD" else None
    if currency is not None and price_currency == currency:
        return price * shares
    return None


def _company_comps(conn, company, rates=None) -> dict:
    rates = rates or {}
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

    # A depositary listing is priced per ADS, so it needs the ratio rather than a
    # currency match; everyone else multiplies directly. Either way an input that is
    # missing yields no market cap, so a wrong one cannot be shown.
    adr_ratio = _adr_ratio(conn, ticker)
    market_cap = _market_cap(price, price_currency, shares, currency, adr_ratio)

    # A depositary quote is in dollars, so the market cap above is too while the filed
    # earnings are not. Every ratio built on it therefore converts its denominator to
    # dollars first; a currency with no rate leaves the ratio empty rather than dividing
    # dollars by kroner, which is how a price/earnings of six would have appeared.
    def _usd(value):
        if value is None or currency is None:
            return None
        return value if currency == "USD" else fx.to_usd(value, currency, rates)

    net_income_usd = _usd(net_income)
    revenue_usd = _usd(revenue)
    pe = (_ratio(market_cap, net_income_usd)
          if (market_cap and net_income_usd and net_income_usd > 0) else None)

    enterprise_value = None
    debt_usd, cash_usd = _usd(total_debt), _usd(cash)
    if market_cap is not None and debt_usd is not None and cash_usd is not None:
        enterprise_value = market_cap + debt_usd - cash_usd
    ev_sales = _ratio(enterprise_value, revenue_usd)

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
        rates = fx.latest_usd_rates(db_path)
        return [_company_comps(conn, c, rates) for c in companies]
    finally:
        conn.close()


def comps_trend(db_path=None, shown_years: int = 6) -> dict:
    """Per-company annual revenue growth and net margin over the last few fiscal years,
    aligned on one shared set of year labels so a multi-company chart can plot one line
    per company. Growth is year-over-year and both ratios are currency-internal, so they
    compare across filers who report in different currencies. Missing years stay null."""
    conn = db.get_connection(db_path)
    try:
        companies = conn.execute(
            "SELECT id, ticker FROM companies ORDER BY ticker").fetchall()
        rows = conn.execute(
            """
            SELECT company_id, period_end, metric, value FROM financials
             WHERE period_type = 'FY' AND metric IN ('Revenues', 'NetIncomeLoss')
               AND period_end IS NOT NULL AND value IS NOT NULL
            """).fetchall()
    finally:
        conn.close()

    by: dict = {}
    years: set = set()
    for r in rows:
        # Keyed on the year the period actually closes, not the stored fiscal_year
        # column. Johnson & Johnson runs a 52/53 week calendar, so its fiscal 2020 ended
        # on 3 January 2021 and EDGAR files it against 2021: there is no row labelled
        # 2020 at all, and growth for the year after it had no prior year to divide by
        # and came out blank. The same snapping the statement labels and the allocation
        # band use.
        _, year = _nearest_month_end(dt.date.fromisoformat(r["period_end"]))
        by.setdefault((r["company_id"], r["metric"]), {})[year] = r["value"]
        years.add(year)
    # The oldest shown year still gets growth from the year before it, which is kept in
    # store even though it is not shown, so the growth series is not short a year.
    display = sorted(years)[-shown_years:]
    labels = [f"FY{y % 100:02d}" for y in display]

    out = []
    for c in companies:
        revenue = by.get((c["id"], "Revenues"), {})
        income = by.get((c["id"], "NetIncomeLoss"), {})
        if not revenue:
            continue
        growth = [_pct_change(revenue.get(y), revenue.get(y - 1)) for y in display]
        margin = [_ratio(income.get(y), revenue.get(y)) for y in display]
        if not any(v is not None for v in growth + margin):
            continue
        out.append({"ticker": c["ticker"], "revenue_growth": growth,
                    "net_margin": margin})
    return {"basis": "annual", "labels": labels, "companies": out}


def price_grid(db_path=None, days: int = 90, max_points: int = 60) -> list[dict]:
    """Recent daily closes for every company in one payload, for the universe's
    small-multiples grid. Downsampled evenly to ``max_points`` so eighteen panels
    arrive in one round trip; the change is over the window actually returned."""
    conn = db.get_connection(db_path)
    try:
        companies = conn.execute(
            "SELECT id, ticker, name FROM companies ORDER BY ticker").fetchall()
        out = []
        for company in companies:
            rows = conn.execute(
                """
                SELECT close FROM prices
                 WHERE company_id = ? AND interval = '1d'
                   AND as_of >= date('now', ?)
                 ORDER BY as_of
                """,
                (company["id"], f"-{int(days)} days"),
            ).fetchall()
            closes = [r["close"] for r in rows]
            if len(closes) > max_points:
                step = len(closes) / max_points
                closes = [closes[int(i * step)] for i in range(max_points)]
            change = (closes[-1] / closes[0] - 1.0
                      if len(closes) > 1 and closes[0] else None)
            out.append({"ticker": company["ticker"], "name": company["name"],
                        "closes": closes, "change": change})
        return out
    finally:
        conn.close()
