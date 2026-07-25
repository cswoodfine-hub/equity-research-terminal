"""Medicare demand from the CMS Spending by Drug datasets.

One universe fetcher pulls the Part D and Part B drug spending tables, matches each drug
to a tracked asset by brand name, and stores the per-year volume as a demand time series
(migration 007). A brand outside the universe is dropped; the match is an exact brand
name, so a drug binds to its own asset and nothing is guessed.

CMS updates the tables about once a year, so the TTL is weekly. Part D is filtered
server side to the Overall rows, one per brand across its manufacturers; Part B carries
no manufacturer split. Both are paged through in full and matched in memory, which is a
few thousand rows.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

import cms
import db
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "demand"
ENTITY_KEY = "cms"
TTL_SECONDS = 7 * 24 * 60 * 60          # CMS publishes yearly; refresh weekly
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 90
_PAGE = 5000


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


class DemandCmsFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def _page_through(self, url: str, params: dict) -> list[dict]:
        rows, offset = [], 0
        while True:
            query = urllib.parse.urlencode({**params, "size": _PAGE, "offset": offset})
            request = urllib.request.Request(
                f"{url}?{query}", headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
                batch = json.loads(resp.read().decode("utf-8", "replace"))
            rows.extend(batch)
            if len(batch) < _PAGE:
                break
            offset += _PAGE
        return rows

    def fetch(self) -> list[dict]:
        part_d = self._page_through(cms.PART_D_URL, {"filter[Mftr_Name]": "Overall"})
        part_b = self._page_through(cms.PART_B_URL, {})
        return ([{**r, "_part": "D"} for r in part_d]
                + [{**r, "_part": "B"} for r in part_b])

    def _brand_map(self, conn) -> dict:
        brands = {}
        for row in conn.execute(
            "SELECT id AS asset_id, brand_name FROM assets"
            " WHERE brand_name IS NOT NULL"):
            brands.setdefault(_norm(row["brand_name"]), row["asset_id"])
        return brands

    def normalise(self, raw) -> list[dict]:
        conn = db.get_connection(self.db_path)
        try:
            brand_map = self._brand_map(conn)
        finally:
            conn.close()
        rows = []
        for item in raw:
            asset_id = brand_map.get(_norm(item.get("Brnd_Name")))
            if asset_id is None:
                continue                       # a drug outside the universe
            for record in cms.parse_row(item, item["_part"]):
                rows.append({**record, "asset_id": asset_id})
        return rows

    def snapshot(self, rows: list[dict]) -> None:
        assets = len({r["asset_id"] for r in rows})
        self._write_snapshot({"records": len(rows), "assets": assets,
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
        try:
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO drug_demand
                        (asset_id, part, brand_name, year, total_spending,
                         total_claims, total_beneficiaries, total_dosage_units,
                         fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(asset_id, part, year) DO UPDATE SET
                        brand_name = excluded.brand_name,
                        total_spending = excluded.total_spending,
                        total_claims = excluded.total_claims,
                        total_beneficiaries = excluded.total_beneficiaries,
                        total_dosage_units = excluded.total_dosage_units,
                        fetched_at = datetime('now')
                    """,
                    (row["asset_id"], row["part"], row["brand"], row["year"],
                     row["total_spending"], row["total_claims"],
                     row["total_beneficiaries"], row["total_dosage_units"]))
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(rows))
