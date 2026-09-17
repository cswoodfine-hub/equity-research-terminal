"""Curated product revenue, and the exposure it lets the LOE view compute.

No free source carries revenue per product. Companies publish it in the product table
of the 10-K and tag it against a product axis, but the XBRL companyfacts API collapses
those dimensions and returns the consolidated line alone. So the figure is typed in from
the filing, exactly as catalysts are, and everything here is built to be honest about
how little of the portfolio that covers at any moment.

Two rules run through the module:

1. A product with no revenue on file is not worth zero. It is unknown, and it is
   counted in ``uncovered`` rather than dropped, so a thin table reads as thin instead
   of reading as a small cliff.
2. Currency is never converted. A company reporting in DKK is summed in DKK and says
   so; mixing it with USD would produce a number that is wrong in both.
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib

import db
import fx
import loe as loe_module

# Product revenue a filer prints in its annual report or 10-Q tables and does not tag
# against the product axis, so neither the data sets nor the results exhibit reader
# carries it. One row per product and period, each with the accession and a verbatim quote.
CURATED = pathlib.Path(__file__).resolve().parent.parent / "data" / "product_revenue.csv"

HORIZON = 10          # years of cliff, matching loe.HORIZON


def _company_id(conn, ticker: str):
    row = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                       (ticker.upper(),)).fetchone()
    return row["id"] if row else None


def resolve_asset(conn, ticker: str, application_number: str):
    """The asset behind an application number, for the company that owns it.

    The application number lives on ``assets.internal_code``. It is emphatically not
    ``exclusivities.identifier``, which holds patent numbers: Olumiant's rows there read
    8420629 and 9737469, so matching on it would silently bind revenue to whichever
    product happened to share digits with a patent.

    Scoped to the company as well, so a number that resolves under another filer
    attaches nothing rather than landing on the wrong company's cliff.
    """
    company_id = _company_id(conn, ticker)
    if company_id is None:
        return None
    row = conn.execute(
        "SELECT id FROM assets WHERE owner_company_id = ? AND internal_code = ?",
        (company_id, application_number.strip().upper()),
    ).fetchone()
    return row["id"] if row else None


def _dedupe_key(row) -> tuple:
    """What makes two rows the same product filed twice.

    The assets table carries duplicates: the same drug resolved to two ids, so the same
    figure is attached to both and the mix counts it twice. Bristol had Opdivo at 10.05bn
    against two asset ids, Sprycel at 0.49bn against two more, and Opdivo Qvantig against
    an id whose brand had been mis-transcribed as "Ovantig". Its product rows summed to
    56.3bn against 48.2bn reported, so Eliquis printed at 25.7% of revenue when its true
    share is 30.0%, understating exactly the concentration a reader opens this for.

    The test is the first word of the brand and the figure itself: two rows that name the
    same drug and carry the same number to the penny are one filing counted twice. Two
    rows naming the same drug with different figures are left alone, because a filer that
    splits a product across segments is reporting two real amounts, and Opdivo at 10.05bn
    sits beside Opdivo Qvantig at 0.24bn untouched.
    """
    brand = (row.get("brand_name") or row.get("generic_name") or "").strip().lower()
    head = brand.split()[0] if brand.split() else brand
    return (row.get("fiscal_year"), head, round(row.get("value") or 0.0, 2))


def list_revenue(db_path=None, ticker: str = "") -> list[dict]:
    """Every curated figure for one company, newest fiscal year first.

    One row per product per year: see _dedupe_key for what counts as the same product
    filed twice, and why summing them was overstating the base every share is struck on.
    """
    conn = db.get_connection(db_path)
    try:
        company_id = _company_id(conn, ticker)
        if company_id is None:
            return []
        rows = [dict(r) for r in conn.execute(
            """
            SELECT r.id, r.asset_id, r.fiscal_year, r.value, r.unit, r.source, r.note,
                   a.brand_name, a.generic_name, a.internal_code, a.modality
              FROM asset_revenue r JOIN assets a ON a.id = r.asset_id
             WHERE a.owner_company_id = ? AND r.period = 'FY'
             ORDER BY r.fiscal_year DESC, r.value DESC
            """,
            (company_id,),
        )]
    finally:
        conn.close()

    # The fullest telling of the name wins. Where two spellings are the same length,
    # "Opdivo Ovantig" against "Opdivo Qvantig", one is a mis-transcription and nothing
    # in the data says which, so the survivor is arbitrary and only the figure is not.
    kept: dict = {}
    for row in rows:
        key = _dedupe_key(row)
        prior = kept.get(key)
        if prior is None or len(row.get("brand_name") or "") > len(
                prior.get("brand_name") or ""):
            kept[key] = row
    return [row for row in rows if kept.get(_dedupe_key(row)) is row]


# How near a model's base revenue has to sit to a reported figure to be read off it. A
# seed carries millions to one decimal, and a filer reporting in thousands rounds to it:
# Incyte's Minjuvi/Monjuvi is 144,578 thousand and its seed says 144.6.
_BASE_TOLERANCE_MM = 0.05


def shared_lines(conn, company_id: int) -> list[dict]:
    """Modelled products of one company that are valued on one reported revenue line.

    The sum of the parts adds every product that carries assumptions, so a line modelled
    under two assets is counted twice. Two ways it happened, and each is named:

    - ``base_revenue``: a model anchored on a figure another modelled product reports
      and it does not. Fiasp Penfill was valued on Fiasp's 2,818mm DKK, worth about 60
      cents a Novo share a second time, and nebulised Tyvaso on Tyvaso DPI's 1,292.5mm.
    - ``revenue_rows``: two products holding the same figures from one source, equal in
      at least two periods and different in none. The revenue fetcher had filed Tyvaso
      DPI's FY2023 and FY2024 under nebulised Tyvaso as well.

    A figure two products happen to share is not a line. Sanofi reports Rezurock and
    Thymoglobulin at 490mm euro each in 2025, Incyte books Minjuvi/Monjuvi and the
    Olumiant royalty at 144.6mm each, and Pfizer's quarters coincide to the million every
    so often. Each of those products reports the figure itself, or differs in another
    period, so none is named here.
    """
    modelled = {r["id"]: r["name"] for r in conn.execute(
        """SELECT DISTINCT a.id, COALESCE(a.brand_name, a.generic_name) AS name
             FROM assets a JOIN assumptions s ON s.asset_id = a.id
            WHERE a.owner_company_id = ?""", (company_id,))}
    if len(modelled) < 2:
        return []
    marks = ", ".join("?" for _ in modelled)
    rows = [dict(r) for r in conn.execute(
        f"""SELECT asset_id, fiscal_year, period, value, source FROM asset_revenue
             WHERE asset_id IN ({marks}) AND value IS NOT NULL""", list(modelled))]
    found = []

    # A nil is left out on both sides: a pipeline seed's zero base and a year a product
    # reported nothing say nothing about whose line it is.
    full_years = [r for r in rows if r["period"] == "FY" and r["value"] > 0]
    for base in conn.execute(
            f"""SELECT asset_id, value FROM assumptions
                 WHERE asset_id IN ({marks}) AND key = 'base_revenue'
                   AND scenario = 'base' AND indication_id IS NULL AND year IS NULL
                   AND value > 0 ORDER BY asset_id""", list(modelled)):
        near = [r for r in full_years
                if abs(r["value"] / 1e6 - base["value"]) <= _BASE_TOLERANCE_MM]
        if any(r["asset_id"] == base["asset_id"] for r in near):
            continue                  # its own line, whoever else reports the same
        by_other: dict = {}
        for row in near:
            by_other.setdefault(row["asset_id"], []).append(row)
        for other_id, held in sorted(by_other.items()):
            found.append({"kind": "base_revenue", "asset_id": base["asset_id"],
                          "name": modelled[base["asset_id"]], "other_id": other_id,
                          "other_name": modelled[other_id],
                          "periods": sorted((r["fiscal_year"], "FY") for r in held),
                          "source": held[-1]["source"]})

    slots: dict = {}
    for row in rows:
        slots.setdefault((row["source"], row["fiscal_year"], row["period"]),
                         {})[row["asset_id"]] = row["value"]
    tally: dict = {}
    for (source, year, period), values in slots.items():
        ids = sorted(values)
        for i, first in enumerate(ids):
            for second in ids[i + 1:]:
                if values[first] == values[second] == 0:
                    continue
                entry = tally.setdefault((first, second, source),
                                         {"same": [], "differ": 0})
                if values[first] == values[second]:
                    entry["same"].append((year, period))
                else:
                    entry["differ"] += 1
    for (first, second, source), entry in sorted(
            tally.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or "")):
        if len(entry["same"]) >= 2 and not entry["differ"]:
            found.append({"kind": "revenue_rows", "asset_id": first,
                          "name": modelled[first], "other_id": second,
                          "other_name": modelled[second],
                          "periods": sorted(entry["same"]), "source": source})
    return found


def load_curated(conn, path=None) -> int:
    """Write ``data/product_revenue.csv`` into ``asset_revenue`` as curated rows, in units
    rather than the file's millions. Runs on every refresh, so a rebuilt database keeps
    the rows. A product not on file is skipped. Returns rows written."""
    source = pathlib.Path(path) if path else CURATED
    if not source.exists():
        return 0
    with source.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(line for line in handle
                                   if not line.lstrip().startswith("#")))
    written = 0
    for row in rows:
        ticker = (row.get("ticker") or "").strip().upper()
        brand = (row.get("brand") or "").strip()
        value = (row.get("value") or "").strip()
        if not (ticker and brand and value):
            continue
        asset = conn.execute(
            """SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                WHERE c.ticker = ? AND LOWER(TRIM(COALESCE(a.brand_name, a.generic_name)))
                      = LOWER(?) ORDER BY a.is_marketed DESC, a.id LIMIT 1""",
            (ticker, brand)).fetchone()
        if asset is None:
            continue
        conn.execute(
            """INSERT INTO asset_revenue (asset_id, fiscal_year, period, period_end, value,
                                         unit, source, note, is_curated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(asset_id, fiscal_year, period) DO UPDATE SET
                   period_end=excluded.period_end, value=excluded.value,
                   unit=excluded.unit, source=excluded.source, note=excluded.note,
                   is_curated=1, updated_at=datetime('now')""",
            (asset["id"], int(row["fiscal_year"]), (row.get("period") or "FY").strip(),
             (row.get("period_end") or "").strip() or None, float(value) * 1e6,
             (row.get("unit") or "USD").strip(),
             f"filing table {(row.get('accession') or '').strip()}",
             (row.get("quote") or "").strip()))
        written += 1
    return written


def set_revenue(db_path, ticker: str, application_number: str, fiscal_year: int,
                value: float, unit: str = "USD", source: str = "",
                note: str = "") -> int:
    """Upsert one product-year. Raises ValueError when the product cannot be resolved."""
    if value is None or value < 0:
        raise ValueError("revenue must be zero or positive")
    if not 1990 <= int(fiscal_year) <= dt.date.today().year + 1:
        raise ValueError(f"implausible fiscal year {fiscal_year}")
    conn = db.get_connection(db_path)
    try:
        asset_id = resolve_asset(conn, ticker, application_number)
        if asset_id is None:
            raise ValueError(
                f"no product for {application_number} under {ticker.upper()}")
        conn.execute(
            """
            INSERT INTO asset_revenue
                (asset_id, fiscal_year, period, value, unit, source, note, is_curated)
            VALUES (?, ?, 'FY', ?, ?, ?, ?, 1)
            ON CONFLICT(asset_id, fiscal_year, period) DO UPDATE SET
                value=excluded.value, unit=excluded.unit, source=excluded.source,
                note=excluded.note, updated_at=datetime('now')
            """,
            (asset_id, int(fiscal_year), float(value), unit, source, note),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM asset_revenue WHERE asset_id = ? AND fiscal_year = ?"
            "  AND period = 'FY'",
            (asset_id, int(fiscal_year)),
        ).fetchone()
        return row["id"]
    finally:
        conn.close()


def delete_revenue(db_path, revenue_id: int) -> bool:
    conn = db.get_connection(db_path)
    try:
        changed = conn.execute("DELETE FROM asset_revenue WHERE id = ?",
                               (revenue_id,)).rowcount
        conn.commit()
        return bool(changed)
    finally:
        conn.close()


def _latest_revenue(conn, company_id: int) -> dict:
    """{asset_id: {'value','unit','fiscal_year'}} taking each product's latest year."""
    rows = conn.execute(
        """
        SELECT r.asset_id, r.fiscal_year, r.value, r.unit
          FROM asset_revenue r JOIN assets a ON a.id = r.asset_id
         WHERE a.owner_company_id = ? AND r.period = 'FY'
         ORDER BY r.asset_id, r.fiscal_year
        """,
        (company_id,),
    ).fetchall()
    out: dict[int, dict] = {}
    for row in rows:                 # ascending year, so the last write is the latest
        out[row["asset_id"]] = {"value": row["value"], "unit": row["unit"],
                                "fiscal_year": row["fiscal_year"]}
    return out


def build_exposure(db_path=None, ticker: str = "", horizon: int = HORIZON) -> dict:
    """The cliff for one company: what falls off protection each year, and what of it
    carries a revenue figure.

    Every year reports both a revenue subtotal and the products behind it, split into
    covered and uncovered. A year of four products where one has revenue on file is a
    different claim from a year of one product that does, and the two must not render
    the same.

    Orphan exclusivity is excluded. It covers a single orphan indication and lapses
    without the product losing anything, so counting it as a cliff overstates exposure,
    which is the mistake this view exists to avoid.
    """
    today = dt.date.today()
    years = list(range(today.year, today.year + horizon))
    conn = db.get_connection(db_path)
    try:
        company_id = _company_id(conn, ticker)
        if company_id is None:
            return None
        revenue = _latest_revenue(conn, company_id)
        # The basis comes from its own ordered subquery rather than from the grouped
        rows = [dict(r) for r in conn.execute(
            """
            SELECT a.id AS asset_id, a.brand_name, a.generic_name, a.modality,
                   a.internal_code
              FROM assets a
             WHERE a.owner_company_id = ?
               AND EXISTS (SELECT 1 FROM exclusivities e3 WHERE e3.asset_id = a.id)
            """,
            (company_id,),
        )]
        # The one rule, shared with the cliff, the profile and the scaffold. This read
        # the latest expiry of any kind, which put Farxiga on the 2041 wall for a
        # method-of-use patent when its compound patent went in April 2026.
        resolved = loe_module.for_assets(conn, [r["asset_id"] for r in rows])
        for row in rows:
            found = resolved.get(row["asset_id"]) or {}
            row["loe"], row["basis"] = found.get("date"), found.get("basis")
    finally:
        conn.close()

    buckets = {year: {"year": year, "revenue": 0.0, "covered": [], "uncovered": []}
               for year in years}
    later = {"year": None, "revenue": 0.0, "covered": [], "uncovered": []}
    units, total_covered, total_uncovered = set(), 0.0, 0

    for row in rows:
        if not row["loe"] or (row["basis"] or "") == "orphan exclusivity":
            continue
        year = int(row["loe"][:4])
        if year < today.year:
            continue                          # already expired, not ahead
        bucket = buckets.get(year, later)
        known = revenue.get(row["asset_id"])
        product = {"brand_name": row["brand_name"],
                   "generic_name": row["generic_name"],
                   "modality": row["modality"], "application": row["internal_code"],
                   "loe": row["loe"], "basis": row["basis"],
                   "revenue": known["value"] if known else None,
                   "fiscal_year": known["fiscal_year"] if known else None}
        if known:
            bucket["revenue"] += known["value"]
            bucket["covered"].append(product)
            total_covered += known["value"]
            if known["unit"]:
                units.add(known["unit"])
        else:
            bucket["uncovered"].append(product)
            total_uncovered += 1

    ordered = [buckets[year] for year in years] + [dict(later, year="later")]
    for bucket in ordered:
        bucket["products"] = len(bucket["covered"]) + len(bucket["uncovered"])
    covered_count = sum(len(b["covered"]) for b in ordered)
    products = covered_count + total_uncovered
    return {
        "ticker": ticker.upper(),
        "years": years,
        "buckets": ordered,
        # One currency or none. Two would have to be added together to make a total,
        # and no rate in this app is allowed to do that.
        "currency": units.pop() if len(units) == 1 else None,
        "mixed_currency": len(units) > 1,
        "revenue_at_risk": total_covered,
        "products_at_risk": products,
        "products_covered": covered_count,
        "products_uncovered": total_uncovered,
        "coverage": covered_count / products if products else None,
    }


def build_revenue_at_risk(db_path=None, ticker: str = "",
                          horizon: int = HORIZON) -> dict | None:
    """The exposure cliff as shares of tagged product revenue, with a cumulative
    curve out to ``horizon`` years.

    The denominator is the sum of every tagged product's latest-year figure for
    the company, so a share reads "of the revenue we can attribute, this much has
    US protection expiring by then". Products with a known expiry but no revenue
    figure travel in a separate unpriced band as counts, drawn but never imputed.
    Orphan exclusivity is already excluded by the exposure builder.
    """
    exposure = build_exposure(db_path, ticker, horizon)
    if exposure is None:
        return None
    conn = db.get_connection(db_path)
    try:
        company_id = _company_id(conn, ticker)
        revenue = _latest_revenue(conn, company_id)
        reported = conn.execute(
            """
            SELECT fiscal_year, value, unit FROM financials
             WHERE company_id = ? AND metric = 'Revenues' AND period_type = 'FY'
             ORDER BY fiscal_year DESC LIMIT 1
            """,
            (company_id,),
        ).fetchone()
    finally:
        conn.close()

    priced_units = {r["unit"] for r in revenue.values() if r["unit"]}
    priced_total = (sum(r["value"] for r in revenue.values())
                    if len(priced_units) <= 1 and revenue else None)

    share_by_year, unpriced_by_year, cumulative = {}, {}, {}
    running = 0.0
    for bucket in exposure["buckets"]:
        year = bucket["year"]
        expiring = bucket["revenue"] if bucket["covered"] else 0.0
        running += expiring
        share_by_year[str(year)] = (expiring / priced_total
                                    if priced_total else None)
        cumulative[str(year)] = (running / priced_total
                                 if priced_total else None)
        unpriced_by_year[str(year)] = len(bucket["uncovered"])

    five_out = str(exposure["years"][4]) if len(exposure["years"]) > 4 else None
    return {
        **exposure,
        "priced_total": priced_total,
        "priced_products": len(revenue),
        "company_reported": dict(reported) if reported else None,
        "share_by_year": share_by_year,
        "cumulative_share": cumulative,
        "unpriced_by_year": unpriced_by_year,
        "share_5y": cumulative.get(five_out) if five_out else None,
    }


def build_universe_at_risk(db_path=None, horizon: int = HORIZON) -> dict:
    """Revenue at risk across the universe, in shares only.

    Companies report in different currencies and this app holds no FX rate, so
    absolute figures cannot be stacked across the universe without fabricating a
    conversion. Shares of each company's own tagged revenue are unitless and
    comparable, so that is what the universe view carries, with the unpriced
    count beside it as the honesty band.
    """
    conn = db.get_connection(db_path)
    try:
        tickers = [r["ticker"] for r in conn.execute(
            "SELECT ticker FROM companies ORDER BY ticker")]
    finally:
        conn.close()
    # Real rates, so absolutes can be compared across reporting currencies. A company
    # whose currency has no rate keeps a null USD figure and stays in the shares view;
    # nothing is converted at a rate that is not on file.
    rates = fx.latest_usd_rates(db_path)
    rows = []
    for ticker in tickers:
        built = build_revenue_at_risk(db_path, ticker, horizon)
        if built is None:
            continue
        cutoff = built["years"][4] if len(built["years"]) > 4 else None
        unpriced_5y = sum(count for year, count in built["unpriced_by_year"].items()
                          if year != "later" and cutoff and int(year) <= cutoff)
        # At-risk absolute inside 5y = tagged revenue expiring by the cutoff.
        at_risk_native = ((built["share_5y"] or 0) * built["priced_total"]
                          if built["share_5y"] is not None
                          and built["priced_total"] is not None else None)
        rows.append({
            "ticker": built["ticker"],
            "currency": built["currency"],
            "priced_total": built["priced_total"],
            "priced_products": built["priced_products"],
            "share_5y": built["share_5y"],
            "unpriced_5y": unpriced_5y,
            "coverage": built["coverage"],
            "priced_total_usd": fx.to_usd(built["priced_total"], built["currency"],
                                          rates),
            "at_risk_5y_usd": fx.to_usd(at_risk_native, built["currency"], rates),
        })
    return {"rows": rows, "horizon": horizon,
            "fx_as_of": rates.get("as_of"),
            "note": ("shares are of each company's own tagged product revenue; USD "
                     "figures are converted at the ECB reference rate on fx_as_of, and "
                     "a company whose currency has no rate carries a null USD figure")}
