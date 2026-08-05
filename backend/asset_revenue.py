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

import datetime as dt

import db
import fx

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
        # MAX: SQLite rejects an aggregate referenced inside a correlated subquery, and
        # ordering by expiry gives the same row the MAX picked.
        rows = conn.execute(
            """
            SELECT a.id AS asset_id, a.brand_name, a.generic_name, a.modality,
                   a.internal_code,
                   (SELECT MAX(e.expiry_date) FROM exclusivities e
                     WHERE e.asset_id = a.id) AS loe,
                   (SELECT e2.protection_type FROM exclusivities e2
                     WHERE e2.asset_id = a.id
                     ORDER BY e2.expiry_date DESC LIMIT 1) AS basis
              FROM assets a
             WHERE a.owner_company_id = ?
               AND EXISTS (SELECT 1 FROM exclusivities e3 WHERE e3.asset_id = a.id)
            """,
            (company_id,),
        ).fetchall()
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
