"""FDA advisory committee meetings from the Federal Register, written as catalysts.

One universe fetcher reads the Federal Register API, keeps the notices that schedule a
real meeting, and matches each to a tracked company two ways: on the application number
in the title against an asset's internal_code, which is exact, and failing that on the
sponsor and product names against the company's own name and brands, which is the same
conservative match the news feed uses. A matched meeting lands in the catalysts table
as an AdCom row with is_curated=0, the review state every machine-produced catalyst
starts in, and the Federal Register notice as its evidence.

A meeting for a sponsor outside the universe is counted and dropped, not stored: the
catalyst calendar is the universe's, not the agency's. The write is idempotent on the
meeting's identity (company, asset, date), so the several notices the FDA publishes for
one meeting collapse to one row, and a meeting that is pulled from the calendar is
withdrawn on the next run.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.request

import db
import fedreg
import rssfeed
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "adcomm"
ENTITY_KEY = "fda"
TTL_SECONDS = 24 * 60 * 60
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 30


class AdCommFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def fetch(self) -> list[dict]:
        request = urllib.request.Request(
            fedreg.API_URL, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        return payload.get("results") or []

    def _match_maps(self, conn):
        """Two ways to bind a meeting to a company: an application-number index for the
        exact match, and a token map per company for the sponsor/brand match."""
        by_appno = {}
        for row in conn.execute(
            "SELECT a.id AS asset_id, a.internal_code, a.owner_company_id AS cid,"
            " c.ticker FROM assets a JOIN companies c ON c.id = a.owner_company_id"
            " WHERE a.internal_code IS NOT NULL"):
            key = fedreg.normalise_appno(row["internal_code"])
            if key and key not in by_appno:
                by_appno[key] = (row["asset_id"], row["cid"], row["ticker"])

        companies = conn.execute("SELECT id, ticker, name FROM companies").fetchall()
        brands = {}
        for row in conn.execute(
            "SELECT owner_company_id AS cid, brand_name FROM assets"
            " WHERE brand_name IS NOT NULL"):
            brands.setdefault(row["cid"], []).append(row["brand_name"])
        token_map = {c["id"]: rssfeed.company_tokens(c["name"], c["ticker"],
                                                     brands.get(c["id"], []))
                     for c in companies}
        tickers = {c["id"]: c["ticker"] for c in companies}
        return by_appno, token_map, tickers

    def normalise(self, raw) -> list[dict]:
        """Every upcoming scheduled meeting, matched to a company where one is named.

        The whole calendar is kept, not just the universe's meetings, so the view has
        agency context; company_id is set only when a meeting binds to a tracked
        company, and those are the ones that also become catalysts. The several notices
        the FDA files for one meeting collapse on meeting_key, newest kept."""
        conn = db.get_connection(self.db_path)
        try:
            by_appno, token_map, tickers = self._match_maps(conn)
        finally:
            conn.close()
        today = dt.date.today().isoformat()
        best: dict[str, dict] = {}
        for meeting in fedreg.parse_documents({"results": raw}):
            if not meeting["meeting_date"] or meeting["meeting_date"] < today:
                continue                        # forward-looking calendar only
            # One meeting, several notices (an establishment notice then amendments) and
            # sometimes a generic one before the detailed one. The committee and date are
            # the meeting's identity; the notice that names an application wins.
            key = f"{meeting['committee']}|{meeting['meeting_date']}"
            asset_id = company_id = ticker = None
            hit = by_appno.get(meeting["application_number"])
            if hit:
                asset_id, company_id, ticker = hit
            else:
                cid = rssfeed.match_company(
                    f"{meeting.get('sponsor') or ''} {meeting.get('product') or ''}",
                    token_map)
                if cid is not None:
                    company_id, ticker = cid, tickers[cid]
            cand = {**meeting, "meeting_key": key, "asset_id": asset_id,
                    "company_id": company_id, "ticker": ticker}
            prev = best.get(key)
            if prev is None or (cand["application_number"]
                                and not prev["application_number"]):
                best[key] = cand
        return list(best.values())

    def snapshot(self, rows: list[dict]) -> None:
        matched = sum(1 for r in rows if r["company_id"] is not None)
        self._write_snapshot({"meetings": len(rows), "matched": matched,
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

    @staticmethod
    def _title(meeting: dict) -> str:
        return meeting.get("product") or meeting["committee"]

    @staticmethod
    def _description(meeting: dict) -> str:
        label = meeting.get("application_label")
        return f"{meeting['committee']}. {label}." if label else meeting["committee"]

    def _store_calendar(self, conn, rows: list[dict]) -> None:
        """The whole scheduled calendar, deduped on meeting_key. A future meeting no
        longer listed was pulled and is removed; past meetings stay as history."""
        for row in rows:
            conn.execute(
                """
                INSERT INTO adcomm_meetings
                    (meeting_key, committee, meeting_date, application_number,
                     application_label, sponsor, product, company_id, asset_id, url,
                     document_number, published, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(meeting_key) DO UPDATE SET
                    company_id = excluded.company_id, asset_id = excluded.asset_id,
                    url = excluded.url, document_number = excluded.document_number,
                    published = excluded.published, fetched_at = datetime('now')
                """,
                (row["meeting_key"], row["committee"], row["meeting_date"],
                 row["application_number"], row["application_label"], row["sponsor"],
                 row["product"], row["company_id"], row["asset_id"], row["url"],
                 row["document_number"], row["published"]))
        live_keys = {row["meeting_key"] for row in rows}
        stale = [r["meeting_key"] for r in conn.execute(
            "SELECT meeting_key FROM adcomm_meetings WHERE meeting_date >= date('now')")
            if r["meeting_key"] not in live_keys]
        for key in stale:
            conn.execute("DELETE FROM adcomm_meetings WHERE meeting_key = ?", (key,))

    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        added = 0
        try:
            self._store_calendar(conn, rows)
            matched = [r for r in rows if r["company_id"] is not None]
            live = set()
            for row in matched:
                key = (row["company_id"], row["asset_id"] if row["asset_id"] else -1,
                       row["meeting_date"])
                live.add(key)
                title, description = self._title(row), self._description(row)
                existing = conn.execute(
                    "SELECT id, title, description, source_url FROM catalysts"
                    " WHERE catalyst_type = 'AdCom' AND is_curated = 0"
                    "   AND company_id = ? AND COALESCE(asset_id, -1) = ?"
                    "   AND expected_date = ?",
                    (row["company_id"], key[1], row["meeting_date"])).fetchone()
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO catalysts
                            (company_id, asset_id, catalyst_type, expected_date,
                             date_confidence, title, description, is_curated,
                             source_url, status)
                        VALUES (?, ?, 'AdCom', ?, 'confirmed', ?, ?, 0, ?, 'pending')
                        """,
                        (row["company_id"], row["asset_id"], row["meeting_date"],
                         title, description, row["url"]))
                    added += 1
                elif (existing["title"] != title
                      or existing["description"] != description
                      or existing["source_url"] != row["url"]):
                    conn.execute(
                        "UPDATE catalysts SET title = ?, description = ?,"
                        " source_url = ?, updated_at = datetime('now') WHERE id = ?",
                        (title, description, row["url"], existing["id"]))

            # A future AdCom row the machine made but this run no longer sees is a
            # meeting pulled from the calendar; withdraw it. Past meetings and the
            # analyst's own curated rows are left alone.
            stale = [
                r["id"] for r in conn.execute(
                    "SELECT id, company_id, asset_id, expected_date FROM catalysts"
                    " WHERE catalyst_type = 'AdCom' AND is_curated = 0"
                    "   AND expected_date >= date('now')")
                if (r["company_id"], r["asset_id"] if r["asset_id"] else -1,
                    r["expected_date"]) not in live
            ]
            for catalyst_id in stale:
                conn.execute("DELETE FROM catalysts WHERE id = ?", (catalyst_id,))
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(rows))
