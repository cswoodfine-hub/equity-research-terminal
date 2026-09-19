"""The negotiated Medicare prices, from the CMS selected-drug file.

CMS publishes one machine-readable file for the whole programme, zipped, holding every
selected drug's Maximum Fair Price per national drug code with the period it applies to.
It changes when a cycle's prices are announced, when the annual inflation adjustment
lands, and when a drug is deselected because a generic arrived, so it is refreshed
weekly rather than read once.

The file is a plain download from cms.gov with no key and no cookie. It carries a CSV and
an identical spreadsheet; only the CSV is read.
"""

from __future__ import annotations

import io
import json
import urllib.request
import zipfile

import db
import ira
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "cms_mfp"
ENTITY_KEY = "negotiated_prices"
TTL_SECONDS = 7 * 24 * 60 * 60
_TIMEOUT_S = 120
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
URL = ("https://www.cms.gov/files/zip/"
       "selected-drug-list-negotiated-prices-also-known-maximum-fair-prices-statutezip.zip")


def csv_from_zip(payload: bytes) -> str:
    """The one CSV inside the CMS archive."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise ValueError("no CSV in the CMS selected-drug archive")
        return archive.read(names[0]).decode("utf-8-sig", "replace")


class NegotiatedPricesCmsFetcher(BaseFetcher):
    """Every selected drug's negotiated price, weekly."""

    source = SOURCE
    ttl_seconds = TTL_SECONDS

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def fetch(self) -> str:
        request = urllib.request.Request(URL, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            return csv_from_zip(resp.read())

    def normalise(self, raw: str) -> list[dict]:
        return ira.parse(raw)

    def snapshot(self, rows: list[dict]) -> None:
        """The price in force for each drug, so a change of price is a change in the
        history rather than a silent overwrite."""
        drugs = sorted({r["drug"] for r in rows})
        self._write({d: {"ipay": next(r["ipay"] for r in rows if r["drug"] == d),
                         "mfp_30des": (ira.current(rows, d) or {}).get("mfp_30des"),
                         "effective_from": (ira.current(rows, d) or {}).get(
                             "effective_from")}
                     for d in drugs})

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT drug, ipay, mfp_30des, effective_from, effective_to"
                "  FROM negotiated_prices")]
        finally:
            conn.close()
        self.snapshot(rows) if rows else self._write({})

    def _write(self, payload: dict) -> None:
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'policy', ?, ?, ?)",
                (SOURCE, ENTITY_KEY, json.dumps(payload), self.refresh_run_id))
            conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        written = 0
        try:
            for row in rows:
                cursor = conn.execute(
                    """INSERT INTO negotiated_prices
                         (drug, ingredient, ipay, ndc9, hcpcs, mfp_30des, unit_price,
                          effective_from, effective_to, as_of, update_kind, remarks,
                          source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(drug, ndc9, effective_from) DO UPDATE SET
                         mfp_30des = excluded.mfp_30des,
                         unit_price = excluded.unit_price,
                         effective_to = excluded.effective_to,
                         as_of = excluded.as_of,
                         update_kind = excluded.update_kind,
                         remarks = excluded.remarks,
                         fetched_at = datetime('now')""",
                    (row["drug"], row["ingredient"], row["ipay"], row["ndc9"],
                     row["hcpcs"], row["mfp_30des"], row["unit_price"],
                     row["effective_from"], row["effective_to"], row["as_of"],
                     row["update_kind"], row["remarks"], SOURCE))
                written += cursor.rowcount
            conn.commit()
        finally:
            conn.close()
        drugs = len({r["drug"] for r in rows})
        return RefreshResult(SOURCE, written,
                             notes=[f"{drugs} selected drugs, {written} price rows"])
