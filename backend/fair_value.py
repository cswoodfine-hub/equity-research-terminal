"""A company's fair value as a range across lenses, not one number.

The sum of the parts is the anchor: every product valued on its own evidence. It is also
one model with conventions of its own, and across the book it read a median 25% below the
share price. So the page sets it beside the other ways a price is judged, each with its
basis stated, and splits the gap to the price into what the forecast explains and what is
left for the valuation's conventions:

- **Revenue against guidance.** The modelled book's revenue for the guided year against
  what the company guides. The book is revalued with its revenue level matched to the
  guidance, so the value the forecast level explains is separated from the rest.
- **The sum of the parts, pushed.** Every discount rate a point either way.
- **Trading comparables.** The peers' price to next-twelve-months consensus EPS (Nasdaq)
  and enterprise value to last-fiscal-year revenue (filed), applied to the company at the
  peers' quartiles.
- **Analyst price targets**, low to high, from the same feed.
- **The trading range** of the last 52 weeks.

Every figure is per US-listed share in dollars: the book's share divisor already folds in
the depositary ratio and the exchange rate. A lens without its inputs is left out with a
reason, never filled.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
import time

import breakpoints as B
import db
import forecast
import forecast_view as V

GUIDED_YEAR = 2026
WACC_STEP = 0.01
PEER_TTL_S = 15 * 60     # the prices it reads refresh on the same cadence
_peer_cache: dict = {}


def _quartiles(values: list) -> tuple | None:
    """(lower quartile, median, upper quartile), or None with fewer than four values."""
    values = sorted(v for v in values if v is not None and math.isfinite(v))
    if len(values) < 4:
        return None
    q = statistics.quantiles(values, n=4, method="inclusive")
    return q[0], q[1], q[2]


# --- revenue against guidance ------------------------------------------------------
def guidance(conn, company_id: int, year: int, prior_revenue: float | None,
             unit: str | None) -> dict | None:
    """The newest revenue guidance for the year, in millions of the reporting currency.
    Growth guidance is applied to the prior year's reported revenue, and says so."""
    row = conn.execute(
        """SELECT metric, value, low, high, currency, as_of, note FROM consensus_estimates
            WHERE company_id = ? AND source = 'guidance' AND period = ?
              AND metric IN ('Revenue', 'RevenueGrowth')
              AND (value IS NOT NULL OR (low IS NOT NULL AND high IS NOT NULL))
            ORDER BY as_of DESC, metric = 'Revenue' DESC LIMIT 1""",
        (company_id, f"FY{year}")).fetchone()
    if row is None:
        return None
    mid = row["value"] if row["value"] is not None else (row["low"] + row["high"]) / 2.0
    low = row["low"] if row["low"] is not None else mid
    high = row["high"] if row["high"] is not None else mid
    if row["metric"] == "RevenueGrowth":
        if prior_revenue is None:
            return None
        scale = prior_revenue / 1e6
        return {"mid": scale * (1 + mid / 100), "low": scale * (1 + low / 100),
                "high": scale * (1 + high / 100), "as_of": row["as_of"], "note": row["note"],
                "basis": f"growth of {low:g}% to {high:g}% on FY{year - 1} reported revenue"}
    if (row["currency"] or unit or "").upper() != (unit or "").upper():
        return None
    return {"mid": mid / 1e6, "low": low / 1e6, "high": high / 1e6, "as_of": row["as_of"],
            "note": row["note"], "basis": "revenue as guided"}


def model_revenue(book: B.Book, year: int) -> dict:
    """The modelled book's revenue in a year, millions of the reporting currency.

    A product or line whose forecast starts the year after is anchored on that year's run
    rate, the first half as reported and the second at the second quarter's pace, and that
    anchor stands in for the year. Pipeline revenue is risked at its probability. Revenue
    is taken before any share of a co-owned product, since guidance is what the company
    books."""
    products = run_rate = pipeline = lines = 0.0
    for part in book.counted:
        years = part.get("years") or []
        share = part.get("share") or 1.0
        scalars = book.inputs_by_asset[part["asset_id"]].get("scalars") or {}
        if year in years:
            value = (part.get("revenue_share") or [])[years.index(year)] / share
            if part.get("is_marketed"):
                products += value
            else:
                pipeline += value * (part.get("pos") if part.get("pos") is not None else 1.0)
        elif (years and min(years) == year + 1 and part.get("is_marketed")
              and scalars.get("base_revenue")):
            run_rate += scalars["base_revenue"]
    for part in book.streams:
        years = part.get("years") or []
        if year in years:
            lines += (part.get("revenue") or [])[years.index(year)]
        elif years and min(years) == year + 1 and part.get("base_revenue"):
            lines += part["base_revenue"]
    return {"products": products, "run_rate": run_rate, "pipeline_risked": pipeline,
            "lines": lines, "total": products + run_rate + pipeline + lines}


def scale_trials(book: B.Book, factor: float, year: int):
    """Trials that move every product and line with revenue in the year by one factor,
    through the input that sets its level: the reported base for a marketed product or a
    line, the pool for a franchise, the net price for a patient-built product."""
    def asset_trial(part, inputs):
        scalars = dict(inputs.get("scalars") or {})
        years = part.get("years") or []
        has_year = year in years or (years and min(years) == year + 1)
        if not has_year or not any(part.get("revenue_share") or []):
            return None
        if part.get("mode") == "marketed" and scalars.get("base_revenue"):
            scalars["base_revenue"] = scalars["base_revenue"] * factor
            return {**inputs, "scalars": scalars}
        if part.get("mode") == "franchise" and scalars.get("franchise_revenue"):
            scalars["franchise_revenue"] = scalars["franchise_revenue"] * factor
            return {**inputs, "scalars": scalars}
        if year in years:
            price = forecast.net_price(scalars)
            if price:
                return V.apply_lever(inputs, "net_price_per_patient", price * factor)
        return None

    def line_trial(part, scalars):
        if not scalars.get("base_revenue"):
            return None
        return {**scalars, "base_revenue": scalars["base_revenue"] * factor}
    return asset_trial, line_trial


def revenue_split(book: B.Book, year: int = GUIDED_YEAR) -> dict:
    """The modelled book's revenue against guidance, and the value that difference
    explains. {"ok": False, "reason"} where no guidance or revenue is on file."""
    conn = db.get_connection(book.db_path)
    try:
        prior = conn.execute(
            """SELECT value, unit FROM financials WHERE company_id = ? AND metric = 'Revenues'
                 AND period_type = 'FY' AND fiscal_year = ? ORDER BY period_end DESC LIMIT 1""",
            (book.company_id, year - 1)).fetchone()
        guided = guidance(conn, book.company_id, year, prior["value"] if prior else None,
                          prior["unit"] if prior else None)
    finally:
        conn.close()
    if guided is None:
        return {"ok": False, "reason": f"no FY{year} revenue guidance on file"}
    modelled = model_revenue(book, year)
    coverage = book.verdict.get("coverage") or {}
    unmodelled = max(0.0, (coverage.get("untagged_revenue") or 0.0) / 1e6)
    if not modelled["total"]:
        return {"ok": False, "reason": f"no modelled revenue in {year}"}

    def matched(target_mm: float) -> float | None:
        factor = (target_mm - unmodelled) / modelled["total"]
        if factor <= 0:
            return None
        value = book.equity_with(*scale_trials(book, factor, year))
        return None if math.isnan(value) else value

    expected = modelled["total"] + unmodelled
    mid = matched(guided["mid"])
    return {
        "ok": True, "year": year, "unit": prior["unit"] if prior else None,
        "guidance": guided, "modelled": modelled,
        "unmodelled_prior_year": unmodelled, "expected": expected,
        "gap_pct": guided["mid"] / expected - 1.0,
        "equity": book.equity, "close": book.close,
        "matched_equity": mid,
        "matched_low": matched(guided["low"]) if guided["low"] != guided["mid"] else mid,
        "matched_high": matched(guided["high"]) if guided["high"] != guided["mid"] else mid,
        "explained_by_revenue": (mid - book.equity) if mid is not None else None,
        "left_for_conventions": (book.close - mid) if mid is not None else None,
        "basis": ("the modelled book's revenue, with launches and lines anchored on the "
                  f"{year} run rate standing in for {year} and pipeline revenue risked, plus "
                  f"FY{year - 1} revenue no product or line carries, held flat; the book is "
                  "revalued with every product and line moved by one factor so the total "
                  "meets guidance"),
    }


# --- the sum of the parts, pushed ---------------------------------------------------
def discount_range(book: B.Book) -> dict:
    def at(shift):
        return book.equity_with(
            lambda part, inputs: V.apply_lever(inputs, "wacc", (part.get("wacc") or 0.07) + shift),
            lambda part, scalars: {**scalars, "wacc": (part.get("wacc") or 0.07) + shift})
    low, high = at(WACC_STEP), at(-WACC_STEP)
    return {"low": low, "mid": book.equity, "high": high,
            "basis": "every product's and line's discount rate a point higher and lower"}


# --- trading comparables ----------------------------------------------------------
def _ntm_eps(conn, company_id: int, as_of: str) -> dict | None:
    """Next-twelve-months EPS: the two consensus fiscal years weighted by the months of
    each inside the twelve months from the price date. Assumes December year ends, which
    every company in the book has."""
    rows = {r["period"]: r["value"] for r in conn.execute(
        """SELECT e.period, e.value FROM consensus_estimates e
            WHERE e.company_id = ? AND e.metric = 'EPS' AND e.source IN ('nasdaq', 'fmp')
              AND e.as_of = (SELECT MAX(as_of) FROM consensus_estimates e2
                              WHERE e2.company_id = e.company_id AND e2.metric = 'EPS'
                                AND e2.period = e.period AND e2.source = e.source)""",
        (company_id,))}
    date = dt.date.fromisoformat(as_of[:10])
    this, nxt = rows.get(f"FY{date.year}"), rows.get(f"FY{date.year + 1}")
    if this is None or nxt is None:
        return None
    remaining = (dt.date(date.year, 12, 31) - date).days / 365.0
    value = this * remaining + nxt * (1.0 - remaining)
    return {"value": value, "weight_this_year": remaining,
            "basis": f"FY{date.year} and FY{date.year + 1} consensus EPS weighted by the "
                     f"months of each in the twelve months from {as_of[:10]}"}


def _metrics(book: B.Book) -> dict:
    """A company's own multiples, per US-listed share."""
    conn = db.get_connection(book.db_path)
    try:
        revenue = conn.execute(
            """SELECT value, fiscal_year FROM financials WHERE company_id = ?
                 AND metric = 'Revenues' AND period_type = 'FY'
                ORDER BY fiscal_year DESC, period_end DESC LIMIT 1""",
            (book.company_id,)).fetchone()
        eps = _ntm_eps(conn, book.company_id, book.sotp.get("price_date") or
                       dt.date.today().isoformat())
    finally:
        conn.close()
    out = {"ticker": book.ticker, "close": book.close}
    net_cash_ps = book.per_share(book.net_cash)
    out["net_cash_ps"] = net_cash_ps
    if revenue and revenue["value"]:
        revenue_ps = revenue["value"] / book.shares
        out.update(revenue_ps=revenue_ps, revenue_year=revenue["fiscal_year"],
                   ev_sales=(book.close - net_cash_ps) / revenue_ps)
    if eps and eps["value"] and eps["value"] > 0:
        out.update(eps_ntm=eps["value"], pe_ntm=book.close / eps["value"],
                   eps_basis=eps["basis"])
    return out


def universe(db_path=None) -> list[dict]:
    """Every valued company's own multiples, for the peer quartiles."""
    conn = db.get_connection(db_path)
    try:
        tickers = [r["ticker"] for r in conn.execute(
            """SELECT DISTINCT c.ticker FROM companies c
                 JOIN assets a ON a.owner_company_id = c.id
                 JOIN assumptions s ON s.asset_id = a.id ORDER BY c.ticker""")]
    finally:
        conn.close()
    out = []
    for ticker in tickers:
        book = B.Book(db_path, ticker)
        if book.ok:
            out.append(_metrics(book))
    return out


def cached_universe(db_path=None) -> list[dict]:
    """The peer multiples, rebuilt at most every fifteen minutes: every company's book
    is valued to read them, and one page asks for all of them."""
    hit = _peer_cache.get(db_path)
    if hit and time.monotonic() - hit[0] < PEER_TTL_S:
        return hit[1]
    peers = universe(db_path)
    _peer_cache[db_path] = (time.monotonic(), peers)
    return peers


def comps(book: B.Book, peers: list[dict]) -> list[dict]:
    """The company valued at its peers' quartile multiples. Peers exclude the company."""
    own = _metrics(book)
    others = [p for p in peers if p["ticker"] != book.ticker]
    lenses = []
    pe = _quartiles([p.get("pe_ntm") for p in others])
    if pe and own.get("eps_ntm"):
        lenses.append({"lens": "trading comps, P/E next twelve months", "key": "pe_ntm",
                       "low": pe[0] * own["eps_ntm"], "mid": pe[1] * own["eps_ntm"],
                       "high": pe[2] * own["eps_ntm"], "own_multiple": own.get("pe_ntm"),
                       "peer_quartiles": pe, "peers": len(others),
                       "basis": "peers' price to next-twelve-months consensus EPS at their "
                                "lower quartile, median and upper quartile, times this "
                                "company's " + own["eps_basis"]})
    evs = _quartiles([p.get("ev_sales") for p in others])
    if evs and own.get("revenue_ps"):
        lenses.append({"lens": f"trading comps, EV / FY{own['revenue_year']} revenue",
                       "key": "ev_sales",
                       "low": evs[0] * own["revenue_ps"] + own["net_cash_ps"],
                       "mid": evs[1] * own["revenue_ps"] + own["net_cash_ps"],
                       "high": evs[2] * own["revenue_ps"] + own["net_cash_ps"],
                       "own_multiple": own.get("ev_sales"), "peer_quartiles": evs,
                       "peers": len(others),
                       "basis": "peers' enterprise value over last fiscal year revenue at "
                                "their quartiles, times this company's revenue, plus its net "
                                "cash"})
    return lenses


# --- the market's own markers -----------------------------------------------------
def price_targets(book: B.Book) -> dict | None:
    conn = db.get_connection(book.db_path)
    try:
        row = conn.execute(
            """SELECT value, low, high, as_of, note FROM consensus_estimates
                WHERE company_id = ? AND metric = 'PriceTarget' AND source IN ('nasdaq', 'fmp', 'manual')
                ORDER BY as_of DESC LIMIT 1""", (book.company_id,)).fetchone()
    finally:
        conn.close()
    if row is None or row["low"] is None or row["high"] is None:
        return None
    return {"lens": "analyst price targets", "key": "targets", "low": row["low"],
            "mid": row["value"], "high": row["high"],
            "basis": f"consensus price target, lowest to highest, as of {row['as_of']} ({row['note']})"}


def trading_range(book: B.Book, weeks: int = 52) -> dict | None:
    conn = db.get_connection(book.db_path)
    try:
        start = (dt.date.fromisoformat(book.sotp["price_date"][:10])
                 - dt.timedelta(weeks=weeks)).isoformat()
        row = conn.execute(
            """SELECT MIN(close) lo, MAX(close) hi, COUNT(*) n FROM prices
                WHERE company_id = ? AND interval = '1d' AND as_of > ?""",
            (book.company_id, start)).fetchone()
    finally:
        conn.close()
    if row is None or not row["n"]:
        return None
    return {"lens": "52-week trading range", "key": "range", "low": row["lo"],
            "mid": book.close, "high": row["hi"],
            "basis": f"lowest and highest daily close since {start}"}


def company(db_path, ticker: str, peers: list[dict] | None = None) -> dict | None:
    """Every lens for one company. None for an unknown ticker."""
    book = B.Book(db_path, ticker)
    if book.verdict is None:
        return None
    if not book.ok:
        return {"ok": False, "ticker": book.verdict["ticker"], "reason": book.reason}
    peers = cached_universe(db_path) if peers is None else peers
    lenses = [{"lens": "sum of the parts, discount rate ±1 point", "key": "sotp_wacc",
               **discount_range(book)}]
    split = revenue_split(book)
    if split["ok"] and split["matched_equity"] is not None:
        lenses.append({"lens": f"sum of the parts, revenue matched to FY{split['year']} guidance",
                       "key": "sotp_guidance", "low": split["matched_low"],
                       "mid": split["matched_equity"], "high": split["matched_high"],
                       "basis": split["basis"]})
    lenses += comps(book, peers)
    for extra in (price_targets(book), trading_range(book)):
        if extra:
            lenses.append(extra)
    return {"ok": True, "ticker": book.ticker, "name": book.name, "close": book.close,
            "price_date": book.sotp.get("price_date"), "equity_per_share": book.equity,
            "revenue_split": split, "lenses": lenses}
