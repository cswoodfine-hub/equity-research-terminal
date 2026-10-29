"""Patent term extensions from the USPTO: which listed patent holds the molecule.

One universe fetcher reads the certificate list and the five-year application list off
www.uspto.gov (keyless spreadsheets, see ``pte.py``) and replaces
``patent_term_extensions``. Nothing is matched here: the LOE resolver joins a
certificate's patent number to an asset's Orange Book rows, so a patent the book does
not list for a product never touches it.

Both lists reissue every few months; the source refreshes weekly with the Orange Book.
"""

from __future__ import annotations

import json
import urllib.request

import db
import pte
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "pte"
ENTITY_KEY = "uspto"
TTL_SECONDS = 7 * 24 * 60 * 60
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 60


class PteFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def _get(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            return resp.read()

    def fetch(self) -> list[dict]:
        certificates = pte.parse_certificates(self._get(pte.CERTIFICATES_URL))
        if not certificates:
            # The list holds over a thousand certificates; an empty parse is a changed
            # file, and replacing the table with nothing would drop every compound date.
            raise RuntimeError("pte: the certificate list parsed to no rows")
        applications = pte.parse_applications(self._get(pte.APPLICATIONS_URL))
        return ([{**r, "kind": "certificate"} for r in certificates]
                + [{**r, "kind": "application"} for r in applications])

    def normalise(self, raw) -> list[dict]:
        return list(raw)

    def snapshot(self, rows: list[dict]) -> None:
        self._write_snapshot({
            "certificates": sum(1 for r in rows if r["kind"] == "certificate"),
            "applications": sum(1 for r in rows if r["kind"] == "application"),
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
            conn.execute("DELETE FROM patent_term_extensions")
            conn.executemany(
                "INSERT INTO patent_term_extensions (patent, kind, trade_name,"
                " original_expiry, extension, extended_expiry, filed, application_number)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(r["patent"], r["kind"], r.get("trade_name"), r.get("original_expiry"),
                  r.get("extension"), r.get("extended_expiry"), r.get("filed"),
                  r.get("application_number")) for r in rows])
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(rows))
