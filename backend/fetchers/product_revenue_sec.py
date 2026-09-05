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
    r"|group|revenues?|sales|medicines?|care|health|diseases?|disorders?|other)$",
    re.I)

# Therapeutic areas and portfolio groupings, which read like products but contain them.
AGGREGATE_WORDS = {
    "oncology", "immunology", "neuroscience", "cardiovascular", "cardiometabolic",
    "cardiometabolichealth", "vaccines", "vaccine", "raredisease", "rarediseases",
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


# Revenue a filer books under a name that does not begin with "Revenue". Only these
# two: everything else this filter would otherwise catch is an expense that happens to
# carry a product axis, research and development or cost of goods, and adding those to
# a product's revenue would be worse than missing them. AstraZeneca is the only filer in
# this universe that uses either, and between them they carry 9bn of its revenue.
_ALLIANCE_TAGS = ("AllianceRevenue", "CollaborationRevenue")


def extract_products(rows, adsh: str, ddate: str = None) -> dict[str, dict]:
    """{product member: {'value', 'unit'}} for one filing and one period end.

    ``rows`` are dicts with the num.txt columns. Only full-year durations are read.
    With ``ddate`` given, only that year. ``extract_products_by_year`` below reads every
    year the filing carries, which is what a growth rate needs.

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
        tag = row.get("tag") or ""
        alliance = tag in _ALLIANCE_TAGS
        if not (tag.startswith("Revenue") or alliance):
            continue
        if row.get("qtrs") != "4" or (ddate is not None and row.get("ddate") != ddate):
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
        by_level.setdefault(extras, {}).setdefault(geography, {})[
            "alliance" if alliance else "sales"] = (value, row.get("uom") or "")

    out = {}
    for product, by_level in collected.items():
        shallowest = min(len(extras) for extras in by_level)
        level = [g for extras, g in by_level.items() if len(extras) == shallowest]
        if len(level) != 1:
            continue                 # several segments at the top: would need summing
        by_geography = level[0]
        # Sales and alliance revenue are added, because they are what the filer adds.
        # A partnered medicine earns AstraZeneca two different things and it tags them
        # separately: Enhertu is 977 of RevenueFromSaleOfGoods and 1,798 of
        # AllianceRevenue in FY2025, and its own table calls the 2,775 Product Revenue.
        # Nothing else here is split this way, so nothing else changes.
        total = worldwide({geo: sum(value for value, _ in kinds.values())
                           for geo, kinds in by_geography.items()})
        if total is None or total <= 0:
            continue
        units = {unit for kinds in by_geography.values()
                 for _, unit in kinds.values() if unit}
        if len(units) != 1:
            continue                 # a product priced in two units cannot be totalled
        out[product] = {"value": total, "unit": units.pop()}
    return out


def extract_products_by_year(rows, adsh: str) -> dict[str, dict]:
    """{period end: {product member: {'value', 'unit'}}} for every year the filing states.

    A 10-K carries its comparative years in the same file, tagged the same way against
    the same product axis. Reading only the filing's own period threw those away, and
    threw away with them the one thing a growth rate is made of: what each product did
    the year before. Twelve of the largest companies in this universe had a revenue
    figure and no way to grow it, and the prior year was in the download all along.
    """
    periods = {row.get("ddate") for row in rows
               if row.get("adsh") == adsh and row.get("qtrs") == "4" and row.get("ddate")}
    out = {}
    for period in periods:
        found = extract_products(rows, adsh, period)
        if found:
            out[period] = found
    return out


# How closely a parent has to match the sum of its members, in every cell, before it is
# taken as one. Tight on purpose. Read against a single figure the test is worthless:
# with twenty products on the page, some subset adds up to almost anything, and a loose
# reading of Novo's 2025 column names Ozempic as a grouping of Wegovy and three others.
# What rescues it is that these filers report every line by geography and carry their
# comparative years in the same filing, so one ambiguous equation becomes eighteen
# simultaneous ones. A coincidence does not hold in the US and in China and in Europe
# and in all three years at once, and at this tolerance none does.
_HIERARCHY_TOLERANCE = 0.02

# Fewer cells than this and the test is not constrained enough to trust. Measured: at
# six cells it starts calling Tagrisso a grouping of four smaller AstraZeneca products.
_HIERARCHY_MIN_CELLS = 4


def _cells(rows: list[dict], adsh: str) -> dict:
    """``{(geography, period): {member: value}}`` for one filing.

    The geography detail that ``extract_products`` adds up is exactly what tells a
    parent from a product here, so this reads the rows before that happens.
    """
    out: dict = {}
    for row in rows:
        if row.get("adsh") != adsh or row.get("coreg") or row.get("qtrs") != "4":
            continue
        if not (row.get("tag") or "").startswith("Revenue"):
            continue
        axes = parse_segments(row.get("segments"))
        member = next((axes[a] for a in PRODUCT_AXES if a in axes), None)
        geography = next((axes[a] for a in GEOGRAPHY_AXES if a in axes), None)
        if not member or not geography or is_aggregate(member):
            continue
        try:
            value = float(row["value"])
        except (TypeError, ValueError, KeyError):
            continue
        siblings = tuple(sorted((axis, name) for axis, name in axes.items()
                                if axis not in PRODUCT_AXES and axis not in GEOGRAPHY_AXES))
        out.setdefault((geography, row.get("ddate")), {})[member] = (value, siblings)
    return out


def _subsets_summing_to(pool: list, target: float, depth: int, start: int = 0,
                        running: float = 0.0, chosen: tuple = ()):
    """Every combination of ``pool`` that sums to ``target``, in turn.

    Every one, not the first. A single column cannot tell a real grouping from an
    accident, so the first subset that adds up is as likely to be the accident as the
    answer, and stopping there loses the answer: it is what let Novo's FastActingInsulin
    through while PremixInsulin and LongActingInsulin, both just as real, were missed.
    The caller tests each against the other cells and keeps the one that survives.

    ``pool`` is sorted descending, which lets a branch stop once it has overshot rather
    than enumerating every combination of twenty products four at a time.
    """
    if len(chosen) == depth:
        if abs(running / target - 1) < _HIERARCHY_TOLERANCE:
            yield chosen
        return
    for i in range(start, len(pool)):
        nxt = running + pool[i][1]
        if nxt > target * (1 + _HIERARCHY_TOLERANCE):
            continue                      # too big on its own, but a smaller one may fit
        yield from _subsets_summing_to(pool, target, depth, i + 1, nxt,
                                       chosen + (pool[i][0],))


def grouping_members(rows: list[dict], adsh: str) -> set:
    """Members that are the total of other members, judged across every cell at once.

    ``drop_groupings`` below catches a parent that says so in its name, Gilead's
    HIVProductSales sitting over HIVProductsBiktarvy. Novo's do not: LongActingInsulin
    and Tresiba read as two products of equal standing, and nothing in the text says one
    contains the other. The filer's arithmetic says it, in every geography and every
    year the filing carries, and that is what is read here.

    Only members sharing the parent's segment are candidates, because a grouping is made
    of the lines printed beneath it, not of lines from another part of the business.
    """
    cells = _cells(rows, adsh)
    if len(cells) < _HIERARCHY_MIN_CELLS:
        return set()
    widest = max(cells, key=lambda key: len(cells[key]))
    found = set()
    for parent, (value, siblings) in cells[widest].items():
        if parent in found or value <= 0:
            continue          # a line the filer reports as nil says nothing about a total
        pool = sorted(((name, other) for name, (other, kin) in cells[widest].items()
                       if name != parent and other < value and kin == siblings),
                      key=lambda pair: -pair[1])
        if len(pool) < 2:
            continue
        # Novo reports Ryzodeg and Awigli as nil in the United States, and a cell where
        # the parent is nil cannot test anything but can divide by zero.
        live = [key for key in cells
                if parent in cells[key] and cells[key][parent][0] > 0]
        if len(live) < _HIERARCHY_MIN_CELLS:
            continue
        for depth in (2, 3, 4):
            if any(all(abs(sum(cells[key][name][0] for name in members
                               if name in cells[key]) / cells[key][parent][0] - 1)
                       < _HIERARCHY_TOLERANCE for key in live)
                   for members in _subsets_summing_to(pool, value, depth)):
                found.add(parent)
                break
    return found


# How closely a parent has to match the sum of its members before it is taken as one.
# Gilead's HIV franchise is 20,752 against members summing to 20,252, the difference
# being the products inside it that are not separately tagged, so this cannot be tight.
# It does not need to be: the test is that a member is roughly the sum of several others
# whose names contain its own, which nothing but a grouping satisfies.
_GROUPING_TOLERANCE = 0.06
_GROUPING_SUFFIXES = ("productsales", "products", "productrevenue", "sales", "revenue")


def _stem(member: str) -> str:
    """A member's name with a trailing revenue word removed, for matching its members."""
    text = _norm(member)
    for suffix in _GROUPING_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix) + 2:
            return text[: -len(suffix)]
    return text


def drop_groupings(rows: list[dict]) -> list[dict]:
    """Remove members that are the total of other members in the same filing.

    A filer tags a franchise and the products inside it against the same axis and at the
    same level, so both arrive here looking like products. Gilead tags HIVProductSales at
    20,752 beside HIVProductsBiktarvy at 14,334 and four more that add up to it; United
    Therapeutics tags Tyvaso at 1,878 beside TyvasoDPI at 1,292 and NebulizedTyvaso at
    586, which is exactly it. Keeping both counts the franchise twice, and the guard that
    notices sums past company revenue then threw away the whole company rather than one
    row: five companies had no product revenue at all for that reason, and Gilead's
    twenty-nine billion read as unattributable.

    A parent is found by arithmetic rather than by a list of names: it is a member whose
    value is about the sum of two or more others whose names contain its stem. One member
    inside another is not enough, or Keytruda would be a grouping of Keytruda Qlex.
    """
    kept, dropped = [], set()
    by_key: dict[tuple, list] = {}
    for row in rows:
        by_key.setdefault((row["ticker"], row["fiscal_year"]), []).append(row)
    for key, group in by_key.items():
        for parent in group:
            stem = _stem(parent["member"])
            if len(stem) < 3:
                continue
            children = [r for r in group if r is not parent and stem in _norm(r["member"])]
            if len(children) < 2:
                continue
            total = sum(r["value"] for r in children)
            if parent["value"] > 0 and abs(total - parent["value"]) <= (
                    parent["value"] * _GROUPING_TOLERANCE):
                dropped.add((key, parent["member"]))
    for row in rows:
        if ((row["ticker"], row["fiscal_year"]), row["member"]) not in dropped:
            kept.append(row)
    return kept


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
                    # A grouping has to go before its members are read, not after,
                    # because reading it is what makes the year double count.
                    groupings = grouping_members(rows_by_adsh[adsh], adsh)
                    by_year = extract_products_by_year(rows_by_adsh[adsh], adsh)
                    for period, products in by_year.items():
                        for member, found_row in products.items():
                            if member in groupings:
                                continue
                            payload.append({"ticker": ticker, "member": member,
                                            "value": found_row["value"],
                                            "unit": found_row["unit"],
                                            "fiscal_year": int(period[:4]),
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

            rows = self._drop_double_counted(conn, drop_groupings(rows))
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
