"""One product's fact profile, assembled from the tables that already key on the asset.

Everything here is sourced: approval and application number from openFDA, the revenue the
SEC data sets tag, the Orange or Purple Book exclusivity with the biologic 12-year floor
merged in the same way the LOE views do, CMS Medicare demand, DailyMed label history,
efficacy supplements, and any Paragraph IV challenge on file. The market size, peak sales
and competitor set an analyst also wants are in no free source, so they are curated by
hand and stored in ``product_notes``; they travel with the profile but are labelled as
the analyst's own, never as fetched data.

A field with nothing behind it comes back null, so the UI can show "no free data" rather
than a zero or a guess.
"""

from __future__ import annotations

import db
import loe as loe_module

NOTE_FIELDS = ("market_size", "peak_sales", "competitors", "thesis")


def get_notes(conn, asset_id: int) -> dict:
    """The curated fields for one asset, all null when the analyst has written none."""
    row = conn.execute(
        "SELECT market_size, peak_sales, competitors, thesis, updated_at"
        " FROM product_notes WHERE asset_id = ?", (asset_id,)).fetchone()
    if row is None:
        return {f: None for f in NOTE_FIELDS} | {"updated_at": None}
    return dict(row)


def save_notes(db_path, asset_id: int, fields: dict) -> bool:
    """Upsert the curated fields. A blank string is stored as null, so clearing a field
    leaves no empty placeholder behind. Returns False when the asset does not exist."""
    conn = db.get_connection(db_path)
    try:
        if conn.execute("SELECT 1 FROM assets WHERE id = ?", (asset_id,)).fetchone() is None:
            return False
        clean = {f: (str(fields.get(f)).strip() or None) if fields.get(f) is not None
                 else None for f in NOTE_FIELDS}
        conn.execute(
            """
            INSERT INTO product_notes (asset_id, market_size, peak_sales, competitors,
                                       thesis, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(asset_id) DO UPDATE SET
                market_size = excluded.market_size, peak_sales = excluded.peak_sales,
                competitors = excluded.competitors, thesis = excluded.thesis,
                updated_at = datetime('now')
            """,
            (asset_id, clean["market_size"], clean["peak_sales"],
             clean["competitors"], clean["thesis"]))
        conn.commit()
        return True
    finally:
        conn.close()


def _loe(conn, asset_id: int) -> dict:
    """The effective loss of exclusivity for the asset, latest and earliest listed expiry
    with the biologic 12-year floor merged in, the same rule the LOE views use."""
    row = conn.execute(
        """
        SELECT MAX(e.expiry_date) AS loe_max, MIN(e.expiry_date) AS loe_earliest,
               (SELECT x.protection_type FROM exclusivities x
                 WHERE x.asset_id = ? ORDER BY x.expiry_date DESC, x.protection_type
                 LIMIT 1) AS basis,
               (SELECT b.loe_year FROM biologic_loe b WHERE b.asset_id = ?)
                 AS bio_floor_year
          FROM exclusivities e WHERE e.asset_id = ?
        """, (asset_id, asset_id, asset_id)).fetchone()
    date, basis = loe_module.merged_loe(row["loe_max"], row["basis"],
                                        row["bio_floor_year"])
    return {
        "loe": date, "basis": basis,
        "loe_year": int(date[:4]) if date else None,
        "loe_earliest_year": (int(row["loe_earliest"][:4])
                              if row["loe_earliest"] else None),
    }


def _demand(conn, asset_id: int) -> dict | None:
    """Medicare Part D and Part B demand, the latest year with the year before it for
    direction, summed across parts. None when CMS has nothing matched to this drug."""
    rows = conn.execute(
        "SELECT year, SUM(total_spending) AS spend, SUM(total_claims) AS claims,"
        "       SUM(total_beneficiaries) AS benes"
        "  FROM drug_demand WHERE asset_id = ? GROUP BY year ORDER BY year DESC LIMIT 2",
        (asset_id,)).fetchall()
    if not rows:
        return None
    latest = dict(rows[0])
    prior = dict(rows[1]) if len(rows) > 1 else None
    growth = None
    if prior and prior["spend"]:
        growth = (latest["spend"] - prior["spend"]) / prior["spend"]
    return {"year": latest["year"], "spend": latest["spend"],
            "claims": latest["claims"], "beneficiaries": latest["benes"],
            "prior_year": prior["year"] if prior else None,
            "spend_growth": growth}


def product_profile(db_path, ticker: str, asset_id: int) -> dict | None:
    """The full profile for one asset owned by ``ticker``. None when the ticker is unknown
    or the asset is not one of its products, so a mismatched id cannot leak another
    company's data."""
    ticker = ticker.upper()
    conn = db.get_connection(db_path)
    try:
        asset = conn.execute(
            """
            SELECT a.id, a.brand_name, a.generic_name, a.modality, a.internal_code,
                   c.ticker, c.name AS company
              FROM assets a JOIN companies c ON c.id = a.owner_company_id
             WHERE a.id = ? AND c.ticker = ?
            """, (asset_id, ticker)).fetchone()
        if asset is None:
            return None

        approvals = [dict(r) for r in conn.execute(
            "SELECT approval_date, application_number, indication_text, agency, region"
            "  FROM approvals WHERE asset_id = ? ORDER BY approval_date", (asset_id,))]
        revenue = [dict(r) for r in conn.execute(
            "SELECT fiscal_year, value, unit FROM asset_revenue"
            "  WHERE asset_id = ? ORDER BY fiscal_year", (asset_id,))]
        label = conn.execute(
            "SELECT effective_time, indication_count, indications_text, population_text"
            "  FROM labels WHERE asset_id = ? ORDER BY effective_time DESC LIMIT 1",
            (asset_id,)).fetchone()
        supplements = [dict(r) for r in conn.execute(
            "SELECT approval_date, description FROM supplements"
            "  WHERE asset_id = ? AND approval_date IS NOT NULL"
            "  ORDER BY approval_date DESC LIMIT 6", (asset_id,))]
        challenges = [dict(r) for r in conn.execute(
            "SELECT application_number, first_submission FROM patent_challenges"
            "  WHERE asset_id = ? ORDER BY first_submission", (asset_id,))]
        catalysts = [dict(r) for r in conn.execute(
            "SELECT expected_date, catalyst_type, title FROM catalysts"
            "  WHERE asset_id = ? AND expected_date >= date('now')"
            "  ORDER BY expected_date LIMIT 6", (asset_id,))]

        return {
            "asset_id": asset["id"],
            "ticker": asset["ticker"],
            "company": asset["company"],
            "brand": asset["brand_name"],
            "generic": asset["generic_name"],
            "modality": asset["modality"],
            "approvals": approvals,
            "first_approval": approvals[0]["approval_date"] if approvals else None,
            "revenue": revenue,
            "loe": _loe(conn, asset_id),
            "demand": _demand(conn, asset_id),
            "label": dict(label) if label else None,
            "supplements": supplements,
            "supplement_count": len(supplements),
            "challenges": challenges,
            "catalysts": catalysts,
            "notes": get_notes(conn, asset_id),
        }
    finally:
        conn.close()
