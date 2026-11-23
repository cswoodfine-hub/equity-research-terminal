"""What a company's insiders did with its shares, as one reading.

`fetchers/insiders_edgar.py` stores every line of every Form 4 filed about a company.
Most of those lines are not decisions. An annual award, the shares withheld to pay the
tax on it, an option exercised the week before it expires and a gift to a family trust
all change what an insider holds and say nothing about what they think the shares are
worth. Two codes are different: P, a purchase, and S, a sale, are the lines where
somebody chose a day and a price. This module keeps the two kinds apart, so that a
reader counting buyers before a readout is not counting a grant date.

`for_company` returns the transactions in a window, newest first, and a summary:

  open_market   code P and code S on the shares themselves (Table I): how many
                transactions, how many distinct people, shares and dollars each way, and
                the net. Sales are split by the form's Rule 10b5-1 box, because a sale
                on a plan adopted months earlier was not decided this week.
  open_market_directors_and_officers
                the same again without the holders of ten per cent who run nothing.
  other         everything else, counted by code and never netted into the above.

Nothing is estimated. A value is shares times price where the form states both and null
where it does not; a total says how many of its lines had no price; and a line whose
form has no 10b5-1 box is counted as not stated, not as outside a plan.

Three things about the form that the arithmetic cannot fix, and the payload says them in
`not_covered` so that a view or a model reading it does not have to know:

  - Codes P and S are "open market or private" on the form. It does not separate them,
    and some filers put a dividend reinvestment under P (AstraZeneca's does).
  - The 10b5-1 box is one for the whole form. It dates from April 2023; before that the
    plan was mentioned in a footnote or not at all.
  - A foreign private issuer may have no forms at all, which is not the same as no
    dealing.

Amendments. A 4/A is stored beside the form it corrects, and counting both would count
one sale twice. The form says which filing it amends (by date) and nothing about which
lines. So a line of an amendment replaces at most one line of the filing it names: the
same person, transaction date, code, table and security, taking the line with the same
share count first. A line it matches is kept in the list, marked `superseded_by`, and
left out of every total. A line of an amendment that matches nothing is taken as new.

Pure reads: this module never writes and never fetches.
"""

from __future__ import annotations

import datetime as dt
import json

import db

SOURCE = "insiders"
DEFAULT_DAYS = 180
# The summary is always over every line in the window. The list is cut here so that a
# company whose officers sell on a plan every other day does not hand a model three
# hundred rows; the payload says when it was cut.
DEFAULT_LIMIT = 100
_FOOTNOTE_CHARS = 240
_UNKNOWN_CODE = "Code not in the form's instructions"

PURCHASE, SALE = "P", "S"

# Form 4's transaction codes, in the form's own general instructions.
CODE_LABELS = {
    "P": "Open market or private purchase",
    "S": "Open market or private sale",
    "V": "Transaction voluntarily reported earlier than required",
    "A": "Grant, award or other acquisition from the company",
    "D": "Sale or transfer back to the company",
    "F": "Shares withheld or delivered to pay an exercise price or tax",
    "I": "Discretionary transaction in an employee plan",
    "M": "Exercise or conversion of a derivative security",
    "C": "Conversion of a derivative security",
    "E": "Expiration of a short derivative position",
    "H": "Expiration or cancellation of a long derivative position",
    "O": "Exercise of an out-of-the-money derivative security",
    "X": "Exercise of an in-the-money or at-the-money derivative security",
    "G": "Gift",
    "L": "Small acquisition",
    "W": "Acquisition or disposition by will or inheritance",
    "Z": "Deposit into or withdrawal from a voting trust",
    "J": "Other acquisition or disposition",
    "K": "Equity swap or similar instrument",
    "U": "Shares tendered in a change of control",
}

NOT_COVERED = (
    "Form 4 and 4/A only, and only where the company is the issuer. Forms 3 (opening "
    "holdings), 5 (annual catch-up) and 144 (notice of a planned sale) are not read.",
    "Codes P and S cover private transactions as well as open market ones; the form "
    "does not separate them, and some filers code a dividend reinvestment as P.",
    "The Rule 10b5-1 box is one for the whole form and exists only on forms from April "
    "2023. A null means the form has no box, not that there was no plan.",
    "Prices are as the form states them: often a weighted average over the day, and "
    "for a foreign issuer converted to dollars by the filer. A line with no stated "
    "price has no value and is counted as unpriced.",
    "Options, warrants and convertibles (Table II) are listed and counted under other, "
    "never in the open market totals.",
    "Two filers reporting one holding (a fund and its manager) are two forms; the same "
    "trade can appear on both.",
    "A foreign private issuer may show nothing: on 2026-11-23 Novo Nordisk, Novartis, "
    "GSK and Sanofi had no Form 4 as issuer. No rows is not evidence of no dealing.",
)


def _value(shares, price) -> float | None:
    """Shares times price where the form states both. Never anything else."""
    if shares is None or price is None:
        return None
    return round(shares * price, 2)


def _person(row: dict) -> str:
    """One key a person: the CIK EDGAR gives the filer, or the printed name without it."""
    return str(row.get("owner_cik") or row.get("owner_name") or "")


def _role(row: dict) -> str | None:
    """The boxes ticked on the form, in words."""
    parts = []
    if row.get("is_director"):
        parts.append("Director")
    if row.get("is_officer"):
        title = (row.get("officer_title") or "").strip()
        parts.append(f"Officer ({title})" if title else "Officer")
    if row.get("is_ten_percent_owner"):
        parts.append("10% owner")
    if row.get("is_other") and not parts:
        parts.append("Other")
    return ", ".join(parts) or None


def _total(values, count: int) -> float | None:
    """A sum of stated figures. Zero where there was nothing to add, null where there
    were lines and none of them stated the figure: an unknown total is not a zero."""
    stated = [v for v in values if v is not None]
    if not stated:
        return 0.0 if count == 0 else None
    return round(sum(stated), 4)


def _side(rows: list[dict], people: str) -> dict:
    return {
        "transactions": len(rows),
        people: len({_person(r) for r in rows}),
        "shares": _total((r["shares"] for r in rows), len(rows)),
        "value": _total((r["value"] for r in rows), len(rows)),
        "unpriced": sum(1 for r in rows if r["value"] is None),
    }


def _net(bought, sold) -> float | None:
    """Purchases less sales, or null where either side is unknown."""
    if bought is None or sold is None:
        return None
    return round(bought - sold, 4)


def mark_superseded(rows: list[dict]) -> None:
    """Mark each line an amendment replaces, in place. See the module docstring.

    Amendments are taken oldest first, so an amendment of an amendment replaces the
    line the first one put in.
    """
    def order(row):
        return (row.get("filed_date") or "", row.get("accepted_at") or "",
                row.get("accession") or "", row.get("row_index") or 0)

    def key(row):
        return (_person(row), row.get("transaction_date"), row.get("transaction_code"),
                row.get("is_derivative") or 0,
                (row.get("security_title") or "").strip().lower())

    for row in rows:
        row.setdefault("superseded_by", None)
    for amended in sorted((r for r in rows if r.get("form_type") == "4/A"), key=order):
        named = amended.get("original_filed_date")
        candidates = [
            r for r in rows
            if r["superseded_by"] is None
            and r.get("accession") != amended.get("accession")
            and key(r) == key(amended)
            and order(r) < order(amended)
            # The filing the amendment names, or an earlier amendment of that filing.
            # An amendment that names no date can only be matched to what came before.
            and (named is None or r.get("filed_date") == named
                 or r.get("original_filed_date") == named)]
        if not candidates:
            continue
        same = [r for r in candidates if r.get("shares") == amended.get("shares")]
        (same or candidates)[0]["superseded_by"] = amended.get("accession")


# How many people each side names. Enough to see who the total is, short enough to read.
LARGEST = 5


def _largest(lines: list[dict]) -> list[dict]:
    """The people behind one side of the total, biggest first.

    A total hides who it is. Dyne's Form 4s for the six months to 2026-11-23 carry 114m
    dollars of sales by six directors and officers, and 113m of it is two directors
    selling on plans, while the four officers between them sold under a million, mostly
    shares withheld for tax on a vesting. Those are different facts about the company
    and one figure states neither. `indirect_shares` is what was held through somebody
    else (a fund, a trust, a spouse), which is how a director who sits on the board for
    an investor usually appears.
    """
    people: dict = {}
    for row in lines:
        slot = people.setdefault(_person(row), {"rows": [], "name": row.get("owner_name"),
                                                "role": _role(row)})
        slot["rows"].append(row)
    out = []
    for slot in people.values():
        rows = slot["rows"]
        indirect = [r for r in rows if r.get("ownership") == "I"]
        out.append({
            "owner": slot["name"], "role": slot["role"], "transactions": len(rows),
            "shares": _total((r["shares"] for r in rows), len(rows)),
            "value": _total((r.get("value") for r in rows), len(rows)),
            "indirect_shares": _total((r["shares"] for r in indirect), len(indirect)),
            "under_10b5_1": sum(1 for r in rows if r.get("plan_10b5_1") == 1),
            "first": min((r.get("transaction_date") or "" for r in rows), default=None),
            "last": max((r.get("transaction_date") or "" for r in rows), default=None),
        })
    out.sort(key=lambda o: (-(o["value"] or 0), -(o["shares"] or 0), o["owner"] or ""))
    return out[:LARGEST]


def _open_market(lines: list[dict]) -> dict:
    """Purchases, sales and the net over Table I lines, each side split by the form's
    Rule 10b5-1 box."""
    bought = [r for r in lines if r.get("transaction_code") == PURCHASE]
    sold = [r for r in lines if r.get("transaction_code") == SALE]
    purchases = _side(bought, "buyers")
    sales = _side(sold, "sellers")
    for side, part, people in ((purchases, bought, "buyers"), (sales, sold, "sellers")):
        side["under_10b5_1"] = _side(
            [r for r in part if r.get("plan_10b5_1") == 1], people)
        side["not_under_plan"] = _side(
            [r for r in part if r.get("plan_10b5_1") == 0], people)
        side["plan_not_stated"] = sum(1 for r in part if r.get("plan_10b5_1") is None)
        side["largest"] = _largest(part)
    return {
        "purchases": purchases,
        "sales": sales,
        "net_shares": _net(purchases["shares"], sales["shares"]),
        "net_value": _net(purchases["value"], sales["value"]),
    }


def summarise(rows: list[dict]) -> dict:
    """The summary over a set of lines, each already carrying `value` and
    `superseded_by`. Pure, and the arithmetic the tests pin.

    The open market figures are given twice: for everybody who files, and for directors
    and officers alone. A holder of more than ten per cent files the same form, and one
    of them can be most of the total: in the year to 2026-11-23 Lilly's Form 4s carried
    703m dollars of sales, 677m of it by Lilly Endowment, which runs nothing at Lilly.
    """
    counted = [r for r in rows if not r.get("superseded_by")]
    traded = [r for r in counted if not r.get("is_derivative")
              and r.get("transaction_code") in (PURCHASE, SALE)]
    taken = {id(r) for r in traded}
    rest = [r for r in counted if id(r) not in taken]

    by_code: dict = {}
    for row in rest:
        code = row.get("transaction_code") or "?"
        slot = by_code.setdefault((code, row.get("is_derivative") or 0), [])
        slot.append(row)
    other = [{
        "code": code,
        "table": "derivative" if derivative else "non-derivative",
        "transactions": len(lines),
        "people": len({_person(r) for r in lines}),
        "shares": _total((r["shares"] for r in lines), len(lines)),
    } for (code, derivative), lines in by_code.items()]
    other.sort(key=lambda o: (-o["transactions"], o["code"], o["table"]))

    return {
        "open_market": _open_market(traded),
        "open_market_directors_and_officers": _open_market(
            [r for r in traded if r.get("is_director") or r.get("is_officer")]),
        "other": {"transactions": len(rest), "by_code": other},
        "superseded_by_amendment": len(rows) - len(counted),
    }


def _line(row: dict) -> dict:
    """One transaction as the payload carries it."""
    note = row.get("footnotes")
    if note and len(note) > _FOOTNOTE_CHARS:
        note = note[:_FOOTNOTE_CHARS].rstrip() + " ..."
    flag = row.get("plan_10b5_1")
    return {
        "transaction_date": row.get("transaction_date"),
        "filed_date": row.get("filed_date"),
        "accepted_at": row.get("accepted_at"),
        "owner": row.get("owner_name"),
        "other_owners": row.get("other_owners"),
        "role": _role(row),
        "code": row.get("transaction_code"),
        "security": row.get("security_title"),
        "derivative": bool(row.get("is_derivative")),
        "acquired_disposed": row.get("acquired_disposed"),
        "shares": row.get("shares"),
        "price": row.get("price_per_share"),
        "value": row.get("value"),
        "shares_owned_after": row.get("shares_owned_after"),
        "ownership": row.get("ownership"),
        "ownership_nature": row.get("ownership_nature"),
        "plan_10b5_1": None if flag is None else bool(flag),
        "form": row.get("form_type"),
        "superseded_by": row.get("superseded_by"),
        "footnotes": note,
        "accession": row.get("accession"),
        "url": row.get("url"),
    }


def _coverage(conn, company_id: int, ticker: str) -> dict:
    """What has been read for the company, so an empty window can be told from an
    unread one."""
    read = conn.execute(
        "SELECT COUNT(*) AS opened,"
        "       SUM(CASE WHEN outcome = 'stored' THEN 1 ELSE 0 END) AS stored,"
        "       SUM(CASE WHEN outcome = 'not_issuer' THEN 1 ELSE 0 END) AS not_issuer,"
        "       MIN(filed_date) AS earliest, MAX(filed_date) AS latest,"
        "       MAX(read_at) AS last_read"
        "  FROM insider_filings WHERE company_id = ?", (company_id,)).fetchone()
    snap = conn.execute(
        "SELECT payload, captured_at FROM snapshots WHERE source = ? AND entity_key = ?"
        "   AND json_extract(payload, '$.fetch_kind') = 'live'"
        " ORDER BY id DESC LIMIT 1", (SOURCE, ticker)).fetchone()
    backlog, last_fetch = None, None
    if snap:
        last_fetch = snap["captured_at"]
        try:
            backlog = json.loads(snap["payload"]).get("backlog")
        except ValueError:
            backlog = None
    return {
        "filings_opened": read["opened"] or 0,
        "filings_with_transactions": read["stored"] or 0,
        "filings_about_another_issuer": read["not_issuer"] or 0,
        "earliest_filed": read["earliest"],
        "latest_filed": read["latest"],
        "last_fetched_at": last_fetch,
        # Forms inside the fetcher's lookback that it had not opened when it last ran.
        # Null where it has never run.
        "filings_not_read_yet": backlog,
    }


def for_company(db_path, ticker: str, days: int = DEFAULT_DAYS,
                as_of: str | None = None, limit: int | None = DEFAULT_LIMIT) -> dict:
    """Insider transactions for one company over the ``days`` to ``as_of``.

    The window is on the transaction date (the filing date where a line has none), and
    ends today unless ``as_of`` is given. With ``as_of`` only forms filed on or before
    that day are used, so the reading is what could have been known then: a sale made
    on the Friday and filed the following Tuesday is not in Monday's answer.

    Returns None for a ticker the book does not hold. A company with nothing read
    returns the same shape with zeros and its coverage, never an error.
    """
    ticker = (ticker or "").upper()
    end = dt.date.fromisoformat(as_of) if as_of else dt.date.today()
    start = end - dt.timedelta(days=int(days))
    conn = db.get_connection(db_path)
    try:
        company = conn.execute(
            "SELECT id, ticker, name FROM companies WHERE ticker = ?",
            (ticker,)).fetchone()
        if company is None:
            return None
        rows = [dict(r) for r in conn.execute(
            """
            SELECT * FROM insider_transactions
             WHERE company_id = :company
               AND COALESCE(transaction_date, filed_date) > :start
               AND COALESCE(transaction_date, filed_date) <= :end
               AND (filed_date IS NULL OR filed_date <= :end)
             ORDER BY COALESCE(transaction_date, filed_date) DESC, filed_date DESC,
                      accession DESC, row_index
            """,
            {"company": company["id"], "start": start.isoformat(),
             "end": end.isoformat()})]
        coverage = _coverage(conn, company["id"], ticker)
    finally:
        conn.close()

    for row in rows:
        row["value"] = _value(row.get("shares"), row.get("price_per_share"))
    mark_superseded(rows)
    shown = rows if limit is None else rows[:limit]
    return {
        "ticker": company["ticker"],
        "company": company["name"],
        "as_of": end.isoformat(),
        "window_days": int(days),
        "window_start": start.isoformat(),
        "source": "SEC Form 4 (EDGAR)",
        "summary": summarise(rows),
        # What each code in this window means, once, so a line does not repeat it.
        "codes": {code: CODE_LABELS.get(code, _UNKNOWN_CODE) for code in sorted(
            {r.get("transaction_code") or "?" for r in rows})},
        "transactions": [_line(r) for r in shown],
        "transactions_in_window": len(rows),
        "truncated": len(shown) < len(rows),
        "coverage": coverage,
        "not_covered": list(NOT_COVERED),
    }
