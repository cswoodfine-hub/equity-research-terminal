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
import time
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

# Members that are roll-ups or categories rather than products. They are excluded by
# name as well as by failing to match an asset, so a company that happens to have an
# asset called "Product" cannot pick up a total.
NOT_A_PRODUCT = {
    "product", "producttotal", "otherproducttotal", "other", "othertotal",
    "collaborationandotherrevenue", "collaborationrevenue", "totalrevenue",
    "revenue", "allotherproducts", "otherproducts", "otherrevenue",
}

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
        if not product or _norm(product) in NOT_A_PRODUCT:
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
        except Exception as exc:      # a quarter that is not published yet is normal
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

            for row in rows:
                asset_id = assets.get((row["ticker"], _norm(row["member"])))
                if asset_id is None:
                    continue          # a category or a product we hold no asset for
                conn.execute(
                    """
                    INSERT INTO asset_revenue
                        (asset_id, fiscal_year, value, unit, source, note, is_curated)
                    VALUES (?, ?, ?, ?, ?, ?, 0)
                    ON CONFLICT(asset_id, fiscal_year) DO UPDATE SET
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
        return RefreshResult(self.source, written, list(self._errors), False, 0)
