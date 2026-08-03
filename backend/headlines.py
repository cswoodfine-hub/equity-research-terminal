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

# How many to show. Six fills two rows of the grid, and one per company means six is six
# different filers. Four was leaving a week that had a $2.58bn deal, three label
# expansions and a foreign filer's Phase 3 result looking like a quiet week.
LIMIT = 6

# The order things matter in, most first. Stated rather than scored, so it can be argued
# with. A kind not listed here does not reach the front page at all.
ORDER = ("deal", "reported", "approval", "regulatory", "filing", "leadership",
         "trial_stopped")

# The same for the forward view. A decision date outranks a vote that informs it, which
# outranks a readout whose date the registry only estimates.
AHEAD_ORDER = ("PDUFA", "panel", "data readout")

# A trial that has stopped, rather than one that has started or changed pace.
_STOPPED = re.compile(r"->\s*(?:Terminated|Withdrawn|Suspended)\b", re.I)

# A filing whose title is the news. An 8-K's title is an item label from a fixed
# vocabulary, "Regulation FD disclosure, Financial statements and exhibits", which says
# what section was used and nothing about what happened. A foreign filer's 6-K carries a
# free-text title that is the announcement itself: "HANSOH POSITIVE 2ND PHASE III RESULTS
# FOR RIZ-REZ" is a headline in the sense this page means.
_TITLED_FORMS = ("6-K",)

# Except that most 6-Ks are UK listing-rule housekeeping. A director's share dealing, a
# buyback tranche and a voting-rights total are filings a company must make, not things
# that happened to it.
_ROUTINE_FILING = re.compile(
    r"^(?:form\s+)?6-k$|director/pdmr|transaction in own shares|total voting rights|"
    r"holding\(s\) in company|admission of further securities|block listing|"
    r"annual financial report|notice of results|publication of|"
    r"result of (?:agm|meeting)|share buyback programme", re.I)


def _is_news(form: str, title: str) -> bool:
    """Whether a filing's title says what happened, or only which form was used."""
    title = (title or "").strip()
    return bool(title) and form in _TITLED_FORMS and not _ROUTINE_FILING.search(title)


def _money(value: float) -> str:
    if value >= 1e9:
        return f"${value / 1e9:.2f}".rstrip("0").rstrip(".") + "bn"
    return f"${value / 1e6:,.0f}m"


def _pair(label: str, value) -> dict:
    return {"label": label, "value": str(value)}


def _reported(conn, tickers, since) -> list:
    """Deals the press says are being discussed, which nobody has announced.

    These are not deals and the box has to say so in every place a reader looks: the chip
    carries the figure with "reported" beside it, the headline says talks rather than a
    verb that states one happened, and the first row of the detail names the publisher.
    The fetcher only stores them above a very high figure, so anything that reaches here
    is a story that moved both companies on the day it broke.
    """
    out = []
    for row in conn.execute(
            "SELECT c.ticker, c.name, r.counterparty, r.deal_type, r.event_date,"
            "       r.reported_value, r.reported_usd, r.quote, r.publisher, r.article_url"
            "  FROM reported_deals r JOIN companies c ON c.id = r.company_id"
            " WHERE r.event_date >= ? ORDER BY r.reported_usd DESC", (since,)):
        if tickers is not None and row["ticker"] not in tickers:
            continue
        out.append({
            "kind": "reported", "ticker": row["ticker"], "name": row["name"],
            "date": (row["event_date"] or "")[:10],
            "headline": (f'{row["ticker"]} reported in {row["deal_type"] or "deal"} '
                         f'talks with {row["counterparty"]}'),
            "figure": f'{_money(row["reported_usd"])} reported',
            "detail": "",
            "summary": [
                _pair("Status", "Reported, not announced"),
                _pair("Counterparty", row["counterparty"]),
                _pair("Reported value", row["reported_value"] or "not stated"),
                _pair("Publisher", row["publisher"] or "not stated"),
            ],
            "evidence": row["quote"],
            "url": row["article_url"],
            # Ranked below every confirmed deal whatever the figures, so a signed
            # billion always leads an unsigned hundred.
            "rank": row["reported_usd"],
        })
    return out


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
            + _reported(conn, wanted, since)
            + _regulatory(db_path, wanted, since)
            + _filings(conn, wanted, since)
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


# What stays capitalised when a shouted title is softened. A vowel test alone is not
# enough: "III" is all vowels and "HSCT-TMA" contains one, and both are abbreviations.
_ROMAN = re.compile(r"^[IVXLCDM]+$")
_HAS_VOWEL = re.compile(r"[AEIOU]")
_COMPOUND = re.compile(r"^[A-Z0-9]+[-/&][A-Z0-9]")
# Short words that are words rather than abbreviations, which is the one thing a length
# test cannot tell on its own.
_SHORT_WORDS = {"IN", "ON", "OF", "TO", "AT", "BY", "AS", "IS", "IT", "OR", "AN", "UP",
                "WE", "DO", "NO", "SO", "BE", "HE", "IF", "MY", "US",
                "THE", "AND", "FOR", "NEW", "OUR", "ITS", "ALL", "TWO", "ONE", "HAS",
                "ARE", "WAS", "OUT", "OFF", "PER", "VIA", "TOP", "BIG", "KEY", "NON",
                "PRE", "MID", "END", "USE", "SET", "GET", "MAY", "CAN", "WILL", "WITH",
                "FROM", "INTO", "OVER", "THAT", "THIS", "MORE", "FULL", "NEXT", "FIRST"}

# An ordinal is a number and a word ending, not an abbreviation: "2ND QUARTER RESULTS".
_ORDINAL = re.compile(r"^\d+(?:ST|ND|RD|TH)$")


def _is_abbreviation(word: str) -> bool:
    """Whether a word in a shouted title was meant to be capitals."""
    letters = "".join(c for c in word if c.isalpha())
    if not letters:
        return True
    if _ORDINAL.match(word):
        return False                      # 2ND, 3RD
    if _COMPOUND.match(word) or any(c.isdigit() for c in word):
        return True                       # R&D, HSCT-TMA, PD-L1
    if _ROMAN.match(letters):
        return True                       # III, IV
    if not _HAS_VOWEL.search(letters):
        return True                       # GSK, BMS
    return len(letters) <= 4 and letters not in _SHORT_WORDS


def _drug_names(conn) -> dict:
    """{ticker: {upper-cased drug name}} so a title keeps its own products capitalised.

    Without it "UPDATE ON ULTOMIRIS PHASE III TRIAL" softens to "ultomiris", which is a
    drug's name written as if it were a word.
    """
    out: dict = {}
    for row in conn.execute(
            "SELECT c.ticker, a.brand_name, a.generic_name FROM assets a"
            "  JOIN companies c ON c.id = a.owner_company_id"):
        for value in (row["brand_name"], row["generic_name"]):
            for word in (value or "").split():
                if len(word) > 3:
                    out.setdefault(row["ticker"], set()).add(word.upper())
    return out


def _sentence_case(title: str, drugs=frozenset()) -> str:
    """A shouted title softened to a sentence, keeping what was meant to be capitals.

    Proper nouns this cannot know about stay lower case, which is the one thing it gets
    wrong and the reason the title as filed rides along in the detail.
    """
    if title != title.upper():
        return title                      # already mixed case: the filer's own choice
    words = []
    for word in title.split():
        if _is_abbreviation(word):
            words.append(word)
        elif word in drugs:
            words.append(word.capitalize())
        else:
            words.append(word.lower())
    out = " ".join(words)
    return out[:1].upper() + out[1:]


def _filings(conn, tickers, since) -> list:
    """A filing whose own title is the announcement.

    Only where the title is news. An 8-K is titled by the items it uses, so its headline
    is "Other events" however large the event; a 6-K is titled by the filer and reads as a
    press release, which is what makes it usable here and an 8-K not.
    """
    out = []
    names = _drug_names(conn)
    for row in conn.execute(
            "SELECT c.ticker, c.name, f.form_type, f.filed_date, f.title, f.url"
            "  FROM filings f JOIN companies c ON c.id = f.company_id"
            " WHERE f.filed_date >= ? AND f.title IS NOT NULL"
            " ORDER BY f.filed_date DESC", (since,)):
        if tickers is not None and row["ticker"] not in tickers:
            continue
        if not _is_news(row["form_type"], row["title"]):
            continue
        # Filers write these in capitals, which shouts over every other headline on the
        # page. The raw title stays in the detail, so nothing is lost by softening it.
        title = _sentence_case(row["title"].strip(), names.get(row["ticker"], set()))
        out.append({
            "kind": "filing", "ticker": row["ticker"], "name": row["name"],
            "date": row["filed_date"][:10],
            "headline": f"{row['ticker']} {title}",
            "figure": row["form_type"], "detail": "",
            "summary": [_pair("What", title),
                        _pair("Filed", row["filed_date"][:10]),
                        _pair("Form", row["form_type"]),
                        _pair("As filed", row["title"].strip())],
            "evidence": None, "url": row["url"], "rank": 0,
        })
    return out
