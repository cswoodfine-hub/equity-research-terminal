"""The few things on this engine worth knowing today, each with the number that makes it.

The change feed answers "what moved" and answers it exhaustively: four hundred rows a
week, sorted by a significance rank that cannot tell a risk-factor diff from an approval.
That is the right structure for working through coverage and the wrong one for opening the
terminal, where the question is narrower and harder: of everything that happened, which
three or four would an analyst be embarrassed not to know?

So this ranks by materiality rather than by recency, and each line carries what makes it
matter: a deal its price, an approval the drug, a safety notice the product. A deal with
no terms is not shown at all, because "J&J announces collaboration" says something
happened and nothing about whether it counts.

The forward half lives in ahead(): what is dated inside the next month, soonest first. A
readout and a panel vote were two sections asking the same question, and the answer to
both is a date with a company against it.

The ranking is a stated order, not a score. A deal worth billions outranks a CEO leaving,
which outranks a trial stopping, which outranks a date moving, and a reader who disagrees
can see the order here rather than inferring it from the output.
"""

from __future__ import annotations

import datetime as dt
import re

import db
import deal_terms
import regulatory
import whatchanged

# How far back a headline can come from. A week: the page answers "what happened since I
# last looked", and a fortnight put things on it that had already been read and acted on.
LOOKBACK_DAYS = 7

# How far forward the companion view looks. A month is the horizon a readout or a decision
# is actually planned against.
AHEAD_DAYS = 30

# How many to show. Four fits above the fold and forces the ranking to mean something.
LIMIT = 4

# The order things matter in, most first. Stated rather than scored, so it can be argued
# with. A kind not listed here does not reach the front page at all.
ORDER = ("deal", "approval", "regulatory", "leadership", "trial_stopped")

# The same for the forward view. A decision date outranks a vote that informs it, which
# outranks a readout whose date the registry only estimates.
AHEAD_ORDER = ("PDUFA", "panel", "data readout")

# A trial that has stopped, rather than one that has started or changed pace.
_STOPPED = re.compile(r"->\s*(?:Terminated|Withdrawn|Suspended)\b", re.I)


def _money(value: float) -> str:
    if value >= 1e9:
        return f"${value / 1e9:.2f}".rstrip("0").rstrip(".") + "bn"
    return f"${value / 1e6:,.0f}m"


def _pair(label: str, value) -> dict:
    return {"label": label, "value": str(value)}


def _deals(conn, tickers, since) -> list:
    """Business development, ranked by what it pays.

    Only a deal whose terms are known: without a figure there is no way to tell a research
    collaboration from a takeover, and "J&J announces collaboration" is a headline about
    nothing.
    """
    out = []
    for row in conn.execute(
            "SELECT c.ticker, c.name, d.counterparty, d.deal_type, d.event_date, d.area,"
            "       d.upfront_usd, d.equity_usd, d.milestones_usd, d.option_usd,"
            "       d.total_usd, d.headline_usd, d.terms_evidence, d.source_url"
            "  FROM deals d JOIN companies c ON c.id = d.company_id"
            " WHERE d.headline_usd IS NOT NULL AND d.event_date >= ?"
            " ORDER BY d.headline_usd DESC", (since,)):
        if tickers is not None and row["ticker"] not in tickers:
            continue
        terms = {f: row[f + "_usd"] for f in deal_terms.FIELDS}
        # The four commitments as their own rows, because that is the whole point of
        # reading them apart: what is being spent now sits next to what is contingent.
        summary = [_pair(label, _money(terms[field]))
                   for field, label in (("upfront", "Upfront"), ("equity", "Equity"),
                                        ("milestones", "Milestones"),
                                        ("option", "Option to acquire"),
                                        ("total", "Total"))
                   if terms.get(field)]
        summary.append(_pair("Counterparty", row["counterparty"]))
        if row["area"]:
            summary.append(_pair("For", row["area"]))
        out.append({
            "kind": "deal", "ticker": row["ticker"], "name": row["name"],
            "date": (row["event_date"] or "")[:10],
            "headline": (f"{row['ticker']} {row['deal_type'] or 'deal'} with "
                         f"{row['counterparty']}"),
            "figure": _money(row["headline_usd"]),
            "detail": deal_terms.summary(terms),
            "summary": summary,
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
        summary = [_pair("What", text)]
        if item.get("reason"):
            summary.append(_pair("Why it is flagged", item["reason"]))
        summary.append(_pair("Read on", (item.get("date") or "")[:10]))
        out.append({
            "kind": kind, "ticker": ticker, "name": "",
            "date": (item.get("date") or "")[:10],
            "headline": f"{ticker} {text}",
            "figure": figure(item) if callable(figure) else figure,
            "detail": "", "summary": summary,
            "evidence": item.get("headline"), "url": None, "rank": 0,
        })
    return out


def _regulatory(db_path, tickers, since) -> list:
    """What the agency announced about a covered company.

    The forward half of the regulatory stream is the ahead view now, so its announced half
    reaches the reader here or nowhere. Already filtered to events upstream: a guidance
    republished is not one, and neither is a ventilator recall at a company this universe
    does not cover.
    """
    out = []
    for item in regulatory.build(db_path).get("behind", []):
        ticker = (item.get("ticker") or "").upper()
        if not ticker or (tickers is not None and ticker not in tickers):
            continue
        if (item.get("date") or "") < since:
            continue
        title = item.get("title") or ""
        summary = [_pair("What", title), _pair("Source", item.get("kind") or "FDA")]
        if item.get("detail"):
            summary.append(_pair("Detail", item["detail"]))
        out.append({
            "kind": "regulatory", "ticker": ticker, "name": "",
            "date": (item.get("date") or "")[:10],
            "headline": f"{ticker} {title}",
            "figure": _REGULATORY_LABEL.get(item.get("kind"), "FDA"),
            "detail": item.get("detail") or "", "summary": summary,
            "evidence": None, "url": item.get("url"), "rank": 0,
        })
    return out


_REGULATORY_LABEL = {"safety": "safety notice", "press": "FDA announcement",
                     "drugs": "FDA drugs item", "panel": "panel vote"}


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
            _from_feed(feed, wanted, ("new_approval", "efficacy_supplement"), "approval",
                       lambda i: ("approval" if i["change_type"] == "new_approval"
                                  else "label expansion"), since)
            + _deals(conn, wanted, since)
            + _regulatory(db_path, wanted, since)
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
        when = int(digits) if digits.isdigit() else 0
        return (ORDER.index(item["kind"]), -item["rank"], -when)

    # Kind first, then size within a kind, then the most recent. One per company, because
    # four headlines about one filer is a page about that filer rather than about the
    # engine.
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


# --- the other direction ---------------------------------------------------------------

def _confidence(kind: str, curated, confidence) -> str:
    """Where the date came from, in the words that name its actual source.

    Not one sentence for all of them: a PDUFA date is read out of an 8-K and a readout out
    of ClinicalTrials.gov, and calling both "derived from the registry" names a source
    that never carried half of them.
    """
    if curated:
        return "curated, entered by hand"
    if kind == "PDUFA":
        return "read from the 8-K that announced the filing, flagged for review"
    if kind == "data readout":
        return (f"derived from the registry primary completion date, "
                f"{confidence or 'estimated'} and liable to slip")
    return f"derived, {confidence or 'estimated'}"


def _catalysts(conn, tickers, today, until) -> list:
    """Dated events inside the window: a decision, a readout, whatever is on the calendar.

    A derived readout is a candidate rather than an event, since it comes from a registry
    completion date that slips, and the row says so instead of the reader having to know.
    """
    out = []
    for row in conn.execute(
            "SELECT c.ticker, c.name, k.catalyst_type, k.expected_date, k.title,"
            "       k.description, k.is_curated, k.source_url, k.date_confidence"
            "  FROM catalysts k JOIN companies c ON c.id = k.company_id"
            " WHERE k.expected_date >= ? AND k.expected_date <= ?"
            " ORDER BY k.expected_date", (today, until)):
        if tickers is not None and row["ticker"] not in tickers:
            continue
        kind = row["catalyst_type"] or "data readout"
        summary = [_pair("What", row["title"] or ""),
                   _pair("Expected", row["expected_date"][:10])]
        # The description is an NCT id for a readout and the announcing sentence for a
        # decision date, so it is labelled by what it is rather than always as a study.
        note = row["description"] or ""
        evidence = None
        if note.startswith("NCT"):
            summary.append(_pair("Study", note))
        elif note:
            evidence = note
        summary.append(_pair("Confidence", _confidence(kind, row["is_curated"],
                                                       row["date_confidence"])))
        out.append({
            "kind": kind, "ticker": row["ticker"], "name": row["name"],
            "date": row["expected_date"][:10],
            "headline": f"{row['ticker']} {row['title'] or kind}",
            "figure": kind, "detail": note if note.startswith("NCT") else "",
            "summary": summary, "evidence": evidence, "url": row["source_url"],
            # Firm means a date somebody stated, whether by hand or in a filing. A
            # registry completion date is nobody's commitment.
            "curated": bool(row["is_curated"]) or kind != "data readout",
        })
    return out


def _panels(conn, tickers, today, until) -> list:
    """A scheduled advisory committee vote, the one firm regulatory date free data gives."""
    out = []
    for row in conn.execute(
            "SELECT m.meeting_date, m.product, m.committee, m.application_label, m.url,"
            "       c.ticker, c.name"
            "  FROM adcomm_meetings m LEFT JOIN companies c ON c.id = m.company_id"
            " WHERE m.meeting_date >= ? AND m.meeting_date <= ?"
            " ORDER BY m.meeting_date", (today, until)):
        if tickers is not None and row["ticker"] not in tickers:
            continue
        summary = [_pair("Product", row["product"] or ""),
                   _pair("Committee", row["committee"] or ""),
                   _pair("Meets", row["meeting_date"][:10])]
        if row["application_label"]:
            summary.append(_pair("Application", row["application_label"]))
        out.append({
            "kind": "panel", "ticker": row["ticker"] or "", "name": row["name"] or "",
            "date": row["meeting_date"][:10],
            "headline": (f"{row['ticker'] + ' ' if row['ticker'] else ''}"
                         f"advisory committee votes on {row['product']}"),
            "figure": "panel vote", "detail": row["committee"] or "",
            "summary": summary, "evidence": None, "url": row["url"], "curated": True,
        })
    return out


def ahead(db_path=None, tickers=None, days: int = AHEAD_DAYS, today=None) -> list:
    """What is dated inside the window, soonest first.

    The mirror of build(): one view of what happened, one of what is about to. A panel
    vote and a readout were two sections asking the same question, and the answer to both
    is a date with a company against it.
    """
    today = today or dt.date.today()
    until = (today + dt.timedelta(days=days)).isoformat()
    wanted = set(tickers) if tickers is not None else None
    conn = db.get_connection(db_path)
    try:
        items = (_catalysts(conn, wanted, today.isoformat(), until)
                 + _panels(conn, wanted, today.isoformat(), until))
    finally:
        conn.close()

    def order(item):
        kind = item["kind"]
        return (item["date"],
                AHEAD_ORDER.index(kind) if kind in AHEAD_ORDER else len(AHEAD_ORDER))

    # A calendar sorts by date. Within a day the firmest kind leads: a decision outranks
    # the vote that informs it, which outranks a readout the registry only estimates.
    items.sort(key=order)
    return items
