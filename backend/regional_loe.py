"""Where outside the US a product sells, and when it loses exclusivity there.

The engine erodes each region on its own date (``forecast.regional_split``). This module
supplies the regions, and every number in them is read, never set:

- **Share.** The product's revenue by geography for its latest reported year, as the filer
  splits it: from the SEC data sets where it tags the split (``asset_revenue_regions``,
  fetched) and from its annual report tables where it only prints them
  (``data/region_revenue.csv``, curated). A split is used only when it is a partition, US
  plus parts that sum to the product's worldwide figure. A filer with a two-way split
  (US and the rest, whatever it calls the rest) has every non-US sale in one region.
- **Date.** The date the filer itself states for that market, from its patent table
  (``data/disclosed_loe_regions.csv``, curated with a verbatim quote per row). Where a
  European region has no stated date, the EU's own statute still sets a floor: ten years of
  data and market protection from the substance's first EU authorisation (Directive
  2001/83/EC, Article 10(1)), read from the EMA. The floor only ever pushes a date later
  than the US one; with no US date there is nothing for it to push.

A region with neither a stated date nor a binding floor follows the US date, which is what
every region did before this module existed.
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib
import re

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
DISCLOSED_REGIONS = DATA_DIR / "disclosed_loe_regions.csv"
CURATED_REVENUE = DATA_DIR / "region_revenue.csv"

LABELS = {"INTL": "Outside the US", "EU": "Europe", "JP": "Japan", "CN": "China",
          "EM": "Emerging markets", "APAC": "Asia Pacific",
          "ESTROW": "Established rest of world", "ROW": "Rest of world", "OTHER": "Other"}
# Which stated date governs a revenue region. A region takes the first of these the filer
# states. Everything outside the US together takes Europe's, the largest market in it for
# every filer here, and says so.
DATE_FOR = {"INTL": ("EU",), "EU": ("EU",), "JP": ("JP",), "CN": ("CN",),
            "APAC": ("JP",), "ESTROW": ("JP",), "EM": ("ROW",), "ROW": ("ROW",)}
# Regions whose sales sit under the EU statute, so its floor applies.
EUROPEAN = {"EU", "INTL"}
PROTECTION_YEARS = 10
_PARTITION_TOLERANCE = 0.03


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _asset_id(conn, ticker: str, brand: str):
    row = conn.execute(
        """SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
            WHERE c.ticker = ? AND LOWER(TRIM(COALESCE(a.brand_name, a.generic_name)))
                  = LOWER(?) AND a.id IN (SELECT asset_id FROM assumptions)
            LIMIT 1""", (ticker, brand)).fetchone()
    if row is None:
        row = conn.execute(
            """SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                WHERE c.ticker = ? AND LOWER(TRIM(COALESCE(a.brand_name, a.generic_name)))
                      = LOWER(?) LIMIT 1""", (ticker, brand)).fetchone()
    return row["id"] if row else None


def _read(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(line for line in handle if not line.lstrip().startswith("#")))


_CACHE: dict = {}


def _rows_cached(path: pathlib.Path) -> list[dict]:
    """The curated file, read once per change to it. A company rollup resolves every
    asset it holds, and reading the file for each one is most of the cost."""
    try:
        stamp = path.stat().st_mtime
    except FileNotFoundError:
        return []
    key = str(path)
    if _CACHE.get(key, (None,))[0] != stamp:
        _CACHE[key] = (stamp, _read(path))
    return _CACHE[key][1]


def disclosed_for(conn, asset_id: int, path=None) -> dict:
    """{region: {"year", "expired", "stated", "basis", "accession"}} the filer states for
    one asset, matched on ticker and brand as the US disclosed file is."""
    asset = conn.execute(
        """SELECT c.ticker, COALESCE(a.brand_name, a.generic_name) name FROM assets a
             JOIN companies c ON c.id = a.owner_company_id WHERE a.id = ?""",
        (asset_id,)).fetchone()
    if asset is None or not asset["name"]:
        return {}
    out: dict = {}
    for row in _rows_cached(pathlib.Path(path) if path else DISCLOSED_REGIONS):
        if ((row.get("ticker") or "").strip().upper() != asset["ticker"]
                or (row.get("brand") or "").strip().lower() != asset["name"].strip().lower()):
            continue
        region = (row.get("region") or "").strip().upper()
        stated = (row.get("loe") or "").strip()
        if not (region and stated):
            continue
        expired = stated.lower() == "expired"
        out[region] = {"year": None if expired else int(stated[:4]), "expired": expired,
                       "stated": stated, "basis": (row.get("basis") or "").strip(),
                       "accession": (row.get("accession") or "").strip()}
    return out


def load_curated_revenue(conn, path=None) -> int:
    """Write the curated regional revenue into ``asset_revenue_regions`` as curated rows,
    in the filer's reporting unit and scaled from millions to units like the fetched rows.
    Returns rows written."""
    written = 0
    for row in _read(pathlib.Path(path) if path else CURATED_REVENUE):
        ticker = (row.get("ticker") or "").strip().upper()
        asset_id = _asset_id(conn, ticker, (row.get("brand") or "").strip())
        if asset_id is None or not (row.get("value") or "").strip():
            continue
        conn.execute(
            """INSERT INTO asset_revenue_regions
                   (asset_id, fiscal_year, member, region, value, unit, source, note,
                    is_curated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(asset_id, fiscal_year, member) DO UPDATE SET
                   region=excluded.region, value=excluded.value, unit=excluded.unit,
                   source=excluded.source, note=excluded.note, is_curated=1,
                   updated_at=datetime('now')""",
            (asset_id, int(row["fiscal_year"]), row["region_label"].strip(),
             row["region"].strip().upper(), float(row["value"]) * 1e6,
             row["unit"].strip(), f"annual report table {row['accession'].strip()}",
             row.get("quote")))
        written += 1
    return written


def split(conn, asset_id: int) -> dict | None:
    """{"year", "total", "parts": [{"region", "member", "value", "source"}]} for the
    latest year whose regional rows partition the product, or None."""
    years = [r["fiscal_year"] for r in conn.execute(
        "SELECT DISTINCT fiscal_year FROM asset_revenue_regions WHERE asset_id = ?"
        " ORDER BY fiscal_year DESC", (asset_id,))]
    for year in years:
        rows = conn.execute(
            """SELECT member, region, value, source, is_curated FROM asset_revenue_regions
                WHERE asset_id = ? AND fiscal_year = ? AND value IS NOT NULL""",
            (asset_id, year)).fetchall()
        # A hand entered split outranks a fetched one for the same year.
        if any(r["is_curated"] for r in rows):
            rows = [r for r in rows if r["is_curated"]]
        us = [r for r in rows if r["region"] == "US"]
        parent = [r for r in rows if r["region"] == "INTL"]
        finer = [r for r in rows if r["region"] not in ("US", "INTL", "OTHER")]
        if len(us) != 1 or len(parent) > 1 or not (parent or finer):
            continue
        world = conn.execute(
            "SELECT value FROM asset_revenue WHERE asset_id = ? AND fiscal_year = ?"
            " AND period = 'FY'", (asset_id, year)).fetchone()
        world = world["value"] if world and world["value"] else None

        def close(a, b):
            return abs(a - b) <= _PARTITION_TOLERANCE * abs(b)

        found = None
        # The finer split where it makes up the whole: checked against the parent the
        # filer also tags, or the product's worldwide figure. Never taken unchecked.
        if finer:
            parts = us + finer
            fits_parent = bool(parent) and close(sum(r["value"] for r in finer), parent[0]["value"])
            fits_world = world is not None and close(sum(r["value"] for r in parts), world)
            if fits_parent or fits_world:
                found = parts
        if found is None and parent:
            parts = us + parent
            if world is None or close(sum(r["value"] for r in parts), world):
                found = parts
        if found is None:
            continue
        total = sum(r["value"] for r in found)
        if total <= 0:
            continue
        # A two-way split is US and everything else, whatever the filer calls the rest.
        two_way = len(found) == 2
        return {"year": year, "total": total,
                "parts": [{"region": ("INTL" if two_way and r["region"] != "US" else r["region"]),
                           "member": r["member"], "value": r["value"],
                           "source": r["source"]} for r in found]}
    return None


def _eu_rows(conn) -> list[dict]:
    """Every originator EU authorisation, normalised once per state of the table. Keyed
    on the database file and what the table holds, never on the connection, whose id is
    reused once it closes."""
    where = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "")
    stamp = tuple(conn.execute("SELECT COUNT(*), MAX(fetched_at) FROM eu_medicines").fetchone())
    key = ("eu", where, stamp)
    if key not in _CACHE:
        for old in [k for k in _CACHE if isinstance(k, tuple) and k[:2] == ("eu", where)]:
            del _CACHE[old]
        _CACHE[key] = [
            {"name": r["name"], "authorised_on": r["authorised_on"],
             "n_name": _norm(r["name"]), "n_substance": _norm(r["active_substance"]),
             "n_inn": _norm(r["inn"])}
            for r in conn.execute(
                """SELECT name, active_substance, inn, authorised_on FROM eu_medicines
                    WHERE authorised_on IS NOT NULL AND is_generic = 0
                      AND is_biosimilar = 0""")]
    return _CACHE[key]


def first_eu_authorisation(conn, asset_id: int) -> dict | None:
    """{"date", "name"} of the substance's earliest EU authorisation, generics and
    biosimilars excluded, or None where the product cannot be found in the EMA data."""
    asset = conn.execute("SELECT brand_name, generic_name FROM assets WHERE id = ?",
                         (asset_id,)).fetchone()
    if asset is None:
        return None
    rows = _eu_rows(conn)
    substances = set()
    brand = _norm(asset["brand_name"])
    for r in rows:
        if brand and r["n_name"] == brand:
            substances.add(r["n_substance"])
    generic = _norm(asset["generic_name"])
    if not substances and generic:
        substances = {r["n_substance"] for r in rows
                      if generic in (r["n_substance"], r["n_inn"])}
    substances.discard("")
    if not substances:
        return None
    matched = [r for r in rows if r["n_substance"] in substances]
    first = min(matched, key=lambda r: r["authorised_on"])
    return {"date": first["authorised_on"], "name": first["name"]}


def for_asset(conn, asset_id: int, disclosed_path=None) -> list[dict]:
    """The engine's ``regions`` input for one asset. Empty where no split is on file."""
    found = split(conn, asset_id)
    if not found:
        return []
    dates = disclosed_for(conn, asset_id, disclosed_path)
    authorised = None
    out = []
    for part in found["parts"]:
        if part["region"] == "US":
            continue
        code = part["region"]
        share = part["value"] / found["total"]
        label = LABELS.get(code, code)
        region = {"region": code, "label": label, "share": share,
                  "share_basis": f"{part['member']} {part['value'] / 1e6:,.0f}mm of "
                                 f"{found['total'] / 1e6:,.0f}mm in FY{found['year']}, "
                                 f"{part['source']}",
                  "year": None, "in_base": False, "basis": None}
        stated = next((dates[key] for key in DATE_FOR.get(code, ()) if key in dates), None)
        if stated:
            which = next(key for key in DATE_FOR.get(code, ()) if key in dates)
            region["year"] = stated["year"]
            region["in_base"] = stated["expired"]
            region["basis"] = (f"{stated['basis'] or 'stated'}, {LABELS.get(which, which)} "
                               f"{stated['stated']}, {stated['accession']}")
            if code == "INTL":
                region["basis"] += "; outside the US taken on the European date"
        if code in EUROPEAN:
            if authorised is None:
                authorised = first_eu_authorisation(conn, asset_id) or {}
            if authorised.get("date"):
                first = dt.date.fromisoformat(authorised["date"])
                floor = first.year + PROTECTION_YEARS
                floor_basis = (f"EU data and market protection, {PROTECTION_YEARS} years from "
                               f"first authorisation of {authorised['name']} on "
                               f"{authorised['date']} (Directive 2001/83/EC, Art. 10(1); EMA)")
                region["floor_year"], region["floor_basis"] = floor, floor_basis
                if region["year"] is not None and not region["in_base"] and floor > region["year"]:
                    region["year"], region["basis"] = floor, floor_basis
        out.append(region)
    return out
