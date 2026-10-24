"""Which of a product's indications its label already covers.

Separate from both callers because both need it and neither can import the other:
``assumptions.load`` tags the indications it hands the engine, and ``forecast_view``
refuses a gate on an indication already approved. The rule has to be the same in both
places or a readout could be priced as an expansion by one and dismissed by the other.

The book cannot answer this from the phase. A phase comes from the trials, trials carry
on after an approval, and an approved indication therefore sits at Phase 3 for as long
as anyone is still studying it. Omvoh's Crohn's disease readout stood as a pending
expansion while the label had read "moderately to severely active Crohn's disease in
adults" since January 2025.
"""

from __future__ import annotations

import datetime as dt

import indication_mapping

_LABEL_DAY = "%b %d, %Y"       # the labels table writes "Oct 22, 2026"


def current_label(conn, asset_id: int):
    """The newest label's indications text, or None.

    The date is parsed rather than sorted in SQL. ``effective_time`` is text in the
    file's own format, so an ORDER BY on it sorts alphabetically: August beats October
    and December beats January, which picks a label at random among a product's
    revisions. A stale label is the one case that matters, because an indication
    approved since would read as unapproved.
    """
    best, best_day = None, None
    for row in conn.execute(
            "SELECT effective_time, indications_text FROM labels"
            "  WHERE asset_id = ? AND indications_text IS NOT NULL", (asset_id,)):
        try:
            day = dt.datetime.strptime((row["effective_time"] or "").strip(),
                                       _LABEL_DAY).date()
        except (ValueError, TypeError):
            day = None
        if best is None or (day and (best_day is None or day > best_day)):
            best, best_day = row["indications_text"], day
    return best


def for_asset(conn, asset_id: int) -> set:
    """The asset_indication ids this product is already approved in.

    Two tests, both conservative, and both failing towards treating an indication as
    unapproved rather than silently removing a gate or a layer.

    Phase 4 is a post-marketing study, which is what the phase means. And an indication
    whose name sits inside the label's own indications text is approved, compared on
    ``indication_mapping.tokens``, the vocabulary the book already matches studies to
    diseases with. That comparison separates the paediatric readouts from the adult ones
    with no extra rule: "Crohn Disease" is found inside "moderately to severely active
    Crohn's disease in adults", and "Pediatric Crohn's disease", which carries a token
    the adults-only label does not, is not.
    """
    pairs = conn.execute(
        "SELECT ai.id, ai.phase, i.name FROM asset_indications ai"
        "  JOIN indications i ON i.id = ai.indication_id"
        " WHERE ai.asset_id = ?", (asset_id,)).fetchall()
    if not pairs:
        return set()
    said = set(indication_mapping.tokens(current_label(conn, asset_id) or ""))
    out = set()
    for pair in pairs:
        if (pair["phase"] or "") == "Phase 4":
            out.add(pair["id"])
            continue
        mine = set(indication_mapping.tokens(pair["name"] or ""))
        if mine and said and mine <= said:
            out.add(pair["id"])
    return out


def indication_ids(conn, asset_id: int) -> set:
    """The same answer keyed on the indication rather than on the pair, which is what
    the engine's per-indication entries carry."""
    approved = for_asset(conn, asset_id)
    if not approved:
        return set()
    marks = ",".join("?" * len(approved))
    return {r[0] for r in conn.execute(
        f"SELECT indication_id FROM asset_indications WHERE id IN ({marks})",
        tuple(sorted(approved)))}
