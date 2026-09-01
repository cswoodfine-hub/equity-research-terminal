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


def merged_loe(loe_max, loe_basis, bio_floor_year):
    """The effective loss of exclusivity: the later of the latest patent or exclusivity on
    file and the biologic 12-year statutory floor. A biologic whose only Purple Book entry
    is a 7-year orphan exclusivity still keeps its market to the 12-year floor, so using
    the orphan date alone understates it. Returns (loe_date, basis)."""
    floor = f"{bio_floor_year}-12-31" if bio_floor_year else None
    if floor and (loe_max is None or floor > loe_max):
        return floor, "statutory floor (12y)"
    return loe_max, loe_basis


def effective(loe_max, loe_basis, bio_floor_year, substance_max=None,
              disclosed=None):
    """The date a product loses its market, and what sets it.

    A molecule patent gates a generic outright; a method-of-use patent covers one
    indication and can be carved out of a generic's label. So where the Orange Book
    flags a drug substance patent, that patent sets the date even when a use patent runs
    later, and the biologic floor still applies on top.

    ``disclosed`` is the biosimilar date the filer itself states, as (date, basis), and
    it sets the date outright. Orphan exclusivity on one indication is the same kind of
    thing as a use patent: it holds that indication, not the molecule. Keytruda carries
    a 2031 orphan date on its latest indication while Merck's 10-K says biosimilar
    competition could begin in December 2028 when the compound patent expires, and the
    later of the two is the wrong one. The statutory floor still applies underneath,
    because a disclosure cannot run earlier than the law allows.
    """
    if disclosed and disclosed[0]:
        return merged_loe(disclosed[0], disclosed[1] or "10-K disclosure",
                          bio_floor_year)
    latest, basis = loe_max, loe_basis
    if substance_max:
        latest, basis = substance_max, "drug substance patent"
    return merged_loe(latest, basis, bio_floor_year)


def _asset_loe(conn):
    """Yield (company_id, asset_id, latest_expiry) for every asset with exclusivity.

    Every date here is US FDA. The Orange Book and the Purple Book are the only free
    sources of this, and both publish the United States only, so a product whose US
    protection runs to 2035 may face a generic in Europe years earlier. Nothing in this
    app knows about that, and the UI has to say so rather than imply a worldwide date.
    """
    placeholders = ", ".join("?" for _ in NOT_A_CLIFF)
    # A biosimilar date the filer states in its 10-K is the cliff, ahead of the book's
    # latest expiry: Keytruda's Purple Book runs to 2031 on an orphan indication and
    # Merck says December 2028. One row per asset in biologic_loe, so the aggregate
    # over the join is the row itself.
    return conn.execute(
        f"""
        SELECT a.owner_company_id AS cid, a.id AS asset_id,
               COALESCE(
                 MAX(CASE WHEN b.disclosed_year IS NOT NULL THEN b.loe_date END),
                 MAX(CASE WHEN e.patent_kind = 'substance' THEN e.expiry_date END),
                 MAX(e.expiry_date)) AS loe
          FROM assets a
          JOIN exclusivities e ON e.asset_id = a.id
          LEFT JOIN biologic_loe b ON b.asset_id = a.id
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
            SELECT a.id AS asset_id, a.brand_name, a.generic_name, a.modality,
                   a.internal_code,
                   MAX(e.expiry_date) AS loe_max,
                   -- The earliest listed expiry too, so a small molecule can show the
                   -- range from its first patent (closer to the real cliff) to its last.
                   MIN(e.expiry_date) AS loe_earliest,
                   -- The molecule patents, which is the window that actually gates a
                   -- generic. A method-of-use patent covers one indication and can be
                   -- carved out of a generic label, so Mounjaro's use patent running to
                   -- 2041 is not when Mounjaro loses its market; its substance patents
                   -- expiring 2036 and 2039 are.
                   MAX(CASE WHEN e.patent_kind = 'substance' THEN e.expiry_date END)
                     AS substance_max,
                   MIN(CASE WHEN e.patent_kind = 'substance' THEN e.expiry_date END)
                     AS substance_earliest,
                   MAX(CASE WHEN e.patent_kind = 'use' THEN e.expiry_date END)
                     AS use_max,
                   -- What kind of protection sets the latest date. For biologics it is
                   -- usually orphan exclusivity, which covers one orphan indication and
                   -- does not gate biosimilar entry, so the basis travels with the date.
                   (SELECT x.protection_type FROM exclusivities x
                     WHERE x.asset_id = a.id
                     ORDER BY x.expiry_date DESC, x.protection_type
                     LIMIT 1) AS loe_basis,
                   -- The biologic 12-year statutory floor, when computed; merged below.
                   (SELECT b.floor_year FROM biologic_loe b WHERE b.asset_id = a.id)
                     AS bio_floor_year,
                   -- And the filer's own biosimilar date where the 10-K states one,
                   -- which sets the LOE outright rather than flooring it.
                   (SELECT b.loe_date FROM biologic_loe b WHERE b.asset_id = a.id
                     AND b.disclosed_year IS NOT NULL) AS bio_disclosed_date,
                   (SELECT b.basis FROM biologic_loe b WHERE b.asset_id = a.id
                     AND b.disclosed_year IS NOT NULL) AS bio_disclosed_basis,
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
        # The molecule patent is what holds the market. Where the book flags one, it
        # sets the date and the use patents behind it are reported separately: a generic
        # can carve a method-of-use claim out of its label, so a use patent running two
        # years past the substance patent does not buy two more years of exclusivity.
        loe, basis = effective(
            asset["loe_max"], asset["loe_basis"], asset["bio_floor_year"],
            asset["substance_max"],
            disclosed=(asset["bio_disclosed_date"], asset["bio_disclosed_basis"])
            if asset["bio_disclosed_date"] else None)
        if loe is None or int(loe[:4]) < this_year:
            continue
        item = dict(asset)
        item["loe"] = loe
        item["loe_basis"] = basis
        item["loe_year"] = int(loe[:4])
        # The window a small molecule loses protection over: first molecule patent to
        # last. Without substance flags it stays the whole listed range, which is all
        # that is known for that product.
        earliest = asset["substance_earliest"] or asset["loe_earliest"]
        item["loe_earliest_year"] = int(earliest[:4]) if earliest else None
        item["use_patent_year"] = (int(asset["use_max"][:4])
                                   if asset["use_max"] else None)
        item["substance_year"] = (int(asset["substance_max"][:4])
                                  if asset["substance_max"] else None)
        out.append(item)
    out.sort(key=lambda a: a["loe"])
    return out
