"""Who holds a company, read from the Form 13F rows the book has stored.

`fetchers/holders_13f.py` stores what each manager filed. This turns that into an
answer for one company: how many managers hold it, who the largest are, what each did
since the quarter before, and how much of the reported holding sits with the top ten.
It is the question asked ahead of a readout, when a share held by forty specialists who
all bought last quarter behaves differently from one held by index funds.

Pure reading. Nothing here writes, fetches or estimates.

What a 13F cannot say is as much a part of the answer as what it can, so the limits
come back as fields (`caveats`) and not as a footnote somebody has to remember to add:

  - long positions only. A short is not reported and not netted, so a manager shown
    holding a million shares may be flat;
  - filers only: managers with discretion over $100 million or more of 13(f)
    securities. Founders, most insiders and holders outside that rule are absent;
  - stated at the quarter end and filed up to 45 days later;
  - options are reported as the shares they are over and are kept apart.

Three rules stand between the rows and the answer, each because the filings are what
the managers typed.

The share count is checked against the value. Every manager prices the same share at
the same quarter end, so value divided by shares should be one number for all of them,
and the median across a few hundred managers is that number whatever a handful of them
got wrong. A row within a factor of two of it is taken as filed. A row at a thousandth
of it is a manager still reporting in thousands of dollars, which the form stopped
asking for in January 2023: the shares are kept and the value is left null, not scaled.
A row anywhere else is set aside whole, because nothing says whether its shares or its
value is the wrong one. For 30 June 2026 that is the manager whose 12,642 Novo Nordisk
ADRs are valued at $606 million. Set-aside rows are listed in the answer, not hidden.

A change is only called one when both quarters can be read. "New" needs the manager to
have filed for the quarter before and not listed the share. "Sold out" needs it to have
filed for this quarter and not listed it. A manager with no report for the other quarter
is a manager that has not filed, or files under a different entity now, and is counted
as that. In 2026 Vanguard reports through several entities and no one of them is "the"
Vanguard holding, which is a fact about the filings this module does not paper over.

And the report has to be there. Norges Bank's public filing for 31 March 2026 states
1,507 lines on its summary page and lists one placeholder, so on the rows alone Norges
held no Lilly in March and 11.5 million shares in June. A report whose table is far
short of what it states (`is_short`) is treated as a report that cannot be read: no
"new", no "sold out", no increase or cut is taken from it, and the row says why.

A share of the company's shares in issue is given only where the book holds a count,
with the date of that count beside it. A depositary share is converted through
`adr_ratios`, and left null where the book has no ratio.
"""

from __future__ import annotations

import datetime as dt
import statistics

import cusips
import db

TOP_DEFAULT = 15
CONCENTRATION_TOP = 10
# Fewer managers than this and a median says too little to judge a row by, so nothing
# is set aside and the answer says the check was not made.
MIN_FOR_PRICE_CHECK = 5
# How far a row's implied price may sit from the quarter's median and still be read as
# filed. Managers price at the quarter-end close, so the honest spread is small. A
# factor of two is far outside it and far inside the thousandfold error the band
# exists to separate.
PRICE_BAND = 2.0
# A share count dated more than this from the quarter end is not the company the
# holders held. A small biotech can double its share count in a year.
MAX_COUNT_GAP_DAYS = 366
FILING_DEADLINE_DAYS = 45
SET_ASIDE_SHOWN = 20
# Under this share of both the lines and the value its summary page states, a filing's
# table is read as mostly not there.
SHORT_FRACTION = 0.9
OPTIONS_SHOWN = 5

OK, THOUSANDS, UNCHECKED = "ok", "thousands", "unchecked"
# The one reason that is the caller's mistake and not a gap in the data, named so a
# route can answer it with a 404 without matching on a sentence.
NOT_IN_UNIVERSE = "not a company in the universe"


def is_short(stated_rows, found_rows, stated_value, found_value) -> bool:
    """True when a filing's table is only part of the report it describes.

    A filing's summary page states how many lines its table has and what they are
    worth. The table usually holds exactly that. Sometimes it holds a fraction (a
    placeholder line where the holdings were withheld, a table cut short and restated
    later), and then the manager's holdings for the quarter are not there to be read.

    Both counts must fall under ``SHORT_FRACTION`` of what was stated. One alone is
    not enough, because the summary page is typed by hand too: a manager that states
    60 lines and files 59, or gets its total wrong by a factor of ten, has filed a
    whole table and a careless summary. A filing that states nothing cannot be judged
    and is taken as whole.
    """
    if not stated_rows or not stated_value:
        return False
    return ((found_rows or 0) < SHORT_FRACTION * stated_rows
            and (found_value or 0) < SHORT_FRACTION * stated_value)


def _unavailable(ticker: str, reason: str, **extra) -> dict:
    return {"ticker": ticker, "available": False, "reason": reason, **extra}


def _periods(conn) -> list:
    """The quarter ends the book has read a release for, newest first."""
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT report_period FROM institutional_holdings_releases"
        " ORDER BY report_period DESC")]


def _filers(conn, period: str) -> tuple:
    """(every manager with a holdings report that stands for the quarter, and of
    those {manager: (lines found, lines stated)} where the table is only part of
    one)."""
    filers, short = set(), {}
    for row in conn.execute(
            "SELECT manager_cik, table_entries, table_value, rows_found, value_found"
            " FROM institutional_holdings_filings"
            " WHERE period_of_report = ? AND status = 'live'", (period,)):
        filers.add(row["manager_cik"])
        if is_short(row["table_entries"], row["rows_found"], row["table_value"],
                    row["value_found"]):
            short[row["manager_cik"]] = (row["rows_found"] or 0, row["table_entries"])
    return filers, short


def _short_note(found_stated: tuple, which: str) -> str:
    found, stated = found_stated
    return (f"its report for {which} lists {found:,} of the {stated:,} lines its "
            f"summary page states")


def _positions(conn, company_id: int, period: str) -> dict:
    """One entry a manager, from the rows of the filings that stand.

    A manager's position is the sum over its standing filings, which is what makes an
    amendment that adds new holdings add. A restated report's rows are not here: the
    join on the filing's status is the whole of the amendment handling at read time.
    """
    managers: dict = {}
    for row in conn.execute(
            """
            SELECT h.manager_cik, h.manager_name, h.accession_number, h.filing_date,
                   h.cusip, h.put_call, h.shares_type, h.shares, h.value_usd,
                   f.is_amendment
              FROM institutional_holdings h
              JOIN institutional_holdings_filings f
                ON f.accession_number = h.accession_number
             WHERE h.company_id = ? AND h.period_of_report = ? AND f.status = 'live'
             ORDER BY h.filing_date, h.accession_number
            """, (company_id, period)):
        entry = managers.setdefault(row["manager_cik"], {
            "manager_cik": row["manager_cik"], "manager": row["manager_name"],
            "shares": 0, "value": None, "has_long": False, "put": 0, "call": 0,
            "other_option": 0, "principal": 0, "principal_value": None,
            "principal_rows": 0, "principal_as_shares": False, "accessions": [],
            "filing_date": None, "amended": False, "cusips": set()})
        # Rows come oldest filing first, so the name and date left standing are the
        # newest filing's.
        entry["manager"] = row["manager_name"] or entry["manager"]
        entry["filing_date"] = row["filing_date"]
        entry["amended"] = entry["amended"] or bool(row["is_amendment"])
        if row["accession_number"] not in entry["accessions"]:
            entry["accessions"].append(row["accession_number"])
        flag = (row["put_call"] or "").lower()
        if flag:
            key = flag if flag in ("put", "call") else "other_option"
            entry[key] += row["shares"] or 0
            continue
        if row["shares_type"] != "SH":
            # Ticked as a principal amount. Kept apart here and looked at again in
            # the price check, which is the only thing that can say what it is.
            entry["principal_rows"] += 1
            entry["principal"] += row["shares"] or 0
            if row["value_usd"] is not None:
                entry["principal_value"] = ((entry["principal_value"] or 0)
                                            + row["value_usd"])
            entry["cusips"].add(row["cusip"])
            continue
        entry["has_long"] = True
        entry["cusips"].add(row["cusip"])
        entry["shares"] += row["shares"] or 0
        if row["value_usd"] is not None:
            entry["value"] = (entry["value"] or 0) + row["value_usd"]
    return managers


def _price_check(managers: dict) -> tuple:
    """Sort the long positions into read-as-filed and set-aside.

    Returns (holders, set_aside, median implied price or None). Each holder gains
    ``check``: ok, thousands (value left null) or unchecked.

    A row ticked as a principal amount is settled here too. The register holds shares
    and depositary shares only, so a principal amount of one is a share count with the
    wrong box ticked, if it is anything. Where its value over its amount is the
    quarter's share price it is read as the shares it is. Otherwise it stays apart.
    Leaving them all apart would have a manager that ticked the wrong box in June
    read as having sold out since March.
    """
    prices = [m["value"] / m["shares"] for m in managers.values()
              if m["has_long"] and m["shares"] > 0 and m["value"]]
    median = statistics.median(prices) if len(prices) >= MIN_FOR_PRICE_CHECK else None
    for m in managers.values():
        if median is None or m["principal"] <= 0 or not m["principal_value"]:
            continue
        price = m["principal_value"] / m["principal"]
        if any(median / PRICE_BAND <= price * scale <= median * PRICE_BAND
               for scale in (1, 1000)):
            m["shares"] += m["principal"]
            m["value"] = (m["value"] or 0) + m["principal_value"]
            m["has_long"] = m["principal_as_shares"] = True
            m["principal_rows"] = 0
    longs = [m for m in managers.values() if m["has_long"]]
    holders, aside = {}, []
    for m in longs:
        if m["shares"] <= 0:
            aside.append({**m, "reason": "no share count filed"})
            continue
        if median is None or not m["value"]:
            # No yardstick, or no value to hold against it: the share count stands as
            # filed and the answer says it was not checked.
            holders[m["manager_cik"]] = {**m, "check": UNCHECKED}
            continue
        price = m["value"] / m["shares"]
        if median / PRICE_BAND <= price <= median * PRICE_BAND:
            holders[m["manager_cik"]] = {**m, "check": OK}
        elif median / PRICE_BAND <= price * 1000 <= median * PRICE_BAND:
            holders[m["manager_cik"]] = {**m, "check": THOUSANDS}
        else:
            aside.append({**m, "reason": (
                f"value over shares is {price:,.2f} a share against a median of "
                f"{median:,.2f} across the quarter's holders")})
    return holders, aside, median


def _share_count(conn, company_id: int, period: str) -> dict | None:
    """The book's share count nearest the quarter end, with its date. None when the
    book holds none within ``MAX_COUNT_GAP_DAYS``."""
    end = dt.date.fromisoformat(period)
    best = None
    for row in conn.execute(
            "SELECT period_end, value FROM financials WHERE company_id = ?"
            " AND metric = 'SharesOutstanding' AND value > 0", (company_id,)):
        try:
            gap = (dt.date.fromisoformat(row["period_end"][:10]) - end).days
        except (TypeError, ValueError):
            continue
        if best is None or abs(gap) < abs(best[0]):
            best = (gap, row["value"], row["period_end"][:10])
    if best is None or abs(best[0]) > MAX_COUNT_GAP_DAYS:
        return None
    return {"shares": best[1], "as_of": best[2], "days_from_period": best[0]}


def _outstanding(conn, company_id: int, ticker: str, period: str,
                 depositary: bool) -> tuple:
    """(the share count or None, ordinary shares to one share as held or None, and
    the reason when either is missing).

    The count is in ordinary shares. A holding of depositary shares is put on the same
    footing by the ratio in ``adr_ratios``, and where the book has no ratio for a
    depositary share the fraction is left null. A wrong ratio is a wrong answer by a
    factor of two or eight, and no ratio is only a missing one.
    """
    count = _share_count(conn, company_id, period)
    if count is None:
        return None, None, ("the book holds no share count within a year of the "
                            "quarter end")
    if not depositary:
        return count, 1.0, None
    row = conn.execute("SELECT ordinary_per_adr FROM adr_ratios WHERE ticker = ?",
                       (ticker,)).fetchone()
    if row is None or not row[0]:
        return count, None, ("the holders are counted in depositary shares and the "
                             "book holds no ratio to ordinary shares for this company")
    return count, float(row[0]), None


def _change(holder: dict, before: dict, before_aside: set, before_filers: set,
            identifier_moved: bool, now_short: dict, before_short: dict) -> dict:
    """What a manager did since the quarter before, or why that cannot be said."""
    cik = holder["manager_cik"]
    blank = {"previous_shares": None, "change_shares": None, "change": None,
             "change_note": None}
    if cik in now_short:
        return {**blank, "change_note": _short_note(now_short[cik], "this quarter")}
    if cik in before_short:
        return {**blank,
                "change_note": _short_note(before_short[cik], "the quarter before")}
    if cik in before_aside:
        return {**blank, "change_note": "its row for the quarter before was set aside"}
    prior = before.get(cik)
    if prior is None:
        if cik in before_filers:
            return {**blank, "previous_shares": 0, "change_shares": holder["shares"],
                    "change": "new"}
        return {**blank, "change_note": "no report from this manager for the quarter "
                                        "before"}
    if identifier_moved:
        return {**blank, "previous_shares": prior["shares"],
                "change_note": "the CUSIP changed between the two quarters, so the "
                               "share counts are not on one footing"}
    delta = holder["shares"] - prior["shares"]
    return {"previous_shares": prior["shares"], "change_shares": delta,
            "change": "added" if delta > 0 else "cut" if delta < 0 else "unchanged",
            "change_note": None}


def _options(managers: dict) -> dict:
    out = {}
    for side in ("put", "call"):
        held = sorted((m for m in managers.values() if m[side] > 0),
                      key=lambda m: (-m[side], m["manager_cik"]))
        out[side] = {"managers": len(held), "shares": sum(m[side] for m in held),
                     "largest": [{"manager_cik": m["manager_cik"],
                                  "manager": m["manager"], "shares": m[side]}
                                 for m in held[:OPTIONS_SHOWN]]}
    return out


def for_company(db_path, ticker: str, top: int = TOP_DEFAULT) -> dict:
    """A company's institutional holders at the newest quarter the book has read.

    Returns ``available: False`` with a ``reason`` where there is nothing to show: a
    company left off the CUSIP register on purpose, one the register has not reached,
    or a book that has read no release. Otherwise the quarter described, the number of
    holders, the ``top`` largest with what each did since the quarter before, the
    share of reported holdings in the top ten, the options held apart, the rows set
    aside, and the caveats.
    """
    ticker = (ticker or "").strip().upper()
    conn = db.get_connection(db_path)
    try:
        company = conn.execute("SELECT id, name FROM companies WHERE ticker = ?",
                               (ticker,)).fetchone()
        if company is None:
            return _unavailable(ticker, NOT_IN_UNIVERSE)
        register = cusips.for_ticker(ticker)
        if not register:
            reason = cusips.left_out().get(ticker) or (
                "the CUSIP register (data/cusips.csv) has no row for this company")
            return _unavailable(ticker, reason, company=company["name"])
        periods = _periods(conn)
        if not periods:
            return _unavailable(ticker, "no Form 13F data set has been read yet",
                                company=company["name"])
        period = periods[0]
        previous = periods[1] if len(periods) > 1 else None
        release = conn.execute(
            "SELECT release, window_end FROM institutional_holdings_releases"
            " ORDER BY window_end DESC LIMIT 1").fetchone()

        managers = _positions(conn, company["id"], period)
        holders, aside, median = _price_check(managers)
        before, before_aside_rows = {}, []
        if previous:
            before, before_aside_rows, _ = _price_check(
                _positions(conn, company["id"], previous))
        before_aside = {m["manager_cik"] for m in before_aside_rows}
        now_aside = {m["manager_cik"] for m in aside}
        now_filers, now_short = _filers(conn, period)
        before_filers, before_short = _filers(conn, previous) if previous \
            else (set(), {})

        cusips_now = set().union(*(m["cusips"] for m in holders.values())) \
            if holders else set()
        cusips_before = set().union(*(m["cusips"] for m in before.values())) \
            if before else set()
        identifier_moved = bool(cusips_now and cusips_before
                                and cusips_now != cusips_before)

        classes = sorted({row["class_title"] for row in register if row["class_title"]})
        depositary = any(cusips.is_depositary(row["class_title"]) for row in register)
        count, ratio, count_note = _outstanding(conn, company["id"], ticker, period,
                                                depositary)

        def of_outstanding(shares):
            if count is None or ratio is None or not shares:
                return None
            return round(shares * ratio / count["shares"], 6)

        ranked = sorted(holders.values(),
                        key=lambda m: (-m["shares"], m["manager_cik"]))
        total = sum(m["shares"] for m in ranked)
        valued = [m for m in ranked if m["check"] == OK]

        counts = {"new": 0, "added": 0, "cut": 0, "unchanged": 0, "sold_out": 0,
                  "not_comparable": 0}
        rows = []
        for rank, m in enumerate(ranked, start=1):
            change = _change(m, before, before_aside, before_filers, identifier_moved,
                             now_short, before_short) \
                if previous else {"previous_shares": None, "change_shares": None,
                                  "change": None,
                                  "change_note": "the book holds one quarter only"}
            counts[change["change"] or "not_comparable"] += 1
            if rank > top:
                continue
            rows.append({
                "rank": rank,
                "manager_cik": m["manager_cik"],
                "manager": m["manager"],
                "shares": m["shares"],
                "value_usd": m["value"] if m["check"] == OK else None,
                "value_note": (
                    "filed in thousands of dollars, so left null" if m["check"] == THOUSANDS
                    else "not checked against the share count" if m["check"] == UNCHECKED
                    and m["value"] else None),
                "value_as_filed": m["value"],
                "share_of_reported": round(m["shares"] / total, 6) if total else None,
                "share_of_outstanding": of_outstanding(m["shares"]),
                **change,
                "filing_date": m["filing_date"],
                "accessions": m["accessions"],
                "amended": m["amended"],
                # Its report lists a fraction of the lines it states, so the shares
                # shown are a floor on what it holds and not the whole of it.
                "incomplete": m["manager_cik"] in now_short,
            })

        # A manager that held it the quarter before and does not list it now has sold
        # out only if it has filed for this quarter and the filing is there to read.
        # One that has not filed has not been heard from, and one whose report is
        # mostly not there may hold it on a line it did not list. Each is counted as
        # what it is.
        sold, unheard, unread = [], 0, 0
        for cik, m in before.items():
            if cik in holders or cik in now_aside:
                continue
            if cik in now_short:
                unread += 1
            elif cik in now_filers:
                sold.append({"manager_cik": cik, "manager": m["manager"],
                             "previous_shares": m["shares"]})
            else:
                unheard += 1
        sold.sort(key=lambda m: (-m["previous_shares"], m["manager_cik"]))
        counts["sold_out"] = len(sold)

        options = _options(managers)
        principal_rows = sum(m["principal_rows"] for m in managers.values())
        in_thousands = sum(1 for m in ranked if m["check"] == THOUSANDS)
        deadline = (dt.date.fromisoformat(period)
                    + dt.timedelta(days=FILING_DEADLINE_DAYS)).isoformat()
        unit = "depositary shares" if depositary else "shares"
        top_ten = sum(m["shares"] for m in ranked[:CONCENTRATION_TOP])

        caveats = {
            "long_only": ("Form 13F reports long positions only. A short position is "
                          "not reported and not netted off, so a manager shown here "
                          "may be flat or short overall. Shares lent to a short "
                          "seller are reported by the lender and again by whoever "
                          "bought them, so reported holdings can exceed the shares "
                          "in issue."),
            "filers_only": ("Only managers with investment discretion over $100 "
                            "million or more of Section 13(f) securities file. "
                            "Founders, most insiders and holders outside that rule "
                            "are absent, so these are never all of the holders."),
            "lag": (f"Holdings are stated at {period} and were due by {deadline}, 45 "
                    f"days later. Nothing here is newer than the quarter end."),
            "options": (f"Puts and calls are reported as the shares they are over and "
                        f"are held apart: {options['put']['managers']} managers with "
                        f"puts and {options['call']['managers']} with calls are in no "
                        f"share count here."),
            "as_filed": (f"Figures are as each manager filed them. {len(aside)} "
                         f"positions whose value does not square with their share "
                         f"count were set aside, and {in_thousands} values filed in "
                         f"thousands of dollars are left null."),
        }
        if median is None:
            caveats["as_filed"] = (
                f"Figures are as each manager filed them. With fewer than "
                f"{MIN_FOR_PRICE_CHECK} valued positions no row could be checked "
                f"against the others.")
        if depositary:
            caveats["unit"] = ("Counted in US depositary shares. Holders of the "
                               "ordinary shares on the home exchange report nothing "
                               "on Form 13F.")
        if identifier_moved:
            caveats["identifier"] = ("The company's CUSIP changed between the two "
                                     "quarters, so increases and cuts are not given.")

        return {
            "ticker": ticker,
            "company": company["name"],
            "available": True,
            "source": "SEC Form 13F data sets",
            "release": release["release"] if release else None,
            "filed_through": release["window_end"] if release else None,
            "period": period,
            "previous_period": previous,
            "filing_deadline": deadline,
            "cusips": [row["cusip"] for row in register],
            "class_title": ", ".join(classes) or None,
            "unit": unit,
            "holders": len(ranked),
            "managers_reporting": len(now_filers),
            "shares_held": total,
            "value_usd": sum(m["value"] for m in valued) if valued else None,
            "value_holders": len(valued),
            "median_implied_price": round(median, 4) if median is not None else None,
            "top_ten_share": round(top_ten / total, 6) if total else None,
            "shares_outstanding": ({**count, "ordinary_per_depositary_share":
                                    ratio if depositary else None}
                                   if count else None),
            "held_share_of_outstanding": of_outstanding(total),
            "outstanding_note": count_note,
            "top": rows,
            "changes": counts,
            "sold_out": sold[:top],
            "not_yet_reported": unheard,
            # Managers holding it in either quarter whose report lists far fewer
            # lines than it states. No change is read off any of them.
            "short_reports": unread + sum(
                1 for cik in holders if cik in now_short or cik in before_short),
            "options": options,
            # Rows ticked as a principal amount: those whose value did not match the
            # share price and stay out of every count, and the managers whose rows
            # did match and were read as shares.
            "principal_amount_rows": principal_rows,
            "principal_read_as_shares": sum(
                1 for m in ranked if m["principal_as_shares"]),
            "set_aside_count": len(aside),
            "set_aside": [
                {"manager_cik": m["manager_cik"], "manager": m["manager"],
                 "shares_as_filed": m["shares"], "value_as_filed": m["value"],
                 "reason": m["reason"]}
                for m in sorted(aside, key=lambda m: (-m["shares"], m["manager_cik"]))
                [:SET_ASIDE_SHOWN]],
            "identifier_changed": identifier_moved,
            "caveats": caveats,
        }
    finally:
        conn.close()
