"""Loss-of-exclusivity for small molecules from the FDA Orange Book.

One ZIP download holds tilde-delimited products/patent/exclusivity files. We keep the
products whose applicant maps to a universe company and that still have listed patents
or exclusivity, turn each into a marketed asset, and store every expiry in the
`exclusivities` table. LOE per product is the latest of those expiries.
"""

from __future__ import annotations

import collections
import datetime as dt
import io
import json
import urllib.request
import zipfile

import db
from assets_util import normalize_appl, upsert_asset
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "exclusivities"
OB_SOURCE = "orange_book"
ENTITY_KEY = "orange_book"
TTL_SECONDS = 7 * 24 * 60 * 60

ORANGE_BOOK_URL = "https://www.fda.gov/media/76860/download"
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 120

# ticker -> applicant-name substrings (uppercase). Curated to catch subsidiaries
# (Roche files as Genentech/Hoffmann-La Roche, J&J as Janssen) and to avoid the
# German Merck KGaA (kept out by requiring "MERCK SHARP"/"MSD" for Merck & Co).
APPLICANT_MAP = {
    "LLY": ["LILLY"],
    "NVO": ["NOVO NORDISK"],
    "MRK": ["MERCK SHARP", "MSD"],
    "PFE": ["PFIZER", "WYETH"],
    "ABBV": ["ABBVIE", "ALLERGAN"],
    "JNJ": ["JANSSEN", "ORTHO MCNEIL"],
    "AZN": ["ASTRAZENECA"],
    "GSK": ["GLAXO", "VIIV"],
    "NVS": ["NOVARTIS"],
    "ROG": ["GENENTECH", "HOFFMANN", "ROCHE"],
    "SNY": ["SANOFI", "GENZYME", "AVENTIS"],
    "BMY": ["BRISTOL", "CELGENE"],
    "AMGN": ["AMGEN"],
    "GILD": ["GILEAD"],
    "VRTX": ["VERTEX PHARM"],
    "REGN": ["REGENERON"],
    "BIIB": ["BIOGEN"],
    "BAYN": ["BAYER"],
}


def _match_ticker(applicant: str, applicant_map: dict) -> str | None:
    upper = (applicant or "").upper()
    for ticker, needles in applicant_map.items():
        if any(needle in upper for needle in needles):
            return ticker
    return None


def _parse_date(text: str):
    try:
        return dt.datetime.strptime((text or "").strip(), "%b %d, %Y").date()
    except ValueError:
        return None


def _rows(text: str):
    lines = text.splitlines()
    header = lines[0].split("~")
    index = {name: i for i, name in enumerate(header)}
    return index, [line.split("~") for line in lines[1:] if line]


def _field(parts, index, name):
    i = index.get(name)
    return parts[i] if i is not None and i < len(parts) else ""


def parse_orange_book(products_text, patents_text, exclusivity_text, applicant_map) -> list[dict]:
    """Turn the three Orange Book files into protected marketed-product rows. Pure."""
    pidx, prows = _rows(products_text)
    products: dict[str, dict] = {}
    for parts in prows:
        ticker = _match_ticker(_field(parts, pidx, "Applicant"), applicant_map)
        if not ticker:
            continue
        appl_no = _field(parts, pidx, "Appl_No")
        if not appl_no:
            continue
        # Type is RX, OTC, or DISCN. A discontinued product is off the market, so its
        # patents running to 2027 are not a loss of exclusivity, they are a dead
        # listing. An application can mix live and discontinued strengths, so it counts
        # as marketed when any one of its rows is, and a live row wins the naming.
        marketed = _field(parts, pidx, "Type").strip().upper() != "DISCN"
        existing = products.get(appl_no)
        if existing is not None and (existing["marketed"] or not marketed):
            continue
        products[appl_no] = {
            "ticker": ticker,
            "marketed": marketed,
            "appl_type": _field(parts, pidx, "Appl_Type"),
            "brand": _field(parts, pidx, "Trade_Name").strip().title() or None,
            "generic": _field(parts, pidx, "Ingredient").strip().title() or None,
        }
    products = {no: p for no, p in products.items() if p["marketed"]}

    patents = collections.defaultdict(list)
    aidx, arows = _rows(patents_text)
    for parts in arows:
        appl_no = _field(parts, aidx, "Appl_No")
        if appl_no not in products:
            continue
        expiry = _parse_date(_field(parts, aidx, "Patent_Expire_Date_Text"))
        if expiry:
            patents[appl_no].append((_field(parts, aidx, "Patent_No"), expiry))

    exclusivity = collections.defaultdict(list)
    eidx, erows = _rows(exclusivity_text)
    for parts in erows:
        appl_no = _field(parts, eidx, "Appl_No")
        if appl_no not in products:
            continue
        expiry = _parse_date(_field(parts, eidx, "Exclusivity_Date"))
        if expiry:
            exclusivity[appl_no].append((_field(parts, eidx, "Exclusivity_Code"), expiry))

    out = []
    for appl_no, product in products.items():
        rows = [
            {"protection_type": "patent", "identifier": pat, "expiry_date": d.isoformat()}
            for pat, d in patents.get(appl_no, [])
        ] + [
            {"protection_type": "regulatory exclusivity", "identifier": code,
             "expiry_date": d.isoformat()}
            for code, d in exclusivity.get(appl_no, [])
        ]
        if not rows:  # only keep products with listed protection
            continue
        out.append(
            {
                "ticker": product["ticker"],
                "internal_code": normalize_appl(product["appl_type"], appl_no),
                "brand": product["brand"],
                "generic": product["generic"],
                "modality": "small molecule",
                "exclusivities": rows,
            }
        )
    return out


class OrangeBookFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, db_path=None):
        super().__init__(db_path)

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def fetch(self) -> dict:
        request = urllib.request.Request(ORANGE_BOOK_URL, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            archive = zipfile.ZipFile(io.BytesIO(resp.read()))
        return {
            "products": archive.read("products.txt").decode("latin-1"),
            "patents": archive.read("patent.txt").decode("latin-1"),
            "exclusivity": archive.read("exclusivity.txt").decode("latin-1"),
        }

    def normalise(self, raw) -> list[dict]:
        return parse_orange_book(
            raw["products"], raw["patents"], raw["exclusivity"], APPLICANT_MAP
        )

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
                {
                    "source": OB_SOURCE,
                    "products": len(rows),
                    "exclusivities": sum(len(r["exclusivities"]) for r in rows),
                    "fetch_kind": "live",
                },
            )
            conn.commit()
        finally:
            conn.close()

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM exclusivities WHERE source = ?", (OB_SOURCE,)
            ).fetchone()[0]
            if not n:
                return
            self._write_snapshot(conn, {"source": OB_SOURCE, "exclusivities": n,
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
                # Refresh this asset's Orange Book exclusivities in place.
                conn.execute(
                    "DELETE FROM exclusivities WHERE asset_id = ? AND source = ?",
                    (asset_id, OB_SOURCE),
                )
                for excl in product["exclusivities"]:
                    conn.execute(
                        """
                        INSERT INTO exclusivities
                            (asset_id, region, protection_type, identifier, expiry_date, source)
                        VALUES (?, 'US', ?, ?, ?, ?)
                        """,
                        (asset_id, excl["protection_type"], excl["identifier"],
                         excl["expiry_date"], OB_SOURCE),
                    )
                    written += 1
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, written, [], False, 0)
