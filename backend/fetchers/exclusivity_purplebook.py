"""Biologics loss-of-exclusivity from the FDA Purple Book (partial coverage).

Only a monthly *changes* CSV is downloadable, so this covers biologics that were newly
approved / added / updated in the latest release, not the full biologic universe. It is
labelled partial in the UI. Each matched BLA becomes a marketed biologic asset with its
reference-product / orphan / interchangeable exclusivity expiries.

The file is titled a changes report and carries the whole register under it: 2,270
presentations in October 2026, 261 of them licensed under section 351(k). Those are the
biosimilars, each naming the reference product it copies, and they are read into
``biosimilar_licences`` (``parse_biosimilars``).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import urllib.request

import db
from assets_util import same_brand_family, upsert_asset
from fetchers.base import BaseFetcher, RefreshResult
import contact

SOURCE = "exclusivities"
PB_SOURCE = "purple_book"
ENTITY_KEY = "purple_book"
TTL_SECONDS = 7 * 24 * 60 * 60

DOWNLOADS_PAGE = "https://purplebooksearch.fda.gov/downloads"
_USER_AGENT = contact.user_agent()
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
    # Merck licenses biologics through several subsidiaries. Needles stay specific so
    # Merck KGaA, a different company and not in this universe, never matches.
    "MRK": ["MERCK SHARP", "MSD", "MERCK & CO", "MERCK AND CO", "ORGANON",
            "SCHERING CORPORATION"],
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
    "INCY": ["INCYTE"],
    "UTHR": ["UNITED THERAP"],
    "ALNY": ["ALNYLAM"],
    "BMRN": ["BIOMARIN"],
    "ARGX": ["ARGENX"],
    "BNTX": ["BIONTECH"],
    "MRNA": ["MODERNATX", "MODERNA"],
    "SRPT": ["SAREPTA"],
    "KRYS": ["KRYSTAL BIOTECH"],
    "LEGN": ["LEGEND BIOTECH"],
}

EXCLUSIVITY_COLUMNS = [
    ("Ref. Product Exclusivity Exp. Date", "reference product exclusivity"),
    ("Exclusivity Expiration Date", "exclusivity"),
    ("First Interchangeable Exclusivity Exp. Date", "interchangeable exclusivity"),
    ("Orphan Exclusivity Exp. Date", "orphan exclusivity"),
]

# The BPCIA gives a biologic 12 years of reference-product exclusivity from its first
# licensure: no biosimilar can enter before then, so it is a hard cliff floor. The Purple
# Book often leaves the exclusivity columns blank (they are only filled while a window is
# open), which left a biologic like Casgevy showing only its 7-year orphan exclusivity as
# its LOE, years short of the real wall. When no reference-product exclusivity is
# published, compute the floor from the licensure date and label it as derived, so the
# date is honest about being the statute, not a value read from the file.
STATUTORY_FLOOR_YEARS = 12
FLOOR_PROTECTION = "reference product exclusivity (12y)"
FLOOR_IDENTIFIER = "12-year statutory floor"
REF_PRODUCT_PROTECTION = "reference product exclusivity"
# Prefer the first-licensure date, the true start of the 12-year clock; fall back to the
# approval date on the row when the dedicated column is blank, as it usually is.
LICENSURE_COLUMNS = ("Date of First Licensure", "Approval Date")


def _statutory_floor(licensure: dt.date) -> str:
    """The 12-year floor expiry as an ISO date, clamped off a Feb 29 start."""
    try:
        return licensure.replace(
            year=licensure.year + STATUTORY_FLOOR_YEARS).isoformat()
    except ValueError:  # a 29 Feb start whose target year is not a leap year
        return dt.date(licensure.year + STATUTORY_FLOOR_YEARS, 12, 31).isoformat()


def _match_ticker(applicant, applicant_map):
    upper = (applicant or "").upper()
    for ticker, needles in applicant_map.items():
        if any(needle in upper for needle in needles):
            return ticker
    return None


# The file has written its dates two ways. "4-Sep-14" is the older form and the one the
# saved fixture carries; the September 2026 release writes "October 18, 2017". Only the
# first was accepted, so against the live file every date read as None, every product
# was dropped for having neither an exclusivity nor a licensure, and the fetcher parsed
# nothing at all while reporting no error. Both forms are read now, and a format this
# source invents next will show up as a drop in the parsed count rather than silence.
_PB_DATE_FORMATS = ("%d-%b-%y", "%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y")


def _pb_date(text):
    text = (text or "").strip()
    if not text:
        return None
    for fmt in _PB_DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _licensure_date(text, today):
    """A licensure or approval date, always in the past. A two-digit year strptime pivots
    into this century (54 -> 2054) can land in the future for a product licensed in the
    1950s or 60s; a licensure date after today is one of those, so roll it back a century
    rather than compute a 12-year floor a lifetime out."""
    parsed = _pb_date(text)
    if parsed and parsed > today:
        try:
            return parsed.replace(year=parsed.year - 100)
        except ValueError:  # 29 Feb in a non-leap target; the date is already off
            return None
    return parsed


def _clean(value):
    value = (value or "").strip()
    return value if value and value.upper() != "N/A" else None


def _molecule_key(product) -> tuple | None:
    """One sponsor's molecule: the ticker (or the linked assets) and the proper name, so
    two BLAs for anifrolumab-fnia from AstraZeneca share a key. None without a name."""
    name = re.sub(r"\s+", " ", (product.get("generic") or "").strip().lower())
    if not name:
        return None
    owner = product.get("ticker") or tuple(sorted(product.get("asset_ids") or ()))
    return (owner, name)


def parse_purple_book(csv_text, applicant_map, today=None, linked=None) -> list[dict]:
    """Turn the Purple Book CSV into biologic product rows with exclusivity. Pure.

    ``linked`` is {BLA code: [asset ids]} for applications an asset on file already
    holds under an applicant the map does not know (Alexion's Ultomiris, booked by
    AstraZeneca). Such a product is kept with ``asset_ids`` in place of a ticker and
    its rows are attached to those assets rather than to a new one.
    """
    today = today or dt.date.today()
    linked = linked or {}
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
        bla = field(row, "BLA Number")
        if not bla:
            continue
        asset_ids = linked.get("BLA" + re.sub(r"\D", "", bla)) if not ticker else None
        if not ticker and not asset_ids:
            continue
        exclusivities = []
        for column, ptype in EXCLUSIVITY_COLUMNS:
            expiry = _pb_date(field(row, column))
            if expiry:
                exclusivities.append(
                    {"protection_type": ptype, "identifier": ptype,
                     "expiry_date": expiry.isoformat()}
                )
        licensure = next((d for d in (_licensure_date(field(row, c), today)
                                      for c in LICENSURE_COLUMNS) if d), None)
        # A row can carry a licensure date without any open exclusivity window; keep it,
        # since the statutory floor is computed from the licensure date alone.
        if not exclusivities and not licensure:
            continue
        key = "BLA" + re.sub(r"\D", "", bla)
        product = products.get(key)
        if product is None:
            products[key] = {
                "ticker": ticker,
                "asset_ids": asset_ids,
                "internal_code": key,
                "brand": _clean(field(row, "Proprietary Name")),
                "generic": _clean(field(row, "Proper Name")),
                "modality": "biologic",
                "exclusivities": exclusivities,
                "licensure": licensure,
            }
        else:
            seen = {(e["protection_type"], e["expiry_date"]) for e in product["exclusivities"]}
            for e in exclusivities:
                if (e["protection_type"], e["expiry_date"]) not in seen:
                    product["exclusivities"].append(e)
            # The earliest licensure across a BLA's rows anchors the 12-year clock.
            if licensure and (product["licensure"] is None
                              or licensure < product["licensure"]):
                product["licensure"] = licensure

    # The 12-year clock runs from the molecule's first licensure, not each application's.
    # A later BLA from the same sponsor for the same molecule (a new formulation or route)
    # earns no new exclusivity (42 U.S.C. 262(k)(7)(C)), yet its own row carries its own
    # approval date: Saphnelo's 2026 subcutaneous BLA set a 2038 floor over the 2033 one
    # its 2021 licensure gives. So every BLA of one sponsor's molecule, read by its proper
    # name, takes the earliest licensure among them.
    first: dict = {}
    for product in products.values():
        key = _molecule_key(product)
        if key and product["licensure"] and (key not in first
                                             or product["licensure"] < first[key]):
            first[key] = product["licensure"]

    # Add the statutory 12-year floor wherever the file publishes no reference-product
    # exclusivity of its own, so a biologic left with only an orphan date reads to the
    # real wall. A published reference-product date always wins over the computed one.
    out = []
    for product in products.values():
        has_ref = any(e["protection_type"] == REF_PRODUCT_PROTECTION
                      for e in product["exclusivities"])
        licensure = first.get(_molecule_key(product)) or product["licensure"]
        product.pop("licensure", None)
        if not has_ref and licensure:
            product["exclusivities"].append(
                {"protection_type": FLOOR_PROTECTION, "identifier": FLOOR_IDENTIFIER,
                 "expiry_date": _statutory_floor(licensure)})
        if product["exclusivities"]:
            out.append(product)
    return out


# --------------------------------------------------------------- licensure dates
# openFDA drugsfda is CDER, so every CBER biologic is absent from it: the CAR-Ts, the
# gene therapies, the vaccines and the clotting factors. 155 marketed products had no
# approval record and almost all of them were this. The Purple Book is the register for
# those same products and carries the licensure date on every row, which makes it the
# route to the date rather than a second opinion on it.
#
# The file's "Licensure" column is a status ("Licensed", "Revoked", "Voluntarily
# Revoked"), not a date. "Approval Date" is the date, filled on 2,257 of the 2,273 rows
# in the September 2026 release.
PB_APPROVAL_SOURCE = "purple_book"


def parse_licensures(csv_text: str) -> list[dict]:
    """Every licensed product in the file, as brand, BLA and first licensure date.

    Independent of ``parse_purple_book`` above, which answers a different question. That
    one keeps a product only where the applicant maps to a company in the universe and
    only where an exclusivity window is open, both right for a loss-of-exclusivity view
    and both fatal here: a 1989 hepatitis B vaccine has no open window and Abeona is in
    no applicant map, and each still has a licensure date that is the thing wanted.

    A BLA appears once per presentation, so the rows are reduced to the earliest date
    per BLA: the original licensure rather than the latest strength added under it.

    A licence with no proprietary name is kept, with ``brand`` None. The file prints
    "N/A" or nothing for 91 dated BLAs in the October 2026 release, the antivenins and
    the unbranded toxoids among them, and each is still a licence with a date. Requiring
    a brand dropped them all, so nothing could date an asset that carries one of those
    application numbers.
    """
    rows = list(csv.reader(io.StringIO(csv_text)))
    header_idx = next((i for i, r in enumerate(rows) if "BLA Number" in r), None)
    if header_idx is None:
        return []
    col = {name: i for i, name in enumerate(rows[header_idx])}

    def field(row, name):
        i = col.get(name)
        return row[i].strip() if i is not None and i < len(row) else ""

    found: dict[tuple, dict] = {}
    for row in rows[header_idx + 1:]:
        brand = _clean(field(row, "Proprietary Name"))
        digits = re.sub(r"\D", "", field(row, "BLA Number"))
        approved = _pb_date(field(row, "Approval Date"))
        if not digits or not approved:
            continue
        key = ((brand or "").upper(), digits)
        listed = field(row, "Marketing Status").rstrip("*")
        entry = found.get(key)
        # Every presentation's status, whichever row carries the earliest date: a
        # licence whose first strength is discontinued and whose current one is not is
        # still sold.
        seen = (entry["listed"] if entry else set()) | ({listed} if listed else set())
        if entry is None or approved.isoformat() < entry["approval_date"]:
            entry = found[key] = {
                "brand": brand,
                "generic": _clean(field(row, "Proper Name")),
                "application_number": "BLA" + digits,
                "approval_date": approved.isoformat(),
                "applicant": field(row, "Applicant"),
                # Carried so a withdrawn product is not silently read as on the market.
                # The licensure date stays true either way, which is why the row is
                # still written: Bexxar was approved in 2003 and withdrawn in 2014, and
                # both are facts.
                "status": field(row, "Licensure"),
            }
        entry["listed"] = seen
    for entry in found.values():
        entry["marketing_status"] = _licence_standing(entry["status"], entry.pop("listed"))
    return sorted(found.values(),
                  key=lambda r: ((r["brand"] or "").upper(), r["application_number"]))


# The file's own words for a presentation, in the words ``approvals.marketing_status``
# already holds from openFDA, so one reading (``marketing_status.py``) serves both.
_PB_STANDING = (("Rx", "Prescription"), ("OTC", "Over-the-counter"),
                ("Disc", "Discontinued"))


def _licence_standing(licensure: str, listed: set) -> str | None:
    """Whether the FDA still lists the licence as sold, or None where the file says
    nothing.

    A revoked licence is discontinued whatever its presentations say. Twelve rows of the
    October 2026 release read "Rx" beside "Voluntarily Revoked", Sanofi's tetanus toxoid
    among them, and a product whose licence has been given up is not on sale. Otherwise
    the strongest presentation decides, as it does for an openFDA application.
    """
    if "revoked" in (licensure or "").lower():
        return "Discontinued"
    for word, standing in _PB_STANDING:
        if word in listed:
            return standing
    return None


def parse_biosimilars(csv_text: str) -> list[dict]:
    """Every biosimilar the file licenses, one row a brand and BLA, with the reference
    product it copies.

    A 351(k) licence is the FDA's finding that the product is biosimilar to, or
    interchangeable with, a named reference product. The file prints one row a
    presentation, so they are reduced: the earliest approval, the widest licence type
    (interchangeable over biosimilar) and "Rx" where any presentation is still listed.
    "Disc" on every presentation is how the file shows a licence nobody sells, which is
    every etanercept biosimilar in October 2026. "Rx" is not a launch: it is a licence
    not discontinued.
    """
    rows = list(csv.reader(io.StringIO(csv_text)))
    header_idx = next((i for i, r in enumerate(rows) if "BLA Number" in r), None)
    if header_idx is None:
        return []
    col = {name: i for i, name in enumerate(rows[header_idx])}

    def field(row, name):
        i = col.get(name)
        return row[i].strip() if i is not None and i < len(row) else ""

    found: dict[tuple, dict] = {}
    for row in rows[header_idx + 1:]:
        licence = field(row, "License Type")
        reference = _clean(field(row, "Ref. Product Proprietary Name"))
        brand = _clean(field(row, "Proprietary Name"))
        digits = re.sub(r"\D", "", field(row, "BLA Number"))
        if "351(k)" not in licence or not reference or not brand or not digits:
            continue
        approved = _pb_date(field(row, "Approval Date"))
        status = field(row, "Marketing Status").rstrip("*")
        entry = found.setdefault((digits, brand.upper()), {
            "bla_number": "BLA" + digits, "proprietary_name": brand,
            "proper_name": _clean(field(row, "Proper Name")),
            "applicant": field(row, "Applicant"), "licence_type": licence,
            "reference_proprietary": reference,
            "reference_proper": _clean(field(row, "Ref. Product Proper Name")),
            "approval_date": None, "marketing_status": "Disc"})
        if approved and (entry["approval_date"] is None
                         or approved.isoformat() < entry["approval_date"]):
            entry["approval_date"] = approved.isoformat()
        if status == "Rx":
            entry["marketing_status"] = "Rx"
        if "Interchangeable" in licence:
            entry["licence_type"] = licence
    return sorted(found.values(),
                  key=lambda r: (r["reference_proprietary"].upper(), r["proprietary_name"]))


def write_biosimilars(conn, licences: list[dict]) -> int:
    """Replace the table with this release's licences. The whole register comes in each
    release, so the table is the release; an empty read leaves what is there alone."""
    if not licences:
        return 0
    conn.execute("DELETE FROM biosimilar_licences")
    conn.executemany(
        "INSERT INTO biosimilar_licences (bla_number, proprietary_name, proper_name,"
        " applicant, licence_type, reference_proprietary, reference_proper, approval_date,"
        " marketing_status) VALUES (:bla_number, :proprietary_name, :proper_name,"
        " :applicant, :licence_type, :reference_proprietary, :reference_proper,"
        " :approval_date, :marketing_status)", licences)
    return len(licences)


def _brand_key(name: str) -> str:
    """A brand reduced to the form both sides can be compared on.

    An asset can hold several brands for one reported line ("Fluarix, Fluarix
    Quadrivalent"); the first is the one the application is filed under.
    """
    return re.split(r"[,;/]", name or "")[0].strip().upper()


def _bla_digits(code) -> str | None:
    """The number of a BLA, without its leading zeros, or None for anything else. An
    asset writes BLA020563 and BLA21017; the file writes 020563 and 021017."""
    found = re.match(r"^\s*BLA\s*0*(\d+)\s*$", (code or "").upper())
    return found.group(1) if found else None


def _licence_for_application(asset, by_application: dict):
    """The licence an asset's own application number names: (row, ambiguous).

    One BLA can carry two products. BLA125326 is Arzerra, licensed in 2009, and Kesimpta,
    licensed under it in 2020, so the number alone does not date either. The row is taken
    where the brand is the asset's, or where the application holds one licence and its
    name is not another product's (``same_brand_family``: Xultophy beside Xultophy
    100/3.6, or either side unbranded). Anything else is refused.
    """
    number = _bla_digits(asset["internal_code"])
    candidates = by_application.get(number) or [] if number else []
    if not candidates:
        return None, False
    brand = (asset["brand_name"] or "").strip().upper()
    named = [c for c in candidates if brand and (c["brand"] or "").strip().upper() == brand]
    if named:
        return named[0], False
    if len(candidates) == 1 and same_brand_family(asset["brand_name"], candidates[0]["brand"]):
        return candidates[0], False
    return None, True


def attach_licensures(conn, licensures: list[dict], today=None) -> dict:
    """Write an approval for every marketed product that has none and that the Purple
    Book names, matched on the application number the asset carries and then on the
    brand.

    Only the gap. A product openFDA already dated is left alone, so this never argues
    with the other source over a product both carry; it reaches the ones only this
    register holds.

    The application number first, because it is exact. An asset the registers created
    holds the BLA it was created from, and that settles what no brand can: ten products
    with no proprietary name at all (Merck's and Pfizer's antivenins, Sanofi's toxoids),
    Menomune-A beside Menomune-A/C, which reduce to one brand key, and Humalog, a name
    the file prints under both BLA020563 and BLA205747. On 2026-11-25 fourteen marketed
    products the registers had created stood without an approval for those three
    reasons, and the file dated every one.

    The brand match is the fallback, for an asset that carries no BLA. It is an exact
    brand and must be unique in the file. A brand standing for two BLAs is not resolved
    by guessing, and in the September 2026 release against this universe there were
    none: 118 of the 157 marketed products without an approval matched exactly one BLA,
    and none matched more.

    The applicant is not required to be the company. Eylea is Bayer's outside the United
    States and the BLA is Regeneron's, and the date of that licensure is what the page
    was missing. The approval stays the applicant's; the date is what is taken.

    The row says whether the licence is still sold, in openFDA's words. Ten of those
    fourteen licences are revoked or discontinued, and a date alone would have turned
    "record missing" into "approved and on the market".
    """
    by_brand: dict[str, list] = {}
    by_application: dict[str, list] = {}
    for row in licensures:
        if _brand_key(row["brand"]):
            by_brand.setdefault(_brand_key(row["brand"]), []).append(row)
        number = _bla_digits(row["application_number"])
        if number:
            by_application.setdefault(number, []).append(row)

    gap = conn.execute(
        "SELECT a.id, a.brand_name, a.internal_code FROM assets a"
        "  WHERE a.is_marketed = 1"
        "    AND NOT EXISTS (SELECT 1 FROM approvals ap WHERE ap.asset_id = a.id)"
    ).fetchall()

    written, ambiguous, unmatched = 0, 0, 0
    for asset in gap:
        row, refused = _licence_for_application(asset, by_application)
        if refused:
            ambiguous += 1
            continue
        if row is None:
            candidates = by_brand.get(_brand_key(asset["brand_name"])) or []
            if not candidates:
                unmatched += 1
                continue
            if len({c["application_number"] for c in candidates}) > 1:
                ambiguous += 1
                continue
            row = candidates[0]
        conn.execute(
            "INSERT INTO approvals"
            "  (asset_id, region, agency, approval_date, application_number, source,"
            "   marketing_status)"
            "  VALUES (?, 'US', 'FDA', ?, ?, ?, ?)",
            (asset["id"], row["approval_date"], row["application_number"],
             PB_APPROVAL_SOURCE, row.get("marketing_status")),
        )
        written += 1
    return {"written": written, "ambiguous": ambiguous, "unmatched": unmatched}


# ``normalise`` used to return a bare list of products and now returns both row types,
# the shape approvals_openfda already uses. A caller or a test holding the old list is
# still answered, so the change is not a break for anything that only wants products.
def _products_of(rows) -> list:
    return rows.get("products", []) if isinstance(rows, dict) else (rows or [])


def _licensures_of(rows) -> list:
    return rows.get("licensures", []) if isinstance(rows, dict) else []


def _biosimilars_of(rows) -> list:
    return rows.get("biosimilars", []) if isinstance(rows, dict) else []


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
        import loe_link
        conn = db.get_connection(self.db_path)
        try:
            linked = loe_link.attach_targets(conn)
        finally:
            conn.close()
        # Merge months newest-first; the first time we see a BLA wins (most recent data).
        merged: dict[str, dict] = {}
        for csv_text in raw["csvs"]:
            for product in parse_purple_book(csv_text, APPLICANT_MAP, linked=linked):
                merged.setdefault(product["internal_code"], product)
        # The newest file alone for the licensures. Each monthly release carries the
        # whole register, not only that month's changes, so merging months adds nothing
        # here and the newest is the most current.
        licensures = parse_licensures(raw["csvs"][0]) if raw.get("csvs") else []
        biosimilars = parse_biosimilars(raw["csvs"][0]) if raw.get("csvs") else []
        return {"products": list(merged.values()), "licensures": licensures,
                "biosimilars": biosimilars}

    def _write_snapshot(self, conn, payload):
        conn.execute(
            """
            INSERT INTO snapshots (source, entity_type, entity_key, payload, refresh_run_id)
            VALUES (?, 'source', ?, ?, ?)
            """,
            (self.source, ENTITY_KEY, json.dumps(payload), self.refresh_run_id),
        )

    def snapshot(self, rows) -> None:
        products = _products_of(rows)
        conn = db.get_connection(self.db_path)
        try:
            self._write_snapshot(
                conn,
                {"source": PB_SOURCE, "products": len(products),
                 "exclusivities": sum(len(r["exclusivities"]) for r in products),
                 "licensures": len(_licensures_of(rows)),
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

    def upsert(self, rows) -> RefreshResult:
        products = _products_of(rows)
        conn = db.get_connection(self.db_path)
        try:
            companies = {r["ticker"]: r["id"] for r in conn.execute(
                "SELECT ticker, id FROM companies")}
            written = 0
            from fetchers.exclusivity_orangebook import attach_direct, clear_direct
            clear_direct(conn, products, PB_SOURCE)
            for product in products:
                if product.get("asset_ids"):
                    written += attach_direct(conn, product, PB_SOURCE, with_kind=False)
                    continue
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
            # The CBER products openFDA cannot reach. Last, so an asset this run has
            # just created is already there to match against.
            got = attach_licensures(conn, _licensures_of(rows))
            written += got["written"]
            written += write_biosimilars(conn, _biosimilars_of(rows))
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, written, [], False, 0)
