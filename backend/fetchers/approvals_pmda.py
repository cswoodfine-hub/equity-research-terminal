"""Japanese new drug approvals from the PMDA's English list of approved products.

Keyless. The list's page links one PDF covering April 2004 to the latest month; the PDF
is replaced, under a new file number, as months are added. A release already read is
never downloaded again, so a weekly run costs one page request until PMDA publishes the
next one. See ``jp_approvals.py`` for the reading and ``regional_loe.py`` for the use.
"""

from __future__ import annotations

import json
import urllib.request

import db
import jp_approvals
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "jp_approvals"
ENTITY_KEY = "pmda_approvals"
TTL_SECONDS = 7 * 24 * 60 * 60
LIST_URL = ("https://www.pmda.go.jp/english/review-services/reviews/approved-information/"
            "drugs/0002.html")
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 120


class PmdaApprovalsFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, db_path=None):
        super().__init__(db_path)
        self._release = None

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def _get(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            return resp.read()

    def fetch(self) -> dict:
        link = jp_approvals.release_link(self._get(LIST_URL).decode("utf-8", "replace"))
        if link is None:
            raise RuntimeError("the PMDA list page links no PDF of approved products")
        url, label = link
        conn = db.get_connection(self.db_path)
        try:
            seen = conn.execute("SELECT 1 FROM jp_approval_releases WHERE url = ?",
                                (url,)).fetchone()
        finally:
            conn.close()
        self._release = {"url": url, "label": label, "new": seen is None}
        if seen:
            return {"text": None}
        return {"text": jp_approvals.text_of(self._get(url))}

    def normalise(self, raw) -> list[dict]:
        return jp_approvals.parse(raw.get("text")) if raw.get("text") else []

    def snapshot(self, rows: list[dict]) -> None:
        release = self._release or {}
        self._write_snapshot({
            "release": release.get("label"), "new_release": bool(release.get("new")),
            "approvals": len(rows),
            "new_ingredients": sum(r["is_new_ingredient"] for r in rows),
            "fetch_kind": "live"})

    def _snapshot_cache(self) -> None:
        self._write_snapshot({"fetch_kind": "cache"})

    def _write_snapshot(self, payload: dict) -> None:
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'source', ?, ?, ?)",
                (self.source, ENTITY_KEY, json.dumps(payload), self.refresh_run_id))
            conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        release = self._release or {}
        conn = db.get_connection(self.db_path)
        try:
            # Insert only: a release adds months and never takes one away, so a row
            # once read stays.
            conn.executemany(
                "INSERT OR IGNORE INTO jp_approvals (approved_on, entry, is_new_ingredient,"
                " is_orphan, release) VALUES (?, ?, ?, ?, ?)",
                [(r["approved_on"], r["entry"], r["is_new_ingredient"], r["is_orphan"],
                  release.get("url")) for r in rows])
            if release.get("new") and rows:
                conn.execute(
                    "INSERT OR IGNORE INTO jp_approval_releases (url, label, entries)"
                    " VALUES (?, ?, ?)", (release["url"], release.get("label"), len(rows)))
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(rows))
