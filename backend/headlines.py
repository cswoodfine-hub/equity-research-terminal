"""The few things on this engine worth knowing today, each with the number that makes it.

The change feed answers "what moved" and answers it exhaustively: four hundred rows a
week, sorted by a significance rank that cannot tell a risk-factor diff from an approval.
That is the right structure for working through coverage and the wrong one for opening the
terminal, where the question is narrower and harder: of everything that happened, which
three or four would an analyst be embarrassed not to know?

So this ranks by materiality rather than by recency, and each line carries what makes it
matter: a deal its price, an approval the drug, a panel vote its date. A deal with no terms
is not shown at all, because "J&J announces collaboration" says something happened and
nothing about whether it counts.

The ranking is a stated order, not a score. A deal worth billions outranks a CEO leaving,
which outranks a trial stopping, which outranks a date moving, and a reader who disagrees
can see the order here rather than inferring it from the output.
"""

from __future__ import annotations

import datetime as dt
import re

import db
import deal_terms
import whatchanged

# How far back a headline can come from. Two weeks, because the front page is about the
# state of things rather than about one day, and a deal signed nine days ago is still the
# thing that happened on this engine.
LOOKBACK_DAYS = 14

# How many to show. Four fits above the fold and forces the ranking to mean something.
LIMIT = 4

# The order things matter in, most first. Stated rather than scored, so it can be argued
# with. A kind not listed here does not reach the front page at all.
ORDER = ("deal", "approval", "panel", "leadership", "trial_stopped")

# A trial that has stopped, rather than one that has started or changed pace.
_STOPPED = re.compile(r"->\s*(?:Terminated|Withdrawn|Suspended)\b", re.I)


def _money(value: float) -> str:
    if value >= 1e9:
        return f"${value / 1e9:.2f}".rstrip("0").rstrip(".") + "bn"
    return f"${value / 1e6:,.0f}m"


def _deals(conn, tickers, since) -> list:
    """Business development, ranked by what it pays.

    Only a deal whose terms are known: without a figure there is no way to tell a research
    collaboration from a takeover, and "J&J announces collaboration" is a headline about
    nothing.
    """
    out = []
    for row in conn.execute(
            "SELECT c.ticker, d.counterparty, d.deal_type, d.event_date, d.area,"
            "       d.upfront_usd, d.equity_usd, d.milestones_usd, d.option_usd,"
            "       d.total_usd, d.headline_usd, d.terms_evidence, d.source_url"
            "  FROM deals d JOIN companies c ON c.id = d.company_id"
            " WHERE d.headline_usd IS NOT NULL AND d.event_date >= ?"
            " ORDER BY d.headline_usd DESC", (since,)):
        if tickers is not None and row["ticker"] not in tickers:
            continue
        terms = {f: row[f + "_usd"] for f in deal_terms.FIELDS}
        out.append({
            "kind": "deal", "ticker": row["ticker"], "date": (row["event_date"] or "")[:10],
            "headline": (f"{row['ticker']} {row['deal_type'] or 'deal'} with "
                         f"{row['counterparty']}"),
            "figure": _money(row["headline_usd"]),
            "detail": deal_terms.summary(terms),
            "evidence": row["terms_evidence"],
            "url": row["source_url"],
            "rank": row["headline_usd"],
        })
    return out


def _from_feed(feed, tickers, kinds, kind, figure, since="", matching=None) -> list:
    """Feed items of one change type, as headlines.

    Read through whatchanged rather than off the changes table: the ticker and the
    readable headline are derived there, and two derivations of the same sentence would
    drift apart.
    """
    out = []
    for item in feed:
        if item.get("kind") != "change" or item.get("change_type") not in kinds:
            continue
        ticker = (item.get("ticker") or "").upper()
        if not ticker or (tickers is not None and ticker not in tickers):
            continue
        # Bounded on the event date as well as on detection. A departure announced in
        # December and first read this week is not this week's news, and dating it today
        # would be wrong twice over.
        if since and (item.get("date") or "")[:10] < since:
            continue
        if matching and not matching.search(item.get("headline") or ""):
            continue
        text = item.get("headline") or ""
        if text.upper().startswith(ticker + " "):
            text = text[len(ticker) + 1:]
        out.append({
            "kind": kind, "ticker": ticker, "date": (item.get("date") or "")[:10],
            "headline": f"{ticker} {text}",
            "figure": figure(item) if callable(figure) else figure,
            "detail": "", "evidence": item.get("headline"), "url": None, "rank": 0,
        })
    return out


def _panels(conn, tickers, today) -> list:
    """A scheduled advisory committee vote, the one firm regulatory date free data gives."""
    out = []
    for row in conn.execute(
            "SELECT m.meeting_date, m.product, m.committee, m.url, c.ticker"
            "  FROM adcomm_meetings m JOIN companies c ON c.id = m.company_id"
            " WHERE m.meeting_date >= ? ORDER BY m.meeting_date", (today,)):
        if tickers is not None and row["ticker"] not in tickers:
            continue
        out.append({
            "kind": "panel", "ticker": row["ticker"], "date": row["meeting_date"][:10],
            "headline": f"{row['ticker']} advisory committee votes on {row['product']}",
            "figure": "panel vote", "detail": row["committee"] or "",
            "evidence": None, "url": row["url"], "rank": 0,
        })
    return out


def build(db_path=None, tickers=None, days: int = LOOKBACK_DAYS, limit: int = LIMIT,
          today=None) -> list:
    """The ranked headlines for a set of companies, or for the whole universe.

    ``tickers`` narrows to one engine's cohort. Passing None reads everything, which is
    what a caller with no engine open wants.
    """
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=days)).isoformat()
    wanted = set(tickers) if tickers is not None else None
    conn = db.get_connection(db_path)
    try:
        feed = whatchanged.build_feed(db_path, days=days)
        items = (
            _deals(conn, wanted, since)
            + _from_feed(feed, wanted, ("new_approval", "efficacy_supplement"), "approval",
                         lambda i: ("approval" if i["change_type"] == "new_approval"
                                    else "label expansion"), since)
            + _panels(conn, wanted, today.isoformat())
            + _from_feed(feed, wanted, ("leadership_change",), "leadership",
                         "senior change", since)
            # A trial stopping, not a trial starting. A status change to Recruiting is
            # a programme beginning, which is not a headline; Terminated, Withdrawn and
            # Suspended are the fastest a programme's value ever changes.
            + _from_feed(feed, wanted, ("status_change",), "trial_stopped",
                         "trial stopped", since, _STOPPED))
    finally:
        conn.close()

    def order(item):
        digits = (item["date"] or "").replace("-", "")[:8]
        # A panel vote is the one forward-dated kind, so the soonest leads; everything
        # else has happened, and the most recent leads.
        when = int(digits) if digits.isdigit() else 0
        return (ORDER.index(item["kind"]), -item["rank"],
                when if item["kind"] == "panel" else -when)

    # Kind first, then size within a kind, then date. One per company, because four
    # headlines about one filer is a page about that filer rather than about the engine.
    items.sort(key=order)
    seen, out = set(), []
    for item in items:
        if item["ticker"] in seen:
            continue
        seen.add(item["ticker"])
        out.append(item)
        if len(out) >= limit:
            break
    return out
