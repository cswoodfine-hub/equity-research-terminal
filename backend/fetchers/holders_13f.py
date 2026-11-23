"""Institutional holders from the SEC's quarterly Form 13F data sets.

A manager with investment discretion over $100 million or more of Section 13(f)
securities reports every such holding at each calendar quarter end, within 45 days. The
SEC flattens the structured part of every filing into a ZIP of tab-separated tables and
posts one ZIP a quarter. This reads the rows that name a CUSIP on the book's register
(`cusips.py`, `data/cusips.csv`) and stores them by filing. `holders.py` is the reader
built on top.

How the source is actually laid out, checked against the live files on 2026-11-23:

  - The listing page, `LISTING_URL`, links every data set since 2013, 54 of them. The
    link is the only reliable address. The newest ZIP sat under
    `/files/datastandardsinnovation/data/form-13f-data-sets/` and the 53 before it
    under `/files/structureddata/data/form-13f-data-sets/`, so a URL is read from the
    page and never built from a pattern.
  - A data set is cut by filing date, not by quarter. Until 2023 the files were
    calendar quarters (`2023q4_form13f.zip`). From March 2024 each holds three months
    of filings ending February, May, August or November
    (`01jun2026-31aug2026_form13f.zip`), posted about two weeks later, which puts the
    45-day deadline inside the window. A filing made after 5:30pm Eastern on the last
    business day falls into the next one.
  - So a release is not a quarter. The June to August 2026 file holds 10,940
    submissions for 30 June 2026, 219 for 31 March 2026 and a tail back to 2001: late
    reports, amendments, and filers catching up on years of arrears. The quarter a
    release is "for" is the one most of its holdings reports name, and it is worked
    out from the file, not from its name.
  - Each ZIP is about 100 MB and unpacks to about 400 MB, nearly all of it
    INFOTABLE.tsv: 3,830,274 lines in the June to August 2026 file. It is streamed to
    disk, read line by line out of the ZIP and deleted. Nothing is unpacked.
  - Seven tables, tab separated, UTF-8, no quoting, dates as `30-JUN-2026`. Three
    matter here. SUBMISSION has the form type (13F-HR, 13F-HR/A, and the notices
    13F-NT and 13F-NT/A), the filer's CIK, the filing date and the period. COVERPAGE
    has the manager's name and the amendment boxes. INFOTABLE has the holdings, keyed
    to the filing by ACCESSION_NUMBER. SUMMARYPAGE is read for two numbers, the lines
    and the value the manager says its table has.
  - VALUE is in dollars. The readme: "Starting on January 3, 2023, market value is
    reported rounded to the nearest dollar. Previously, market value was reported in
    thousands." A filing made before that date gets a null value here and is never
    scaled. In practice a good many filers still report thousands (193 of the 4,608
    managers holding Lilly at 30 June 2026 give a value a thousandth of what their
    share count implies) and a few file nonsense (one gives 12,642 Novo Nordisk ADRs
    a value of $606 million). Both are stored exactly as filed. The reader is where
    they are set aside, because that takes the whole quarter's rows.
  - A filing's table is not always the manager's whole report. SUMMARYPAGE gives the
    lines and the value the manager says its table has, and for about 98 filings in
    100 INFOTABLE holds exactly that many lines. For a few it holds a fraction, and
    the two checked against EDGAR are true to the filings, not a fault in the data
    set: Norges Bank's report for 31 March 2026 states 1,507 lines worth $865 billion
    and its public table is one placeholder line (issuer NA, CUSIP 000000000), and
    JPMorgan's first filing for that quarter carried a 203 KB table where its
    restatement the same day carried 18.9 MB. Both stated figures are stored beside
    what was found, and the reader will not call a manager new or sold out on the
    strength of a report that is mostly not there.
  - PUTCALL is `Put`, `Call` or empty, on 123,083 of those 3.8 million lines. The
    form has an option reported as the shares it is over, under the share's own
    CUSIP, so an option line looks exactly like a holding except for this column. It
    is stored apart, under its flag, and never summed into shares held. A few
    managers (JPMorgan among them) file their options under the pseudo-CUSIPs the
    SEC's official list gives calls and puts, Lilly's 532457108 with its last three
    characters overwritten as 908 and 958. Those are not on the register and are not
    read, so the option counts here are a floor.
  - SSHPRNAMTTYPE is `SH` or `PRN`. PRN is a principal amount and belongs to notes. A
    few filers tick it against a share. It is stored as filed, and the reader takes
    such a row as shares only where its value over its amount is the share price.

Amendments. The readme does not say how to handle them. It says only that the data is
"as filed" including amendments and "may contain redundancies, inconsistencies, and
discrepancies relative to prior submissions". The rule used is the form's own: the
cover page of an amendment ticks one of two boxes, and COVERPAGE carries the answer in
AMENDMENTTYPE. `RESTATEMENT` replaces the manager's report for that period in full, so
the earlier filing stops counting. `NEW HOLDINGS` adds entries to it, so both count.
About 400 amendments a release, two thirds of them restatements. Eight in the March to
May 2026 file tick neither box. Such a filing is stored and not applied, since
replacing and adding give different answers and it does not say which it means.

This is not a tidying step. For 30 June 2026 the California State Teachers' Retirement
System filed its table with the share and value columns the wrong way round and
restated it the same day. Read without the rule, the first filing makes it the largest
holder of Lilly with 1.46 billion shares, half as many again as Lilly has issued.
JPMorgan's first filing for 31 March 2026 lists 378 of the 33,063 lines its summary
page states and was restated the same day too.

One box cannot be taken at its word. An amendment that "adds new holdings entries"
should list the additions and nothing else. More than half do not: of the 85 such
amendments in the two files that amend a report the book holds, 49 carry at least half
the lines and half the value of that report, and wherever the book can see both (21
filings holding one of its companies) the lines are the same lines over again.
Stempoint Capital's for 31 March 2026 is 84 lines against the 83 of the report it
amends. Adding those would count the manager twice. So an amendment ticked as new
holdings that is at least `REPEAT_FRACTION` the size of the report standing before it,
in lines and in value, is read as the restatement it is. The 36 smaller ones are added,
as the form says, and none of them repeats a line the book can see.

An amendment arrives in a later release than the report it corrects, so which filings
stand is recomputed for a manager and period every time one of its filings is written
(`resolve`), over everything held and not just the release in hand. Nothing is deleted.

What is kept. Holdings reports for the quarter a release is for, and for any quarter an
earlier release here was for. A late report for a quarter the book never loaded is
dropped: forty filings are not a quarter's holders. Every kept filing is recorded
whether or not it names a company here, because a restatement that names none still
replaces one that did.

The first run reads the two newest releases, so a quarter-on-quarter change exists.
After that a run reads whatever is newer than the newest it holds, normally nothing:
one request for the listing page. A release already in `institutional_holdings_releases`
is not downloaded again, with one exception. If the register has gained a CUSIP since a
release was read, the two newest are read again, since otherwise a company added to the
register would show no holders until the next quarter and no change until the one
after.
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import io
import json
import os
import re
import shutil
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import contact
import cusips
import db
import holders
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "holders_13f"
ENTITY_KEY = "holders_13f"
TTL_SECONDS = 7 * 24 * 60 * 60

LISTING_URL = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
# A download is taken only from the host the listing page itself is on. A page that
# pointed somewhere else would be a page that had been changed, not a new address.
SEC_HOST = "www.sec.gov"
FIRST_RUN_RELEASES = 2
REREAD_RELEASES = 2
# The form asked for dollars from this filing date and for thousands before it.
DOLLARS_FROM = "2023-01-03"

CACHE_DIR = Path(os.getenv("ER_TOOL_CACHE",
                           Path(__file__).resolve().parent.parent / "cache")) / "holders_13f"
_TIMEOUT_S = 120
_PAUSE_S = 0.5              # between requests: a handful a run, far inside ten a second
_CHUNK = 1 << 20

HOLDINGS_FORMS = ("13F-HR", "13F-HR/A")
# An amendment that says it adds new holdings, and is at least this share of the report
# it amends in both lines and value, is that report filed again.
REPEAT_FRACTION = 0.5
RESTATEMENT, NEW_HOLDINGS = "RESTATEMENT", "NEW HOLDINGS"
LIVE, SUPERSEDED, UNAPPLIED = "live", "superseded", "unapplied"

_MEMBERS = ("SUBMISSION.TSV", "COVERPAGE.TSV", "INFOTABLE.TSV")
_INFOTABLE_COLUMNS = ("ACCESSION_NUMBER", "CUSIP", "VALUE", "SSHPRNAMT",
                      "SSHPRNAMTTYPE", "PUTCALL")
_MONTHS = {name: number for number, name in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
    start=1)}
_ZIP_LINK = re.compile(r'href="([^"]+?/([^"/]+_form13f\.zip))"', re.IGNORECASE)
_WINDOW_NAME = re.compile(
    r"^(\d{2})([a-z]{3})(\d{4})-(\d{2})([a-z]{3})(\d{4})_form13f\.zip$", re.IGNORECASE)
_QUARTER_NAME = re.compile(r"^(\d{4})q([1-4])_form13f\.zip$", re.IGNORECASE)


# --- the listing page -----------------------------------------------------------------

def release_window(name: str) -> tuple | None:
    """(first filing date, last filing date) a data set spans, from its file name.

    Two shapes: `01jun2026-31aug2026_form13f.zip` since 2024 and `2023q4_form13f.zip`
    before. None for a name that is neither, which the caller leaves alone.
    """
    match = _WINDOW_NAME.match(name or "")
    if match:
        d1, m1, y1, d2, m2, y2 = match.groups()
        try:
            return (dt.date(int(y1), _MONTHS[m1.upper()], int(d1)).isoformat(),
                    dt.date(int(y2), _MONTHS[m2.upper()], int(d2)).isoformat())
        except (KeyError, ValueError):
            return None
    match = _QUARTER_NAME.match(name or "")
    if match:
        year, quarter = int(match.group(1)), int(match.group(2))
        start = dt.date(year, 3 * quarter - 2, 1)
        end = (dt.date(year + (quarter == 4), 3 * quarter % 12 + 1, 1)
               - dt.timedelta(days=1))
        return start.isoformat(), end.isoformat()
    return None


def parse_listing(html: str) -> list[dict]:
    """Every data set the listing page links, newest first. Pure.

    Each is {release, url, window_start, window_end}. The release is the ZIP's file
    name, which is what the SEC keeps stable. A link off the SEC's own host is left out.
    """
    found: dict = {}
    for href, name in _ZIP_LINK.findall(html or ""):
        window = release_window(name)
        url = urllib.parse.urljoin(LISTING_URL, href)
        if window is None or urllib.parse.urlsplit(url).netloc != SEC_HOST:
            continue
        found.setdefault(name.lower(), {"release": name.lower(), "url": url,
                                        "window_start": window[0],
                                        "window_end": window[1]})
    return sorted(found.values(), key=lambda r: r["window_end"], reverse=True)


def plan(listing: list[dict], loaded: dict, register: set) -> list[dict]:
    """Which releases this run reads, oldest first. Pure.

    ``loaded`` is {release: {"window_end", "cusips_read"}} for what the book holds.
    With nothing held, the newest ``FIRST_RUN_RELEASES``. Otherwise every release newer
    than the newest held, and the newest ``REREAD_RELEASES`` held ones again where the
    register now has a CUSIP they were not read against.
    """
    if not loaded:
        todo = listing[:FIRST_RUN_RELEASES]
    else:
        newest = max(meta["window_end"] or "" for meta in loaded.values())
        todo = [r for r in listing
                if r["release"] not in loaded and r["window_end"] > newest]
        held = [r for r in listing if r["release"] in loaded][:REREAD_RELEASES]
        todo += [r for r in held
                 if register - set(loaded[r["release"]].get("cusips_read") or ())]
    return sorted(todo, key=lambda r: r["window_end"])


# --- the tables -----------------------------------------------------------------------

def iso_date(text: str) -> str | None:
    """`30-JUN-2026` as `2026-06-30`. None for anything else.

    Spelled out and not left to strptime's %b, which reads month names in the
    machine's locale and would fail on a server set to anything but English.
    """
    parts = (text or "").strip().upper().split("-")
    if len(parts) != 3 or parts[1] not in _MONTHS:
        return None
    try:
        return dt.date(int(parts[2]), _MONTHS[parts[1]], int(parts[0])).isoformat()
    except ValueError:
        return None


def _number(text: str) -> int | None:
    """A whole number as filed, or None. A decimal point is tolerated, since the
    column is numeric and a filing agent occasionally writes one."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return None


def _cik(text: str) -> str:
    """A filer's CIK padded to ten digits. SUBMISSION pads nearly all of them and
    leaves the odd one bare (`1539994`), and a manager must be one manager whichever
    way its number was written, or its amendment would never meet its report."""
    text = (text or "").strip()
    return text.zfill(10) if text.isdigit() else text


def tsv_rows(lines):
    """One dict a line of a tab-separated table, keyed by its header. For the small
    tables. The files use no quoting, so a quote mark in a manager's name is a quote
    mark and nothing else."""
    reader = csv.reader(lines, delimiter="\t", quoting=csv.QUOTE_NONE)
    header = next(reader, None)
    if not header:
        return
    header = [name.strip().upper() for name in header]
    for row in reader:
        if row:
            yield dict(zip(header, row))


def read_filings(submission_lines, cover_lines, summary_lines=None) -> dict:
    """{accession: filing} for every holdings report in a release. Pure.

    Notices (13F-NT) are left out: they say another manager reports the holdings and
    carry no table. A holdings report with no readable period or filing date is left
    out too, since neither where it belongs nor when it was known could be said.
    """
    covers = {row.get("ACCESSION_NUMBER"): row for row in tsv_rows(cover_lines)}
    stated = {}
    for row in tsv_rows(summary_lines or ()):
        stated[row.get("ACCESSION_NUMBER")] = (_number(row.get("TABLEENTRYTOTAL")),
                                               _number(row.get("TABLEVALUETOTAL")))
    filings = {}
    for row in tsv_rows(submission_lines):
        form = (row.get("SUBMISSIONTYPE") or "").strip().upper()
        accession = (row.get("ACCESSION_NUMBER") or "").strip()
        period = iso_date(row.get("PERIODOFREPORT"))
        filed = iso_date(row.get("FILING_DATE"))
        if form not in HOLDINGS_FORMS or not accession or not period or not filed:
            continue
        cover = covers.get(accession) or {}
        ticked = (cover.get("ISAMENDMENT") or "").strip().upper() == "Y"
        filings[accession] = {
            "accession_number": accession,
            "manager_cik": _cik(row.get("CIK")),
            "manager_name": (cover.get("FILINGMANAGER_NAME") or "").strip() or None,
            "period_of_report": period,
            "filing_date": filed,
            "submission_type": form,
            "report_type": (cover.get("REPORTTYPE") or "").strip() or None,
            # Either sign makes it an amendment. The two disagree on one filing a
            # release: a 13F-HR whose cover page ticks "adds new holdings entries".
            "is_amendment": form.endswith("/A") or ticked,
            "amendment_no": _number(cover.get("AMENDMENTNO")),
            "amendment_type": (cover.get("AMENDMENTTYPE") or "").strip().upper() or None,
            # What the manager's summary page says its table holds. What the data
            # set holds for it is filled in when the table has been read.
            "table_entries": stated.get(accession, (None, None))[0],
            "table_value": stated.get(accession, (None, None))[1],
            "rows_found": None,
            "value_found": None,
        }
    return filings


def report_period(filings: dict) -> str | None:
    """The quarter end a release is for: the one most of its first-time holdings
    reports name. Amendments are not counted, since a release can carry a wave of
    them for an older quarter."""
    counts = collections.Counter(
        f["period_of_report"] for f in filings.values() if not f["is_amendment"])
    return counts.most_common(1)[0][0] if counts else None


def parse_infotable(lines, wanted_cusips, wanted_accessions) -> tuple:
    """Sum the holdings table to one row a filing, security, option flag and amount
    type, keeping only the register's CUSIPs and the filings being kept. Pure.

    ``lines`` is read once, front to back, and never held: the table is millions of
    lines and about 400 MB. Returns ({(accession, cusip, put_call, shares_type):
    {"shares", "value", "source_rows"}}, {accession: [lines, value]} for every kept
    filing whatever it holds, and {"lines", "malformed"}).

    A manager lists one security on several lines, one for each other manager it
    shares discretion with, and the lines are one position: they are summed. An option
    line carries the same CUSIP as the share, so the flag is part of the key and an
    option can never be added to a holding.
    """
    reader = csv.reader(lines, delimiter="\t", quoting=csv.QUOTE_NONE)
    header = [name.strip().upper() for name in (next(reader, None) or [])]
    missing = [name for name in _INFOTABLE_COLUMNS if name not in header]
    if missing:
        raise ValueError(f"INFOTABLE has no {', '.join(missing)} column: the layout "
                         f"has changed")
    i_acc, i_cusip, i_value, i_amount, i_type, i_putcall = (
        header.index(name) for name in _INFOTABLE_COLUMNS)
    width = len(header)
    rows: dict = {}
    found: dict = {}
    count = malformed = 0
    for row in reader:
        count += 1
        if len(row) != width:
            malformed += 1
            continue
        accession = row[i_acc]
        if accession not in wanted_accessions:
            continue
        # Every line of a kept filing is counted, on the register or not, so the
        # filing can be held against what its own summary page says it contains.
        value = _number(row[i_value]) or 0
        tally = found.get(accession)
        if tally is None:
            tally = found[accession] = [0, 0]
        tally[0] += 1
        tally[1] += value
        cusip = row[i_cusip].strip().upper()
        if cusip not in wanted_cusips:
            continue
        key = (accession, cusip, row[i_putcall].strip().title(),
               row[i_type].strip().upper())
        entry = rows.get(key)
        if entry is None:
            entry = rows[key] = {"shares": 0, "value": 0, "source_rows": 0}
        entry["shares"] += _number(row[i_amount]) or 0
        entry["value"] += value
        entry["source_rows"] += 1
    return rows, found, {"lines": count, "malformed": malformed}


def _member(archive: zipfile.ZipFile, wanted: str) -> str | None:
    for name in archive.namelist():
        if name.rsplit("/", 1)[-1].upper() == wanted:
            return name
    return None


def _text(archive: zipfile.ZipFile, name: str):
    return io.TextIOWrapper(archive.open(name), encoding="utf-8", errors="replace",
                            newline="")


def parse_release(path, wanted_cusips, covered_periods=()) -> dict:
    """Read one data set ZIP from disk. Returns its filings, holdings and counts.

    ``covered_periods`` are the quarter ends earlier releases were for. A holdings
    report is kept when it is for one of those or for this release's own quarter.
    """
    with zipfile.ZipFile(path) as archive:
        names = {wanted: _member(archive, wanted) for wanted in _MEMBERS}
        missing = [wanted for wanted, name in names.items() if name is None]
        if missing:
            raise ValueError(f"the data set has no {', '.join(missing)}: the layout "
                             f"has changed")
        summary = _member(archive, "SUMMARYPAGE.TSV")
        with _text(archive, names["SUBMISSION.TSV"]) as submissions, \
                _text(archive, names["COVERPAGE.TSV"]) as covers:
            submission_lines = list(submissions)
            if summary:
                with _text(archive, summary) as pages:
                    filings = read_filings(submission_lines, covers, pages)
            else:
                filings = read_filings(submission_lines, covers)
        period = report_period(filings)
        if period is None:
            raise ValueError("the data set holds no holdings report")
        covered = set(covered_periods) | {period}
        kept = {acc: f for acc, f in filings.items()
                if f["period_of_report"] in covered}
        with _text(archive, names["INFOTABLE.TSV"]) as table:
            rows, found, stats = parse_infotable(table, wanted_cusips, kept)
    for accession, filing in kept.items():
        filing["rows_found"], filing["value_found"] = found.get(accession, (0, 0))
    holdings = []
    for (accession, cusip, put_call, shares_type), entry in rows.items():
        filing = kept[accession]
        holdings.append({
            "accession_number": accession,
            "manager_cik": filing["manager_cik"],
            "manager_name": filing["manager_name"],
            "period_of_report": filing["period_of_report"],
            "filing_date": filing["filing_date"],
            "cusip": cusip, "put_call": put_call, "shares_type": shares_type,
            "shares": entry["shares"],
            # Null, not scaled, for a filing made while the form asked for thousands.
            "value_usd": (entry["value"] if filing["filing_date"] >= DOLLARS_FROM
                          else None),
            "source_rows": entry["source_rows"],
        })
    return {"report_period": period, "filings": list(kept.values()),
            "holdings": holdings,
            "stats": {"submissions": max(0, len(submission_lines) - 1),
                      "filings_kept": len(kept),
                      "filings_dropped": len(filings) - len(kept),
                      "infotable_rows": stats["lines"],
                      "malformed": stats["malformed"]}}


def short_filings(filings) -> list[dict]:
    """The filings whose table is far short of what their own summary page states,
    largest stated value first."""
    short = [f for f in filings
             if holders.is_short(f["table_entries"], f["rows_found"],
                                 f["table_value"], f["value_found"])]
    return sorted(short, key=lambda f: -(f["table_value"] or 0))


# --- amendments -----------------------------------------------------------------------

def _order(filing: dict) -> tuple:
    """Filing order within one manager and period. The date is a day, not a time, so a
    report and its amendment filed the same day are put report first, then by the
    amendment's own number, then by accession."""
    return (filing["filing_date"], 1 if filing["is_amendment"] else 0,
            filing.get("amendment_no") or 0, filing["accession_number"])


def _repeats(amendment: dict, report: dict | None) -> bool:
    """True when an amendment ticked as new holdings is the report filed again: at
    least ``REPEAT_FRACTION`` of it in lines and in value. With either size unknown
    the tick is believed, since there is nothing to hold it against."""
    if report is None:
        return False
    sizes = (amendment.get("rows_found"), amendment.get("value_found"),
             report.get("rows_found"), report.get("value_found"))
    if not all(sizes):
        return False
    rows, value, report_rows, report_value = sizes
    return (rows >= REPEAT_FRACTION * report_rows
            and value >= REPEAT_FRACTION * report_value)


def resolve(filings: list[dict]) -> dict:
    """Which of one manager's filings for one period count. Pure.

    Returns {accession: (status, superseded_by)}. Walking the filings in the order
    they were made: a first report or a restatement replaces everything before it, an
    amendment that adds new holdings stands beside what is there, and an amendment
    that says neither is not applied. So the answer is the last full report plus every
    addition made after it.

    An amendment ticked as new holdings that is the size of the report it amends is
    that report again and is read as a restatement (``_repeats``).

    An addition with nothing before it stands on its own. That is the manager whose
    whole report was filed confidentially and released later as new holdings.
    """
    out: dict = {}
    standing: list = []
    report = None                      # the full report the standing filings rest on
    for filing in sorted(filings, key=_order):
        accession = filing["accession_number"]
        kind = filing.get("amendment_type") if filing["is_amendment"] else RESTATEMENT
        if kind not in (RESTATEMENT, NEW_HOLDINGS):
            out[accession] = (UNAPPLIED, None)
            continue
        if kind == RESTATEMENT or _repeats(filing, report):
            for earlier in standing:
                out[earlier] = (SUPERSEDED, accession)
            standing = []
            report = filing
        standing.append(accession)
        out[accession] = (LIVE, None)
    return out


# --- the network ----------------------------------------------------------------------

def _agent() -> str:
    """The User-Agent the SEC asks for: a name and an address. It refuses a request
    that gives no way to reach whoever is making it, so with no address set the run
    says so and does not send one that would be blocked anyway."""
    if not contact.address():
        raise RuntimeError("SEC_USER_AGENT is not set; the SEC blocks anonymous requests")
    return contact.user_agent()


def _get_listing() -> str:
    request = urllib.request.Request(LISTING_URL, headers={"User-Agent": _agent()})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _download(url: str, dest: Path) -> int:
    """Stream a ZIP to ``dest`` and return its size. Written under a `.part` name and
    renamed when whole, and refused if the server promised a different length, so a
    connection that dropped at 60 MB is never read as a short quarter."""
    if urllib.parse.urlsplit(url).netloc != SEC_HOST:
        raise ValueError(f"{url} is not on {SEC_HOST}, so it was not downloaded")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": _agent()})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp, \
                part.open("wb") as out:
            promised = resp.headers.get("Content-Length")
            shutil.copyfileobj(resp, out, _CHUNK)
        size = part.stat().st_size
        if promised and int(promised) != size:
            raise IOError(f"{url} sent {size:,} bytes of a promised {int(promised):,}")
        os.replace(part, dest)
    finally:
        if part.exists():
            part.unlink()
    return size


def _megabytes(size) -> str:
    return f"{(size or 0) / 1e6:.1f} MB"


# --- the fetcher ----------------------------------------------------------------------

class Holders13FFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, db_path=None, get_listing=None, download=None, cache_dir=None,
                 register=None):
        super().__init__(db_path)
        self._get_listing = get_listing or _get_listing
        self._download = download or _download
        self._cache_dir = Path(cache_dir) if cache_dir is not None else CACHE_DIR
        self._register = register          # a path, for tests; None is data/cusips.csv
        self._notes: list[str] = []
        self._errors: list[str] = []
        self.downloads = 0

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def _loaded(self) -> dict:
        conn = db.get_connection(self.db_path)
        try:
            return {r["release"]: {"window_end": r["window_end"],
                                   "report_period": r["report_period"],
                                   "cusips_read": (r["cusips_read"] or "").split(",")}
                    for r in conn.execute(
                        "SELECT release, window_end, report_period, cusips_read"
                        " FROM institutional_holdings_releases")}
        finally:
            conn.close()

    def _clear_cache(self) -> None:
        """Remove any ZIP a killed run left behind. Each is 100 MB the book has no
        further use for, and a partial one must never be mistaken for a release."""
        if not self._cache_dir.exists():
            return
        for stale in self._cache_dir.glob("*_form13f.zip*"):
            try:
                stale.unlink()
            except OSError:
                pass

    # --- fetch ------------------------------------------------------------------------
    def fetch(self) -> dict:
        self._notes, self._errors, self.downloads = [], [], 0
        self._errors.extend(f"holders_13f: cusips.csv: {problem}"
                            for problem in cusips.problems(self._register))
        by_cusip = cusips.by_cusip(self._register)
        if not by_cusip:
            self._notes.append("holders_13f: the CUSIP register is empty, so nothing "
                               "was read")
            return {"releases": [], "by_cusip": {}, "checked": False}
        listing = parse_listing(self._get_listing())
        if not listing:
            raise RuntimeError("the Form 13F data sets page links no data set: its "
                               "layout has changed")
        loaded = self._loaded()
        todo = plan(listing, loaded, set(by_cusip))
        covered = {meta["report_period"] for meta in loaded.values()}
        self._clear_cache()
        releases = []
        failed = False
        for item in todo:
            path = self._cache_dir / item["release"]
            try:
                time.sleep(_PAUSE_S)
                size = self._download(item["url"], path)
                self.downloads += 1
                parsed = parse_release(path, set(by_cusip), covered)
            except Exception as exc:
                # Oldest first, and stop at the first that fails: reading a newer
                # release over a gap would apply its amendments to a quarter that is
                # not there. The next run starts again from this one.
                self._errors.append(f"holders_13f: {item['release']} was not read "
                                    f"({type(exc).__name__}: {exc})")
                failed = True
                break
            finally:
                if path.exists():
                    path.unlink()
            parsed["release"] = {**item, "zip_bytes": size,
                                 "reread": item["release"] in loaded}
            covered.add(parsed["report_period"])
            releases.append(parsed)
        if not todo:
            newest = listing[0]["release"]
            self._notes.append(f"holders_13f: {newest} is the newest data set and is "
                               f"already read, so nothing was downloaded")
        # A run that could not read a release it wanted has not done the week's work,
        # so it is not marked as the live fetch the TTL counts from and the next
        # refresh tries again.
        return {"releases": releases, "by_cusip": by_cusip, "checked": not failed}

    # --- normalise --------------------------------------------------------------------
    def normalise(self, raw: dict) -> dict:
        conn = db.get_connection(self.db_path)
        try:
            company_ids = {r["ticker"]: r["id"] for r in conn.execute(
                "SELECT ticker, id FROM companies")}
        finally:
            conn.close()
        by_cusip = raw.get("by_cusip") or {}
        unknown = sorted({t for t in by_cusip.values() if t not in company_ids})
        if unknown:
            self._notes.append(f"holders_13f: cusips.csv names {', '.join(unknown)}, "
                               f"which the companies table does not hold; their rows "
                               f"were not stored")
        out = []
        for parsed in raw.get("releases") or []:
            name = parsed["release"]["release"]
            holdings = []
            for row in parsed["holdings"]:
                company_id = company_ids.get(by_cusip.get(row["cusip"]))
                if company_id is not None:
                    holdings.append({**row, "company_id": company_id, "release": name})
            stats = parsed["stats"]
            out.append({
                "release": {**parsed["release"], **stats,
                            "report_period": parsed["report_period"],
                            "rows_kept": len(holdings),
                            "companies": len({h["company_id"] for h in holdings}),
                            "cusips_read": ",".join(sorted(by_cusip))},
                "filings": [{**f, "release": name} for f in parsed["filings"]],
                "holdings": holdings})
        return {"releases": out, "checked": raw.get("checked", False)}

    # --- snapshot ---------------------------------------------------------------------
    def _write_snapshot(self, conn, payload: dict) -> None:
        conn.execute(
            "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
            " refresh_run_id) VALUES (?, 'source', ?, ?, ?)",
            (self.source, ENTITY_KEY, json.dumps(payload), self.refresh_run_id))

    def _held(self, conn) -> dict:
        row = conn.execute(
            "SELECT release, report_period FROM institutional_holdings_releases"
            " ORDER BY window_end DESC LIMIT 1").fetchone()
        return {"newest_release": row["release"] if row else None,
                "report_period": row["report_period"] if row else None,
                "releases": conn.execute(
                    "SELECT COUNT(*) FROM institutional_holdings_releases").fetchone()[0],
                "rows": conn.execute(
                    "SELECT COUNT(*) FROM institutional_holdings").fetchone()[0]}

    def snapshot(self, data: dict) -> None:
        """One row for the feed, written before the tables change, so what it says
        the book holds is what it held going in. A run that asked the listing page and
        found nothing new is a live fetch all the same: the question is what the
        weekly TTL rations, and marking it otherwise would have the page asked on
        every refresh."""
        conn = db.get_connection(self.db_path)
        try:
            self._write_snapshot(conn, {
                **self._held(conn),
                "read_this_run": [r["release"]["release"] for r in data["releases"]],
                "rows_this_run": sum(len(r["holdings"]) for r in data["releases"]),
                "fetch_kind": "live" if data.get("checked") else "cache"})
            conn.commit()
        finally:
            conn.close()

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            self._write_snapshot(conn, {**self._held(conn), "fetch_kind": "cache"})
            conn.commit()
        finally:
            conn.close()

    # --- upsert -----------------------------------------------------------------------
    def _settle(self, conn, groups: set) -> dict:
        """Recompute which filings stand for each (manager, period) touched, over every
        filing the book holds for it. Returns how many ended in each state."""
        counts: collections.Counter = collections.Counter()
        for cik, period in sorted(groups):
            filings = [dict(r) for r in conn.execute(
                "SELECT accession_number, filing_date, is_amendment, amendment_no,"
                " amendment_type, rows_found, value_found"
                " FROM institutional_holdings_filings"
                " WHERE manager_cik = ? AND period_of_report = ?", (cik, period))]
            for accession, (status, by) in resolve(filings).items():
                conn.execute(
                    "UPDATE institutional_holdings_filings SET status = ?,"
                    " superseded_by = ? WHERE accession_number = ?",
                    (status, by, accession))
                counts[status] += 1
        return dict(counts)

    def upsert(self, data: dict) -> RefreshResult:
        written = 0
        for one in data.get("releases") or []:
            release = one["release"]
            conn = db.get_connection(self.db_path)
            try:
                # One transaction a release, so a release is in the book whole or not
                # at all, and the guard row is written with the rows it guards.
                with conn:
                    conn.executemany(
                        """
                        INSERT INTO institutional_holdings_filings
                            (accession_number, manager_cik, manager_name,
                             period_of_report, filing_date, submission_type,
                             report_type, is_amendment, amendment_no, amendment_type,
                             table_entries, table_value, rows_found, value_found,
                             release)
                        VALUES (:accession_number, :manager_cik, :manager_name,
                                :period_of_report, :filing_date, :submission_type,
                                :report_type, :is_amendment, :amendment_no,
                                :amendment_type, :table_entries, :table_value,
                                :rows_found, :value_found, :release)
                        ON CONFLICT(accession_number) DO UPDATE SET
                            manager_name = excluded.manager_name,
                            table_entries = excluded.table_entries,
                            table_value = excluded.table_value,
                            rows_found = excluded.rows_found,
                            value_found = excluded.value_found
                        """, [{**f, "is_amendment": int(f["is_amendment"])}
                              for f in one["filings"]])
                    conn.executemany(
                        """
                        INSERT INTO institutional_holdings
                            (company_id, accession_number, manager_cik, manager_name,
                             period_of_report, filing_date, cusip, put_call,
                             shares_type, shares, value_usd, source_rows, release)
                        VALUES (:company_id, :accession_number, :manager_cik,
                                :manager_name, :period_of_report, :filing_date, :cusip,
                                :put_call, :shares_type, :shares, :value_usd,
                                :source_rows, :release)
                        ON CONFLICT(accession_number, cusip, put_call, shares_type)
                        DO UPDATE SET shares = excluded.shares,
                            value_usd = excluded.value_usd,
                            source_rows = excluded.source_rows
                        """, one["holdings"])
                    states = self._settle(conn, {
                        (f["manager_cik"], f["period_of_report"])
                        for f in one["filings"]})
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO institutional_holdings_releases
                            (release, zip_url, window_start, window_end, report_period,
                             zip_bytes, submissions, filings_kept, filings_dropped,
                             infotable_rows, rows_kept, companies, cusips_read)
                        VALUES (:release, :url, :window_start, :window_end,
                                :report_period, :zip_bytes, :submissions, :filings_kept,
                                :filings_dropped, :infotable_rows, :rows_kept,
                                :companies, :cusips_read)
                        """, release)
                    # Only the filings left standing: a part-filed report its manager
                    # restated the same day is the amendment rule's business, and it
                    # has already dealt with it.
                    short = short_filings([dict(r) for r in conn.execute(
                        "SELECT manager_name, period_of_report, table_entries,"
                        " table_value, rows_found, value_found"
                        " FROM institutional_holdings_filings"
                        " WHERE release = ? AND status = ?",
                        (release["release"], LIVE))])
            finally:
                conn.close()
            written += len(one["holdings"])
            untyped = sum(1 for f in one["filings"] if f["is_amendment"]
                          and f["amendment_type"] not in (RESTATEMENT, NEW_HOLDINGS))
            self._notes.append(
                f"holders_13f: read {release['release']} ({_megabytes(release['zip_bytes'])},"
                f" {release['infotable_rows']:,} lines) for {release['report_period']}:"
                f" {release['filings_kept']:,} holdings reports kept,"
                f" {release['filings_dropped']:,} for quarters the book does not cover"
                f" dropped, {release['rows_kept']:,} rows for {release['companies']}"
                f" companies; {states.get(SUPERSEDED, 0):,} filings now replaced by a"
                f" later report")
            if short:
                worst = short[0]
                self._notes.append(
                    f"holders_13f: {len(short)} reports in {release['release']} list"
                    f" far fewer lines than their own summary page states, the largest"
                    f" {worst['manager_name']} for {worst['period_of_report']}"
                    f" ({worst['rows_found']:,} of {worst['table_entries']:,} lines);"
                    f" no change is read off them")
            if untyped:
                self._notes.append(
                    f"holders_13f: {untyped} amendments in {release['release']} tick"
                    f" neither restatement nor new holdings, so they are stored and"
                    f" not applied")
            if release.get("malformed"):
                self._notes.append(
                    f"holders_13f: {release['malformed']:,} lines of"
                    f" {release['release']} had the wrong number of columns and were"
                    f" skipped")
        return RefreshResult(self.source, written, errors=list(self._errors),
                             notes=list(self._notes))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Read the newest SEC Form 13F data sets for the book's companies.")
    parser.parse_args(argv)
    fetcher = Holders13FFetcher()
    fetcher.force = True
    result = fetcher.run()
    print(json.dumps({"rows_written": result.rows_fetched,
                      "downloads": fetcher.downloads, "errors": result.errors,
                      "notes": result.notes, "elapsed_ms": result.elapsed_ms}, indent=1))


if __name__ == "__main__":
    main()
