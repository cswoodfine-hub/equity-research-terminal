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
PRODUCT_AXIS = "ProductOrService"
GEOGRAPHY_AXIS = "Geographical"

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


def extract_products(rows, adsh: str, ddate: str) -> dict[str, float]:
    """{product member: worldwide revenue} for one filing and one period end.

    ``rows`` are dicts with the num.txt columns. Only full-year durations are read, and
    a value carrying any axis other than product and geography is skipped: a
    product-by-arrangement or product-by-segment row is a slice, not a total.
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
        product = axes.get(PRODUCT_AXIS)
        if not product or _norm(product) in NOT_A_PRODUCT:
            continue
        if set(axes) - {PRODUCT_AXIS, GEOGRAPHY_AXIS}:
            continue
        try:
            value = float(row["value"])
        except (TypeError, ValueError, KeyError):
            continue
        collected.setdefault(product, {})[axes.get(GEOGRAPHY_AXIS)] = value

    out = {}
    for product, by_geography in collected.items():
        total = worldwide(by_geography)
        if total is not None and total > 0:
            out[product] = total
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
                    for member, value in products.items():
                        payload.append({"ticker": ticker, "member": member,
                                        "value": value,
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
                    VALUES (?, ?, ?, 'USD', ?, ?, 0)
                    ON CONFLICT(asset_id, fiscal_year) DO UPDATE SET
                        value=excluded.value, source=excluded.source,
                        note=excluded.note, updated_at=datetime('now')
                     -- A hand entered figure is a correction and outranks the filing.
                     WHERE asset_revenue.is_curated = 0
                    """,
                    (asset_id, row["fiscal_year"], row["value"], SEC_SOURCE,
                     f'{row["form"]} {row["adsh"]}'),
                )
                written += 1
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, written, list(self._errors), False, 0)
