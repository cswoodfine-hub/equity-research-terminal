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


def list_revenue(db_path=None, ticker: str = "") -> list[dict]:
    """Every curated figure for one company, newest fiscal year first."""
    conn = db.get_connection(db_path)
    try:
        company_id = _company_id(conn, ticker)
        if company_id is None:
            return []
        return [dict(r) for r in conn.execute(
            """
            SELECT r.id, r.asset_id, r.fiscal_year, r.value, r.unit, r.source, r.note,
                   a.brand_name, a.generic_name, a.internal_code, a.modality
              FROM asset_revenue r JOIN assets a ON a.id = r.asset_id
             WHERE a.owner_company_id = ?
             ORDER BY r.fiscal_year DESC, r.value DESC
            """,
            (company_id,),
        )]
    finally:
        conn.close()


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
                (asset_id, fiscal_year, value, unit, source, note, is_curated)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(asset_id, fiscal_year) DO UPDATE SET
                value=excluded.value, unit=excluded.unit, source=excluded.source,
                note=excluded.note, updated_at=datetime('now')
            """,
            (asset_id, int(fiscal_year), float(value), unit, source, note),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM asset_revenue WHERE asset_id = ? AND fiscal_year = ?",
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
         WHERE a.owner_company_id = ?
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
