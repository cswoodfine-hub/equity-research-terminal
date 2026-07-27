"""Risk factors and MD&A text from EDGAR annual and quarterly filings.

A per-company fetcher that reads the primary document of the recent 10-K, 10-Q and 20-F
filings already listed in the filings table, extracts the two tracked sections, and
stores them (migration 008). The diff engine then compares each section to the last
filing of the same form. Only filings whose sections are not stored yet are downloaded,
so the first run reads the two most recent of each form to seed a comparison and later
runs read only what is new.

The documents are large, so the fetch is polite: one section pull per filing, a short
sleep between, and never more than a handful of filings a company. Foreign filers file a
20-F, whose sections sit under different item numbers, so it is read by its own rules:
its risk factors are Item 3.D, and its financial review is kept whole because the review
Item 5 points at is printed further down the same document.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request

import db
import filingtext
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "filing_text"
TTL_SECONDS = 24 * 60 * 60
_TIMEOUT_S = 40
_SLEEP_S = 0.3                      # EDGAR asks for under 10 requests a second
# The 20-F is the foreign filer's annual report. Roche and Bayer are not SEC
# registrants at all, so they have no filing here to read whatever the form.
FORMS = ("10-K", "10-Q", "20-F")
PER_FORM = 2                        # the latest two of each form seed one comparison


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
            filings = conn.execute(
                "SELECT accession, form_type, filed_date, url FROM filings"
                " WHERE company_id = ? AND form_type = ? AND url IS NOT NULL"
                " ORDER BY filed_date DESC LIMIT ?",
                (company["id"], form, PER_FORM)).fetchall()
            for f in filings:
                # A 10-K is done only once its patents section is recorded, so filings
                # stored before that section existed are re-read to add it; a 10-Q has no
                # patents section and is done once anything is stored.
                # A 10-K is done once its patents section is recorded and a 20-F once
                # its financial review is, so filings stored before either section
                # existed are re-read to add it.
                marker = ("AND section = 'patents'" if form == "10-K" else
                          "AND section = 'financial_review'" if form == "20-F" else "")
                have = conn.execute(
                    f"SELECT COUNT(*) FROM filing_sections WHERE accession = ? {marker}",
                    (f["accession"],)).fetchone()[0]
                if not have:
                    pending.append({**dict(f), "company_id": company["id"]})
        return pending

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
                request = urllib.request.Request(
                    filing["url"], headers={"User-Agent": user_agent})
                with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
                    html = resp.read().decode("utf-8", "replace")
            except Exception:
                continue                       # one unreadable filing never fails the run
            full = filingtext.html_to_text(html)
            is_20f = filing["form_type"] == "20-F"
            sections = (filingtext.extract_20f_sections(full) if is_20f
                        else filingtext.extract_sections(full))
            for name in (filingtext.SECTIONS_20F if is_20f else filingtext.SECTIONS):
                text = sections.get(name) or ""
                if text:
                    rows.append({**filing, "section": name, "text": text})
            # Patent-cliff years sit in Item 1 and its patent table, not risk factors, so
            # they are harvested from the whole 10-K rather than a section span.
            if filing["form_type"] in ("10-K", "20-F"):
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
