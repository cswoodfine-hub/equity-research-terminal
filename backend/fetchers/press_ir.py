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

# How recent an announcement must be to also count as a change. The first run for a
# company reads its whole archive, which for AstraZeneca is 1,626 items back to 2013 and
# 523 that classify. Writing a change for each would bury the day's news under a decade
# of it. Everything older is still stored as news; it just does not claim to be new.
CHANGE_WINDOW_DAYS = 21

# What a kind is worth in the feed. An approval or a deal moves the stock, a CHMP opinion
# or a filing acceptance is a step on the way, and a scheduled earnings call is neither.
SIGNIFICANCE = {
    "approval": "high",
    "deal": "high",
    "PDUFA": "high",
    "data readout": "high",
    "regulatory": "medium",
    "panel": "medium",
    "results": "low",
    "dividend": "low",
}

# The kinds that name a dated future event, and so can become a catalyst rather than a
# change. Both are also written as a change: a decision date being set is itself news.
CATALYST_KINDS = {"PDUFA": "PDUFA", "panel": "AdCom"}


def change_type(kind: str) -> str:
    """A press release's change type, e.g. ``press_data_readout``.

    The kind stays in the type rather than in a separate column, so the changes table
    keeps saying what it holds and one prefix separates announcements from everything
    else.
    """
    return "press_" + kind.lower().replace(" ", "_")


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

    def snapshot(self, rows: list[dict]) -> None:
        classified = sum(1 for r in rows if r["kind"])
        self._write_snapshot({"releases": len(rows), "classified": classified,
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
        if getattr(self, "no_feed", False):
            return RefreshResult(SOURCE, 0, notes=[f"{self.ticker}: no IR feed seeded"])
        cutoff = (dt.date.today()
                  - dt.timedelta(days=CHANGE_WINDOW_DAYS)).isoformat()
        conn = db.get_connection(self.db_path)
        written = changed = catalysts = 0
        try:
            for row in rows:
                cursor = conn.execute(
                    "INSERT INTO news (company_id, source, title, url, published_at)"
                    " VALUES (?, ?, ?, ?, ?) ON CONFLICT(url) DO NOTHING",
                    (row["company_id"], SOURCE, row["title"], row["url"],
                     row["published"]))
                # A release already stored is already reported. Only the insert that
                # takes decides anything, so a re-run cannot repeat a change.
                if not cursor.rowcount:
                    continue
                written += 1
                if not row["kind"]:
                    continue
                if row["published"] and row["published"] >= cutoff:
                    conn.execute(
                        "INSERT INTO changes (entity_type, entity_key, field,"
                        "  old_value, new_value, change_type, significance,"
                        "  refresh_run_id)"
                        " VALUES ('company', ?, 'press release', NULL, ?, ?, ?, ?)",
                        (f"{row['ticker']}|{row['url']}", row["title"],
                         change_type(row["kind"]),
                         SIGNIFICANCE.get(row["kind"], "low"), self.refresh_run_id))
                    changed += 1
                if row["ahead"] and row["stated_date"]:
                    conn.execute(
                        "INSERT INTO catalysts (company_id, catalyst_type,"
                        "  expected_date, date_confidence, title, description,"
                        "  is_curated, source_url, status)"
                        " VALUES (?, ?, ?, 'confirmed', ?, ?, 0, ?, 'pending')",
                        (row["company_id"], CATALYST_KINDS[row["kind"]],
                         row["stated_date"], row["title"],
                         f"Announced by {row['ticker']} on {row['published']}",
                         row["url"]))
                    catalysts += 1
            conn.commit()
        finally:
            conn.close()
        notes = []
        if written:
            notes.append(f"{self.ticker}: {written} releases, {changed} changes,"
                         f" {catalysts} catalysts")
        return RefreshResult(SOURCE, written, notes=notes)
