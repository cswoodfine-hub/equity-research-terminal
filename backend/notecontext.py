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

# A news headline that announces a deal. The IR feed names the counterparty and often
# the therapeutic area in the headline itself, so the note can name an acquisition or a
# licence without any model call and without inventing a party. A generic 8-K item that
# names no one is handled by the note prompt, which forbids inventing a counterparty.
# Stems, so "acqui" matches acquire and acquisition alike; no trailing boundary, which
# would stop a stem from matching the longer word it begins.
_DEAL_RE = re.compile(
    r"\b(acqui|merger|tender offer|licen[sc]|collaborat|deal with|partnership|"
    r"divest|joint venture|to buy|takeover)", re.I)
# The filing-form prefix the news pipeline puts on an EDGAR-sourced headline.
_FILING_PREFIX = re.compile(r"^\s*\d*-?[A-Z0-9]{1,3}\s*:\s*", re.I)
# Deal and filing vocabulary, dropped when keying a headline for de-duplication so the
# counterparty is what identifies a deal. One transaction is announced, tendered and
# completed under three headlines that all share the target's name.
_DEAL_VOCAB = frozenset((
    "acquire", "acquires", "acquired", "acquiring", "acquisition", "announce",
    "announces", "agrees", "agreement", "enters", "completes", "completed", "complete",
    "tender", "offer", "deal", "licenses", "license", "licence", "licensing",
    "collaboration", "collaborate", "collaborates", "merger", "merges", "partnership",
    "divest", "divestiture", "novel", "with", "from", "into", "will", "share",
    "shares", "stake", "company", "therapeutics", "pharmaceuticals",
))


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
                within_days: int = 240, limit: int = 4) -> list[str]:
    """Recent M&A, licensing and collaboration headlines from the IR news feed.

    The headline is the company's own words, so the counterparty and often the area
    read straight out of it. Several headlines can be stages of one deal (agreed, then
    completed); they are passed through and the note prompt collapses them to the latest
    state. A foreign filer's 6-K headline is descriptive; a US 8-K item names no party
    and so does not match here, which is correct, since inventing one is forbidden.
    """
    cutoff = (today - dt.timedelta(days=within_days)).isoformat()
    own = conn.execute("SELECT ticker, name FROM companies WHERE id = ?",
                       (cid,)).fetchone()
    own_tokens = set(re.findall(r"[a-z]{3,}",
                                f"{own['ticker']} {own['name']}".lower())) if own else set()
    rows = conn.execute(
        """
        SELECT title, published_at FROM news
         WHERE company_id = ? AND title IS NOT NULL AND published_at >= ?
         ORDER BY published_at DESC
        """, (cid, cutoff)).fetchall()
    lines, seen = [], []
    for r in rows:
        if not _DEAL_RE.search(r["title"]):
            continue
        clean = _FILING_PREFIX.sub("", r["title"]).strip()
        # The distinctive words of the headline: the counterparty and any named asset,
        # once the company's own name and the deal vocabulary are removed.
        key = {w for w in re.findall(r"[a-z]{4,}", clean.lower())
               if w not in _DEAL_VOCAB and w not in own_tokens}
        if key and any(key & prior for prior in seen):
            continue                                   # a later stage of a kept deal
        seen.append(key)
        lines.append(f"{clean} ({(r['published_at'] or '')[:10]}).")
        if len(lines) >= limit:
            break
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
