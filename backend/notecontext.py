"""Company context for the morning note.

The change feed says what is new; this says what the company is. It reads a compact,
factual snapshot from the tables a refresh already fills, so the note can lead with a
number and tie a catalyst or an exclusivity loss to the revenue behind it, rather than
reading out a list of events with no sense of the business.

Every line is a fact already stored: reported revenue and its year-on-year change, net
income, R&D, the recent share move, and any Phase 2 or Phase 3 trial readouts. A figure
that is not in the database is left out, never estimated. When nothing is known the
context is empty and the note falls back to the feed alone.
"""

from __future__ import annotations

import datetime as dt
import re

import db

_METRIC_LABEL = {
    "Revenues": "Revenue",
    "NetIncomeLoss": "Net income",
    "ResearchAndDevelopmentExpense": "R&D",
}
_ANNUAL_METRICS = ("Revenues", "NetIncomeLoss", "ResearchAndDevelopmentExpense")
_YEAR_MIN, _YEAR_MAX = 350, 380     # a quarter's year-ago comparable, in days

# How each deal type reads at the head of a line. Deals are read from filings into the
# deals table by the deals extractor, which names the counterparty, the value where the
# text states one, and the area; the note reads them here.
_DEAL_VERB = {
    "acquisition": "Acquired",
    "licensing": "Licensing deal with",
    "collaboration": "Collaboration with",
    "divestiture": "Divested to",
}
# The headline figure inside a stored value, which sometimes carries the whole
# consideration clause (a per-share price plus a contingent value right). The note wants
# the number, not the paragraph.
_VALUE_HEAD = re.compile(
    r"\$[\d.,]+\s*(?:billion|million|bn|mn|per\s*share|/\s*share)", re.I)


def _short_value(value: str | None) -> str | None:
    if not value:
        return None
    match = _VALUE_HEAD.search(value)
    if match:
        return match.group(0)
    return value if len(value) <= 40 else None


def _party_key(counterparty: str) -> str:
    """The first significant word of a party, the stable handle for de-duplicating the
    several filings of one deal."""
    tokens = re.findall(r"[a-z0-9]{3,}", (counterparty or "").lower())
    return tokens[0] if tokens else (counterparty or "").lower()


def _short_party(counterparty: str) -> str:
    """The name, trimmed of a trailing corporate structure. A press release can name the
    party as its full legal chain ("X, (Y Group), through its subsidiary Z"); the note
    wants the name it is known by. Only a long value is trimmed, so "Apellis
    Pharmaceuticals, Inc." is left alone."""
    counterparty = counterparty.strip()
    if len(counterparty) <= 50:
        return counterparty
    head = re.split(r"[,(]", counterparty, 1)[0].strip()
    return head or counterparty[:50]


def _company_id(conn, ticker: str):
    row = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                       (ticker.upper(),)).fetchone()
    return row["id"] if row else None


def _fmt_money(value, unit) -> str | None:
    """A reported figure as a signed magnitude with its unit: 65.2B USD, -1.4B DKK."""
    if value is None:
        return None
    mag = abs(value)
    if mag >= 1e9:
        num = f"{value / 1e9:.1f}B"
    elif mag >= 1e6:
        num = f"{value / 1e6:.0f}M"
    else:
        num = f"{value:.0f}"
    return f"{num} {unit}".strip() if unit else num


def _yoy(value, prior) -> float | None:
    """Year-on-year change, or None when there is no positive base to divide by."""
    if value is None or not prior or prior <= 0:
        return None
    return (value - prior) / prior


def _annual(conn, cid: int, metric: str):
    """The latest full year for a metric and its year-before value.

    Rows are read oldest first so a later restatement of the same fiscal year overwrites
    the earlier one; the prior value is the year before the latest, not merely the second
    row, so a gap in the history never mislabels the comparison."""
    by_year: dict[int, tuple] = {}
    for r in conn.execute(
        """
        SELECT fiscal_year, value, unit FROM financials
         WHERE company_id = ? AND metric = ? AND period_type = 'FY'
               AND fiscal_period = '12M' AND value IS NOT NULL AND fiscal_year IS NOT NULL
         ORDER BY period_end ASC
        """, (cid, metric)):
        by_year[r["fiscal_year"]] = (r["value"], r["unit"])
    if not by_year:
        return None
    year = max(by_year)
    value, unit = by_year[year]
    prior = by_year.get(year - 1, (None,))[0]
    return year, value, unit, prior


def _financials_lines(conn, cid: int) -> list[str]:
    lines = []
    for metric in _ANNUAL_METRICS:
        got = _annual(conn, cid, metric)
        if not got:
            continue
        year, value, unit, prior = got
        money = _fmt_money(value, unit)
        yoy = _yoy(value, prior)
        label = _METRIC_LABEL[metric]
        if yoy is not None:
            lines.append(f"{label} FY{year} {money}, {yoy * 100:+.0f}% vs FY{year - 1}.")
        else:
            lines.append(f"{label} FY{year} {money}.")
    return lines


def _quarter_line(conn, cid: int) -> str | None:
    """Latest reported quarter revenue with its year-on-year change.

    The freshest read on the growth line the annual figure smooths over. The year-ago
    quarter is matched on a date window rather than a fiscal-period label, since every
    quarter is stored as a bare '3M' and only the period end tells them apart.
    """
    rows = conn.execute(
        """
        SELECT period_end, value, unit FROM financials
         WHERE company_id = ? AND metric = 'Revenues' AND period_type = 'Q'
               AND fiscal_period = '3M' AND value IS NOT NULL
         ORDER BY period_end DESC
        """, (cid,)).fetchall()
    if not rows:
        return None
    latest = rows[0]
    try:
        end = dt.date.fromisoformat(latest["period_end"][:10])
    except (TypeError, ValueError):
        return None
    money = _fmt_money(latest["value"], latest["unit"])
    prior = None
    for r in rows[1:]:
        try:
            gap = (end - dt.date.fromisoformat(r["period_end"][:10])).days
        except (TypeError, ValueError):
            continue
        if _YEAR_MIN <= gap <= _YEAR_MAX:
            prior = r["value"]
            break
    yoy = _yoy(latest["value"], prior)
    quarter = f"Q ending {end.isoformat()} revenue {money}"
    return f"{quarter}, {yoy * 100:+.0f}% YoY." if yoy is not None else f"{quarter}."


def _price_line(conn, cid: int) -> str | None:
    """Latest daily close and the move over about one and three months."""
    rows = conn.execute(
        """
        SELECT as_of, close FROM prices
         WHERE company_id = ? AND interval = '1d' AND close IS NOT NULL
         ORDER BY as_of DESC LIMIT 70
        """, (cid,)).fetchall()
    if not rows:
        return None
    last = rows[0]

    def move(back: int):
        if len(rows) > back and rows[back]["close"]:
            return (last["close"] - rows[back]["close"]) / rows[back]["close"]
        return None

    parts = [f"last close {last['close']:.2f} on {last['as_of'][:10]}"]
    for back, label in ((21, "1 month"), (63, "3 months")):
        m = move(back)
        if m is not None:
            parts.append(f"{m * 100:+.0f}% over {label}")
    return ", ".join(parts) + "."


def _readout_lines(conn, cid: int, today: dt.date,
                   within_days: int = 365, limit: int = 4) -> list[str]:
    cutoff = (today - dt.timedelta(days=within_days)).isoformat()
    rows = conn.execute(
        """
        SELECT drug, phase, outcome, event_date FROM trial_readouts
         WHERE company_id = ? AND outcome IN ('positive', 'negative')
               AND event_date >= ?
         ORDER BY event_date DESC LIMIT ?
        """, (cid, cutoff, limit)).fetchall()
    return [f"Phase {r['phase']} {r['outcome']} readout for {r['drug']} "
            f"({r['event_date']})." for r in rows]


def _deal_lines(conn, cid: int, today: dt.date,
                within_days: int = 400, limit: int = 4) -> list[str]:
    """Recent M&A, licensing and collaboration deals read from the deals table.

    The deals extractor pulls the counterparty, the value where the filing states one,
    and the area out of the press release, so a US filer whose 8-K names no party is
    covered as well as a foreign filer's 6-K. A deal can be filed more than once, when it
    is agreed then completed, or recapped in a later earnings release; the rows are
    de-duplicated on the counterparty keeping the earliest date, so the announcement date
    wins over a recap and the deal reads once.
    """
    cutoff = (today - dt.timedelta(days=within_days)).isoformat()
    rows = conn.execute(
        """
        SELECT deal_type, counterparty, value, area, event_date FROM deals
         WHERE company_id = ? AND deal_type IN
               ('acquisition', 'licensing', 'collaboration', 'divestiture')
               AND counterparty IS NOT NULL AND event_date IS NOT NULL
         ORDER BY event_date ASC
        """, (cid,)).fetchall()
    merged: dict = {}
    for r in rows:
        key = _party_key(r["counterparty"])
        deal = merged.get(key)
        if deal is None:                               # first row is the earliest date
            merged[key] = {"deal_type": r["deal_type"], "counterparty": r["counterparty"],
                           "value": r["value"], "area": r["area"],
                           "event_date": r["event_date"]}
            continue
        deal["value"] = deal["value"] or r["value"]    # fill a figure from any later filing
        deal["area"] = deal["area"] or r["area"]
    kept = [d for d in merged.values() if (d["event_date"] or "") >= cutoff]
    kept.sort(key=lambda d: d["event_date"] or "", reverse=True)
    lines = []
    for d in kept[:limit]:
        parts = [f"{_DEAL_VERB.get(d['deal_type'], 'Deal with')} "
                 f"{_short_party(d['counterparty'])}"]
        value = _short_value(d["value"])
        if value:
            parts.append(f"for {value}")
        if d["area"]:
            parts.append(f"({d['area']})")
        lines.append(" ".join(parts) + f", {(d['event_date'] or '')[:10]}.")
    return lines


def company_context(db_path=None, ticker: str = "", today=None) -> str:
    """A factual snapshot of the company for the note, or "" when nothing is known."""
    today = today or dt.date.today()
    conn = db.get_connection(db_path)
    try:
        cid = _company_id(conn, ticker)
        if cid is None:
            return ""
        blocks = []
        fin = _financials_lines(conn, cid)
        quarter = _quarter_line(conn, cid)
        if quarter:
            fin.append(quarter)
        if fin:
            blocks.append("Financials: " + " ".join(fin))
        price = _price_line(conn, cid)
        if price:
            blocks.append("Share price: " + price)
        reads = _readout_lines(conn, cid, today)
        if reads:
            blocks.append("Trial readouts: " + " ".join(reads))
        deals = _deal_lines(conn, cid, today)
        if deals:
            blocks.append("Recent deals: " + " ".join(deals))
    finally:
        conn.close()
    return "\n".join(blocks)
