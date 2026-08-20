"""A company's own investor-relations feed, which is where it announces things first.

The change feed knew what a company filed with the SEC and what the FDA published, and
almost nothing of what the company said. AstraZeneca's news table held sixty-six rows,
every one an 8-K whose title was the form number twice over, while its own feed carried
1,626 items: "US FDA decision date extended for SERENA-6 filing of camizestrant",
"Ultomiris granted Priority Review", "Truqap recommended by FDA Advisory Committee",
"Trixeo recommended for approval in the EU by CHMP". A decision date moving, a priority
review, an adcomm outcome and a CHMP opinion, none of which reached the terminal.

The deals fetcher's note says IR feeds "sit behind bot protection and time out or
refuse". That is true of the default urllib agent and false of a browser one: all ten
seeded feeds answer, every item carrying a link and a date.

What this cannot do is give the date inside the release. AstraZeneca's feed carries only
link, guid, title and pubDate, with no body at all, so a catalyst is written only where
the headline itself states a full date. A quarter is not a date and is not turned into
one.

The parsing and the classifying live in ``press_releases``, tested against saved feeds.
This module is the plumbing around them.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.request

import db
import press_releases
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "press_ir"
TTL_SECONDS = 6 * 60 * 60
_TIMEOUT_S = 30
# A feed whose newest item is older than a quarter has stopped
# carrying the company, whatever HTTP status it returns.
STALE_FEED_DAYS = 90

# The default urllib agent is refused with a 403 by AstraZeneca and others, so the agent
# is browser-shaped, with the project's name left on it so the request is still
# attributable rather than pretending to be someone else.
#
# The contact address goes in From and not in the agent string. Q4 hosts most of these
# feeds behind a filter that does not refuse an agent containing an email address, it
# hangs: the same URL that answers in 0.1s with the address moved out reads for thirty
# seconds and times out with it in. From is where HTTP puts a contact anyway.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
              " (KHTML, like Gecko) NovatalisResearch/0.1")
CONTACT = "cswoodfine@icloud.com"
HEADERS = {"User-Agent": USER_AGENT, "From": CONTACT,
           "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"}


class PressIrFetcher(BaseFetcher):
    """One IR feed per company, headlines in, news and changes out."""

    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()

    @property
    def entity_key(self) -> str:
        return self.ticker

    def fetch(self) -> dict:
        conn = db.get_connection(self.db_path)
        try:
            company = conn.execute(
                "SELECT id, ticker, name, ir_rss_url FROM companies WHERE ticker = ?",
                (self.ticker,)).fetchone()
        finally:
            conn.close()
        if not company:
            raise ValueError(f"no company {self.ticker}")
        feed = (company["ir_rss_url"] or "").strip()
        if not feed:
            # Not an error. Most of the universe has no feed seeded yet, and a company
            # without one has nothing to report rather than something to fix.
            return {"company": dict(company), "xml": None}
        request = urllib.request.Request(feed, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            xml_text = resp.read().decode("utf-8", "ignore")
        return {"company": dict(company), "xml": xml_text}

    def normalise(self, raw) -> list[dict]:
        company = raw["company"]
        self.no_feed = raw["xml"] is None
        if self.no_feed:
            return []
        rows = []
        for item in press_releases.parse_feed(raw["xml"]):
            if not item["url"]:
                continue        # the url is the identity, and news has no other key
            kind, ahead = press_releases.classify(item["title"])
            rows.append({
                "company_id": company["id"], "ticker": company["ticker"],
                "title": item["title"], "url": item["url"],
                "published": item["published"], "kind": kind, "ahead": ahead,
                "stated_date": press_releases.stated_date(item["title"]) if ahead
                else None,
            })
        return rows

    def newest_published(self, rows: list[dict]) -> str | None:
        dates = sorted(r["published"] for r in rows if r.get("published"))
        return dates[-1] if dates else None

    def stale_by_days(self, rows: list[dict]) -> int | None:
        """How far behind the feed's newest item is, or None if it is current.

        A dead feed does not answer with an error. Moderna's returns HTTP 200 and 142
        items every single run, and the newest is dated 2025-05-01: the URL now serves
        an abandoned commentary feed rather than the press wire. Counting what parsed
        and calling it a success meant the company went unwatched for fifteen months
        with nothing anywhere saying so.

        No large-cap goes a quarter without announcing anything, so a feed whose newest
        item is older than that is reporting on itself, not on the company.
        """
        newest = self.newest_published(rows)
        if not newest:
            return None
        try:
            newest_dt = dt.date.fromisoformat(newest[:10])
        except ValueError:
            return None
        behind = (dt.date.today() - newest_dt).days
        return behind if behind > STALE_FEED_DAYS else None

    def snapshot(self, rows: list[dict]) -> None:
        classified = sum(1 for r in rows if r["kind"])
        payload = {"releases": len(rows), "classified": classified,
                   "fetch_kind": "live"}
        newest = self.newest_published(rows)
        if newest:
            payload["newest_published"] = newest
        self._write_snapshot(payload)

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
        if getattr(self, "no_feed", False):
            return RefreshResult(SOURCE, 0, notes=[f"{self.ticker}: no IR feed seeded"])
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
        behind = self.stale_by_days(rows)
        if behind is not None:
            # A note, not an error: the fetch worked, the feed answered, and what it
            # said is the finding. Errors mark a run partial, and a feed the company
            # abandoned is not this run failing.
            notes.append(f"{self.ticker}: feed newest item is {behind} days old"
                         f" ({self.newest_published(rows)}); the URL seeded for this"
                         f" company has stopped carrying its releases")
        return RefreshResult(SOURCE, written, notes=notes)
