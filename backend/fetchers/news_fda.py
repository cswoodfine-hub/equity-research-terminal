"""FDA announcement feeds: the layer around approvals and label changes.

One universe fetcher pulls the FDA press-release, drug, and MedWatch safety RSS
feeds, matches each item to a company by name or brand, and stores it in the news
table. It catches the announcement an approval or a supplement corroborates, and it
reaches the CBER products drugsfda cannot: a gene-therapy approval shows up here as a
press release even though it never appears in drugsfda.

EMA's general news RSS was retired; only per-medicine feeds remain, so the EU
indication-extension signal is left to the EPAR data rather than fetched here.
"""

from __future__ import annotations

import json
import urllib.request

import db
import rssfeed
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "regulatory_news"
ENTITY_KEY = "fda"
TTL_SECONDS = 12 * 60 * 60
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 30

FEEDS = {
    "fda_press": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/"
                 "press-releases/rss.xml",
    "fda_drugs": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/"
                 "drugs/rss.xml",
    "fda_safety": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/"
                  "medwatch/rss.xml",
}


class NewsFdaFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def _token_map(self, conn) -> dict:
        companies = conn.execute(
            "SELECT id, ticker, name FROM companies").fetchall()
        brands = {}
        for row in conn.execute(
            "SELECT owner_company_id AS cid, brand_name FROM assets"
            " WHERE brand_name IS NOT NULL"):
            brands.setdefault(row["cid"], []).append(row["brand_name"])
        return {c["id"]: rssfeed.company_tokens(c["name"], c["ticker"],
                                                brands.get(c["id"], []))
                for c in companies}

    def fetch(self) -> list[dict]:
        out = []
        for source, url in FEEDS.items():
            try:
                request = urllib.request.Request(
                    url, headers={"User-Agent": _USER_AGENT})
                with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
                    xml_text = resp.read().decode("utf-8", "replace")
                for item in rssfeed.parse_feed(xml_text):
                    out.append({**item, "feed": source})
            except Exception:
                continue                       # one dead feed never fails the run
        return out

    def normalise(self, raw) -> list[dict]:
        conn = db.get_connection(self.db_path)
        try:
            token_map = self._token_map(conn)
        finally:
            conn.close()
        rows = []
        for item in raw:
            company_id = rssfeed.match_company(
                f"{item['title']} {item.get('summary', '')}", token_map)
            rows.append({**item, "company_id": company_id})
        return rows

    def snapshot(self, rows: list[dict]) -> None:
        matched = sum(1 for r in rows if r["company_id"] is not None)
        self._write_snapshot({"items": len(rows), "matched": matched,
                              "fetch_kind": "live"})

    def _snapshot_cache(self) -> None:
        self._write_snapshot({"fetch_kind": "cache"})

    def _write_snapshot(self, payload: dict) -> None:
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'feed', ?, ?, ?)",
                (self.source, ENTITY_KEY, json.dumps(payload), self.refresh_run_id))
            conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        written = 0
        try:
            for row in rows:
                # The url is unique, so re-fetching the same item is a no-op and the
                # news table never carries a duplicate.
                changed = conn.execute(
                    """
                    INSERT INTO news (company_id, source, title, url, published_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(url) DO NOTHING
                    """,
                    (row["company_id"], row["feed"], row["title"], row["url"],
                     row["published"])).rowcount
                written += changed
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, written)
