"""Loss-of-exclusivity cliff.

For each marketed asset, LOE is the latest of its patent/exclusivity expiries. The
cliff counts products losing exclusivity per year, per company. There is no free
product-level revenue, so this is a count, not a revenue-weighted cliff, and biologics
coverage is partial (Purple Book). Both facts are labelled in the UI.
"""

from __future__ import annotations

import datetime as dt

import db

HORIZON = 10  # number of upcoming years shown as columns


# Orphan exclusivity covers one orphan indication and lapses without the product losing
# anything, so counting it as a cliff overstates the wall. It is 97 of the biologics in
# the universe, which is enough to change the shape of the chart rather than nudge it.
NOT_A_CLIFF = ("orphan exclusivity",)


def _asset_loe(conn):
    """Yield (company_id, asset_id, latest_expiry) for every asset with exclusivity.

    Every date here is US FDA. The Orange Book and the Purple Book are the only free
    sources of this, and both publish the United States only, so a product whose US
    protection runs to 2035 may face a generic in Europe years earlier. Nothing in this
    app knows about that, and the UI has to say so rather than imply a worldwide date.
    """
    placeholders = ", ".join("?" for _ in NOT_A_CLIFF)
    return conn.execute(
        f"""
        SELECT a.owner_company_id AS cid, a.id AS asset_id, MAX(e.expiry_date) AS loe
          FROM assets a
          JOIN exclusivities e ON e.asset_id = a.id
         WHERE COALESCE(e.protection_type, '') NOT IN ({placeholders})
         GROUP BY a.id
        """,
        NOT_A_CLIFF,
    )


def build_loe(db_path=None, horizon: int = HORIZON) -> dict:
    this_year = dt.date.today().year
    years = list(range(this_year, this_year + horizon))
    conn = db.get_connection(db_path)
    try:
        companies = conn.execute(
            "SELECT id, ticker, name FROM companies ORDER BY ticker"
        ).fetchall()
        counts: dict[int, dict] = {}
        for row in _asset_loe(conn):
            loe_year = int(row["loe"][:4])
            if loe_year < this_year:  # already lost exclusivity; not part of the cliff
                continue
            bucket = loe_year if loe_year < this_year + horizon else "later"
            counts.setdefault(row["cid"], {}).setdefault(bucket, 0)
            counts[row["cid"]][bucket] += 1
    finally:
        conn.close()

    rows = []
    for company in companies:
        by_bucket = counts.get(company["id"], {})
        year_counts = {year: by_bucket.get(year, 0) for year in years}
        later = by_bucket.get("later", 0)
        rows.append(
            {
                "ticker": company["ticker"],
                "name": company["name"],
                "years": year_counts,
                "later": later,
                "total": sum(year_counts.values()) + later,
            }
        )
    return {"years": years, "later_label": f"{this_year + horizon}+", "rows": rows}


def loe_detail(db_path, ticker: str) -> list[dict] | None:
    """Upcoming-LOE assets for one company (latest expiry >= this year)."""
    this_year = dt.date.today().year
    conn = db.get_connection(db_path)
    try:
        company = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (ticker.upper(),)
        ).fetchone()
        if company is None:
            return None
        assets = conn.execute(
            """
            SELECT a.brand_name, a.generic_name, a.modality, a.internal_code,
                   MAX(e.expiry_date) AS loe,
                   -- What kind of protection sets that date. For biologics it is
                   -- usually orphan exclusivity, which covers one orphan indication
                   -- and does not gate biosimilar entry, so the basis has to travel
                   -- with the date rather than be inferred from it.
                   (SELECT x.protection_type FROM exclusivities x
                     WHERE x.asset_id = a.id
                     ORDER BY x.expiry_date DESC, x.protection_type
                     LIMIT 1) AS loe_basis,
                   -- A Paragraph IV certification on record is a filed challenge to the
                   -- patent that sets this date, so the expiry may not hold. The join
                   -- is on the asset; the date is the first certification, or null for
                   -- a pre-1984 reference.
                   pc.first_submission AS challenge_date,
                   (pc.asset_id IS NOT NULL) AS challenged
              FROM assets a
              JOIN exclusivities e ON e.asset_id = a.id
              LEFT JOIN patent_challenges pc ON pc.asset_id = a.id
             WHERE a.owner_company_id = ?
             GROUP BY a.id
            """,
            (company["id"],),
        ).fetchall()
    finally:
        conn.close()

    out = []
    for asset in assets:
        loe = asset["loe"]
        if int(loe[:4]) < this_year:
            continue
        item = dict(asset)
        item["loe_year"] = int(loe[:4])
        out.append(item)
    out.sort(key=lambda a: a["loe"])
    return out
