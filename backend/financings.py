"""Money raised after the balance sheet date, which no XBRL fact will carry for a quarter.

A balance sheet is a photograph of one day. Dyne's says 898.5m of cash at 30 June 2026 and
the company raised another 405m net in July, three weeks before it filed. Nothing tags
that: the raise lands in the Q3 statements in November, so a runway computed from the
newest available facts is 45% short of the cash the company actually has, for three
months, for every clinical-stage name that finances between quarters.

The filing says so in words. The 10-Q's liquidity paragraph reads "our cash, cash
equivalents and marketable securities as of June 30, 2026, as well as the approximately
$405.0 in net proceeds from the July 2026 offering", and the 8-K exhibit that announced
the quarter says it again. That sentence is the source here.

Three rules keep it from inflating a balance sheet:

Net proceeds only. Gross is before underwriting discounts and expenses, and the difference
is real money: Dyne's raise was 431m gross and 405m net. A filing that states only gross is
skipped rather than discounted by a guessed fee.

After the period end only, by calendar month. A raise in the same month as the balance
sheet date is already in the balance sheet, and adding it would count it twice.

Stated, not projected. "We may raise", "we expect to receive" and an at-the-market
programme's remaining capacity are all money that does not exist yet.
"""

from __future__ import annotations

import re

import db
import runway

# A financing described in the filing's own words.
_NET_PROCEEDS = re.compile(r"\bnet proceeds\b", re.I)
_MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*(million|billion)\b", re.I)
_SCALE = {"million": 1e6, "billion": 1e9}

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")
_WHEN = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(?:\d{1,2},\s*)?(\d{4})\b", re.I)

# What kind of raise it was, in the words a reader uses. First match wins, most specific
# first: a convertible note offering is a note offering, not a public offering.
_KINDS = (
    ("convertible notes", (r"convertible\s+(?:senior\s+)?notes",)),
    ("term loan", (r"\bterm loan\b", r"\bcredit facility\b", r"\bloan agreement\b")),
    ("private placement", (r"\bprivate placement\b", r"\bregistered direct\b")),
    ("at-the-market", (r"\bat[- ]the[- ]market\b", r"\bATM\b")),
    ("public offering", (r"\bpublic offering\b", r"\bunderwritten offering\b",
                         r"\bfollow[- ]on\b", r"\boffering\b")),
)

# Money that is not money yet, or money already counted. Four kinds, each from a company
# that produced a wrong figure before the guard existed:
#
# An aggregate since inception is the history of the balance sheet, not an addition to it.
# A sentence about what the proceeds will be spent on is not a statement that they were
# received: Allogene's "we expect to use the net proceeds" paired with an unrelated 12.9m.
# A period already closed is already on the balance sheet: Cabaletta's "during the first
# quarter of 2026, we sold ... for net proceeds of $22.6 million" is inside its March 31
# cash. And a conditional raise has not happened.
_NOT_A_RAISE = re.compile(
    r"\b(?:aggregate|since inception|through\s+(?:march|june|september|december)|to date|"
    r"cumulative|may\s+(?:raise|receive|sell)|expects?\s+to\s+(?:raise|receive)|"
    r"remaining available|available to be sold|if we|could\s+(?:raise|receive)|"
    r"use\s+(?:the|of)\s+(?:net\s+)?proceeds|if applicable|agreed to|"
    r"during the (?:first|second|third|fourth) quarter|"
    r"during the (?:three|six|nine|twelve) months ended)\b", re.I)

# How far from the words "net proceeds" a figure can sit and still be that figure.
# Anywhere in the window was too loose: it read Dyne's quarterly R&D expense of 152.2m as
# a raise because both sat in the same two sentences.
PROCEEDS_WINDOW = 60

# Sentences are read two at a time. A filing states the date in one and the amount in the
# next: "In July 2026, we completed an underwritten public offering" is followed by "We
# estimate that the net proceeds from the offering were approximately $405.0 million".
_SENTENCE = re.compile(r"(?<=[.;])\s+(?=[A-Z])")
WINDOW = 2

# Where the text is read from, most authoritative first. The 10-Q's own liquidity
# discussion is the filer's considered statement; the 8-K exhibit is the press release
# that announced it, and arrives first.
SECTIONS = ("mdna", "exhibit", "body", "financial_review")


def _clean(text: str) -> str:
    return " ".join((text or "").split())


def _kind(text: str, near: int = 0) -> str:
    """What kind of raise it was, read from around the proceeds phrase and nowhere else.

    The window is two sentences and the second one is often about something else.
    uniQure's June raise sits beside a paragraph on its Hercules loan amendment, and
    scanning the whole window labelled an equity raise a term loan. Unlabelled is the
    right answer where the sentence does not say: the filing's own heading reads
    "Financing" and so does this.
    """
    scope = text[max(0, near - PROCEEDS_WINDOW): near + PROCEEDS_WINDOW]
    for name, patterns in _KINDS:
        if any(re.search(p, scope, re.I) for p in patterns):
            return name
    return "financing"


def _amount(text: str) -> float | None:
    """The net proceeds stated beside the words "net proceeds", or None.

    Beside, not anywhere: a figure further off in the same two sentences is some other
    number. Read forward first, since "net proceeds of $141.0 million" is the commoner
    order, then back for "raised approximately $211.2 million in net proceeds".
    """
    marker = _NET_PROCEEDS.search(text)
    if not marker:
        return None
    after = _MONEY.search(text, marker.end(), marker.end() + PROCEEDS_WINDOW)
    before = None
    for match in _MONEY.finditer(text[max(0, marker.start() - PROCEEDS_WINDOW):
                                      marker.start()]):
        before = match
    match = after or before
    if not match:
        return None
    return float(match.group(1).replace(",", "")) * _SCALE[match.group(2).lower()]


def _month(text: str, near: int, low: str, high: str) -> str | None:
    """The closing month of the raise: the one nearest ``near`` that could be it.

    Bounded first, then nearest. A liquidity sentence names two dates, the balance sheet
    date and the raise: "cash of $116.6 million as of March 31, 2026, along with net
    proceeds of approximately $141.0 million from our May 2026 financing". Nearest alone
    picked March, which is the date the money was not there.
    """
    best, closest = None, None
    for match in _WHEN.finditer(text):
        month = (f"{int(match.group(2)):04d}-"
                 f"{_MONTHS.index(match.group(1).lower()) + 1:02d}")
        if not low < month <= high:
            continue
        gap = min(abs(match.start() - near), abs(match.end() - near))
        if closest is None or gap < closest:
            closest, best = gap, month
    return best


def raises(text: str, after: str, before: str = "") -> list:
    """Every financing the text states closing after the month of ``after``.

    ``after`` is the balance sheet date the cash figure was read at; comparison is by
    month, since a raise in the same month is already in that balance sheet. ``before`` is
    the filing date, and nothing can close after the document that reports it: without
    that bound, "notes maturing between 2028 and 2032" read as a raise in 2032.
    """
    if not after:
        return []
    cutoff = after[:7]
    ceiling = (before or "9999-12")[:7]
    sentences = [_clean(s) for s in _SENTENCE.split(text or "")]
    found: dict = {}
    for index in range(len(sentences)):
        window = " ".join(sentences[index:index + WINDOW])
        marker = _NET_PROCEEDS.search(window)
        if not marker or _NOT_A_RAISE.search(window):
            continue
        amount = _amount(window)
        month = _month(window, marker.start(), cutoff, ceiling)
        if not amount or not month:
            continue
        # One raise is described several times in one filing, and often at two figures:
        # Dyne's 8-K states 352.1m before the underwriters' option and 405.0m after. Keyed
        # on the month alone, so the repetitions collapse to the first statement found,
        # which is the one from the most authoritative section. Two raises in one month
        # collapse too, which understates the cash rather than overstating it.
        found.setdefault(month, {"amount": amount, "month": month,
                                 "kind": _kind(window, marker.start()),
                                 "evidence": window})
    return sorted(found.values(), key=lambda r: r["month"])


def _sources(conn, company_id: int) -> list:
    """The stored text worth reading, newest filing first, one row per section."""
    rows = []
    for section in SECTIONS:
        rows += conn.execute(
            "SELECT accession, form_type, filed_date, section, text"
            "  FROM filing_sections WHERE company_id = ? AND section = ?"
            "    AND text IS NOT NULL ORDER BY filed_date DESC LIMIT 3",
            (company_id, section)).fetchall()
    return sorted(rows, key=lambda r: r["filed_date"], reverse=True)


def extract(conn, company_id: int) -> list:
    """Financings this company states closing after its latest balance sheet date."""
    money = runway.liquidity(conn, company_id)
    if not money["as_of"]:
        return []
    out: dict = {}
    for row in _sources(conn, company_id):
        for entry in raises(row["text"], money["as_of"], row["filed_date"]):
            # One raise per month per company, and the first source to state it wins.
            # Sources are read newest filing first, so the latest account of a raise is
            # the one kept.
            if entry["month"] in out:
                continue
            out[entry["month"]] = {
                **entry, "company_id": company_id, "as_of": money["as_of"],
                "accession": row["accession"], "form_type": row["form_type"],
                "filed_date": row["filed_date"], "section": row["section"]}
    return sorted(out.values(), key=lambda r: r["month"])


def build(db_path=None) -> dict:
    """Write every post-period financing, replacing what a company had before.

    Replaced rather than merged: once the next 10-Q lands, its balance sheet includes the
    raise and the row must disappear, or the cash would be counted twice.
    """
    conn = db.get_connection(db_path)
    written = 0
    try:
        for company in conn.execute("SELECT id FROM companies"):
            rows = extract(conn, company["id"])
            conn.execute("DELETE FROM financings WHERE company_id = ?", (company["id"],))
            for row in rows:
                conn.execute(
                    "INSERT INTO financings (company_id, closed_month, amount_usd, kind,"
                    "    evidence, balance_sheet_date, accession, form_type, filed_date,"
                    "    section) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (company["id"], row["month"], row["amount"], row["kind"],
                     row["evidence"], row["as_of"], row["accession"], row["form_type"],
                     row["filed_date"], row["section"]))
                written += 1
        conn.commit()
    finally:
        conn.close()
    return {"written": written}


def since_balance_sheet(conn, company_id: int, as_of: str) -> dict:
    """{total, rows} of stored financings that closed after this balance sheet date.

    The stored date is checked again rather than trusted, so a row written against an
    older balance sheet cannot be added to a newer one it is already inside.
    """
    rows = [dict(r) for r in conn.execute(
        "SELECT closed_month, amount_usd, kind, evidence, filed_date, form_type"
        "  FROM financings WHERE company_id = ? AND closed_month > ?"
        "  ORDER BY closed_month", (company_id, (as_of or "")[:7]))]
    return {"total": sum(r["amount_usd"] for r in rows) or None, "rows": rows}
