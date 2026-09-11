"""Loss-of-exclusivity cliff.

For each marketed asset, LOE is the latest of its patent/exclusivity expiries. The
cliff counts products losing exclusivity per year, per company. There is no free
product-level revenue, so this is a count, not a revenue-weighted cliff, and biologics
coverage is partial (Purple Book). Both facts are labelled in the UI.
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib

import db

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"

HORIZON = 10  # number of upcoming years shown as columns


# Orphan exclusivity covers one orphan indication and lapses without the product losing
# anything, so counting it as a cliff overstates the wall. It is 97 of the biologics in
# the universe, which is enough to change the shape of the chart rather than nudge it.
NOT_A_CLIFF = ("orphan exclusivity",)


# A paediatric extension is the same patent plus six months, filed as the patent number
# with "*PED" after it. It is not a patent of its own and must not be read as one.
_PED_SUFFIX = "*PED"


CURATED_COMPOUND = DATA_DIR / "compound_patent.csv"


def curated_compound(conn, path=None) -> dict:
    """{asset_id: patent identifier} for the compound patents an analyst has written down.

    The Orange Book flags several patents per product as "drug substance" and never says
    which of them claims the molecule. Farxiga carries two, Ozempic six, Trikafta twelve.
    Taking the earliest is right for Farxiga, whose 6515117 is dapagliflozin, and wrong
    for Ozempic, whose earliest expires 2026-03-20 while semaglutide's own patent runs to
    2031-12-05. Taking the latest is the reverse. It cannot be derived from the book, so
    it is written down here or it is not claimed.
    """
    source = pathlib.Path(path) if path else CURATED_COMPOUND
    if not source.exists():
        return {}
    with source.open(newline="", encoding="utf-8") as handle:
        rows = [line for line in handle if not line.lstrip().startswith("#")]
    out = {}
    for row in csv.DictReader(rows):
        ticker = (row.get("ticker") or "").strip().upper()
        brand = (row.get("brand") or "").strip()
        patent = (row.get("patent") or "").strip()
        if not (ticker and brand and patent):
            continue
        found = conn.execute(
            """SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                WHERE c.ticker = ? AND LOWER(TRIM(COALESCE(a.brand_name, a.generic_name)))
                      = LOWER(?) LIMIT 1""", (ticker, brand)).fetchone()
        if found:
            out[found["id"]] = patent
    return out


def compound_expiry(rows, identifier=None) -> tuple:
    """(date, identifier) of the patent that holds the molecule, PED included.

    ``identifier`` is the curated compound patent for this asset. Given one, that patent
    sets the date, extended by its own paediatric exclusivity where the book lists one:
    Farxiga's 6515117 expires 2025-10-04 and its "*PED" row runs to 2026-04-04, and April
    2026 is when generics could come.

    Without one this falls back to the latest drug substance patent, which is what the app
    did before the curated file existed. That is not the compound patent either, but it is
    the conservative end of a range the book does not resolve, and guessing the other end
    would put Ozempic out of patent five years early.
    """
    dated = [r for r in rows if r["expiry_date"]]
    if identifier:
        own = [r for r in dated
               if (r["identifier"] or "").split(_PED_SUFFIX)[0] == identifier]
        if own:
            return max(r["expiry_date"] for r in own), identifier
    substance = [r for r in dated if (r["patent_kind"] or "") == "substance"]
    if not substance:
        return None, None
    last = max(substance, key=lambda r: r["expiry_date"])
    return last["expiry_date"], last["identifier"] or None


def for_assets(conn, asset_ids=None, exclude_orphan: bool = False) -> dict:
    """{asset_id: {date, basis, identifier, past}} on one rule, for every caller.

    Computed in Python from the rows rather than as an aggregate, because the compound
    patent is a curated patent number joined to its own paediatric extension and SQL that
    expresses that in every call site is SQL that drifts between them. One query, one
    rule, and the callers that used to take MAX(expiry_date) now agree with the ones
    that did not.

    ``exclude_orphan`` leaves out orphan exclusivity, which holds one indication and not
    the molecule. The cliff chart and the valuation scaffold exclude it, because counting
    it overstates the wall; the per-asset list keeps it and names it, because an analyst
    reading one product wants to see what the date rests on.
    """
    where, params = "", []
    if asset_ids is not None:
        ids = list(asset_ids)
        if not ids:
            return {}
        where = f" WHERE asset_id IN ({', '.join('?' for _ in ids)})"
        params = ids
    grouped: dict = {}
    for row in conn.execute(
            "SELECT asset_id, identifier, expiry_date, patent_kind, protection_type"
            f"  FROM exclusivities{where}", params):
        grouped.setdefault(row["asset_id"], []).append(row)

    curated = curated_compound(conn)
    floors = {r["asset_id"]: r for r in conn.execute(
        "SELECT asset_id, floor_year, loe_date, basis, disclosed_year FROM biologic_loe")}

    today = dt.date.today().isoformat()
    out = {}
    # An asset can carry a statutory floor or a filer's own biosimilar date without a
    # single Purple Book row: Tepezza's 10-K says 2032 and the book lists nothing. Iterating
    # the exclusivity rows alone dropped every such asset, so the floors are folded in.
    wanted = set(grouped) | {aid for aid in floors
                             if asset_ids is None or aid in set(asset_ids)}
    for asset_id in wanted:
        rows = grouped.get(asset_id, [])
        dated = [r for r in rows if r["expiry_date"]
                 and not (exclude_orphan
                          and (r["protection_type"] or "") in NOT_A_CLIFF)]
        latest = max((r["expiry_date"] for r in dated), default=None)
        basis = next((r["protection_type"] for r in sorted(
            dated, key=lambda r: r["expiry_date"], reverse=True)), None)
        compound, identifier = compound_expiry(rows, curated.get(asset_id))
        bio = floors.get(asset_id)
        disclosed = None
        if bio and bio["disclosed_year"] and bio["loe_date"]:
            disclosed = (bio["loe_date"], bio["basis"])
        date, why = effective(latest, basis, bio["floor_year"] if bio else None,
                              compound, disclosed=disclosed)
        if why == "compound patent" and asset_id not in curated:
            why = "drug substance patent"
        out[asset_id] = {"date": date, "basis": why, "identifier": identifier,
                         "past": bool(date and date < today)}
    return out


def merged_loe(loe_max, loe_basis, bio_floor_year):
    """The effective loss of exclusivity: the later of the latest patent or exclusivity on
    file and the biologic 12-year statutory floor. A biologic whose only Purple Book entry
    is a 7-year orphan exclusivity still keeps its market to the 12-year floor, so using
    the orphan date alone understates it. Returns (loe_date, basis)."""
    floor = f"{bio_floor_year}-12-31" if bio_floor_year else None
    if floor and (loe_max is None or floor > loe_max):
        return floor, "statutory floor (12y)"
    return loe_max, loe_basis


def effective(loe_max, loe_basis, bio_floor_year, compound=None,
              disclosed=None):
    """The date a product loses its market, and what sets it.

    A molecule patent gates a generic outright; a method-of-use patent covers one
    indication and can be carved out of a generic's label. So where the Orange Book
    flags a drug substance patent, ``compound`` is the earliest of them with its
    paediatric extension, and that sets the date even when a use patent or a later
    substance patent runs after it. The biologic floor still applies on top.

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
    if compound:
        latest, basis = compound, "compound patent"
    return merged_loe(latest, basis, bio_floor_year)


def _asset_loe(conn):
    """Yield {cid, asset_id, loe, basis} for every asset with exclusivity.

    The date is the one for_assets settles: the compound patent where the book flags a
    drug substance, the filer's own biosimilar date where it states one, the statutory
    floor underneath both.

    Every date here is US FDA. The Orange Book and the Purple Book are the only free
    sources of this, and both publish the United States only, so a product whose US
    protection runs to 2035 may face a generic in Europe years earlier. Nothing in this
    app knows about that, and the UI has to say so rather than imply a worldwide date.
    """
    resolved = for_assets(conn, exclude_orphan=True)
    for row in conn.execute(
            "SELECT a.owner_company_id AS cid, a.id AS asset_id FROM assets a"
            "  JOIN exclusivities e ON e.asset_id = a.id GROUP BY a.id"):
        found = resolved.get(row["asset_id"])
        if found and found["date"]:
            yield {"cid": row["cid"], "asset_id": row["asset_id"],
                   "loe": found["date"], "basis": found["basis"]}


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

    conn = db.get_connection(db_path)
    try:
        resolved = for_assets(conn, [a["asset_id"] for a in assets])
    finally:
        conn.close()

    out = []
    for asset in assets:
        # The molecule patent is what holds the market. Where the book flags one, it
        # sets the date and the use patents behind it are reported separately: a generic
        # can carve a method-of-use claim out of its label, so a use patent running two
        # years past the substance patent does not buy two more years of exclusivity.
        found = resolved.get(asset["asset_id"]) or {}
        loe, basis = found.get("date"), found.get("basis")
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
