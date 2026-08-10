"""The IR page, for the fourteen companies that publish no feed.

Fifty-six of seventy answer with RSS. The rest include GSK, Merck, Johnson & Johnson,
Sanofi, Roche and Novo Nordisk, which between them are a large part of the universe by
revenue and were reaching the change feed only through their SEC filings, or in Roche and
Bayer's case not at all.

Five of the fourteen work: GSK, Johnson & Johnson, Merck, Roche and, thinly, Bayer. The
other nine draw their lists with script after the page loads, and what Jina returns for
them is a navigation bar and a cookie banner. They stay seeded because the url is right
and a key would resolve them, and because a fetcher that says it found nothing is worth
more than a company quietly absent from the list.

Jina Reader (``https://r.jina.ai/<url>``) renders a page to markdown, free and without a
key. Two passes: the listing gives the release urls, and each release page gives its own
``Title:`` and ``Published Time:``. The second pass exists because the four listings look
nothing like each other while Jina's page header is identical for all of them, so the
headline is the company's exactly rather than something reassembled out of a list item.

This is a scrape and it is worth saying what that costs. A feed is a contract and a page
is not, so a redesign breaks this where it would not break ``press_ir``, and the failure
is silent: the listing still renders, the urls simply stop matching. Hence the note when a
run finds nothing on a page that has worked before. Set ``JINA_API_KEY`` to lift the rate
limit; without one the free tier is about twenty requests a minute, which is why the
number of releases read per company per run is capped.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

import db
import press_pages
import press_releases
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "press_page"
TTL_SECONDS = 12 * 60 * 60
READER = "https://r.jina.ai/"
_TIMEOUT_S = 90

# The free tier is roughly twenty requests a minute per address, and each new release
# costs one. Ten a company a run is the whole of a listing page on the first run and far
# more than a day's news after it.
MAX_RELEASES = 10
_PAUSE_S = 3.0


def _read(url: str, timeout: int = _TIMEOUT_S) -> str:
    headers = {"User-Agent": "NovatalisResearch/0.1", "Accept": "text/plain"}
    key = os.getenv("JINA_API_KEY", "").strip()
    if key:
        # The controls that make a client-rendered list resolve are ignored on the free
        # tier: sent without a key, x-engine and x-no-cache return the same cached bytes
        # to the byte. They are worth sending only alongside one.
        headers["Authorization"] = f"Bearer {key}"
        headers["x-engine"] = "browser"
        headers["x-no-cache"] = "true"
    request = urllib.request.Request(READER + url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


class PressPageFetcher(BaseFetcher):
    """One IR listing per company, read through Jina, releases out."""

    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()
        self.errors: list[str] = []
        self.listed = 0

    @property
    def entity_key(self) -> str:
        return self.ticker

    def _company(self):
        conn = db.get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT id, ticker, name, ir_news_url FROM companies WHERE ticker = ?",
                (self.ticker,)).fetchone()
        finally:
            conn.close()
        if not row:
            raise ValueError(f"no company {self.ticker}")
        return dict(row)

    def _known(self, urls) -> set:
        """The release urls already stored, so a run pays Jina only for what is new."""
        if not urls:
            return set()
        conn = db.get_connection(self.db_path)
        try:
            marks = ",".join("?" * len(urls))
            return {r[0] for r in conn.execute(
                f"SELECT url FROM news WHERE url IN ({marks})", list(urls))}
        finally:
            conn.close()

    def fetch(self) -> dict:
        company = self._company()
        listing = (company["ir_news_url"] or "").strip()
        if not listing:
            return {"company": company, "releases": None}
        index = _read(listing)
        urls = press_pages.release_urls(index, listing)
        # Roche's release pages carry no Published Time, so without the listing's own
        # dates its news would arrive undated, and an undated release never reaches the
        # change feed. The page's date still wins where it has one.
        dates = press_pages.listing_dates(index, listing)
        self.listed = len(urls)
        fresh = [u for u in urls if u not in self._known(urls)][:MAX_RELEASES]
        releases = []
        for i, url in enumerate(fresh):
            if i:
                time.sleep(_PAUSE_S)        # the free tier is about 20 a minute
            try:
                page = press_pages.release(_read(url))
            except Exception as exc:        # one release, not the company
                self.errors.append(f"{self.ticker} {url}: {exc}")
                continue
            if page:
                releases.append({**page, "url": url,
                                 "published": page["published"] or dates.get(url)})
        return {"company": company, "releases": releases}

    def normalise(self, raw) -> list[dict]:
        company = raw["company"]
        self.no_page = raw["releases"] is None
        if self.no_page:
            return []
        rows = []
        for item in raw["releases"]:
            kind, ahead = press_releases.classify(item["title"])
            rows.append({
                "company_id": company["id"], "ticker": company["ticker"],
                "title": item["title"], "url": item["url"],
                "published": item["published"], "kind": kind, "ahead": ahead,
                "stated_date": press_releases.stated_date(item["title"]) if ahead
                else None,
            })
        return rows

    def snapshot(self, rows: list[dict]) -> None:
        self._write_snapshot({"listed": self.listed, "read": len(rows),
                              "fetch_kind": "live"})

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM news n JOIN companies c ON c.id = n.company_id"
                " WHERE n.source = ? AND c.ticker = ?",
                (SOURCE, self.ticker)).fetchone()[0]
        finally:
            conn.close()
        self._write_snapshot({"releases": n, "fetch_kind": "cache"})

    def _write_snapshot(self, payload) -> None:
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'company', ?, ?, ?)",
                (SOURCE, self.entity_key, json.dumps(payload), self.refresh_run_id))
            conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        if getattr(self, "no_page", False):
            return RefreshResult(SOURCE, 0,
                                 notes=[f"{self.ticker}: no IR page seeded"])
        conn = db.get_connection(self.db_path)
        try:
            written, changed, catalysts = press_releases.record(
                conn, rows, SOURCE, self.refresh_run_id)
            conn.commit()
        finally:
            conn.close()
        notes = []
        if written:
            notes.append(f"{self.ticker}: {written} releases, {changed} changes,"
                         f" {catalysts} catalysts")
        elif not self.listed:
            # The page rendered and matched nothing. A scrape fails this way rather than
            # by raising, so it is said out loud instead of passing as a quiet day. Nine
            # of the fourteen do this today, their lists being drawn by script after the
            # page loads; a JINA_API_KEY is what would resolve them.
            notes.append(f"{self.ticker}: the IR page listed no releases, so either it"
                         " was redesigned or its list needs a JINA_API_KEY to render")
        return RefreshResult(SOURCE, written, errors=list(self.errors), notes=notes)
