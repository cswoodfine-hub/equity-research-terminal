"""One molecule, several brands, and which of them the studies belong to.

Novo sells semaglutide as Ozempic, Wegovy and Rybelsus. All three carry the same generic
name, so a semaglutide trial matched all three equally and the tie fell to row order:
Wegovy is row 589 and Ozempic 597, so Wegovy took every one, including a diabetic eye
disease study and a NASH study that are not obesity trials. Ozempic, on 127bn of revenue,
showed no pipeline at all. 159 molecules are sold under more than one brand by one
company.

Three ways to answer it and two are worse. Leaving the tie to row order is what produced
the blank page. Attributing the study to every sibling triple-counts it, and the inflation
lands hardest on the largest franchises, which is where a pipeline count is read most.

So the study stays on one row and the grouping is written down. ``molecule_id`` points
every sibling at the holder, the holder is the earliest approved of them, and a brand's
page reaches the molecule's studies through the group rather than showing nothing. A
product with no sibling is its own molecule, so every query keeps one shape.

What this deliberately does not do is decide which brand a study belongs to. An obesity
study is Wegovy's and a diabetes study is Ozempic's, but that is a commercial reading of a
registry that states neither, and the honest answer is that the molecule is in Phase 3 and
the brands share it.

The known limit is the generic name it groups on. openFDA gives one ingredient where a
product has several, so Breztri, a triple combination, is filed as "Budesonide" alongside
Rhinocort, a nasal spray, and ten groups mix a combination with a single agent this way.
It costs nothing today, because a combination keeps its own studies through its brand name
and only an intervention naming the bare ingredient is affected, of which there are eleven
and they are ambiguous however they are read. It would cost something the moment a study
names only the shared ingredient. The fix is the active ingredient list, which drugsfda
returns and the approvals fetcher already reads without storing.
"""

from __future__ import annotations

import json

import asset_merge
import db


def ingredients(raw) -> tuple:
    """The active ingredients a product contains, canonical and ordered, from the column.

    Ordered rather than as written, so budesonide with formoterol is the same molecule
    however the payload lists them, and canonicalised so a salt does not split it.
    """
    if not raw:
        return ()
    try:
        names = json.loads(raw)
    except (TypeError, ValueError):
        return ()
    if not isinstance(names, list):
        return ()
    parts = {asset_merge.canonical_generic(str(n)) for n in names if n}
    return tuple(sorted(p for p in parts if len(p) >= 3))


def group_key(owner_company_id, generic_name: str, active_ingredients=None):
    """What makes two brands the same molecule, or None where nothing on file can say.

    The full ingredient list decides it where drugsfda gave one. The generic name alone
    cannot: it holds the first ingredient only, so Breztri, which is budesonide with
    glycopyrrolate and formoterol, reads as "Budesonide" beside Rhinocort, a budesonide
    nasal spray, and the two are not one molecule.

    Where no list is on file the generic name is the fallback, canonical so that a salt
    does not split a molecule: Calquence is filed as both acalabrutinib and acalabrutinib
    maleate.
    """
    if not owner_company_id:
        return None
    parts = ingredients(active_ingredients)
    if parts:
        return (owner_company_id, parts)
    canonical = asset_merge.canonical_generic(generic_name)
    if len(canonical) < 3:
        return None
    return (owner_company_id, (canonical,))


def holder(rows) -> int:
    """The sibling the molecule is keyed on: earliest approved, then oldest row.

    Approval date rather than row order, so the answer is a fact about the drug instead of
    an accident of what was fetched first, and stable when the table is rebuilt.
    """
    def rank(row):
        return (row["first_approval"] or "9999-12-31", row["id"])
    return min(rows, key=rank)["id"]


def assign(db_path=None) -> dict:
    """Point every asset at its molecule. Returns counts.

    Idempotent, and safe to run on every refresh: it is derived wholly from the names and
    approvals on file.
    """
    conn = db.get_connection(db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT a.id, a.owner_company_id, a.generic_name, a.is_marketed,
                      a.active_ingredients,
                      (SELECT MIN(ap.approval_date) FROM approvals ap
                        WHERE ap.asset_id = a.id) AS first_approval
                 FROM assets a""")]
        groups: dict = {}
        for row in rows:
            key = group_key(row["owner_company_id"], row["generic_name"],
                            row["active_ingredients"])
            if key:
                groups.setdefault(key, []).append(row)

        shared = 0
        conn.execute("UPDATE assets SET molecule_id = id")   # a singleton is its own
        for members in groups.values():
            if len(members) < 2:
                continue
            lead = holder(members)
            for member in members:
                conn.execute("UPDATE assets SET molecule_id = ? WHERE id = ?",
                             (lead, member["id"]))
            shared += len(members)
        conn.commit()
        return {"assets": len(rows), "molecules": len(groups),
                "shared_brands": shared,
                "groups_with_siblings": sum(1 for m in groups.values() if len(m) > 1)}
    finally:
        conn.close()


def siblings(conn, asset_id: int) -> list[dict]:
    """The other brands of one asset's molecule, for a page that would otherwise be blank.

    Empty for a product that is its own molecule, which is most of them.
    """
    return [dict(r) for r in conn.execute(
        """SELECT s.id, s.brand_name, s.generic_name,
                  (SELECT COUNT(*) FROM trials t WHERE t.asset_id = s.id) AS trials
             FROM assets a JOIN assets s ON s.molecule_id = a.molecule_id
            WHERE a.id = ? AND s.id <> a.id AND a.molecule_id IS NOT NULL
            ORDER BY s.id""", (asset_id,))]


def molecule_trials(conn, asset_id: int) -> list[dict]:
    """Every study of this asset's molecule, whichever sibling holds it.

    What a product page asks for. Ozempic's own row carries none, and answering "none" to
    a reader looking at a 127bn franchise is worse than saying the molecule's studies sit
    under Wegovy.
    """
    return [dict(r) for r in conn.execute(
        """SELECT t.nct_id, t.phase, t.overall_status, t.title, t.asset_id,
                  (SELECT COALESCE(brand_name, generic_name) FROM assets
                    WHERE id = t.asset_id) AS held_by
             FROM trials t
            WHERE t.asset_id IN (SELECT s.id FROM assets a JOIN assets s
                                   ON s.molecule_id = a.molecule_id WHERE a.id = ?)
            ORDER BY t.phase DESC, t.nct_id""", (asset_id,))]
