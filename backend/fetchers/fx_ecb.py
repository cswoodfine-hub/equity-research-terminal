"""ECB daily reference exchange rates, to USD.

One small XML download for the whole universe, the same shape as the Orange and
Purple Book fetchers: a universe source, weekly-ish TTL (the daily set moves once a
day and the app converts annual revenue, so a stale rate is harmless). Free, no key.
Rates ride into ``fx_rates`` as USD-quoted; ``fx`` does the parsing.
"""

from __future__ import annotations

import json
import urllib.request

import db
import fx
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "fx"
ENTITY_KEY = "ecb"
TTL_SECONDS = 12 * 60 * 60          # the daily set changes at most once a day
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 30


class FxEcbFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def fetch(self) -> list[dict]:
        request = urllib.request.Request(ECB_URL, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            return [{"xml": resp.read().decode("utf-8")}]

    def normalise(self, raw) -> list[dict]:
        if not raw:
            return []
        as_of, usd_rates = fx.parse_ecb(raw[0]["xml"])
        return [{"as_of": as_of, "usd_rates": usd_rates}]

    def snapshot(self, rows: list[dict]) -> None:
        payload = ({"as_of": rows[0]["as_of"], "currencies": len(rows[0]["usd_rates"]),
                    "fetch_kind": "live"} if rows
                   else {"fetch_kind": "live", "as_of": None})
        self._write_snapshot(payload)

    def _snapshot_cache(self) -> None:
        latest = fx.latest_usd_rates(self.db_path)
        self._write_snapshot({"as_of": latest.get("as_of"),
                              "currencies": len([k for k in latest if k != "as_of"]),
                              "fetch_kind": "cache"})

    def _write_snapshot(self, payload: dict) -> None:
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'fx', ?, ?, ?)",
                (self.source, self.entity_key, json.dumps(payload),
                 self.refresh_run_id))
            conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        if not rows:
            return RefreshResult(self.source, 0, ["ecb returned no rates"])
        written = fx.store(self.db_path, rows[0]["as_of"], rows[0]["usd_rates"])
        return RefreshResult(self.source, written)
