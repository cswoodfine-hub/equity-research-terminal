"""Biologics loss-of-exclusivity from the FDA Purple Book (partial coverage).

Only a monthly *changes* CSV is downloadable, so this covers biologics that were newly
approved / added / updated in the latest release, not the full biologic universe. It is
labelled partial in the UI. Each matched BLA becomes a marketed biologic asset with its
reference-product / orphan / interchangeable exclusivity expiries.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import urllib.request

import db
from assets_util import upsert_asset
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "exclusivities"
PB_SOURCE = "purple_book"
ENTITY_KEY = "purple_book"
TTL_SECONDS = 7 * 24 * 60 * 60

DOWNLOADS_PAGE = "https://purplebooksearch.fda.gov/downloads"
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 90
# Each file is one month's changes, so merge several recent months for coverage.
_MONTHS_TO_MERGE = 6
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


def _url_recency(url: str):
    match = re.search(r"/(\d{4})/purplebook-search-([a-z]+)-data", url, re.IGNORECASE)
    if not match:
        return (0, 0)
    return (int(match.group(1)), _MONTHS.get(match.group(2).lower(), 0))

# Applicant substrings for biologics (includes biologic subsidiaries: MedImmune=AZ,
# Kite=Gilead, Janssen Biotech=J&J).
APPLICANT_MAP = {
    "LLY": ["LILLY"],
    "NVO": ["NOVO NORDISK"],
    "MRK": ["MERCK SHARP", "MSD"],
    "PFE": ["PFIZER", "WYETH", "HOSPIRA"],
    "ABBV": ["ABBVIE", "ALLERGAN"],
    "JNJ": ["JANSSEN"],
    "AZN": ["ASTRAZENECA", "MEDIMMUNE"],
    "GSK": ["GLAXO", "VIIV"],
    "NVS": ["NOVARTIS"],
    "ROG": ["GENENTECH", "HOFFMANN", "ROCHE"],
    "SNY": ["SANOFI", "GENZYME", "AVENTIS"],
    "BMY": ["BRISTOL", "CELGENE"],
    "AMGN": ["AMGEN"],
    "GILD": ["GILEAD", "KITE"],
    "VRTX": ["VERTEX"],
    "REGN": ["REGENERON"],
    "BIIB": ["BIOGEN"],
    "BAYN": ["BAYER"],
}

EXCLUSIVITY_COLUMNS = [
    ("Ref. Product Exclusivity Exp. Date", "reference product exclusivity"),
    ("Exclusivity Expiration Date", "exclusivity"),
    ("First Interchangeable Exclusivity Exp. Date", "interchangeable exclusivity"),
    ("Orphan Exclusivity Exp. Date", "orphan exclusivity"),
]


def _match_ticker(applicant, applicant_map):
    upper = (applicant or "").upper()
    for ticker, needles in applicant_map.items():
        if any(needle in upper for needle in needles):
            return ticker
    return None


def _pb_date(text):
    try:
        return dt.datetime.strptime((text or "").strip(), "%d-%b-%y").date()
    except ValueError:
        return None


def _clean(value):
    value = (value or "").strip()
    return value if value and value.upper() != "N/A" else None


def parse_purple_book(csv_text, applicant_map) -> list[dict]:
    """Turn the Purple Book CSV into biologic product rows with exclusivity. Pure."""
    rows = list(csv.reader(io.StringIO(csv_text)))
    header_idx = next((i for i, r in enumerate(rows) if "BLA Number" in r), None)
    if header_idx is None:
        return []
    col = {name: i for i, name in enumerate(rows[header_idx])}

    def field(row, name):
        i = col.get(name)
        return row[i].strip() if i is not None and i < len(row) else ""

    products: dict[str, dict] = {}
    for row in rows[header_idx + 1:]:
        ticker = _match_ticker(field(row, "Applicant"), applicant_map)
        if not ticker:
            continue
        bla = field(row, "BLA Number")
        if not bla:
            continue
        exclusivities = []
        for column, ptype in EXCLUSIVITY_COLUMNS:
            expiry = _pb_date(field(row, column))
            if expiry:
                exclusivities.append(
                    {"protection_type": ptype, "identifier": ptype,
                     "expiry_date": expiry.isoformat()}
                )
        if not exclusivities:
            continue
        key = "BLA" + re.sub(r"\D", "", bla)
        product = products.get(key)
        if product is None:
            products[key] = {
                "ticker": ticker,
                "internal_code": key,
                "brand": _clean(field(row, "Proprietary Name")),
                "generic": _clean(field(row, "Proper Name")),
                "modality": "biologic",
                "exclusivities": exclusivities,
            }
        else:
            seen = {(e["protection_type"], e["expiry_date"]) for e in product["exclusivities"]}
            for e in exclusivities:
                if (e["protection_type"], e["expiry_date"]) not in seen:
                    product["exclusivities"].append(e)
    return list(products.values())


class PurpleBookFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def fetch(self) -> dict:
        request = urllib.request.Request(DOWNLOADS_PAGE, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            html = resp.read().decode("utf-8", "ignore")
        urls = re.findall(
            r'href="(https://[^"]+purplebook-search-[^"]+\.csv)"', html, re.IGNORECASE
        )
        if not urls:
            raise ValueError("no Purple Book CSV links found")
        urls.sort(key=_url_recency, reverse=True)  # newest month first

        csvs, last_error = [], None
        for url in urls:
            if len(csvs) >= _MONTHS_TO_MERGE:
                break
            try:
                req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
                with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                    text = resp.read().decode("latin-1")
                if "BLA Number" in text:
                    csvs.append(text)
            except Exception as exc:  # noqa: BLE001 - skip a missing month
                last_error = exc
        if not csvs:
            raise ValueError(f"no downloadable Purple Book CSV ({last_error})")
        return {"csvs": csvs}

    def normalise(self, raw) -> list[dict]:
        # Merge months newest-first; the first time we see a BLA wins (most recent data).
        merged: dict[str, dict] = {}
        for csv_text in raw["csvs"]:
            for product in parse_purple_book(csv_text, APPLICANT_MAP):
                merged.setdefault(product["internal_code"], product)
        return list(merged.values())

    def _write_snapshot(self, conn, payload):
        conn.execute(
            """
            INSERT INTO snapshots (source, entity_type, entity_key, payload, refresh_run_id)
            VALUES (?, 'source', ?, ?, ?)
            """,
            (self.source, ENTITY_KEY, json.dumps(payload), self.refresh_run_id),
        )

    def snapshot(self, rows: list[dict]) -> None:
        conn = db.get_connection(self.db_path)
        try:
            self._write_snapshot(
                conn,
                {"source": PB_SOURCE, "products": len(rows),
                 "exclusivities": sum(len(r["exclusivities"]) for r in rows),
                 "fetch_kind": "live"},
            )
            conn.commit()
        finally:
            conn.close()

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM exclusivities WHERE source = ?", (PB_SOURCE,)
            ).fetchone()[0]
            if not n:
                return
            self._write_snapshot(conn, {"source": PB_SOURCE, "exclusivities": n,
                                        "fetch_kind": "cache"})
            conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        try:
            companies = {r["ticker"]: r["id"] for r in conn.execute(
                "SELECT ticker, id FROM companies")}
            written = 0
            for product in rows:
                company_id = companies.get(product["ticker"])
                if company_id is None:
                    continue
                asset_id = upsert_asset(
                    conn, company_id, product["internal_code"], product["brand"],
                    product["generic"], product["modality"],
                )
                conn.execute(
                    "DELETE FROM exclusivities WHERE asset_id = ? AND source = ?",
                    (asset_id, PB_SOURCE),
                )
                for excl in product["exclusivities"]:
                    conn.execute(
                        """
                        INSERT INTO exclusivities
                            (asset_id, region, protection_type, identifier, expiry_date, source)
                        VALUES (?, 'US', ?, ?, ?, ?)
                        """,
                        (asset_id, excl["protection_type"], excl["identifier"],
                         excl["expiry_date"], PB_SOURCE),
                    )
                    written += 1
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, written, [], False, 0)
