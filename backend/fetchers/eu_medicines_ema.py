"""Centrally authorised medicines from the European Medicines Agency.

The EMA publishes every medicine it has assessed as one JSON file, refreshed daily, with
no key and no login. What this terminal needs from it is one date per product: when the
European Commission first authorised it. A substance's first EU authorisation starts its
regulatory data and market protection (Directive 2001/83/EC, Article 10(1)): no generic
or biosimilar may be sold for ten years after it. That is the floor under a product's
European exclusivity whatever its patents do, as the BPCIA's twelve years are under a US
biologic's.

Human medicines only. A product withdrawn later still keeps its authorisation date,
because the protection it started runs from that date regardless. Generic and biosimilar
authorisations are stored and flagged, since they are the market opening rather than the
protection, and never count as a substance's first authorisation.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.request

import db
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "eu_medicines"
ENTITY_KEY = "ema_medicines"
TTL_SECONDS = 7 * 24 * 60 * 60

MEDICINES_URL = ("https://www.ema.europa.eu/en/documents/report/"
                 "medicines-output-medicines_json-report_en.json")
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 120


def _iso(stated: str | None) -> str | None:
    """EMA writes dates day first, 08/02/2018. None where the field is blank or not a
    date, never a guess at which way round it was meant."""
    stated = (stated or "").strip()
    if not stated:
        return None
    try:
        return dt.datetime.strptime(stated, "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def parse_medicines(payload: dict) -> list[dict]:
    """Rows for the eu_medicines table from the EMA's JSON report."""
    out = []
    for record in (payload or {}).get("data") or []:
        if (record.get("category") or "").strip() != "Human":
            continue
        number = (record.get("ema_product_number") or "").strip()
        if not number:
            continue
        out.append({
            "ema_product_number": number,
            "name": (record.get("name_of_medicine") or "").strip(),
            "active_substance": (record.get("active_substance") or "").strip().lower(),
            "inn": (record.get("international_non_proprietary_name_common_name")
                    or "").strip().lower(),
            "status": (record.get("medicine_status") or "").strip(),
            "authorised_on": _iso(record.get("marketing_authorisation_date")),
            "holder": (record.get("marketing_authorisation_developer_applicant_holder")
                       or "").strip(),
            "is_generic": int((record.get("generic") or "").strip() == "Yes"),
            "is_biosimilar": int((record.get("biosimilar") or "").strip() == "Yes"),
            "is_orphan": int((record.get("orphan_medicine") or "").strip() == "Yes"),
        })
    return out


class EuMedicinesFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, db_path=None):
        super().__init__(db_path)

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def fetch(self) -> dict:
        request = urllib.request.Request(MEDICINES_URL, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def normalise(self, raw) -> list[dict]:
        return parse_medicines(raw)

    def _write_snapshot(self, conn, payload: dict) -> None:
        conn.execute(
            "INSERT INTO snapshots (source, entity_type, entity_key, payload, refresh_run_id)"
            " VALUES (?, 'source', ?, ?, ?)",
            (self.source, ENTITY_KEY, json.dumps(payload), self.refresh_run_id))

    def snapshot(self, rows: list[dict]) -> None:
        conn = db.get_connection(self.db_path)
        try:
            self._write_snapshot(conn, {
                "medicines": len(rows),
                "authorised": sum(1 for r in rows if r["authorised_on"]),
                "fetch_kind": "live"})
            conn.commit()
        finally:
            conn.close()

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            n = conn.execute("SELECT COUNT(*) FROM eu_medicines").fetchone()[0]
            if n:
                self._write_snapshot(conn, {"medicines": n, "fetch_kind": "cache"})
                conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        try:
            for row in rows:
                conn.execute(
                    """INSERT INTO eu_medicines
                           (ema_product_number, name, active_substance, inn, status,
                            authorised_on, holder, is_generic, is_biosimilar, is_orphan,
                            fetched_at)
                       VALUES (:ema_product_number, :name, :active_substance, :inn, :status,
                               :authorised_on, :holder, :is_generic, :is_biosimilar,
                               :is_orphan, datetime('now'))
                       ON CONFLICT(ema_product_number) DO UPDATE SET
                           name=excluded.name, active_substance=excluded.active_substance,
                           inn=excluded.inn, status=excluded.status,
                           authorised_on=excluded.authorised_on, holder=excluded.holder,
                           is_generic=excluded.is_generic,
                           is_biosimilar=excluded.is_biosimilar,
                           is_orphan=excluded.is_orphan, fetched_at=datetime('now')""",
                    row)
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(rows))
