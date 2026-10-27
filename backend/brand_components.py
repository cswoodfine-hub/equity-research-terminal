"""The individual products behind a brand row that names several.

A revenue line is not always one product. Pfizer reports rimegepant as "Nurtec ODT /
Vydura", Merck reports "Gardasil / Gardasil 9", Johnson & Johnson reports four
paliperidone presentations on one line, and each of those arrives as its own asset
because that is how the filing names it. The individual drugs arrive separately, from
openFDA and the NDC directory, under their own single names.

Both rows are right and neither is a duplicate to be merged. The franchise row is the
grain the company reports revenue at, and the model is built on it; the component rows
are the grain the FDA and CMS publish at, and the evidence hangs off them. Merging them
would be wrong in general -- Opdivo and Opdivo Qvantig are genuinely different products
sharing a stem, and folding one into the other would throw away an approval.

What was wrong is that nothing connected them, so evidence sat where nobody looked for
it. Rimegepant's Medicare Part D series -- spending, claims and beneficiaries, which is
how this book prices a retail drug -- is filed against the single-brand row, while the
model and the $1,424mm anchor sit on the combined row. An analyst pricing the combined
row saw no demand data and concluded none existed, and wrote a placeholder instead.
Fourteen of the fifteen combined-brand rows the book models are in that position.

So this resolves one to the other and changes nothing else. Nothing is merged, nothing
is deleted, and a row that names one product resolves to itself.
"""

from __future__ import annotations

import re

import asset_merge

# "Prevnar / Prevenar family" and "Novo Mix And Novo Log Mix" are both one line naming
# two products. The slash is the common form; "and" appears where a source spelled it.
_SPLIT = re.compile(r"\s*/\s*|\s+[Aa]nd\s+")
# Words a reported line adds that are not part of any product's name.
_NOISE = re.compile(r"\b(family|franchise|revenue\s+share|copackaged|co-packaged)\b", re.I)


def parts(brand: str) -> list[str]:
    """The product names inside a combined brand line, in order, without duplicates.

    A name with no separator returns itself, so a caller does not have to ask first.
    """
    cleaned = _NOISE.sub(" ", brand or "").strip()
    out, seen = [], set()
    for piece in _SPLIT.split(cleaned):
        name = " ".join(piece.split())
        key = asset_merge.canonical_brand(name)
        if len(key) > 2 and key not in seen:
            seen.add(key)
            out.append(name)
    return out


def components(conn, asset_id: int) -> list[int]:
    """Sibling assets of the same company that this row's brand names.

    Empty where the brand names one product, or where the named products are not on
    file. The asset itself is never returned: the caller already has it, and including
    it would double-count anything summed across the result.
    """
    row = conn.execute(
        "SELECT id, owner_company_id, brand_name FROM assets WHERE id = ?",
        (asset_id,)).fetchone()
    if row is None:
        return []
    named = parts(row["brand_name"] or "")
    if len(named) < 2:
        return []
    wanted = {asset_merge.canonical_brand(n) for n in named}
    out = []
    for other in conn.execute(
            "SELECT id, brand_name FROM assets"
            "  WHERE owner_company_id = ? AND id <> ? AND brand_name IS NOT NULL",
            (row["owner_company_id"], asset_id)):
        if asset_merge.canonical_brand(other["brand_name"]) in wanted:
            out.append(other["id"])
    return sorted(out)


def demand_rows(conn, asset_id: int) -> list:
    """The CMS demand series for this asset, or for the products its brand names.

    Its own rows win. A combined row is only asked about its components when it carries
    nothing itself, so a line that does file its own demand is never mixed with a
    component's and double counted.
    """
    mine = conn.execute(
        "SELECT * FROM drug_demand WHERE asset_id = ? ORDER BY part, year",
        (asset_id,)).fetchall()
    if mine:
        return mine
    kids = components(conn, asset_id)
    if not kids:
        return []
    marks = ",".join("?" * len(kids))
    return conn.execute(
        f"SELECT * FROM drug_demand WHERE asset_id IN ({marks})"
        "  ORDER BY asset_id, part, year", tuple(kids)).fetchall()
