"""Form 13F holders: the listing page, the tables, the amendment rule, the option split,
the load on a temp database and the reader built on it. No network.

The fixture is real. `fixtures/holders_13f/` holds lines copied byte for byte from the
SEC's March to May 2026 and June to August 2026 data sets (read 2026-11-23), one folder
a release with the ZIP's own member names, and the test zips each folder the way the
SEC ships it. 54 submissions from 26 filers, 796 holdings lines. Nothing in it is edited.
What was done is cutting:

  - seven small managers are whole, with their SUMMARYPAGE rows: Lilly Endowment,
    Defilade, Novo Holdings, Matthew 25, Morgens Waterfall, Arini and Ramiah;
  - fourteen large ones are cut to the lines naming Lilly (532457108), Dyne
    (26818M108) or Novo Nordisk's ADR (670100205), the official list's option
    pseudo-CUSIPs for Lilly, and each filing's first two other lines. They carry no
    SUMMARYPAGE row, since a stated total would no longer describe a cut table. Two
    exceptions keep theirs because the stated total is the point: JPMorgan's first
    report for March, which lists 378 of the 33,063 lines its summary page states,
    and Norges Bank's, which lists one placeholder line of 1,507;
  - one notice (13F-NT), one report for a quarter the book does not cover and one
    amendment that ticks neither box, for the paths that drop them.

`sec_13f_data_sets_listing.html` is the listing page's table as served, six of its 54
rows kept.

Why these managers. CalSTRS filed June with its share and value columns swapped and
restated the same day. Defilade restated March in June, so the restatement is in the
later release. Arini's and Stempoint's amendments tick "adds new holdings" and are the
whole report again. Ramiah's is a real addendum. T. Rowe Price still reports values in
thousands. PeakShares reports them a thousand times too large. Susquehanna holds
puts, calls and shares in the same three companies. Buffalo ticked "principal amount"
against its Lilly shares in June. Jupiter Topco first filed in June.
"""

from __future__ import annotations

import ast
import json
import zipfile
from pathlib import Path

import pytest

import cusips
import db
import holders
from fetchers import holders_13f
from fetchers.holders_13f import (
    LIVE, SUPERSEDED, UNAPPLIED, Holders13FFetcher, iso_date, parse_infotable,
    parse_listing, parse_release, plan, read_filings, release_window, report_period,
    resolve)

_FIX = Path(__file__).resolve().parent / "fixtures" / "holders_13f"
_MARCH = "01mar2026-31may2026_form13f.zip"
_JUNE = "01jun2026-31aug2026_form13f.zip"
_LISTING = (_FIX / "sec_13f_data_sets_listing.html").read_text(encoding="utf-8")
_LLY, _DYN, _NVO = "532457108", "26818M108", "670100205"

# Managers, by the CIK they file under.
_ENDOWMENT, _BLACKROCK, _SUSQUEHANNA = "0000316011", "0002012383", "0001446194"
_CALSTRS, _JPMORGAN, _NORGES = "0001081019", "0000019617", "0001374170"
_DEFILADE, _ARINI, _RAMIAH, _STEMPOINT = ("0002088557", "0002056819", "0001566307",
                                          "0001952142")
_TROWE, _PEAKSHARES, _BUFFALO, _JUPITER = ("0000080255", "0002113507", "0002103405",
                                           "0002146052")
_MORGENS, _NOVO_HOLDINGS = "0001016150", "0001388325"


def _zip_release(name: str, dest: Path) -> int:
    """Zip a fixture folder into ``dest`` with the member names the SEC uses."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
        for member in sorted((_FIX / name[:-len(".zip")]).glob("*.tsv")):
            archive.write(member, member.name)
    return dest.stat().st_size


class _Sec:
    """The SEC as the fetcher sees it: a listing page and ZIPs, served from disk."""

    def __init__(self, listing=_LISTING, fail=()):
        self.listing = listing
        self.fail = set(fail)
        self.downloads: list[str] = []

    def get_listing(self) -> str:
        return self.listing

    def download(self, url: str, dest: Path) -> int:
        name = url.rsplit("/", 1)[-1]
        self.downloads.append(name)
        if name in self.fail:
            raise ConnectionError("connection reset by peer")
        return _zip_release(name, dest)


def _db(folder: Path) -> str:
    path = str(folder / "holders.db")
    db.init(path)
    conn = db.get_connection(path)
    tickers = sorted({row["ticker"] for row in cusips.load()} | {"ROG"})
    conn.executemany("INSERT INTO companies (id, ticker, name) VALUES (?, ?, ?)",
                     [(i, t, f"{t} company") for i, t in enumerate(tickers, start=1)])
    # Lilly's cover-page share count, as the book holds it. Novo Nordisk has none.
    conn.execute(
        "INSERT INTO financials (company_id, period_end, period_type, metric, value,"
        " unit) SELECT id, '2026-08-03', 'instant', 'SharesOutstanding', 941357065,"
        " 'shares' FROM companies WHERE ticker = 'LLY'")
    conn.commit()
    conn.close()
    return path


def _fetcher(path: str, sec: _Sec, cache: Path) -> Holders13FFetcher:
    fetcher = Holders13FFetcher(path, get_listing=sec.get_listing,
                                download=sec.download, cache_dir=cache)
    fetcher.force = True
    return fetcher


def _query(path: str, sql: str, params=()) -> list[dict]:
    conn = db.get_connection(path)
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


@pytest.fixture(scope="module")
def book(tmp_path_factory):
    """A database with both fixture releases loaded, by one run."""
    folder = tmp_path_factory.mktemp("holders")
    path, sec = _db(folder), _Sec()
    result = _fetcher(path, sec, folder / "cache").run()
    return {"path": path, "sec": sec, "result": result, "cache": folder / "cache",
            "folder": folder}


def _holder(answer: dict, cik: str) -> dict:
    return next(row for row in answer["top"] if row["manager_cik"] == cik)


def _lines(release: str, member: str):
    return (_FIX / release[:-len(".zip")] / member).open(encoding="utf-8", newline="")


# --- the listing page -----------------------------------------------------------------

def test_the_listing_gives_each_data_set_its_address_as_served():
    listing = parse_listing(_LISTING)
    assert [r["release"] for r in listing] == [
        _JUNE, _MARCH, "01dec2025-28feb2026_form13f.zip",
        "01jan2024-29feb2024_form13f.zip", "2023q4_form13f.zip", "2013q2_form13f.zip"]
    # The newest file sits under a different folder from every one before it, which is
    # why the address is read off the page and never built.
    assert listing[0]["url"] == ("https://www.sec.gov/files/datastandardsinnovation/"
                                 "data/form-13f-data-sets/" + _JUNE)
    assert listing[1]["url"] == ("https://www.sec.gov/files/structureddata/data/"
                                 "form-13f-data-sets/" + _MARCH)
    assert (listing[0]["window_start"], listing[0]["window_end"]) == (
        "2026-06-01", "2026-08-31")


def test_both_file_name_shapes_give_a_filing_window():
    assert release_window("01jan2024-29feb2024_form13f.zip") == ("2024-01-01",
                                                                 "2024-02-29")
    assert release_window("2023q4_form13f.zip") == ("2023-10-01", "2023-12-31")
    assert release_window("2013q2_form13f.zip") == ("2013-04-01", "2013-06-30")
    assert release_window("form_13f_readme.pdf") is None
    assert release_window("31feb2026-31may2026_form13f.zip") is None


def test_a_link_off_the_secs_host_is_not_a_data_set():
    planted = _LISTING + ('<a href="https://example.org/files/'
                          '01sep2026-30nov2026_form13f.zip">2026 Sep Oct Nov</a>')
    assert [r["release"] for r in parse_listing(planted)][0] == _JUNE


def test_dates_are_read_without_the_locale():
    assert iso_date("30-JUN-2026") == "2026-06-30"
    assert iso_date("29-feb-2024") == "2024-02-29"
    assert iso_date("30-FEB-2026") is None
    assert iso_date("") is None


def test_the_first_run_takes_two_releases_and_later_runs_only_what_is_newer():
    listing = parse_listing(_LISTING)
    register = {_LLY, _DYN}
    assert [r["release"] for r in plan(listing, {}, register)] == [_MARCH, _JUNE]
    held = {_MARCH: {"window_end": "2026-05-31", "cusips_read": [_LLY, _DYN]}}
    assert [r["release"] for r in plan(listing, held, register)] == [_JUNE]
    held[_JUNE] = {"window_end": "2026-08-31", "cusips_read": [_LLY, _DYN]}
    assert plan(listing, held, register) == []


def test_a_cusip_added_to_the_register_has_the_two_newest_releases_read_again():
    listing = parse_listing(_LISTING)
    held = {_MARCH: {"window_end": "2026-05-31", "cusips_read": [_LLY]},
            _JUNE: {"window_end": "2026-08-31", "cusips_read": [_LLY]}}
    assert plan(listing, held, {_LLY}) == []
    assert [r["release"] for r in plan(listing, held, {_LLY, _DYN})] == [_MARCH, _JUNE]


# --- the tables -----------------------------------------------------------------------

def _june_filings() -> dict:
    with _lines(_JUNE, "SUBMISSION.tsv") as sub, _lines(_JUNE, "COVERPAGE.tsv") as cov, \
            _lines(_JUNE, "SUMMARYPAGE.tsv") as summary:
        return read_filings(sub, cov, summary)


def test_filings_carry_the_form_the_dates_and_the_amendment_boxes():
    filings = _june_filings()
    # 26 submissions, one of them a notice: a 13F-NT has no table and is not kept.
    assert len(filings) == 25
    assert {f["submission_type"] for f in filings.values()} == {"13F-HR", "13F-HR/A"}
    restated = filings["0001081019-26-000020"]
    assert restated["manager_name"] == "CALIFORNIA STATE TEACHERS RETIREMENT SYSTEM"
    assert (restated["manager_cik"], restated["period_of_report"],
            restated["filing_date"]) == (_CALSTRS, "2026-06-30", "2026-08-24")
    assert (restated["is_amendment"], restated["amendment_type"]) == (True,
                                                                     "RESTATEMENT")
    first = filings["0001081019-26-000019"]
    assert (first["is_amendment"], first["amendment_type"]) == (False, None)
    addendum = filings["0001172661-26-003819"]
    assert (addendum["amendment_type"], addendum["amendment_no"],
            addendum["table_entries"], addendum["table_value"]) == (
        "NEW HOLDINGS", 1, 28, 974731526)


def test_a_cik_filed_without_its_leading_zeros_is_the_same_manager():
    with _lines(_MARCH, "SUBMISSION.tsv") as sub, _lines(_MARCH, "COVERPAGE.tsv") as cov:
        filings = read_filings(sub, cov)
    # SUBMISSION.tsv writes this one as 1539994.
    assert filings["0001539994-26-000022"]["manager_cik"] == "0001539994"


def test_a_release_is_for_the_quarter_most_of_its_reports_name():
    # The June file also carries a report for December 2023 and a restatement of
    # March. Its name says only when the filings were made.
    filings = _june_filings()
    assert {"2023-12-31", "2026-03-31"} < {f["period_of_report"]
                                           for f in filings.values()}
    assert report_period(filings) == "2026-06-30"


def test_a_managers_lines_for_one_security_are_one_position():
    filings = _june_filings()
    with _lines(_JUNE, "INFOTABLE.tsv") as table:
        rows, found, stats = parse_infotable(table, {_LLY, _DYN, _NVO}, filings)
    assert stats == {"lines": 450, "malformed": 0}
    # BlackRock lists Lilly on 23 lines, one for each manager it shares discretion with.
    blackrock = rows[("0002012383-26-003238", _LLY, "", "SH")]
    assert blackrock == {"shares": 67540400, "value": 81009980560, "source_rows": 23}
    # Every line of a kept filing is counted, on the register or off it.
    assert found["0001172661-26-003819"] == [28, 974731526]
    assert {cusip for _, cusip, _, _ in rows} == {_LLY, _DYN, _NVO}


def test_an_option_is_kept_apart_from_the_shares_it_is_over():
    filings = _june_filings()
    with _lines(_JUNE, "INFOTABLE.tsv") as table:
        rows, _, _ = parse_infotable(table, {_LLY}, filings)
    accession = "0001446194-26-000008"
    held = {flag: row for (acc, _, flag, _), row in rows.items() if acc == accession}
    # Susquehanna: 295,487 shares of Lilly, puts over 3.2 million and calls over 3.8
    # million. All three carry Lilly's own CUSIP.
    assert held[""]["shares"] == 295487
    assert held["Put"]["shares"] == 3212700
    assert held["Call"]["shares"] == 3769500
    # JPMorgan files its Lilly options under the official list's pseudo-CUSIPs, which
    # are on no register: they are not read as Lilly, and never as shares.
    with _lines(_JUNE, "INFOTABLE.tsv") as table:
        assert sum("532457908" in line or "532457958" in line for line in table) == 2
    assert not cusips.valid_cusip("532457908") and not cusips.valid_cusip("532457958")


def test_a_renamed_column_fails_loudly():
    with pytest.raises(ValueError, match="SSHPRNAMT"):
        parse_infotable(["ACCESSION_NUMBER\tCUSIP\tVALUE\tSHARES\tPUTCALL\n"], set(),
                        set())


def test_a_line_with_the_wrong_number_of_columns_is_counted_and_skipped():
    with _lines(_JUNE, "INFOTABLE.tsv") as table:
        lines = list(table)
    broken = lines[:2] + [lines[2].rstrip("\r\n") + "\textra\n"] + lines[3:]
    _, _, stats = parse_infotable(broken, {_LLY}, _june_filings())
    assert stats == {"lines": 450, "malformed": 1}


def test_a_filing_made_while_the_form_asked_for_thousands_gets_no_value(tmp_path):
    # Made-up lines, because the two newest releases hold no filing from before 3
    # January 2023 and the rule still has to hold for whoever loads an older one.
    members = {
        "SUBMISSION.tsv": "ACCESSION_NUMBER\tFILING_DATE\tSUBMISSIONTYPE\tCIK\t"
                          "PERIODOFREPORT\n"
                          "A-1\t14-NOV-2022\t13F-HR\t1\t30-SEP-2022\n"
                          "A-2\t03-JAN-2023\t13F-HR\t2\t30-SEP-2022\n",
        "COVERPAGE.tsv": "ACCESSION_NUMBER\tISAMENDMENT\tAMENDMENTTYPE\t"
                         "FILINGMANAGER_NAME\tREPORTTYPE\n"
                         "A-1\t\t\tEarly\t13F HOLDINGS REPORT\n"
                         "A-2\t\t\tLate\t13F HOLDINGS REPORT\n",
        "INFOTABLE.tsv": "ACCESSION_NUMBER\tCUSIP\tVALUE\tSSHPRNAMT\tSSHPRNAMTTYPE\t"
                         "PUTCALL\n"
                         f"A-1\t{_LLY}\t3233\t10000\tSH\t\n"
                         f"A-2\t{_LLY}\t3233000\t10000\tSH\t\n"}
    path = tmp_path / "2022q4_form13f.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    parsed = parse_release(path, {_LLY})
    values = {h["accession_number"]: h["value_usd"] for h in parsed["holdings"]}
    assert values == {"A-1": None, "A-2": 3233000}
    assert {h["shares"] for h in parsed["holdings"]} == {10000}


def test_a_zip_missing_a_table_is_refused(tmp_path):
    path = tmp_path / "broken_form13f.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("SUBMISSION.tsv", "ACCESSION_NUMBER\n")
    with pytest.raises(ValueError, match="COVERPAGE.TSV, INFOTABLE.TSV"):
        parse_release(path, {_LLY})


# --- amendments -----------------------------------------------------------------------

def _filing(accession, filed, kind=None, number=None, rows=100, value=1000) -> dict:
    return {"accession_number": accession, "filing_date": filed,
            "is_amendment": kind is not None, "amendment_type": kind or None,
            "amendment_no": number, "rows_found": rows, "value_found": value}


def test_a_restatement_replaces_the_report_and_an_addendum_stands_beside_it():
    report = _filing("R", "2026-05-15")
    restated = _filing("R/A1", "2026-05-20", "RESTATEMENT", 1)
    addendum = _filing("R/A2", "2026-06-01", "NEW HOLDINGS", 2, rows=3, value=40)
    assert resolve([addendum, report, restated]) == {
        "R": (SUPERSEDED, "R/A1"), "R/A1": (LIVE, None), "R/A2": (LIVE, None)}
    # A later restatement restates the addendum too. The first report keeps the name
    # of the filing that replaced it, which is the one a reader would look for.
    again = _filing("R/A3", "2026-07-01", "RESTATEMENT", 3)
    assert resolve([report, restated, addendum, again]) == {
        "R": (SUPERSEDED, "R/A1"), "R/A1": (SUPERSEDED, "R/A3"),
        "R/A2": (SUPERSEDED, "R/A3"), "R/A3": (LIVE, None)}


def test_a_report_and_its_amendment_filed_the_same_day_are_taken_in_that_order():
    report = _filing("0001081019-26-000019", "2026-08-24")
    restated = _filing("0001081019-26-000020", "2026-08-24", "RESTATEMENT", 1)
    assert resolve([restated, report]) == {
        "0001081019-26-000019": (SUPERSEDED, "0001081019-26-000020"),
        "0001081019-26-000020": (LIVE, None)}


def test_new_holdings_the_size_of_the_report_is_the_report_again():
    # Arini's real sizes: a 27-line report worth $484 million and an amendment
    # ticked "adds new holdings" of 28 lines worth $975 million.
    report = _filing("0001172661-26-003320", "2026-08-12", rows=27, value=483556989)
    repeat = _filing("0001172661-26-003819", "2026-08-14", "NEW HOLDINGS", 1,
                     rows=28, value=974731526)
    assert resolve([report, repeat]) == {
        "0001172661-26-003320": (SUPERSEDED, "0001172661-26-003819"),
        "0001172661-26-003819": (LIVE, None)}
    # Ramiah's: 35 lines against 32, but a seventh of the value. A different list.
    report = _filing("0001566307-26-000003", "2026-04-21", rows=32, value=99475086)
    addendum = _filing("0001566307-26-000071", "2026-05-29", "NEW HOLDINGS", 1,
                       rows=35, value=14970455)
    assert set(resolve([report, addendum]).values()) == {(LIVE, None)}
    # With no size to hold it against, the box is believed.
    unsized = _filing("X/A", "2026-08-14", "NEW HOLDINGS", 1, rows=None, value=None)
    assert resolve([_filing("X", "2026-08-12"), unsized])["X"] == (LIVE, None)


def test_an_amendment_that_ticks_neither_box_is_not_applied():
    report = _filing("R", "2026-05-15")
    untyped = _filing("R/A", "2026-05-20", "", 1)
    untyped["is_amendment"] = True
    assert resolve([report, untyped]) == {"R": (LIVE, None), "R/A": (UNAPPLIED, None)}


def test_an_addendum_with_no_report_before_it_stands_alone():
    assert resolve([_filing("A", "2026-09-01", "NEW HOLDINGS", 1)]) == {
        "A": (LIVE, None)}


# --- the load -------------------------------------------------------------------------

def test_the_first_run_loads_the_two_newest_releases_oldest_first(book):
    assert book["result"].errors == []
    assert book["sec"].downloads == [_MARCH, _JUNE]
    releases = {r["release"]: r for r in _query(
        book["path"], "SELECT * FROM institutional_holdings_releases")}
    march, june = releases[_MARCH], releases[_JUNE]
    assert (march["report_period"], june["report_period"]) == ("2026-03-31",
                                                               "2026-06-30")
    assert (march["window_start"], march["window_end"]) == ("2026-03-01", "2026-05-31")
    assert june["zip_url"].startswith("https://www.sec.gov/files/"
                                      "datastandardsinnovation/")
    assert (march["submissions"], march["infotable_rows"], march["rows_kept"]) == (
        28, 346, 56)
    assert (june["submissions"], june["infotable_rows"], june["rows_kept"]) == (
        26, 450, 66)
    assert book["result"].rows_fetched == 122
    assert _LLY in june["cusips_read"].split(",")


def test_reports_for_quarters_the_book_does_not_cover_are_dropped(book):
    periods = {r["period_of_report"] for r in _query(
        book["path"], "SELECT DISTINCT period_of_report FROM"
                      " institutional_holdings_filings")}
    assert periods == {"2026-03-31", "2026-06-30"}
    # March dropped a December 2023 report and a June 2025 amendment, June a December
    # 2023 report. June kept its restatement of March, a quarter the book does cover.
    dropped = {r["release"]: r["filings_dropped"] for r in _query(
        book["path"], "SELECT release, filings_dropped FROM"
                      " institutional_holdings_releases")}
    assert dropped == {_MARCH: 2, _JUNE: 1}
    assert not _query(book["path"], "SELECT 1 FROM institutional_holdings_filings"
                                    " WHERE submission_type LIKE '13F-NT%'")


def test_the_zips_are_not_kept(book):
    assert list(book["cache"].glob("*")) == []


def test_a_second_run_downloads_nothing_and_changes_nothing(book):
    before = _query(book["path"], "SELECT COUNT(*) AS n, SUM(shares) AS shares FROM"
                                  " institutional_holdings")[0]
    states = _query(book["path"], "SELECT accession_number, status, superseded_by FROM"
                                  " institutional_holdings_filings ORDER BY 1")
    sec = _Sec()
    again = _fetcher(book["path"], sec, book["cache"])
    result = again.run()
    assert sec.downloads == [] and again.downloads == 0
    assert result.errors == [] and result.rows_fetched == 0
    assert any("already read" in note for note in result.notes)
    assert _query(book["path"], "SELECT COUNT(*) AS n, SUM(shares) AS shares FROM"
                                " institutional_holdings")[0] == before
    assert _query(book["path"], "SELECT accession_number, status, superseded_by FROM"
                                " institutional_holdings_filings ORDER BY 1") == states
    # The check of the listing page is the live fetch the weekly TTL rations.
    newest = _query(book["path"], "SELECT payload FROM snapshots WHERE source ="
                                  " 'holders_13f' ORDER BY id DESC LIMIT 1")[0]
    assert json.loads(newest["payload"])["fetch_kind"] == "live"
    unforced = Holders13FFetcher(book["path"], get_listing=sec.get_listing,
                                 download=sec.download, cache_dir=book["cache"])
    assert unforced.run().skipped_ttl is True


def test_reading_a_release_twice_writes_the_same_rows(tmp_path):
    path, sec = _db(tmp_path), _Sec()
    _fetcher(path, sec, tmp_path / "cache").run()
    first = _query(path, "SELECT accession_number, cusip, put_call, shares_type,"
                         " shares, value_usd, source_rows FROM institutional_holdings"
                         " ORDER BY 1, 2, 3, 4")
    states = _query(path, "SELECT accession_number, status, superseded_by FROM"
                          " institutional_holdings_filings ORDER BY 1")
    # Forget which releases were read, so the same two are read over the same rows.
    conn = db.get_connection(path)
    conn.execute("DELETE FROM institutional_holdings_releases")
    conn.commit()
    conn.close()
    result = _fetcher(path, sec, tmp_path / "cache").run()
    assert result.errors == [] and sec.downloads == [_MARCH, _JUNE] * 2
    assert _query(path, "SELECT accession_number, cusip, put_call, shares_type,"
                        " shares, value_usd, source_rows FROM institutional_holdings"
                        " ORDER BY 1, 2, 3, 4") == first
    assert _query(path, "SELECT accession_number, status, superseded_by FROM"
                        " institutional_holdings_filings ORDER BY 1") == states


def test_a_restatement_filed_the_same_day_replaces_the_swapped_columns(book):
    rows = {r["accession_number"]: r for r in _query(
        book["path"],
        "SELECT h.accession_number, h.shares, h.value_usd, f.status, f.superseded_by"
        "  FROM institutional_holdings h JOIN institutional_holdings_filings f"
        "    ON f.accession_number = h.accession_number JOIN companies c"
        "    ON c.id = h.company_id"
        " WHERE c.ticker = 'LLY' AND h.manager_cik = ?"
        "   AND h.period_of_report = '2026-06-30'", (_CALSTRS,))}
    # As filed first: 1.46 billion "shares" worth $1.2 million. Stored, and marked.
    first, restated = rows["0001081019-26-000019"], rows["0001081019-26-000020"]
    assert (first["shares"], first["value_usd"]) == (1460379190, 1217561)
    assert (first["status"], first["superseded_by"]) == (SUPERSEDED,
                                                         "0001081019-26-000020")
    assert (restated["shares"], restated["value_usd"], restated["status"]) == (
        1217561, 1460379190, LIVE)
    calstrs = _holder(holders.for_company(book["path"], "LLY"), _CALSTRS)
    assert (calstrs["shares"], calstrs["amended"]) == (1217561, True)
    assert (calstrs["previous_shares"], calstrs["change"]) == (1214622, "added")


def test_a_restatement_in_a_later_release_reaches_back(book):
    filings = {r["accession_number"]: r for r in _query(
        book["path"], "SELECT * FROM institutional_holdings_filings WHERE"
                      " manager_cik = ? AND period_of_report = '2026-03-31'",
        (_DEFILADE,))}
    first, restated = filings["0002088557-26-000005"], filings["0002088557-26-000006"]
    assert (first["release"], restated["release"]) == (_MARCH, _JUNE)
    assert (first["status"], first["superseded_by"]) == (SUPERSEDED,
                                                         "0002088557-26-000006")
    assert restated["status"] == LIVE
    # Whole in the data set: the lines found are the lines the summary page states.
    assert (restated["table_entries"], restated["rows_found"]) == (31, 31)
    # And the position is counted once, from the restatement.
    defilade = _holder(holders.for_company(book["path"], "LLY"), _DEFILADE)
    assert (defilade["previous_shares"], defilade["shares"]) == (20696, 39086)


def test_new_holdings_that_repeat_the_report_are_not_counted_twice(book):
    # Arini lists 6,000 Lilly shares in its June report and again in the amendment
    # that "adds new holdings". It holds 6,000, not 12,000.
    arini = _holder(holders.for_company(book["path"], "LLY", top=50), _ARINI)
    assert (arini["shares"], arini["accessions"]) == (6000, ["0001172661-26-003819"])
    # Stempoint's 506,075 Dyne shares at March, the same way, then none at June.
    dyne = holders.for_company(book["path"], "DYN")
    assert dyne["sold_out"] == [{"manager_cik": _STEMPOINT,
                                 "manager": "STEMPOINT CAPITAL LP",
                                 "previous_shares": 506075}]


def test_a_real_addendum_adds_to_the_report(book):
    filings = _query(
        book["path"], "SELECT accession_number, amendment_type, status FROM"
                      " institutional_holdings_filings WHERE manager_cik = ? AND"
                      " period_of_report = '2026-03-31' ORDER BY filing_date",
        (_RAMIAH,))
    assert [(f["amendment_type"], f["status"]) for f in filings] == [
        (None, LIVE), ("NEW HOLDINGS", LIVE)]
    # AbbVie is on the addendum only, and it is what June is measured against.
    ramiah = _holder(holders.for_company(book["path"], "ABBV"), _RAMIAH)
    assert (ramiah["previous_shares"], ramiah["shares"], ramiah["change"]) == (
        1968, 1865, "cut")


# --- the reader -----------------------------------------------------------------------

def test_the_answer_says_which_quarter_and_how_old_it_is(book):
    lilly = holders.for_company(book["path"], "lly")
    assert lilly["available"] is True
    assert (lilly["period"], lilly["previous_period"]) == ("2026-06-30", "2026-03-31")
    assert (lilly["release"], lilly["filed_through"], lilly["filing_deadline"]) == (
        _JUNE, "2026-08-31", "2026-08-14")
    assert (lilly["cusips"], lilly["class_title"], lilly["unit"]) == (
        [_LLY], "COM", "shares")
    assert set(lilly["caveats"]) == {"long_only", "filers_only", "lag", "options",
                                     "as_filed"}
    assert "2026-06-30" in lilly["caveats"]["lag"]
    assert "45 days" in lilly["caveats"]["lag"]
    assert "$100 million" in lilly["caveats"]["filers_only"]


def test_top_holders_with_shares_value_and_the_change_since_march(book):
    lilly = holders.for_company(book["path"], "LLY", top=5)
    assert [(h["rank"], h["manager"], h["shares"]) for h in lilly["top"]] == [
        (1, "LILLY ENDOWMENT INC", 90376978),
        (2, "BlackRock, Inc.", 67540400),
        (3, "VANGUARD CAPITAL MANAGEMENT LLC", 53528868),
        (4, "STATE STREET CORP", 36215754),
        (5, "FMR LLC", 28462475)]
    endowment = lilly["top"][0]
    assert (endowment["value_usd"], endowment["previous_shares"],
            endowment["change_shares"], endowment["change"]) == (
        108400858723, 91896978, -1520000, "cut")
    assert lilly["top"][1]["change"] == "added"
    everyone = holders.for_company(book["path"], "LLY", top=50)
    assert lilly["holders"] == everyone["holders"] == len(everyone["top"]) == 16
    assert _holder(everyone, _MORGENS)["change"] == "unchanged"
    assert (_holder(everyone, _ARINI)["change"],
            _holder(everyone, _ARINI)["previous_shares"]) == ("new", 0)
    assert everyone["changes"] == {"new": 1, "added": 8, "cut": 4, "unchanged": 1,
                                   "sold_out": 0, "not_comparable": 2}
    # Sixteen holders, 319.6 million shares, 91% of them with the ten largest.
    assert lilly["shares_held"] == sum(h["shares"] for h in everyone["top"])
    assert lilly["top_ten_share"] == round(
        sum(h["shares"] for h in everyone["top"][:10]) / lilly["shares_held"], 6)


def test_new_and_sold_out_need_a_report_for_both_quarters(book):
    lilly = holders.for_company(book["path"], "LLY", top=50)
    # Jupiter Topco filed nothing for March. That is not a purchase.
    jupiter = _holder(lilly, _JUPITER)
    assert (jupiter["change"], jupiter["previous_shares"]) == (None, None)
    assert "no report" in jupiter["change_note"]
    # Novo Holdings did file for March, without Dyne. That is one.
    dyne = holders.for_company(book["path"], "DYN", top=50)
    novo = _holder(dyne, _NOVO_HOLDINGS)
    assert (novo["change"], novo["previous_shares"], novo["shares"]) == (
        "new", 0, 960394)
    assert dyne["changes"]["sold_out"] == 1 and dyne["not_yet_reported"] == 0


def test_no_change_is_read_off_a_report_that_is_mostly_not_there(book):
    # Norges Bank's March report states 1,507 lines and lists one placeholder.
    stated = _query(book["path"], "SELECT table_entries, rows_found, status FROM"
                                  " institutional_holdings_filings WHERE"
                                  " manager_cik = ? AND period_of_report ="
                                  " '2026-03-31'", (_NORGES,))
    assert stated == [{"table_entries": 1507, "rows_found": 1, "status": LIVE}]
    assert holders.is_short(1507, 1, 864690921985, 0) is True
    lilly = holders.for_company(book["path"], "LLY", top=50)
    norges = _holder(lilly, _NORGES)
    assert norges["shares"] == 11471413
    assert (norges["change"], norges["previous_shares"]) == (None, None)
    assert norges["change_note"] == ("its report for the quarter before lists 1 of "
                                     "the 1,507 lines its summary page states")
    assert lilly["short_reports"] == 1
    assert any("NORGES BANK" in note and "1 of 1,507" in note
               for note in book["result"].notes)
    # JPMorgan's part-filed first report was restated the same day, so it is the
    # amendment rule's business and JPMorgan's change stands.
    assert _holder(lilly, _JPMORGAN)["change"] == "cut"


def test_a_careless_summary_page_is_not_a_missing_report():
    # 59 lines of a stated 60, and a stated value ten times too large: a whole table.
    assert holders.is_short(60, 59, 6893446481, 689344648) is False
    assert holders.is_short(215435, 18827, 3413105261, 274942926) is True
    assert holders.is_short(None, 4, None, 100) is False


def test_options_are_in_no_share_count(book):
    lilly = holders.for_company(book["path"], "LLY", top=50)
    susquehanna = _holder(lilly, _SUSQUEHANNA)
    assert susquehanna["shares"] == 295487
    assert lilly["options"]["put"] == {
        "managers": 1, "shares": 3212700,
        "largest": [{"manager_cik": _SUSQUEHANNA,
                     "manager": "SUSQUEHANNA INTERNATIONAL GROUP, LLP",
                     "shares": 3212700}]}
    assert (lilly["options"]["call"]["managers"],
            lilly["options"]["call"]["shares"]) == (1, 3769500)
    stored = _query(book["path"],
                    "SELECT SUM(h.shares) AS shares FROM institutional_holdings h"
                    "  JOIN institutional_holdings_filings f"
                    "    ON f.accession_number = h.accession_number"
                    "  JOIN companies c ON c.id = h.company_id"
                    " WHERE c.ticker = 'LLY' AND h.period_of_report = '2026-06-30'"
                    "   AND f.status = 'live' AND h.put_call = ''")[0]["shares"]
    # Every share row but PeakShares's, which is set aside below.
    assert lilly["shares_held"] == stored - 1217
    assert "1 managers with puts and 1 with calls" in lilly["caveats"]["options"]


def test_a_value_in_thousands_is_left_null_and_a_nonsense_row_is_set_aside(book):
    lilly = holders.for_company(book["path"], "LLY", top=50)
    assert lilly["median_implied_price"] == pytest.approx(1199.43, abs=0.01)
    trowe = _holder(lilly, _TROWE)
    # 13.9 million shares filed with a value of $16.7 million: thousands.
    assert (trowe["shares"], trowe["value_usd"], trowe["value_as_filed"]) == (
        13911839, None, 16686278)
    assert trowe["value_note"] == "filed in thousands of dollars, so left null"
    assert lilly["value_holders"] == 15
    assert lilly["value_usd"] == sum(h["value_usd"] for h in lilly["top"]
                                     if h["value_usd"])
    # PeakShares: 1,217 shares valued at $1.46 billion.
    assert lilly["set_aside_count"] == 1
    aside = lilly["set_aside"][0]
    assert (aside["manager_cik"], aside["shares_as_filed"], aside["value_as_filed"]) \
        == (_PEAKSHARES, 1217, 1459706000)
    assert _PEAKSHARES not in {h["manager_cik"] for h in lilly["top"]}
    assert "1 positions" in lilly["caveats"]["as_filed"]


def test_shares_ticked_as_a_principal_amount_are_still_shares(book):
    rows = _query(book["path"],
                  "SELECT h.period_of_report, h.shares_type, h.shares FROM"
                  " institutional_holdings h JOIN companies c ON c.id = h.company_id"
                  " WHERE c.ticker = 'LLY' AND h.manager_cik = ? ORDER BY 1",
                  (_BUFFALO,))
    assert rows == [
        {"period_of_report": "2026-03-31", "shares_type": "SH", "shares": 10355},
        {"period_of_report": "2026-06-30", "shares_type": "PRN", "shares": 10454}]
    lilly = holders.for_company(book["path"], "LLY", top=50)
    buffalo = _holder(lilly, _BUFFALO)
    # $12.5 million over 10,454 is Lilly's share price, so the box was the mistake.
    assert (buffalo["shares"], buffalo["previous_shares"], buffalo["change"]) == (
        10454, 10355, "added")
    assert (lilly["principal_read_as_shares"], lilly["principal_amount_rows"]) == (1, 0)
    assert lilly["sold_out"] == []


def test_a_share_of_the_company_only_where_the_book_holds_a_dated_count(book):
    lilly = holders.for_company(book["path"], "LLY")
    assert lilly["shares_outstanding"] == {
        "shares": 941357065.0, "as_of": "2026-08-03", "days_from_period": 34,
        "ordinary_per_depositary_share": None}
    assert lilly["top"][0]["share_of_outstanding"] == round(90376978 / 941357065, 6)
    assert lilly["held_share_of_outstanding"] == round(
        lilly["shares_held"] / 941357065, 6)
    novo = holders.for_company(book["path"], "NVO")
    assert (novo["unit"], novo["class_title"]) == ("depositary shares", "ADR")
    assert novo["shares_outstanding"] is None
    assert novo["held_share_of_outstanding"] is None
    assert novo["top"][0]["share_of_outstanding"] is None
    assert "no share count" in novo["outstanding_note"]
    assert "depositary" in novo["caveats"]["unit"]


def test_a_depositary_share_is_put_on_the_footing_of_the_share_count(tmp_path):
    path = _db(tmp_path)
    _fetcher(path, _Sec(), tmp_path / "cache").run()
    conn = db.get_connection(path)
    # A made-up count of two billion ordinary shares, for the arithmetic only.
    conn.execute(
        "INSERT INTO financials (company_id, period_end, period_type, metric, value,"
        " unit) SELECT id, '2025-12-31', 'instant', 'SharesOutstanding', 2000000000,"
        " 'shares' FROM companies WHERE ticker = 'NVO'")
    conn.execute("UPDATE adr_ratios SET ordinary_per_adr = 0.5 WHERE ticker = 'NVO'")
    conn.commit()
    novo = holders.for_company(path, "NVO")
    assert novo["shares_outstanding"]["ordinary_per_depositary_share"] == 0.5
    assert novo["held_share_of_outstanding"] == round(
        novo["shares_held"] * 0.5 / 2000000000, 6)
    # With no ratio the fraction is null, not a guess at one for one.
    conn.execute("DELETE FROM adr_ratios WHERE ticker = 'NVO'")
    conn.commit()
    conn.close()
    novo = holders.for_company(path, "NVO")
    assert novo["held_share_of_outstanding"] is None
    assert "no ratio" in novo["outstanding_note"]


def test_a_company_with_no_cusip_gets_the_reason_and_no_number(book):
    roche = holders.for_company(book["path"], "ROG")
    assert roche["available"] is False
    assert "over the counter" in roche["reason"]
    assert "holders" not in roche and "top" not in roche
    unknown = holders.for_company(book["path"], "ZZZZ")
    assert (unknown["available"], unknown["reason"]) == (
        False, holders.NOT_IN_UNIVERSE)


def test_a_book_that_has_read_nothing_says_so(tmp_path):
    answer = holders.for_company(_db(tmp_path), "LLY")
    assert (answer["available"], answer["reason"]) == (
        False, "no Form 13F data set has been read yet")


# --- failing soft ---------------------------------------------------------------------

def test_a_failed_download_is_reported_and_the_newer_release_is_not_read(tmp_path):
    path, sec = _db(tmp_path), _Sec(fail={_MARCH})
    result = _fetcher(path, sec, tmp_path / "cache").run()
    # The older release failed, so the newer was never asked for: read over the gap,
    # its restatements of March would have nothing to replace.
    assert sec.downloads == [_MARCH]
    assert len(result.errors) == 1 and _MARCH in result.errors[0]
    assert "ConnectionError" in result.errors[0]
    assert _query(path, "SELECT COUNT(*) AS n FROM institutional_holdings")[0]["n"] == 0
    assert _query(path, "SELECT COUNT(*) AS n FROM"
                        " institutional_holdings_releases")[0]["n"] == 0
    assert list((tmp_path / "cache").glob("*")) == []
    # The next run starts again from the one that failed, and does not wait out the
    # week first: a run that read nothing it wanted is not the TTL's live fetch.
    sec.fail.clear()
    unforced = Holders13FFetcher(path, get_listing=sec.get_listing,
                                 download=sec.download, cache_dir=tmp_path / "cache")
    result = unforced.run()
    assert result.skipped_ttl is False and result.errors == []
    assert sec.downloads == [_MARCH, _MARCH, _JUNE]
    assert unforced.run().skipped_ttl is True


def test_the_older_release_is_kept_when_the_newer_one_fails(tmp_path):
    path, sec = _db(tmp_path), _Sec(fail={_JUNE})
    result = _fetcher(path, sec, tmp_path / "cache").run()
    assert len(result.errors) == 1 and result.rows_fetched == 56
    assert holders.for_company(path, "LLY")["period"] == "2026-03-31"
    sec.fail.clear()
    assert _fetcher(path, sec, tmp_path / "cache").run().rows_fetched == 66
    assert sec.downloads == [_MARCH, _JUNE, _JUNE]
    assert holders.for_company(path, "LLY")["period"] == "2026-06-30"


def test_a_page_with_no_data_set_is_an_error_not_a_crash(tmp_path):
    path = _db(tmp_path)
    result = _fetcher(path, _Sec(listing="<html>maintenance</html>"),
                      tmp_path / "cache").run()
    assert len(result.errors) == 1 and "links no data set" in result.errors[0]
    snapshot = json.loads(_query(
        path, "SELECT payload FROM snapshots WHERE source = 'holders_13f'")[0]["payload"])
    assert snapshot["fetch_kind"] == "error" and "links no data set" in snapshot["error"]


def test_a_truncated_zip_is_reported_and_removed(tmp_path):
    class _Cut(_Sec):
        def download(self, url, dest):
            size = super().download(url, dest)
            dest.write_bytes(dest.read_bytes()[: size // 2])
            return size // 2

    path = _db(tmp_path)
    result = _fetcher(path, _Cut(), tmp_path / "cache").run()
    assert len(result.errors) == 1 and "BadZipFile" in result.errors[0]
    assert list((tmp_path / "cache").glob("*")) == []


def test_a_zip_left_by_a_killed_run_is_cleared(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / (_MARCH + ".part")).write_bytes(b"half a download")
    path = _db(tmp_path)
    assert _fetcher(path, _Sec(), cache).run().errors == []
    assert list(cache.glob("*")) == []


def test_a_bad_register_row_is_reported_and_never_used(tmp_path):
    register = tmp_path / "cusips.csv"
    register.write_text(
        "ticker,cusip,class_title,source,note\n"
        f"LLY,{_LLY},COM,test,\n"
        "DYN,26818M109,COM,test,a wrong check digit\n", encoding="utf-8")
    path, sec = _db(tmp_path), _Sec()
    fetcher = Holders13FFetcher(path, get_listing=sec.get_listing,
                                download=sec.download, cache_dir=tmp_path / "cache",
                                register=register)
    fetcher.force = True
    result = fetcher.run()
    assert len(result.errors) == 1 and "26818M109" in result.errors[0]
    tickers = {r["ticker"] for r in _query(
        path, "SELECT DISTINCT c.ticker FROM institutional_holdings h JOIN companies c"
              " ON c.id = h.company_id")}
    assert tickers == {"LLY"}


# --- the contract ---------------------------------------------------------------------

def test_the_fetcher_imports_no_other_fetcher():
    tree = ast.parse(Path(holders_13f.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert {name for name in imported if name.startswith("fetchers")} == {
        "fetchers.base"}
