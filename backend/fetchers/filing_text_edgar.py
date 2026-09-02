"""Filing text from EDGAR: the periodic reports, and the current reports between them.

A per-company fetcher that reads the primary document of the recent filings already listed
in the filings table, extracts the tracked sections, and stores them (migration 008). The
diff engine then compares each section to the last filing of the same form. Only filings
whose sections are not stored yet are downloaded, so the first run reads the latest few of
each form and later runs read only what is new.

Three kinds of document, read by their own rules. A 10-K or 10-Q gives risk factors and
MD&A by item number. A 20-F is the foreign filer's annual report and is not laid out like
a 10-K: its risk factors are Item 3.D, and its financial review is kept whole because the
review Item 5 points at is printed further down the same document.

An 8-K or 6-K is the third, and it is the one that carries what happened between the
quarters. Its body is short and often only a pointer: Dyne's quarterly 8-K says that "a
copy of the press release is furnished as Exhibit 99.1", and the results, the cash
position and the IND clearance are all in that exhibit. So a current report is read twice,
the body for its item numbers and the exhibit for the news, which needs the filing's own
directory listing to find. Without the exhibit the stored text says nothing the filing's
title did not already say.

The documents are large, so the fetch is polite: a short sleep between requests and never
more than a handful of filings a company.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request

import db
import edgar_items
import filingtext
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "filing_text"
TTL_SECONDS = 24 * 60 * 60
_TIMEOUT_S = 40
_SLEEP_S = 0.3                      # EDGAR asks for under 10 requests a second
# The 20-F is the foreign filer's annual report and the 6-K its current report. Roche and
# Bayer are not SEC registrants at all, so they have no filing here whatever the form.
FORMS = ("10-K", "10-Q", "20-F", "8-K", "6-K")
# How many of each form to read. Two of a periodic report seeds one comparison. A current
# report is not compared to anything, it is read for what it says, and a busy filer files
# several a quarter, so more of them are taken.
PER_FORM = {"10-K": 2, "10-Q": 2, "20-F": 2, "8-K": 8, "6-K": 8}
_DEFAULT_PER_FORM = 2

# How many of a current report budget are held for the ones that report results, and how
# far back to look for them.
#
# Taking the most recent eight 8-Ks spends the budget on whatever a company happened to
# file lately, and what a company files lately is mostly director changes and shareholder
# votes. Abeona's earnings release for the June 2025 quarter is its eleventh most recent
# 8-K, so it was never read: twelve thousand characters stating 225.9m of cash, the
# quarter's R&D and SG&A, the balance sheet and the launch of its first approved product,
# in a filing already indexed and one request away.
#
# An earnings release is the densest document a company files, and a small company files
# few of them and many of everything else, so the reserve matters most exactly where the
# data is thinnest.
RESULTS_RESERVED = 5
_LOOKBACK = 60                      # filings to consider before choosing, per form
CURRENT_REPORTS = ("8-K", "6-K")

# A press release furnished with a current report. Filenames vary by filing agent, and
# the word is spelled out as often as it is abbreviated: dyn-ex99_1.htm, d123456dex991.htm
# and exhibit992sail.htm are all exhibit 99. Matching "ex99" alone missed the third, which
# is how Johnson & Johnson's agent names them.
_EXHIBIT_NAME = re.compile(r"ex(?:hibit)?9{2}", re.I)
_EXHIBITS_PER_FILING = 3            # 99.1 to 99.3; the rest are consents and opinions

# The filing's own index page states each document's type, and that is the record to
# read. Lilly's agent names its release "q226lillysalesandearningsp.htm", with no
# "ex99" anywhere in it, and every Lilly earnings release on file was the 8-K's body
# alone: a pointer, with the news missing. A row of the index table is the sequence,
# the description, the document link, the type and the size.
_INDEX_ROW = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>\d+</td>\s*<td[^>]*>[^<]*</td>\s*"
    r"<td[^>]*><a href=\"([^\"]+)\">[^<]*</a>[^<]*(?:<(?!/tr>)[^>]+>[^<]*)*</td>\s*"
    r"<td[^>]*>(EX-99[^<]*)</td>", re.I | re.S)


def exhibits_from_index(page: str) -> list:
    """The documents an index page types as exhibit 99, as site-relative paths."""
    out = []
    for href, _kind in _INDEX_ROW.findall(page or ""):
        if href.startswith("/ix?doc="):
            href = href[len("/ix?doc="):]
        out.append(href)
    return out


class FilingTextEdgarFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()

    @property
    def entity_key(self) -> str:
        return self.ticker

    def _pending(self, conn) -> list[dict]:
        """The recent 10-K and 10-Q filings whose sections are not stored yet."""
        company = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (self.ticker,)).fetchone()
        if company is None:
            return []
        pending = []
        for form in FORMS:
            filings = self._choose(conn, company["id"], form)
            for f in filings:
                # A 10-K is done only once its patents section is recorded, so filings
                # stored before that section existed are re-read to add it; a 10-Q has no
                # patents section and is done once anything is stored.
                # A 10-K is done once its patents section is recorded and a 20-F once
                # its financial review is, so filings stored before either section
                # existed are re-read to add it.
                marker = ("AND section = 'patents'" if form == "10-K" else
                          "AND section = 'financial_review'" if form == "20-F" else
                          "AND section = 'body'" if form in CURRENT_REPORTS else "")
                have = conn.execute(
                    f"SELECT COUNT(*) FROM filing_sections WHERE accession = ? {marker}",
                    (f["accession"],)).fetchone()[0]
                if not have:
                    pending.append({**dict(f), "company_id": company["id"]})
        return pending

    def _choose(self, conn, company_id: int, form: str) -> list:
        """The filings of one form worth reading, newest first.

        For an annual or quarterly report that is simply the most recent ones. For a
        current report it is the most recent earnings releases first, then the most recent
        of anything else, because recency alone buys a company's director changes and
        leaves its results unread.
        """
        budget = PER_FORM.get(form, _DEFAULT_PER_FORM)
        rows = conn.execute(
            "SELECT accession, form_type, filed_date, url, title FROM filings"
            " WHERE company_id = ? AND form_type = ? AND url IS NOT NULL"
            " ORDER BY filed_date DESC LIMIT ?",
            (company_id, form, _LOOKBACK if form in CURRENT_REPORTS else budget)).fetchall()
        if form not in CURRENT_REPORTS:
            return [dict(r) for r in rows]
        results = [r for r in rows if edgar_items.reports_results(r["title"])]
        chosen = list(results[:RESULTS_RESERVED])
        taken = {r["accession"] for r in chosen}
        for row in rows:                       # fill what is left, newest first
            if len(chosen) >= budget:
                break
            if row["accession"] not in taken:
                chosen.append(row)
                taken.add(row["accession"])
        chosen.sort(key=lambda r: r["filed_date"], reverse=True)
        return [dict(r) for r in chosen]

    def _read(self, url: str, user_agent: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            return resp.read().decode("utf-8", "replace")

    def _exhibit_urls(self, primary_url: str, user_agent: str) -> list:
        """The press releases furnished with a current report, from its own directory.

        EDGAR publishes an index.json beside every filing. One extra request buys the
        exhibit that holds the news, which is the only reason to read an 8-K at all.
        """
        directory = primary_url.rsplit("/", 1)[0] + "/"
        # The typed index first. The folder name is the accession without its dashes.
        folder = directory.rstrip("/").rsplit("/", 1)[-1]
        if len(folder) == 18 and folder.isdigit():
            accession = f"{folder[:10]}-{folder[10:12]}-{folder[12:]}"
            try:
                page = self._read(f"{directory}{accession}-index.html", user_agent)
                typed = [f"https://www.sec.gov{path}" if path.startswith("/") else directory + path
                         for path in exhibits_from_index(page)
                         if path.lower().endswith((".htm", ".html", ".txt"))]
                if typed:
                    return typed[:_EXHIBITS_PER_FILING]
            except Exception:
                pass                           # the untyped listing below still serves
        try:
            listing = json.loads(self._read(directory + "index.json", user_agent))
        except Exception:
            return []
        names = [item.get("name") or ""
                 for item in listing.get("directory", {}).get("item", [])]
        wanted = [n for n in names
                  if _EXHIBIT_NAME.search(n.replace("-", "").replace("_", ""))
                  and n.lower().endswith((".htm", ".html", ".txt"))]
        return [directory + n for n in sorted(wanted)[:_EXHIBITS_PER_FILING]]

    def fetch(self) -> list[dict]:
        user_agent = (os.getenv("SEC_USER_AGENT") or "").strip()
        if not user_agent:
            raise RuntimeError("SEC_USER_AGENT is not set; EDGAR blocks anonymous requests")
        conn = db.get_connection(self.db_path)
        try:
            pending = self._pending(conn)
        finally:
            conn.close()
        rows = []
        for filing in pending:
            try:
                html = self._read(filing["url"], user_agent)
            except Exception:
                continue                       # one unreadable filing never fails the run
            full = filingtext.html_to_text(html)
            form = filing["form_type"]
            if form in CURRENT_REPORTS:
                for name, text in filingtext.extract_current_report(full).items():
                    if text:
                        rows.append({**filing, "section": name, "text": text})
                # The body is a pointer; the exhibit is the news. Missing exhibits are not
                # an error: most 8-Ks furnish none, and the body still stands on its own.
                # Each exhibit is its own section, because one 8-K can furnish two press
                # releases about two different deals: J&J announced Firefly at 1bn and
                # Sail at 2.58bn in one filing, and joined into one document the terms of
                # each read as the terms of the other.
                time.sleep(_SLEEP_S)
                for index, url in enumerate(self._exhibit_urls(filing["url"], user_agent)):
                    try:
                        text = filingtext.html_to_text(self._read(url, user_agent))
                    except Exception:
                        text = ""
                    if text:
                        rows.append({**filing,
                                     "section": filingtext.exhibit_section(index),
                                     "text": text[:filingtext.CURRENT_REPORT_MAX]})
                    time.sleep(_SLEEP_S)
                continue

            is_20f = form == "20-F"
            sections = (filingtext.extract_20f_sections(full) if is_20f
                        else filingtext.extract_sections(full))
            for name in (filingtext.SECTIONS_20F if is_20f else filingtext.SECTIONS):
                text = sections.get(name) or ""
                if text:
                    rows.append({**filing, "section": name, "text": text})
            # Patent-cliff years sit in Item 1 and its patent table, not risk factors, so
            # they are harvested from the whole 10-K rather than a section span.
            if form in ("10-K", "20-F"):
                patents = filingtext.patent_passages(full)
                if patents:
                    rows.append({**filing, "section": "patents", "text": patents})
            time.sleep(_SLEEP_S)
        return rows

    def normalise(self, raw) -> list[dict]:
        return raw

    def snapshot(self, rows: list[dict]) -> None:
        self._write_snapshot({"sections": len(rows), "fetch_kind": "live"})

    def _snapshot_cache(self) -> None:
        self._write_snapshot({"fetch_kind": "cache"})

    def _write_snapshot(self, payload: dict) -> None:
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'filing_text', ?, ?, ?)",
                (self.source, self.ticker, json.dumps(payload), self.refresh_run_id))
            conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        written = 0
        try:
            for row in rows:
                # A filing is immutable once public, so a stored section is never
                # rewritten; re-fetching the same accession is a no-op.
                changed = conn.execute(
                    """
                    INSERT INTO filing_sections
                        (company_id, accession, form_type, filed_date, section,
                         char_count, text)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(accession, section) DO NOTHING
                    """,
                    (row["company_id"], row["accession"], row["form_type"],
                     row["filed_date"], row["section"], len(row["text"]),
                     row["text"])).rowcount
                written += changed
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, written)
