"""The wording of Orange Book patent use codes, from FDA's per-application patent pages.

Reads only the codes the book holds that ``patent_use_codes`` does not define yet, at
most ``PAGES_PER_RUN`` pages a run and one a second, each application's products in
turn until its codes are covered, so a first run's backlog is spread
over a few weekly runs and later runs read only new codes. See ``use_codes.py``.
"""

from __future__ import annotations

import json
import time
import urllib.request

import db
import use_codes
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "ob_use_codes"
ENTITY_KEY = "orange_book"
TTL_SECONDS = 7 * 24 * 60 * 60
PAGES_PER_RUN = 120
PRODUCTS = ("001", "002", "003", "004")
_PAUSE_S = 1.0
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 60


def needed(conn) -> dict:
    """{application: codes it lists that have no definition yet}."""
    known = {r[0] for r in conn.execute("SELECT code FROM patent_use_codes")}
    out: dict = {}
    for r in conn.execute(
            "SELECT o.appl_code, e.use_codes FROM exclusivities e"
            " JOIN orange_book_listings o ON o.asset_id = e.asset_id"
            " WHERE e.use_codes IS NOT NULL"):
        missing = {c for c in r["use_codes"].split(",") if c and c not in known}
        if missing and r["appl_code"]:
            out.setdefault(r["appl_code"], set()).update(missing)
    return out


class UseCodesFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def _get(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            return resp.read().decode("utf-8", "replace")

    def fetch(self) -> list[dict]:
        conn = db.get_connection(self.db_path)
        try:
            wanted = needed(conn)
        finally:
            conn.close()
        rows, pages = [], 0
        for appl in use_codes.plan(wanted, limit=PAGES_PER_RUN):
            # A code is listed on the strength that carries it, which need not be
            # product 001, so the next products are read until the application's codes
            # are covered or a page lists none.
            missing = set(wanted[appl])
            for product in PRODUCTS:
                url = use_codes.page_url(appl, product)
                if not url or pages >= PAGES_PER_RUN:
                    break
                found = use_codes.parse(self._get(url))
                pages += 1
                time.sleep(_PAUSE_S)
                for code, text in found.items():
                    rows.append({"code": code, "definition": text, "appl_code": appl})
                missing -= set(found)
                if not missing or not found:
                    break
        return rows

    def normalise(self, raw) -> list[dict]:
        return list(raw)

    def snapshot(self, rows: list[dict]) -> None:
        self._write_snapshot({"codes": len({r["code"] for r in rows}),
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
            # Insert only: a code once defined keeps its first wording, and a page read
            # later never blanks one.
            conn.executemany(
                "INSERT OR IGNORE INTO patent_use_codes (code, definition, appl_code)"
                " VALUES (?, ?, ?)",
                [(r["code"], r["definition"], r["appl_code"]) for r in rows])
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(rows))
