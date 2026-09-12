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
from assets_util import normalize_appl, resolve_alias, upsert_asset
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
    # Merck needles are deliberately specific. The book also lists MERCK KGAA, the
    # German company, which is not in this universe and must never match here.
    "MRK": ["MERCK SHARP", "MSD", "MERCK AND CO", "MERCK CO INC",
            "MERCK RESEARCH LAB"],
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
    # The rest of the universe's filers. Incyte and United Therapeutics were missing
    # for as long as the map existed, so Jakafi and Tyvaso never carried a patent.
    "INCY": ["INCYTE"],
    "UTHR": ["UNITED THERAP"],
    "ALNY": ["ALNYLAM"],
    "BMRN": ["BIOMARIN"],
    "EXEL": ["EXELIXIS"],
    "IONS": ["IONIS"],
    "NBIX": ["NEUROCRINE"],
    "SRPT": ["SAREPTA"],
    "AXSM": ["AXSOME"],
    "KRYS": ["KRYSTAL BIOTECH"],
    "LNTH": ["LANTHEUS"],
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


def patent_kind(flags) -> str | None:
    """What a listed patent covers, or None when the book flags nothing.

    Substance outranks product, which outranks use: a patent claiming the molecule
    blocks a generic whatever else it also claims, while one claiming only a method of
    use can be carved out of a generic's label and does not hold the market.
    """
    if not flags:
        return None
    if flags.get("substance"):
        return "substance"
    if flags.get("product"):
        return "product"
    return "use" if flags.get("use") else None


def parse_orange_book(products_text, patents_text, exclusivity_text, applicant_map,
                      linked=None) -> list[dict]:
    """Turn the three Orange Book files into protected marketed-product rows. Pure.

    ``linked`` is {application code: [asset ids]} for applications an asset on file
    already holds under an applicant the map does not know: Pfizer books Xtandi on
    Astellas's NDA. Such a product is kept and carries ``asset_ids`` instead of a
    ticker, and the upsert attaches its rows to those assets rather than creating one.
    """
    linked = linked or {}
    pidx, prows = _rows(products_text)
    products: dict[str, dict] = {}
    for parts in prows:
        # Applicant is an abbreviation: Novo Nordisk is "NOVO" and Merck & Co is
        # "MERCK", neither of which matched, dropping 33 and 114 products including
        # Ozempic and Wegovy. The full name is unambiguous and is also what separates
        # Merck & Co from Merck KGaA.
        ticker = _match_ticker(_field(parts, pidx, "Applicant_Full_Name"), applicant_map) \
            or _match_ticker(_field(parts, pidx, "Applicant"), applicant_map)
        appl_no = _field(parts, pidx, "Appl_No")
        if not appl_no:
            continue
        code = normalize_appl(_field(parts, pidx, "Appl_Type"), appl_no)
        asset_ids = linked.get(code) if not ticker else None
        if not ticker and not asset_ids:
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
            "asset_ids": asset_ids,
            "marketed": marketed,
            "appl_type": _field(parts, pidx, "Appl_Type"),
            "brand": _field(parts, pidx, "Trade_Name").strip().title() or None,
            "generic": _field(parts, pidx, "Ingredient").strip().title() or None,
            "approval_date": (_parse_date(_field(parts, pidx, "Approval_Date")) or dt.date.min).isoformat()
            if _parse_date(_field(parts, pidx, "Approval_Date")) else None,
            "applicant": _field(parts, pidx, "Applicant_Full_Name").strip() or None,
        }
    products = {no: p for no, p in products.items() if p["marketed"]}

    # A patent is listed once per strength and once per use code, so its flags arrive
    # spread over many rows: 11357820 is flagged a drug substance on one row and not on
    # another. Any row saying substance makes it a substance patent, since the book is
    # asserting the claim somewhere.
    patent_kinds: dict = {}
    patents = collections.defaultdict(list)
    aidx, arows = _rows(patents_text)
    for parts in arows:
        appl_no = _field(parts, aidx, "Appl_No")
        if appl_no not in products:
            continue
        expiry = _parse_date(_field(parts, aidx, "Patent_Expire_Date_Text"))
        if not expiry:
            continue
        number = _field(parts, aidx, "Patent_No")
        patents[appl_no].append((number, expiry))
        key = (appl_no, number)
        flags = patent_kinds.setdefault(key, {"substance": False, "product": False,
                                              "use": False})
        flags["substance"] |= _field(parts, aidx, "Drug_Substance_Flag").strip() == "Y"
        flags["product"] |= _field(parts, aidx, "Drug_Product_Flag").strip() == "Y"
        flags["use"] |= bool(_field(parts, aidx, "Patent_Use_Code").strip())

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
        # The book lists a patent once per product strength, so a six-strength product
        # carried the same patent six times. Mounjaro held 522 rows for 10 patents and
        # the table was 63% exact duplicates. The protection belongs to the
        # application, so it is deduplicated here.
        seen = set()
        rows = []
        for kind, items in (("patent", patents.get(appl_no, [])),
                            ("regulatory exclusivity", exclusivity.get(appl_no, []))):
            for identifier, expiry in items:
                key = (kind, identifier, expiry)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"protection_type": kind, "identifier": identifier,
                             "expiry_date": expiry.isoformat(),
                             "patent_kind": patent_kind(
                                 patent_kinds.get((appl_no, identifier)))
                             if kind == "patent" else None})
        # A marketed product with nothing listed is kept, marked, and attached only to
        # an asset already on file: the silence is a finding about that product, and
        # not a reason to create an asset for every old NDA in the book.
        out.append(
            {
                "ticker": product["ticker"],
                "asset_ids": product.get("asset_ids"),
                "internal_code": normalize_appl(product["appl_type"], appl_no),
                "brand": product["brand"],
                "generic": product["generic"],
                "modality": "small molecule",
                "exclusivities": rows,
                "listed_only": not rows,
                "approval_date": product.get("approval_date"),
                "applicant": product.get("applicant"),
            }
        )
    return out


def record_listing(conn, product: dict, asset_id: int) -> None:
    """Note that the book lists this product for this asset, and how many live rows."""
    conn.execute(
        """INSERT INTO orange_book_listings
               (asset_id, appl_code, approval_date, applicant, live_rows, fetched_at)
           VALUES (?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(asset_id) DO UPDATE SET appl_code = excluded.appl_code,
               approval_date = MIN(COALESCE(orange_book_listings.approval_date, '9999'),
                                   COALESCE(excluded.approval_date, '9999')),
               applicant = excluded.applicant,
               live_rows = orange_book_listings.live_rows + excluded.live_rows,
               fetched_at = datetime('now')""",
        (asset_id, product.get("internal_code"), product.get("approval_date"),
         product.get("applicant"), len(product.get("exclusivities") or [])))


def clear_direct(conn, rows: list, source: str) -> None:
    """Clear this source's rows once per targeted asset, before any product attaches.
    An asset can be the target of two applications (Xtandi's capsule and tablet NDAs);
    clearing per product kept only the last one's patents."""
    targets = sorted({aid for p in rows for aid in (p.get("asset_ids") or [])})
    for aid in targets:
        conn.execute("DELETE FROM exclusivities WHERE asset_id = ? AND source = ?",
                     (aid, source))


def attach_direct(conn, product: dict, source: str, with_kind: bool) -> int:
    """Write a product's rows onto the assets on file that hold its application,
    creating nothing. Returns rows written. The modality is filled where the asset had
    none, since the book that lists it says what it is."""
    written = 0
    for asset_id in product.get("asset_ids") or []:
        if source == OB_SOURCE:
            record_listing(conn, product, asset_id)
        conn.execute("UPDATE assets SET modality = COALESCE(modality, ?) WHERE id = ?",
                     (product.get("modality"), asset_id))
        for excl in product["exclusivities"]:
            if with_kind:
                conn.execute(
                    "INSERT INTO exclusivities (asset_id, region, protection_type,"
                    " identifier, expiry_date, patent_kind, source)"
                    " VALUES (?, 'US', ?, ?, ?, ?, ?)",
                    (asset_id, excl["protection_type"], excl["identifier"],
                     excl["expiry_date"], excl.get("patent_kind"), source))
            else:
                conn.execute(
                    "INSERT INTO exclusivities (asset_id, region, protection_type,"
                    " identifier, expiry_date, source) VALUES (?, 'US', ?, ?, ?, ?)",
                    (asset_id, excl["protection_type"], excl["identifier"],
                     excl["expiry_date"], source))
            written += 1
    return written


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
        import loe_link
        conn = db.get_connection(self.db_path)
        try:
            linked = loe_link.attach_targets(conn)
        finally:
            conn.close()
        return parse_orange_book(
            raw["products"], raw["patents"], raw["exclusivity"], APPLICANT_MAP, linked
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
            # The listings are rebuilt from the full book each run, and accumulate across
            # the applications one asset holds within it.
            conn.execute("DELETE FROM orange_book_listings")
            clear_direct(conn, rows, OB_SOURCE)
            for product in rows:
                if product.get("asset_ids"):
                    written += attach_direct(conn, product, OB_SOURCE, with_kind=True)
                    continue
                company_id = companies.get(product["ticker"])
                if company_id is None:
                    continue
                if product.get("listed_only"):
                    # Only an asset already on file takes the finding.
                    existing = conn.execute(
                        "SELECT id FROM assets WHERE internal_code = ?",
                        (product["internal_code"],)).fetchone()
                    alias = None if existing else resolve_alias(conn, product["internal_code"])
                    target = existing[0] if existing else alias
                    if target is not None:
                        record_listing(conn, product, target)
                    continue
                asset_id = upsert_asset(
                    conn, company_id, product["internal_code"], product["brand"],
                    product["generic"], product["modality"],
                )
                record_listing(conn, product, asset_id)
                # Refresh this asset's Orange Book exclusivities in place.
                conn.execute(
                    "DELETE FROM exclusivities WHERE asset_id = ? AND source = ?",
                    (asset_id, OB_SOURCE),
                )
                for excl in product["exclusivities"]:
                    conn.execute(
                        """
                        INSERT INTO exclusivities
                            (asset_id, region, protection_type, identifier, expiry_date,
                             patent_kind, source)
                        VALUES (?, 'US', ?, ?, ?, ?, ?)
                        """,
                        (asset_id, excl["protection_type"], excl["identifier"],
                         excl["expiry_date"], excl.get("patent_kind"), OB_SOURCE),
                    )
                    written += 1
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, written, [], False, 0)
