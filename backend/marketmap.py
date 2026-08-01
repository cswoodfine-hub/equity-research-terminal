"""The engine at a glance: every company as a box, sized by what it runs on.

A grid of ninety price panels shows each company's shape and nothing about the group. This
answers the other question, the one a reader opens the terminal already holding: where is
the money on this engine, and which way has it moved.

Area is not market capitalisation, because that number is not honestly available here. It
would be shares outstanding times the last close, and for a foreign private issuer the
share count is in ordinary shares while the quoted price is per ADR: GSK computes to 223bn
against a real ninety, and Sanofi to 53 against a real hundred and thirty. The ADR ratio is
not in any free source, so five of the eighteen majors would be wrong by a factor and
wrong in a chart is worse than absent.

So area is the thing each engine actually scales on, which differs because the companies
do. A major and a mid-cap are sized by revenue, the measure they are run and valued on. A
platform developer with no product is sized by cash, because that is what it has and what
decides how long it lasts. Each map says which, and no map mixes the two: an area that
means revenue for one box and cash for the next is a chart that cannot be read.

Colour is the price move over the window, diverging around zero. Colour and area are
independent on purpose: a large box that is deep red is the fact the page exists to show.
"""

from __future__ import annotations

import db
import engines
import fx
import productivity
import runway

# What area means on each engine, and the words that say so.
BY_REVENUE = "revenue"
BY_CASH = "cash"

METRIC_BY_ENGINE = {
    engines.PHARMA: BY_REVENUE,
    engines.BIOTECH: BY_REVENUE,
    engines.CELLGENE: BY_CASH,
}
LABELS = {
    BY_REVENUE: "sized by revenue, latest full year",
    BY_CASH: "sized by cash and investments",
}

# The price window the colour reads. A quarter is long enough that one day's move does not
# set the colour of a box and short enough to still be news.
WINDOW_DAYS = 90


def _change(conn, company_id: int, days: int):
    """Price change over the window, or None where the series is too short to say."""
    rows = conn.execute(
        "SELECT close FROM prices WHERE company_id = ? AND interval = '1d'"
        "  AND close IS NOT NULL AND as_of >= date('now', ?) ORDER BY as_of",
        (company_id, f"-{int(days)} days")).fetchall()
    if len(rows) < 5 or not rows[0]["close"]:
        return None
    return rows[-1]["close"] / rows[0]["close"] - 1


def build(db_path=None, engine: str | None = None, days: int = WINDOW_DAYS) -> dict:
    """{metric, label, window_days, rows, unsized} for one engine, or the whole universe.

    A company the metric cannot size is not drawn at zero: an area of nothing reads as a
    company of nothing. It is counted in ``unsized`` and named, so the map says what it
    left out rather than quietly being a map of the rest.
    """
    metric = METRIC_BY_ENGINE.get(engine, BY_REVENUE)
    homes = engines.home(db_path)
    conn = db.get_connection(db_path)
    try:
        rates = fx.latest_usd_rates(db_path)
        rows, unsized = [], []
        for company in conn.execute(
                "SELECT id, ticker, name FROM companies ORDER BY ticker"):
            if engine in engines.ENGINES and homes.get(company["ticker"]) != engine:
                continue
            if metric == BY_CASH:
                size = runway.liquidity(conn, company["id"])["available"]
            else:
                size = productivity.latest_revenue(conn, company["id"], rates)
            if not size or size <= 0:
                unsized.append(company["ticker"])
                continue
            rows.append({"ticker": company["ticker"], "name": company["name"],
                         "size": float(size),
                         "change": _change(conn, company["id"], days),
                         "engine": homes.get(company["ticker"])})
    finally:
        conn.close()
    rows.sort(key=lambda r: -r["size"])
    return {"metric": metric, "label": LABELS[metric], "window_days": days,
            "rows": rows, "unsized": unsized}
