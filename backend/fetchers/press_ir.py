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

When the investor site answers a bot challenge, ``ir_rss_url`` names another route to the
same releases, in this order of preference, and never the unprotected origin behind the
challenged host, which would be the same work-around a solved challenge is:

1. Another of the company's own sites. BioMarin's WordPress site publishes its press
   releases as a feed of their own (``/feed/?post_type=press-release``), and gilead.com
   draws its news page from a Sitecore search listing (``/sxa/search/results/``), read
   by ``press_releases.parse_sxa``. Each returned every release the challenged feed had
   stored, 16 of 16 and 14 of 14.
2. A wire aggregator's feed for the ticker, for a company whose every own site is
   challenged (Pfizer and BMS, 2026-10-09). StockTitan republishes the wire releases
   under their own headlines and publishes a feed per ticker, linked from its pages and
   allowed by its robots file; for BMS it held 13 of the 14 stored releases, the one
   missing being BioNTech's. It tags a release by every ticker the release names, so a
   partner's release lands under both and an exchange's bell notice under a dozen: an
   item counts only when its headline names the company or one of its own products.

The parsing and the classifying live in ``press_releases``, tested against saved feeds.
This module is the plumbing around them.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
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


# What a bot-protection interstitial looks like. Cloudflare serves a 403 whose body is
# an HTML challenge page rather than a refusal, and the distinction matters: a plain 403
# is a feed saying no to this client, and a challenge is a feed saying no to every
# client that is not running a browser. The second cannot be fixed by asking more
# politely, and this does not try: solving a challenge is working around a control the
# publisher put there on purpose. It is reported so a different URL can be seeded.
_CHALLENGE = re.compile(
    r"just a moment|challenges\.cloudflare\.com|cf-chl|__cf_chl|"
    r"enable javascript and cookies", re.I)


class FeedChallenged(RuntimeError):
    """A feed answered with a bot challenge rather than its contents."""


# Hosts whose feed carries other companies' releases too, filtered to the company's own.
AGGREGATORS = ("stocktitan.net",)

# What makes a name legal rather than the one a headline uses: "Pfizer Inc" is
# "Pfizer" in every headline it writes.
_LEGAL = re.compile(r"[,\s]+(?:inc|incorporated|co|company|corp|corporation|plc|ag|sa|"
                    r"se|n\.?v|ltd|limited|holdings?)\.?$", re.I)

# A product name shorter than this matches inside ordinary headline words.
_MIN_TERM = 4


def is_aggregator(feed: str) -> bool:
    host = (urllib.parse.urlparse(feed).hostname or "").lower()
    return any(host == a or host.endswith("." + a) for a in AGGREGATORS)


def is_sxa(feed: str) -> bool:
    return "/sxa/search/results" in urllib.parse.urlparse(feed).path.lower()


def own_names(conn, company) -> list[str]:
    """The names a headline uses for the company and its products: the company's name
    without its legal ending, its first word, and every asset's generic and brand name
    and development code (``BMS-986278``) it owns."""
    name = _LEGAL.sub("", (company["name"] or "").strip())
    terms = {name}
    first = name.split()[0] if name else ""
    if len(first) >= _MIN_TERM:
        terms.add(first.split("-")[0])
    for row in conn.execute(
            "SELECT generic_name, brand_name, internal_code FROM assets"
            " WHERE owner_company_id = ?", (company["id"],)):
        for value in row:
            for part in re.split(r"[;,/]| and ", value or ""):
                if len(part.strip()) >= _MIN_TERM:
                    terms.add(part.strip())
    return sorted(t for t in terms if t)


def names_pattern(names: list[str]):
    """A headline test for any of ``names``, whole words only, a space and a hyphen
    read alike ("Bristol-Myers Squibb" is "Bristol Myers Squibb" in its headlines)."""
    alternatives = [r"[\s-]+".join(re.escape(w) for w in re.split(r"[\s-]+", n))
                    for n in sorted(names, key=len, reverse=True)]
    return re.compile(r"(?<![\w-])(?:" + "|".join(alternatives) + r")(?![\w-])", re.I)


def _refusal(exc, feed: str) -> Exception:
    """The clearest exception a refused request can be turned into.

    "HTTP Error 403: Forbidden" says nothing a reader can act on. Three IR feeds
    stopped answering around 2026-09-08 and the run detail reported exactly that
    string for each, so nobody could tell a dead path from a blocked client without
    going to look.
    """
    body = ""
    try:
        body = exc.read().decode("utf-8", "ignore")[:4000]
    except Exception:
        pass
    if exc.code in (403, 503) and _CHALLENGE.search(body):
        return FeedChallenged(
            f"{feed} answers a bot challenge rather than the feed, so this client "
            "cannot read it and no user agent will change that. Seed a different "
            "ir_rss_url: another of the company's own sites first, a wire "
            "aggregator's feed for the ticker failing that (see this module's notes)")
    return exc


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
            feed = ((company["ir_rss_url"] if company else "") or "").strip()
            names = own_names(conn, company) if company and is_aggregator(feed) else None
        finally:
            conn.close()
        if not company:
            raise ValueError(f"no company {self.ticker}")
        if not feed:
            # Not an error. Most of the universe has no feed seeded yet, and a company
            # without one has nothing to report rather than something to fix.
            return {"company": dict(company), "xml": None}
        headers = HEADERS
        if is_sxa(feed):
            headers = {**HEADERS, "Accept": "application/json"}
        request = urllib.request.Request(feed, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
                xml_text = resp.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as exc:
            raise _refusal(exc, feed) from exc
        return {"company": dict(company), "xml": xml_text, "feed": feed, "names": names}

    def normalise(self, raw) -> list[dict]:
        company = raw["company"]
        self.no_feed = raw["xml"] is None
        self.not_own = 0
        if self.no_feed:
            return []
        feed = raw.get("feed") or ""
        items = (press_releases.parse_sxa(raw["xml"], feed) if is_sxa(feed)
                 else press_releases.parse_feed(raw["xml"]))
        if raw.get("names"):
            own = names_pattern(raw["names"])
            kept = [i for i in items if own.search(i["title"])]
            self.not_own = len(items) - len(kept)
            items = kept
        rows = []
        for item in items:
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
        if getattr(self, "not_own", 0):
            notes.append(f"{self.ticker}: {self.not_own} items on the aggregator's feed"
                         f" named neither the company nor one of its products, left out")
        behind = self.stale_by_days(rows)
        if behind is not None:
            # A note, not an error: the fetch worked, the feed answered, and what it
            # said is the finding. Errors mark a run partial, and a feed the company
            # abandoned is not this run failing.
            notes.append(f"{self.ticker}: feed newest item is {behind} days old"
                         f" ({self.newest_published(rows)}); the URL seeded for this"
                         f" company has stopped carrying its releases")
        return RefreshResult(SOURCE, written, notes=notes)
