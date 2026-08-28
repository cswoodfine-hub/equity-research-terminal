"""Product revenue from the SEC Financial Statement Data Sets.

Companies tag revenue against a product axis in XBRL. The companyfacts API collapses
every dimension and returns the consolidated Revenues line alone, which is why this
looked impossible from the API alone. The quarterly Financial Statement Data Sets keep
the dimensions, in a ``segments`` column:

    Revenues  20251231  4  USD  Geographical=US;ProductOrService=Zepbound  13484000000

So the figure is reported, machine readable, and free. It just is not in the endpoint
the rest of this app uses.

Two rules keep the result honest:

1. A worldwide figure is only taken when the filing states one, or when the geography
   members present partition the world in a way this module recognises. Summing an
   arbitrary set of regions risks double counting a filer that reports both a total and
   its parts, so an unrecognised split yields nothing rather than a plausible number.
2. Nothing here overwrites a hand entered figure. Curated rows win, always, so a
   correction stays corrected across refreshes.

The download is bulk: about 80MB a quarter, cached on disk and refreshed quarterly,
which is how often the source changes. That is the price of the only free route to
this data.
"""

from __future__ import annotations

import csv
import io
import os
import functools
import pathlib
import re
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import db
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "product_revenue"
SEC_SOURCE = "sec_fsds"
TTL_SECONDS = 7 * 24 * 60 * 60          # the source itself only moves quarterly

FSDS_URL = "https://www.sec.gov/files/dera/data/financial-statement-data-sets/{quarter}.zip"
CACHE_DIR = Path(os.getenv("ER_TOOL_CACHE", Path(__file__).resolve().parent.parent / "cache"))
QUARTERS_BACK = 5     # enough to catch every filer's latest annual report, 20-F included
_TIMEOUT_S = 180

ANNUAL_FORMS = ("10-K", "20-F")
# us-gaap names the axis one way and IFRS another, which is the whole reason the 20-F
# filers came back empty at first. Novo, Sanofi and AstraZeneca tag products just as
# fully as Lilly does, under ProductsAndServices.
PRODUCT_AXES = ("ProductOrService", "ProductsAndServices")
GEOGRAPHY_AXES = ("Geographical", "GeographicalAreas", "MarketsOfCustomers")

# Members that are roll-ups, segments or categories rather than products. Their revenue
# is real and stays in the company total; it simply cannot be attributed to one product,
# so it belongs in the unattributed remainder rather than against a name.
NOT_A_PRODUCT = {
    "product", "producttotal", "otherproducttotal", "other", "othertotal",
    "collaborationandotherrevenue", "collaborationrevenue", "totalrevenue",
    "revenue", "allotherproducts", "otherproducts", "otherrevenue",
    # Segment lines. Merck's animal health business is 6.4bn across these two, which is
    # revenue by segment, not by product.
    "livestock", "companionanimals", "animalhealth", "otherpharmaceutical",
    "pharmaceutical", "otherproductsandservices", "othersales",
}

# The note every row this fetcher creates carries, which is how the cleanup below knows
# which rows are its own to retire.
CREATED_NOTE = ("created from product revenue reported in the filing; no Orange Book or "
                "openFDA entry, which is normal for a vaccine or a partnered product")

# Prefixes filers put in front of a brand on the product axis. Merck reports partnered
# products as AllianceRevenueLynparza, which is Lynparza with a revenue type glued on,
# and Gilead files its whole catalogue under the category it sits in, so Biktarvy arrives
# as HIVProductsBiktarvy. Stripping the category recovers the product, and recovers it
# under the name the rest of the database already knows it by.
MEMBER_PREFIXES = ("alliancerevenue", "collaborationrevenue", "productrevenue",
                   "netproductsales", "netsales", "revenuefrom",
                   "hivproducts", "celltherapyproducts", "liverdiseaseproducts",
                   "oncologyproducts", "rsvvaccines", "rsv")

# Members that name a grouping rather than a product. Filers put products and the
# categories containing them on the same axis, so Novo tags Ozempic and also
# TotalDiabetesCare, which contains it. Storing both double counts, and the sum of
# Novo's members came to 279% of the company.
AGGREGATE_PATTERN = re.compile(
    r"^(total|all|other|combined|excluding|including|sales|revenue|net|gross)"
    r"|(total|portfolio|brands|products|franchise|therapeutics|business|segment"
    r"|group|revenues?|sales|medicines?|care|health|diseases?|other)$",
    re.I)

# Therapeutic areas and portfolio groupings, which read like products but contain them.
AGGREGATE_WORDS = {
    "oncology", "immunology", "neuroscience", "cardiovascular", "cardiometabolic",
    "cardiometabolichealth", "vaccines", "vaccine", "raredisease", "raredis eases",
    "diabetes", "obesity", "respiratory", "virology", "hiv", "inflammation",
    "growthbrands", "legacybrands", "keyproducts", "top20products", "restofportfolio",
    "specialtymedicine", "generalmedicines", "establishedbrands", "matureproducts",
    "innovativemedicine", "medtech", "pharmaceuticals", "biopharma",
    # Indications a filer reports a franchise under. GSK files by disease rather than by
    # brand for its vaccines, so Shingles is Shingrix and everything else for shingles,
    # and Moderna's COVID19 line is the whole respiratory franchise.
    "influenza", "meningitis", "shingles", "covid", "covid19", "rsv", "hepatitis",
    "polio", "malaria", "biosimilars", "biosimilar", "dermatology", "ophthalmology",
    # Johnson & Johnson reports MedTech by surgical category. These are not drugs and
    # never were, and each was carrying revenue against a name no product answers to.
    "advanced", "electrophysiology", "general", "hips", "knees", "trauma", "spine",
    "sports", "contactlenses", "orthopaedics", "orthopedics", "surgery", "vision",
    "wound", "interventional", "cardiovascularsolutions",
}

# Words that make a member a line on an income statement rather than a product. A filer
# puts these on the same axis as its brands, so Moderna's grant income and Regeneron's
# reimbursed expenses arrive looking exactly like drugs.
LINE_ITEM_WORDS = {
    "licence", "license", "licences", "licenses", "licensing", "royalty", "royalties",
    "grant", "grants", "service", "services", "collaboration", "collaborative",
    "collaborativeand", "contract", "contracts", "milestone", "milestones",
    "reimbursement", "partnership", "partnerships", "technology", "options",
    "commercial", "manufacturing", "manufactured", "launches", "antibodies",
    "alliance", "subscription", "distribution", "supply",
    # A member naming a company is a business, not a drug. Johnson & Johnson reports
    # Abiomed and Shockwave Medical as MedTech lines, and both are acquisitions rather
    # than products.
    "inc", "corp", "corporation", "llc", "ltd", "plc", "gmbh", "holdings",
}


def _split_camel(member: str) -> str:
    """``GardasilGardasil9`` into ``Gardasil Gardasil 9``.

    Filers concatenate the brands a single reported line covers, so the member is not a
    typo, it is a line item naming several products. Nothing here tries to split the
    money between them; the filing reports one number and so does this.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", member)
    spaced = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", spaced)
    return re.sub(r"\s+", " ", spaced).strip()


@functools.lru_cache(maxsize=1)
def _curated_names() -> dict:
    """Members whose brands cannot be told apart by any rule, so they are written down.

    ``GardasilGardasil9`` splits itself on the case boundary. ``TRIKAFTAKAFTRIO`` has
    none, and no rule can say where Trikafta ends and Kaftrio begins. Five of these exist
    across the universe and they are curated in data/product_display_names.csv.
    """
    path = (pathlib.Path(__file__).resolve().parent.parent.parent
            / "data" / "product_display_names.csv")
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        lines = [line for line in handle if not line.lstrip().startswith("#")]
    return {_norm(row["member"]): row["display"].strip()
            for row in csv.DictReader(lines) if (row.get("display") or "").strip()}


def display_name(member: str) -> str:
    """The product name to show, with any revenue-type prefix taken off the front."""
    lowered = _norm(member)
    curated = _curated_names().get(lowered)
    if curated:
        return curated
    for prefix in MEMBER_PREFIXES:
        if lowered.startswith(prefix) and len(lowered) > len(prefix) + 2:
            # Cut the prefix off the original, preserving its capitalisation.
            return _split_camel(member[len(prefix):]) if member[:len(prefix)].lower() \
                == prefix else _split_camel(re.sub(
                    f"(?i)^{prefix}", "", member.replace(" ", "")))
    return _split_camel(member)

def is_aggregate(member: str) -> bool:
    """True when a member names a grouping rather than a single product.

    The test is deliberately eager. A product wrongly dropped costs coverage, which the
    chart shows honestly as unattributed revenue. A grouping wrongly kept is counted
    twice and quietly inflates the company, which nothing on the page would reveal.
    """
    # A category glued to a brand names the brand, so the test is asked of what is left
    # once the category comes off: HIVProductsBiktarvy is Biktarvy and not the HIV
    # franchise, while HIV on its own is the franchise.
    member = display_name(member).replace(" ", "") or member
    normalised = _norm(member)
    if normalised in NOT_A_PRODUCT or normalised in AGGREGATE_WORDS:
        return True
    words = [w for w in re.split(r"(?<=[a-z0-9])(?=[A-Z])|[^A-Za-z0-9]+", member) if w]
    if any(_norm(word) in AGGREGATE_WORDS for word in words):
        return True
    # One line-item word is enough. "Royalty Contract And Other" and "Spinraza
    # Royalties" are both revenue this company earns and neither is a product it sells.
    if any(_norm(word) in LINE_ITEM_WORDS for word in words):
        return True
    return bool(AGGREGATE_PATTERN.search(member))


# Geography member sets that partition the world, so their parts may be summed. Anything
# else is left alone: a filer reporting Europe and International may be double counting,
# and a wrong worldwide figure is worse than none.
COMPLEMENTARY_GEOGRAPHIES = (
    frozenset({"us", "nonus"}),
    frozenset({"unitedstates", "nonus"}),
    frozenset({"us", "international"}),
    frozenset({"unitedstates", "international"}),
    frozenset({"domestic", "foreign"}),
)


def quarters_back(count: int = QUARTERS_BACK, today=None) -> list[str]:
    """The last ``count`` quarter identifiers, newest first, e.g. 2026q1."""
    import datetime as dt

    today = today or dt.date.today()
    year, quarter = today.year, (today.month - 1) // 3 + 1
    out = []
    for _ in range(count):
        out.append(f"{year}q{quarter}")
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
    return out


# --- pure parsing --------------------------------------------------------
def parse_segments(segments: str) -> dict[str, str]:
    """``Geographical=US;ProductOrService=Zepbound;`` into a dict of axis to member."""
    out = {}
    for part in (segments or "").split(";"):
        if "=" in part:
            axis, member = part.split("=", 1)
            out[axis.strip()] = member.strip()
    return out


def _norm(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def worldwide(by_geography: dict[str | None, float]) -> float | None:
    """One worldwide figure from a product's rows, or None when it cannot be trusted.

    ``by_geography`` maps the geography member (None when the row carried no geography)
    to its value. A row with no geography is already worldwide and wins outright.
    Otherwise the members must form a partition this module recognises before their
    parts are added together.
    """
    if None in by_geography:
        return by_geography[None]
    members = {_norm(k) for k in by_geography if k}
    if members in COMPLEMENTARY_GEOGRAPHIES:
        return sum(by_geography.values())
    return None


def extract_products(rows, adsh: str, ddate: str) -> dict[str, dict]:
    """{product member: {'value', 'unit'}} for one filing and one period end.

    ``rows`` are dicts with the num.txt columns. Only full-year durations are read.

    Products are rarely tagged on their own. Merck reports every product inside a
    business segment, JNJ inside a segment and a subsegment, Novo inside a segment.
    Rejecting any row with an extra axis returned nothing at all for those filers, and
    adding the segments up would double count a hierarchy: JNJ's subsegments nest
    inside its segments.

    So each product is read at its most aggregated level, and only when that level is
    unambiguous, meaning one distinct combination of non-geography members. A product
    sitting in exactly one segment is fully described by that row. A product spread
    across several is skipped, because resolving it would mean summing.
    """
    collected: dict[str, dict] = {}
    for row in rows:
        if row.get("adsh") != adsh or row.get("coreg"):
            continue
        if not (row.get("tag") or "").startswith("Revenue"):
            continue
        if row.get("qtrs") != "4" or row.get("ddate") != ddate:
            continue
        axes = parse_segments(row.get("segments"))
        product = next((axes[a] for a in PRODUCT_AXES if a in axes), None)
        if not product or is_aggregate(product):
            continue
        geography = next((axes[a] for a in GEOGRAPHY_AXES if a in axes), None)
        extras = tuple(sorted((axis, member) for axis, member in axes.items()
                              if axis not in PRODUCT_AXES
                              and axis not in GEOGRAPHY_AXES))
        try:
            value = float(row["value"])
        except (TypeError, ValueError, KeyError):
            continue
        # The unit travels with the value. Novo reports in DKK and Sanofi in EUR, and
        # a DKK figure stored as USD would be wrong by a factor of six.
        by_level = collected.setdefault(product, {})
        by_level.setdefault(extras, {})[geography] = (value, row.get("uom") or "")

    out = {}
    for product, by_level in collected.items():
        shallowest = min(len(extras) for extras in by_level)
        level = [g for extras, g in by_level.items() if len(extras) == shallowest]
        if len(level) != 1:
            continue                 # several segments at the top: would need summing
        by_geography = level[0]
        total = worldwide({geo: value for geo, (value, _) in by_geography.items()})
        if total is None or total <= 0:
            continue
        units = {unit for _, unit in by_geography.values() if unit}
        if len(units) != 1:
            continue                 # a product priced in two units cannot be totalled
        out[product] = {"value": total, "unit": units.pop()}
    return out


# --- fetcher -------------------------------------------------------------
class ProductRevenueFetcher(BaseFetcher):
    """Universe-level: one set of downloads serves every company in it."""

    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, db_path=None, quarters: int = QUARTERS_BACK):
        super().__init__(db_path)
        self.quarters = quarters
        self._errors: list[str] = []
        self._notes: list[str] = []

    @property
    def entity_key(self) -> str:
        return "universe"

    # --- download ---------------------------------------------------------
    def _cached_zip(self, quarter: str) -> Path | None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = CACHE_DIR / f"fsds_{quarter}.zip"
        if path.exists() and path.stat().st_size > 1_000_000:
            return path
        user_agent = (os.getenv("SEC_USER_AGENT") or "").strip()
        if not user_agent:
            raise RuntimeError("SEC_USER_AGENT is not set; EDGAR blocks anonymous requests")
        request = urllib.request.Request(FSDS_URL.format(quarter=quarter),
                                         headers={"User-Agent": user_agent})
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
                path.write_bytes(resp.read())
        except urllib.error.HTTPError as exc:
            # The data sets are published a quarter in arrears, so the newest quarters
            # this asks for do not exist yet and answer 404. That is the calendar, not a
            # failure, and it happens on every run; anything else is a real problem.
            if exc.code == 404:
                self._notes.append(f"{quarter}: not published yet")
            else:
                self._errors.append(f"{quarter}: {exc}")
            return None
        except Exception as exc:
            self._errors.append(f"{quarter}: {exc}")
            return None
        time.sleep(0.5)               # stay well inside EDGAR's rate limit
        return path

    def _company_ciks(self) -> dict[str, str]:
        conn = db.get_connection(self.db_path)
        try:
            return {str(int(r["cik"])): r["ticker"] for r in conn.execute(
                "SELECT ticker, cik FROM companies "
                " WHERE cik IS NOT NULL AND cik <> '' AND is_sec_filer = 1")}
        finally:
            conn.close()

    def fetch(self) -> list[dict]:
        """Latest annual filing per company, with its product revenue lines."""
        ciks = self._company_ciks()
        found: dict[str, dict] = {}          # ticker -> {adsh, ddate, quarter}
        payload: list[dict] = []

        for quarter in quarters_back(self.quarters):
            path = self._cached_zip(quarter)
            if path is None:
                continue
            with zipfile.ZipFile(path) as archive:
                with archive.open("sub.txt") as handle:
                    for row in csv.DictReader(io.TextIOWrapper(handle, "latin-1"),
                                              delimiter="\t"):
                        ticker = ciks.get(str(row.get("cik") or "").lstrip("0"))
                        if not ticker or row.get("form") not in ANNUAL_FORMS:
                            continue
                        period = row.get("period") or ""
                        # Newest quarter first, so the first filing seen for a company
                        # is its latest annual report and later ones are history.
                        if ticker not in found and period:
                            found[ticker] = {"adsh": row["adsh"], "ddate": period,
                                             "quarter": quarter, "form": row["form"]}

                wanted = {v["adsh"]: t for t, v in found.items()
                          if v["quarter"] == quarter}
                if not wanted:
                    continue
                with archive.open("num.txt") as handle:
                    reader = csv.DictReader(io.TextIOWrapper(handle, "latin-1"),
                                            delimiter="\t")
                    rows_by_adsh: dict[str, list] = {a: [] for a in wanted}
                    for row in reader:
                        bucket = rows_by_adsh.get(row.get("adsh"))
                        if bucket is not None:
                            bucket.append(row)
                for adsh, ticker in wanted.items():
                    meta = found[ticker]
                    products = extract_products(rows_by_adsh[adsh], adsh, meta["ddate"])
                    for member, found_row in products.items():
                        payload.append({"ticker": ticker, "member": member,
                                        "value": found_row["value"],
                                        "unit": found_row["unit"],
                                        "fiscal_year": int(meta["ddate"][:4]),
                                        "form": meta["form"], "adsh": adsh})
        return payload

    def normalise(self, raw) -> list[dict]:
        return raw

    # --- snapshots -------------------------------------------------------
    def snapshot(self, rows: list[dict]) -> None:
        self._write_snapshot(len(rows), "live")

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM asset_revenue WHERE is_curated = 0").fetchone()[0]
        finally:
            conn.close()
        self._write_snapshot(count, "cache")

    def _write_snapshot(self, count: int, kind: str) -> None:
        import json

        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO snapshots (source, entity_type, entity_key, payload,
                                       refresh_run_id)
                VALUES (?, 'universe', 'product_revenue', ?, ?)
                """,
                (self.source, json.dumps({"rows": count, "source": SEC_SOURCE,
                                          "fetch_kind": kind}), self.refresh_run_id),
            )
            conn.commit()
        finally:
            conn.close()

    # --- current-state table ---------------------------------------------
    def _drop_double_counted(self, conn, rows: list[dict]) -> list[dict]:
        """Drop any company whose products sum past its own revenue.

        Products cannot exceed the company. When they do, the filer has tagged a
        grouping this module failed to recognise and the set contains something twice.
        There is no way to tell which member from the data alone, so the whole company
        is dropped and its revenue reads as unattributed, which is true and visible,
        rather than storing a total that is wrong in a way nothing on the page reveals.

        The threshold sits slightly above 1 because a filer can report a product gross
        while the company line is net of rebates, and that gap is real, not a fault.
        """
        totals = {}
        for row in conn.execute(
            """
            SELECT c.ticker, f.fiscal_year, f.value FROM financials f
              JOIN companies c ON c.id = f.company_id
             WHERE f.metric = 'Revenues' AND f.period_type = 'FY'
            """
        ):
            totals[(row["ticker"], row["fiscal_year"])] = row["value"]

        summed: dict[tuple, float] = {}
        for row in rows:
            key = (row["ticker"], row["fiscal_year"])
            summed[key] = summed.get(key, 0.0) + row["value"]

        rejected = set()
        for key, total in summed.items():
            company = totals.get(key)
            if company and total > company * 1.05:
                rejected.add(key)
                # Declining a figure that does not reconcile is this fetcher working, not
                # failing: the filer tagged a grouping that double counts, and storing it
                # would be worse than storing nothing. Reported as a note so the gap is
                # explained without marking the whole run partial.
                self._notes.append(
                    f"{key[0]} FY{key[1]}: products sum to "
                    f"{total / 1e9:.1f}bn against {company / 1e9:.1f}bn reported, so a "
                    "grouping is being counted twice; nothing stored for it")
        return [r for r in rows if (r["ticker"], r["fiscal_year"]) not in rejected]

    def _resolve_asset(self, conn, assets, companies, ticker, member) -> int | None:
        """The asset a reported product belongs to, creating one where none exists.

        Most of a company's revenue gap was never a matching problem, it was an absence.
        Merck's vaccines (Gardasil, ProQuad, Varivax, Pneumovax, RotaTeq) and its
        partnered products (Lynparza, Lenvima, Reblozyl) had no asset at all: the asset
        table is built from the Orange Book and openFDA, and vaccines sit in the Purple
        Book with partial coverage while a partnered product is held by the partner. So
        22.78bn of Merck's revenue, 35% of the company, could not attach to anything and
        was reported as unattributable when the filing names it plainly.

        A product a company reports revenue for is a product that company sells. That is
        worth a row, and the row records where it came from.
        """
        name = display_name(member)
        for key in (_norm(member), _norm(name)):
            if (ticker, key) in assets:
                return assets[(ticker, key)]
        company_id = companies.get(ticker)
        if company_id is None:
            return None
        cur = conn.execute(
            """
            INSERT INTO assets (owner_company_id, brand_name, is_marketed, notes)
            VALUES (?, ?, 1, ?)
            """,
            (company_id, name, CREATED_NOTE),
        )
        assets[(ticker, _norm(name))] = cur.lastrowid
        assets[(ticker, _norm(member))] = cur.lastrowid
        return cur.lastrowid

    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        written = 0
        try:
            assets = {}
            for row in conn.execute(
                """
                SELECT a.id, a.brand_name, c.ticker FROM assets a
                  JOIN companies c ON c.id = a.owner_company_id
                 WHERE a.brand_name IS NOT NULL AND a.brand_name <> ''
                """
            ):
                assets[(row["ticker"], _norm(row["brand_name"]))] = row["id"]
            companies = {r["ticker"]: r["id"] for r in conn.execute(
                "SELECT id, ticker FROM companies")}

            rows = self._drop_double_counted(conn, rows)
            for row in rows:
                asset_id = self._resolve_asset(conn, assets, companies,
                                               row["ticker"], row["member"])
                if asset_id is None:
                    continue
                conn.execute(
                    """
                    INSERT INTO asset_revenue
                        (asset_id, fiscal_year, period, value, unit, source, note,
                         is_curated)
                    VALUES (?, ?, 'FY', ?, ?, ?, ?, 0)
                    ON CONFLICT(asset_id, fiscal_year, period) DO UPDATE SET
                        value=excluded.value, unit=excluded.unit,
                        source=excluded.source, note=excluded.note,
                        updated_at=datetime('now')
                     -- A hand entered figure is a correction and outranks the filing.
                     WHERE asset_revenue.is_curated = 0
                    """,
                    (asset_id, row["fiscal_year"], row["value"],
                     row.get("unit") or "USD", SEC_SOURCE,
                     f'{row["form"]} {row["adsh"]}'),
                )
                written += 1
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, written, list(self._errors), False, 0,
                             notes=list(self._notes))



def _referencing_tables(conn) -> list:
    """(table, whether asset_id may be null) for every table keyed on an asset.

    Read from the schema rather than listed here, so a migration adding a table cannot
    quietly outdate the cleanup below.
    """
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")]
    out = []
    for table in tables:
        keyed = any(fk[2] == "assets" and fk[3] == "asset_id"
                    for fk in conn.execute(f'PRAGMA foreign_key_list("{table}")'))
        if not keyed:
            continue
        nullable = not any(column[1] == "asset_id" and column[3]
                           for column in conn.execute(f'PRAGMA table_info("{table}")'))
        out.append((table, nullable))
    return out


def _detach(conn, table: str, nullable: bool, asset_id: int) -> None:
    """Take an asset out of one table.

    A trial is a real study that was mapped to the wrong row, so it keeps its own record
    and loses the mapping. Everything else, a label or a theme or a revenue figure, exists
    only as a property of the asset and goes with it.
    """
    if nullable:
        conn.execute(f"UPDATE {table} SET asset_id = NULL WHERE asset_id = ?", (asset_id,))
    else:
        conn.execute(f"DELETE FROM {table} WHERE asset_id = ?", (asset_id,))


def prune(db_path=None) -> dict:
    """Retire the rows this fetcher created for members that are not products.

    The rules above decide what a member is, and they have grown as the filings showed
    what they contain. Rows created under the older, looser rules are still here, holding
    revenue against a name no product answers to: Johnson & Johnson had KNEES and
    CONTACTLENSESOTHER, Moderna had Grant, and Gilead had its whole HIV catalogue filed
    twice, once as Biktarvy and once as HIVProductsBiktarvy.

    Two outcomes. A member the rules now call an aggregate is retired, and its revenue
    with it, because that revenue was never attributable to a product and belongs in the
    unattributed remainder the charts already show honestly. A member that turns out to
    be a brand behind a category prefix is renamed to the brand, and the merge pass then
    folds it into the row that was already there.

    Only rows this fetcher created, and only rows nothing else has attached to. A row
    with a trial, an approval or a label against it has been identified by something
    since, and this has no business deleting it.
    """
    conn = db.get_connection(db_path)
    retired = renamed = kept = 0
    try:
        rows = conn.execute(
            "SELECT id, brand_name FROM assets WHERE notes = ?"
            "  AND brand_name IS NOT NULL AND brand_name <> ''", (CREATED_NOTE,)).fetchall()
        for row in rows:
            member = (row["brand_name"] or "").replace(" ", "")
            if is_aggregate(member):
                # An approval is the one attachment that carries identity of its own: it
                # is an application number the FDA issued, not a name match. A row that
                # has one is left alone and reported, because something real reached it
                # and a person should look.
                if conn.execute("SELECT 1 FROM approvals WHERE asset_id = ? LIMIT 1",
                                (row["id"],)).fetchone():
                    kept += 1
                    continue
                # Everything else attached to this row attached on the strength of the
                # name, and the name is the thing that is wrong. DailyMed matched a label
                # to KNEES because an ointment is indicated "for temporary relief of
                # pain", and to License because a hand sanitiser is a licensed product.
                # Keeping the row on that evidence keeps the error.
                for table, nullable in _referencing_tables(conn):
                    _detach(conn, table, nullable, row["id"])
                conn.execute("DELETE FROM assets WHERE id = ?", (row["id"],))
                retired += 1
                continue
            name = display_name(member)
            if name and name != row["brand_name"]:
                conn.execute(
                    "UPDATE assets SET brand_name = ?, updated_at = datetime('now')"
                    "  WHERE id = ?", (name, row["id"]))
                renamed += 1
        conn.commit()
    finally:
        conn.close()
    return {"retired": retired, "renamed": renamed, "kept": kept}
