"""Paragraph IV patent challenges from the FDA certifications list.

One universe fetcher resolves the current list PDF off the certifications page,
extracts its text, and matches each reference drug's NDA number to a tracked asset. A
match is stored as a patent challenge, which the LOE view reads as a challenged state
between protected and expired. A reference drug outside the universe is dropped; the
match is exact on the application number, so nothing is guessed.

The list reissues about monthly, so a drug whose challenge is resolved and removed from
the list is withdrawn here on the next run. The PDF is large but the extraction is
text, and only the number-and-date pairs are read from it.
"""

from __future__ import annotations

import json
import urllib.request

import db
import fedreg
import paragraph_iv
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "paragraph_iv"
ENTITY_KEY = "fda"
TTL_SECONDS = 7 * 24 * 60 * 60          # the list moves about monthly; refresh weekly
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 60


class ParagraphIvFetcher(BaseFetcher):
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
        page = self._get(paragraph_iv.LIST_PAGE).decode("utf-8", "replace")
        url = paragraph_iv.resolve_list_url(page)
        if not url:
            raise RuntimeError("could not resolve the Paragraph IV list link")
        import pypdf                                # only this source needs a PDF reader
        import io
        reader = pypdf.PdfReader(io.BytesIO(self._get(url)))
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        return paragraph_iv.parse_list(text)

    def normalise(self, raw) -> list[dict]:
        conn = db.get_connection(self.db_path)
        try:
            by_appno = {}
            for row in conn.execute(
                "SELECT id AS asset_id, internal_code FROM assets"
                " WHERE internal_code IS NOT NULL"):
                key = fedreg.normalise_appno(row["internal_code"])
                if key and key not in by_appno:
                    by_appno[key] = row["asset_id"]
        finally:
            conn.close()
        rows = []
        for item in raw:
            asset_id = by_appno.get(item["application_number"])
            if asset_id is not None:
                rows.append({**item, "asset_id": asset_id})
        return rows

    def snapshot(self, rows: list[dict]) -> None:
        self._write_snapshot({"challenges": len(rows), "fetch_kind": "live"})

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
                    INSERT INTO patent_challenges
                        (asset_id, application_number, first_submission, fetched_at)
                    VALUES (?, ?, ?, datetime('now'))
                    ON CONFLICT(asset_id) DO UPDATE SET
                        application_number = excluded.application_number,
                        first_submission = excluded.first_submission,
                        fetched_at = datetime('now')
                    """,
                    (row["asset_id"], row["application_number"],
                     row["first_submission"]))
            # A challenge no longer on the list has been resolved or withdrawn; drop it,
            # so the LOE view stops showing a drug as challenged once it is not.
            live = {row["asset_id"] for row in rows}
            existing = [r["asset_id"] for r in conn.execute(
                "SELECT asset_id FROM patent_challenges")]
            for asset_id in existing:
                if asset_id not in live:
                    conn.execute("DELETE FROM patent_challenges WHERE asset_id = ?",
                                 (asset_id,))
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(rows))
