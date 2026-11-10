"""Which marketed drug each pipeline price and uptake was borrowed from, made visible,
and how far that drug has since moved.

A small biotech's value turns on three rows, and all three are borrowed: of the pipeline
assets' price and peak-uptake rows graded analogue, every one names a marketed comparator
in prose ("comparator estimate: Leqvio (inclisiran), CMS Part D 2024: 14.4m over 2,681
beneficiaries"). The borrowing is real and reasoned, and nothing in the book records it
as a relationship. So when Leqvio's realised price or uptake moves in the next CMS year,
the five assets priced off it do not. Nobody else can make that connection, because
nobody else has the borrowing written down.

This reads it out of the prose and keeps it as a link. Two rules keep the reading
honest.

**Only a row that says it borrowed.** ``evidence.classify`` grades a row analogue on
several cues, and some of them are not comparators: "workbook" and "fitted" grade the
same way, so Casgevy's net price, sourced to a workbook cell, reads analogue with no
comparator in it. The link is taken only where the source carries a borrowing cue, and
the cue list is here rather than in the grader so the two cannot drift apart silently.

**A brand is resolved, never inferred.** A comparator is matched against the brand names
the book holds, in ``assets`` and as CMS spells them in ``drug_demand``, and a row that
names a class ("the approved BCMA cell therapies") or another seed file rather than a
drug is reported as unresolved rather than guessed. A row that names two is two links,
which is right: Milvexian's price is the mean of Eliquis and Xarelto, and both move it.

The drift is the comparator's own realised figures, from CMS: spending per beneficiary
and beneficiaries, in the latest year on file against the year the seed cites. Where the
seed cites the latest year there is no drift yet, and the view says so rather than
printing nil as a finding. CMS lands a year late, so this is an annual signal with a lag,
and the link is the part that is worth having today: it puts the borrowing on the page.
"""

from __future__ import annotations

import re
from collections import defaultdict

import db

KEYS = ("list_price_per_patient", "net_price_per_patient", "penetration_peak_pct")

# The words a source uses when it borrowed. Kept apart from evidence.py's analogue rule
# on purpose: that rule also fires on "workbook" and "fitted", which borrow nothing.
CUE = re.compile(r"(?i)comparator|analogue|\banalog(?:ue)?s?\b|as \S+ carries it|"
                 r"borrowed from|reused from|closest analogue|the price is \S+'s")
CITED_YEAR = re.compile(r"\b(20[12]\d)\b")
MIN_BRAND_CHARS = 4


def _brands(conn) -> dict:
    """{lowercase brand: asset_id}, from the book and from CMS's own spellings."""
    out: dict = {}
    for row in conn.execute(
            "SELECT id, brand_name FROM assets WHERE brand_name IS NOT NULL"):
        if len(row["brand_name"]) >= MIN_BRAND_CHARS:
            out.setdefault(row["brand_name"].lower(), row["id"])
    for row in conn.execute(
            "SELECT DISTINCT asset_id, brand_name FROM drug_demand WHERE brand_name IS NOT NULL"):
        if len(row["brand_name"]) >= MIN_BRAND_CHARS:
            out.setdefault(row["brand_name"].lower(), row["asset_id"])
    return out


def resolve(source: str, brands: dict, own_asset_id: int | None = None) -> list[int]:
    """The comparator asset ids a source names, longest brand first so "Pulmicort
    Respules" is not read as "Pulmicort". A row's own brand is never its comparator."""
    low = source.lower()
    found: list[int] = []
    taken: list[tuple] = []
    for brand in sorted(brands, key=len, reverse=True):
        start = low.find(brand)
        while start >= 0:
            end = start + len(brand)
            if not any(s <= start < e or s < end <= e for s, e in taken):
                taken.append((start, end))
                aid = brands[brand]
                if aid != own_asset_id and aid not in found:
                    found.append(aid)
            start = low.find(brand, end)
    return found


def demand_series(conn, asset_id: int) -> dict:
    """{(part, year): {spend_per_beneficiary, beneficiaries}} for one comparator."""
    out = {}
    for row in conn.execute(
            """SELECT part, year, total_spending, total_beneficiaries FROM drug_demand
                WHERE asset_id = ? AND total_beneficiaries > 0 ORDER BY part, year""",
            (asset_id,)):
        out[(row["part"], row["year"])] = {
            "spend_per_beneficiary": row["total_spending"] / row["total_beneficiaries"],
            "beneficiaries": row["total_beneficiaries"]}
    return out


def drift(series: dict, cited_year: int | None) -> dict | None:
    """How the comparator moved since the year the seed cites, on the part with the
    most beneficiaries in the latest year. None where there is no later year."""
    if not series:
        return None
    latest_year = max(y for _, y in series)
    parts = {p for p, y in series if y == latest_year}
    part = max(parts, key=lambda p: series[(p, latest_year)]["beneficiaries"])
    now = series[(part, latest_year)]
    if cited_year is None or cited_year >= latest_year or (part, cited_year) not in series:
        return {"part": part, "latest_year": latest_year, "cited_year": cited_year,
                "moved": False,
                "reason": ("the seed cites the latest CMS year on file, so there is no "
                           "later year to measure against yet" if cited_year
                           else "the seed does not name the CMS year it took")}
    then = series[(part, cited_year)]
    return {"part": part, "latest_year": latest_year, "cited_year": cited_year,
            "moved": True,
            "price_change": now["spend_per_beneficiary"] / then["spend_per_beneficiary"] - 1,
            "volume_change": now["beneficiaries"] / then["beneficiaries"] - 1}


def build(db_path=None) -> dict:
    """{links, unresolved, totals}. Reads; never writes."""
    conn = db.get_connection(db_path)
    try:
        brands = _brands(conn)
        rows = [dict(r) for r in conn.execute(
            f"""SELECT a.id AS row_id, a.asset_id, a.key, a.source,
                       COALESCE(s.brand_name, s.generic_name, s.internal_code) AS asset,
                       c.ticker
                  FROM assumptions a JOIN assets s ON s.id = a.asset_id
                  JOIN companies c ON c.id = s.owner_company_id
                 WHERE a.key IN ({', '.join('?' for _ in KEYS)}) AND s.is_marketed = 0
                   AND a.scenario = 'base' AND a.source IS NOT NULL""", KEYS)]
        links, unresolved = [], []
        names = {}
        cache: dict = {}
        for r in rows:
            if not CUE.search(r["source"]):
                continue
            found = resolve(r["source"], brands, r["asset_id"])
            cited = CITED_YEAR.search(r["source"])
            cited_year = int(cited.group(1)) if cited else None
            if not found:
                unresolved.append({k: r[k] for k in ("ticker", "asset", "key", "source")})
                continue
            for cid in found:
                if cid not in names:
                    got = conn.execute(
                        "SELECT COALESCE(brand_name, generic_name) AS n FROM assets WHERE id = ?",
                        (cid,)).fetchone()
                    names[cid] = got["n"] if got else str(cid)
                if cid not in cache:
                    cache[cid] = demand_series(conn, cid)
                links.append({"ticker": r["ticker"], "asset_id": r["asset_id"],
                              "asset": r["asset"], "key": r["key"],
                              "comparator_id": cid, "comparator": names[cid],
                              "cited_year": cited_year,
                              "cms_years": sorted({y for _, y in cache[cid]}),
                              "drift": drift(cache[cid], cited_year)})
    finally:
        conn.close()
    with_series = [l for l in links if l["cms_years"]]
    return {
        "links": links, "unresolved": unresolved,
        "totals": {
            "rows_with_a_cue": len(links) + len(unresolved),
            "links": len(links),
            "pipeline_assets_linked": len({l["asset_id"] for l in links}),
            "comparators": len({l["comparator_id"] for l in links}),
            "links_with_a_cms_series": len(with_series),
            "links_that_moved": sum(1 for l in with_series if (l["drift"] or {}).get("moved")),
            "unresolved": len(unresolved),
        },
    }
