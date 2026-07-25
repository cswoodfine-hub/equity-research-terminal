"""Reads over the CMS demand time series.

One drug is one asset and one part (a Part D oral or a Part B infusion), carrying up to
five years of spending, claims and beneficiaries. company_demand rolls the rows up into
one record per drug: the latest year's figures, the year before for direction, and the
whole series for a sparkline. Sorted by latest spending, so the drugs that move the
Medicare book lead.
"""

from __future__ import annotations

import db

PART_LABEL = {"D": "Part D, retail", "B": "Part B, clinic"}


def company_demand(db_path, ticker: str) -> list[dict] | None:
    conn = db.get_connection(db_path)
    try:
        company = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (ticker.upper(),)
        ).fetchone()
        if company is None:
            return None
        rows = conn.execute(
            """
            SELECT d.asset_id, d.part, d.year, d.total_spending, d.total_claims,
                   d.total_beneficiaries, d.brand_name,
                   a.brand_name AS asset_brand, a.generic_name
              FROM drug_demand d
              JOIN assets a ON a.id = d.asset_id
             WHERE a.owner_company_id = ?
             ORDER BY d.asset_id, d.part, d.year
            """,
            (company["id"],),
        ).fetchall()
    finally:
        conn.close()

    drugs: dict[tuple, dict] = {}
    for row in rows:
        key = (row["asset_id"], row["part"])
        drug = drugs.setdefault(key, {
            "brand": row["brand_name"] or row["asset_brand"],
            "generic": row["generic_name"],
            "part": row["part"], "part_label": PART_LABEL.get(row["part"], row["part"]),
            "series": []})
        drug["series"].append({"year": row["year"],
                               "spending": row["total_spending"],
                               "claims": row["total_claims"],
                               "beneficiaries": row["total_beneficiaries"]})

    out = []
    for drug in drugs.values():
        series = drug["series"]
        latest, prior = series[-1], (series[-2] if len(series) > 1 else None)
        drug["latest_year"] = latest["year"]
        drug["spending"] = latest["spending"]
        drug["claims"] = latest["claims"]
        drug["beneficiaries"] = latest["beneficiaries"]
        drug["prior_spending"] = prior["spending"] if prior else None
        out.append(drug)
    # The drugs that move the book first; a null spend sorts last.
    out.sort(key=lambda d: d["spending"] or 0, reverse=True)
    return out
