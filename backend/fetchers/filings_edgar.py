"""Recent SEC filings from EDGAR submissions.

Populates the filings table with material forms and turns 8-K / 6-K (material events,
often press releases) into news. New filings become "new_filing" signals in the diff
engine. The same endpoint serves US filers (8-K/10-K/10-Q) and foreign filers (6-K/20-F).
"""

from __future__ import annotations

import json
import os
import urllib.request

import db
import edgar_items
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "filings"
EDGAR_SOURCE = "edgar"
TTL_SECONDS = 24 * 60 * 60

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_TIMEOUT_S = 30
MAX_FILINGS = 60  # keep the recent material filings, not the whole history

MATERIAL_FORMS = {"8-K", "6-K", "10-K", "10-Q", "20-F", "40-F"}
NEWS_FORMS = {"8-K", "6-K"}


def _doc_url(cik, accession, primary_document) -> str:
    cik_int = str(int(cik)) if str(cik).strip() else ""
    base = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession.replace('-', '')}"
    return f"{base}/{primary_document}" if primary_document else base


def parse_submissions(payload: dict, cik: str) -> list[dict]:
    """Turn an EDGAR submissions payload into material filing rows. Pure."""
    recent = (payload.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    documents = recent.get("primaryDocument") or []
    descriptions = recent.get("primaryDocDescription") or []
    items = recent.get("items") or []

    rows = []
    for i, form in enumerate(forms):
        if form not in MATERIAL_FORMS:
            continue
        accession = accessions[i]
        document = documents[i] if i < len(documents) else ""
        description = descriptions[i] if i < len(descriptions) else ""
        item_codes = items[i] if i < len(items) else ""
        # The item codes say what an 8-K is about. primaryDocDescription is almost
        # always just the form name, so the whole feed read "8-K: 8-K" without this.
        title = edgar_items.describe(item_codes, form)
        if title == form and description and description != form:
            title = description
        rows.append(
            {
                "form_type": form,
                "filed_date": dates[i] if i < len(dates) else None,
                "accession": accession,
                "title": title,
                "items": item_codes,
                "is_material": edgar_items.is_material(item_codes),
                "url": _doc_url(cik, accession, document),
            }
        )
        if len(rows) >= MAX_FILINGS:
            break
    return rows


class FilingsEdgarFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()
        self._cik = None

    @property
    def entity_key(self) -> str:
        return self.ticker

    def _company(self, conn):
        return conn.execute(
            "SELECT id, cik FROM companies WHERE ticker = ?", (self.ticker,)
        ).fetchone()

    def fetch(self) -> dict:
        conn = db.get_connection(self.db_path)
        try:
            company = self._company(conn)
        finally:
            conn.close()
        if company is None or not company["cik"]:
            raise ValueError(f"no CIK for {self.ticker}")
        self._cik = company["cik"]
        user_agent = (os.getenv("SEC_USER_AGENT") or "").strip()
        if not user_agent:
            raise RuntimeError("SEC_USER_AGENT is not set; EDGAR blocks anonymous requests")
        url = SUBMISSIONS_URL.format(cik=self._cik)
        request = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def normalise(self, raw) -> list[dict]:
        return parse_submissions(raw, self._cik)

    # --- snapshots -------------------------------------------------------
    def _write_snapshot(self, conn, payload):
        conn.execute(
            """
            INSERT INTO snapshots (source, entity_type, entity_key, payload, refresh_run_id)
            VALUES (?, 'company', ?, ?, ?)
            """,
            (self.source, self.ticker, json.dumps(payload), self.refresh_run_id),
        )

    def snapshot(self, rows: list[dict]) -> None:
        conn = db.get_connection(self.db_path)
        try:
            self._write_snapshot(
                conn,
                {"ticker": self.ticker, "filings": len(rows),
                 "latest": rows[0]["accession"] if rows else None,
                 "source": EDGAR_SOURCE, "fetch_kind": "live"},
            )
            conn.commit()
        finally:
            conn.close()

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            company = self._company(conn)
            if company is None:
                return
            n = conn.execute(
                "SELECT COUNT(*) FROM filings WHERE company_id = ?", (company["id"],)
            ).fetchone()[0]
            if not n:
                return
            self._write_snapshot(conn, {"ticker": self.ticker, "filings": n,
                                        "source": EDGAR_SOURCE, "fetch_kind": "cache"})
            conn.commit()
        finally:
            conn.close()

    # --- current-state tables --------------------------------------------
    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        try:
            company = self._company(conn)
            if company is None:
                return RefreshResult(self.source, 0, [f"unknown ticker {self.ticker}"], False, 0)
            company_id = company["id"]
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO filings
                        (company_id, form_type, filed_date, accession, title, url, source, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(accession) DO UPDATE SET
                        form_type=excluded.form_type, filed_date=excluded.filed_date,
                        title=excluded.title, url=excluded.url, fetched_at=datetime('now')
                    """,
                    (company_id, row["form_type"], row["filed_date"], row["accession"],
                     row["title"], row["url"], EDGAR_SOURCE),
                )
                if row["form_type"] in NEWS_FORMS:
                    conn.execute(
                        """
                        INSERT INTO news (company_id, source, title, url, published_at)
                        VALUES (?, 'edgar_8k', ?, ?, ?)
                        ON CONFLICT(url) DO NOTHING
                        """,
                        (company_id, f"{row['form_type']}: {row['title']}", row["url"],
                         row["filed_date"]),
                    )
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(rows), [], False, 0)
