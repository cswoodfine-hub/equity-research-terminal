"""Route a trial to the brand whose label covers what it studies.

One molecule can be sold as two products. Tirzepatide is Mounjaro in type 2 diabetes and
Zepbound in obesity and obstructive sleep apnoea: two applications, two labels, two
prices, one ingredient. ClinicalTrials.gov names the ingredient and never the brand, so
all twenty-two tirzepatide studies matched both rows equally and the mapper put every one
of them on whichever it reached first. Mounjaro showed 23bn of revenue and no trials.

The split is in the labels. Mounjaro's indications say type 2 diabetes mellitus and never
obesity; Zepbound's say obesity, overweight and obstructive sleep apnoea and never
diabetes. So a trial goes to the brand whose label covers its condition, which is a fact
both documents state rather than a rule about what the drug is for.

A study listing several conditions is decided on the first, which is the registry's
primary condition, and only falls back to counting the rest when the first names nothing
either label covers. Where both brands cover it, or neither does, the trial is left where
it is and reported as undecided: two brands of one molecule is exactly the case where a
guess would be invisible and wrong. A curated mapping always wins.
"""

from __future__ import annotations

import json
import re

import db

# "Diabetes Mellitus, Type 2" is the registry's inverted form of "type 2 diabetes
# mellitus". Both are tried, so a condition matches a label written either way round.
_PUNCT = re.compile(r"[^a-z0-9 ]+")


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", _PUNCT.sub(" ", (text or "").lower())).strip()


def _variants(condition: str) -> list:
    """The condition as written, and uninverted when it carries a comma."""
    plain = _normalise(condition)
    if not plain:
        return []
    out = [plain]
    if "," in condition:
        head, _, tail = condition.partition(",")
        swapped = _normalise(f"{tail} {head}")
        if swapped:
            out.append(swapped)
    return out


def covers(label_text: str, condition: str) -> bool:
    """Whether a label's indications name this condition."""
    label = _normalise(label_text)
    return bool(label) and any(v in label for v in _variants(condition))


def _conditions(raw) -> list:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw or "[]")
        except ValueError:
            return [raw] if raw else []
        return parsed if isinstance(parsed, list) else [parsed]
    return list(raw or [])


def decide(labels: dict, conditions: list):
    """The asset whose label covers these conditions, or None when it is not one.

    ``labels`` is {asset_id: indications text}. The first condition decides where it
    can; otherwise the brand covering the most conditions wins, and a tie decides
    nothing.
    """
    if not conditions or len(labels) < 2:
        return None
    primary = [aid for aid, text in labels.items() if covers(text, conditions[0])]
    if len(primary) == 1:
        return primary[0]
    scores = {aid: sum(1 for c in conditions if covers(text, c))
              for aid, text in labels.items()}
    best = max(scores.values())
    winners = [aid for aid, n in scores.items() if n == best]
    return winners[0] if best and len(winners) == 1 else None


def base_brand(names: dict):
    """The plain product among a set of brand variants, or None when there is no such
    thing. Rinvoq and Rinvoq LQ are the same drug in two formulations with the same
    indications, so no label can separate their trials; the plain name is the product
    and the qualified one is a presentation of it. Only a name that prefixes every
    other name in the group counts, so Mounjaro and Zepbound produce nothing here.
    """
    candidates = [aid for aid, name in names.items()
                  if name and all(other == name or other.startswith(name + " ")
                                  for other in names.values() if other)]
    return candidates[0] if len(candidates) == 1 else None


def _groups(conn) -> list:
    """Marketed assets that share a generic name inside one company: one molecule, more
    than one product, which is the only case this module has anything to say about."""
    rows = conn.execute(
        """
        SELECT owner_company_id AS cid, LOWER(generic_name) AS generic,
               GROUP_CONCAT(id) AS ids
          FROM assets
         WHERE is_marketed = 1 AND generic_name IS NOT NULL AND generic_name != ''
         GROUP BY owner_company_id, LOWER(generic_name)
        HAVING COUNT(*) > 1
        """).fetchall()
    return [(r["generic"], [int(i) for i in r["ids"].split(",")]) for r in rows]


def split(db_path=None) -> dict:
    """Re-route every trial sitting on a shared-molecule brand to the right one."""
    conn = db.get_connection(db_path)
    moved = undecided = groups = to_base = 0
    try:
        curated = {r["nct_id"] for r in conn.execute(
            "SELECT nct_id FROM trial_asset_map WHERE asset_id IS NOT NULL")}
        for _generic, asset_ids in _groups(conn):
            placeholders = ",".join("?" * len(asset_ids))
            labels = {}
            for asset_id in asset_ids:
                row = conn.execute(
                    "SELECT indications_text FROM labels WHERE asset_id = ?"
                    "  AND indications_text IS NOT NULL"
                    "  ORDER BY effective_time DESC LIMIT 1", (asset_id,)).fetchone()
                if row:
                    labels[asset_id] = row["indications_text"]
            names = {r["id"]: _normalise(r["brand_name"] or "") for r in conn.execute(
                f"SELECT id, brand_name FROM assets WHERE id IN ({placeholders})",
                asset_ids)}
            base = base_brand(names)
            # Two labels can tell two products apart; a base brand can tell a product
            # from its own presentation. With neither there is nothing to say, and the
            # commonest case by far is a group whose members are the same brand filed
            # more than once, where nothing needs saying.
            if len(labels) < 2 and base is None:
                continue
            groups += 1
            trials = conn.execute(
                f"SELECT nct_id, asset_id, conditions FROM trials"
                f"  WHERE asset_id IN ({placeholders})", asset_ids).fetchall()
            for trial in trials:
                if trial["nct_id"] in curated:
                    continue      # the analyst's answer outranks this one
                target = (decide(labels, _conditions(trial["conditions"]))
                          if len(labels) >= 2 else None)
                if target is None and base is not None:
                    # The labels cannot separate a formulation from its parent product,
                    # so the trial belongs to the product.
                    target = base
                    to_base += 1
                if target is None:
                    undecided += 1
                elif target != trial["asset_id"]:
                    conn.execute("UPDATE trials SET asset_id = ? WHERE nct_id = ?",
                                 (target, trial["nct_id"]))
                    moved += 1
        conn.commit()
    finally:
        conn.close()
    return {"groups": groups, "moved": moved, "undecided": undecided,
            "by_base_brand": to_base}
