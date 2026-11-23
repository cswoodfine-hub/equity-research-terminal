"""The base rate behind a gate, with the sample it was measured on.

A probability with no denominator cannot be argued with. The book's odds on a readout
come from one published study (data/pos_transitions.csv: BIO, Informa and QLS, 2011 to
2020), cut by therapeutic area, modality, prevalence, biomarker selection and oncology
type, and each cut is a rate over a stated number of phase transitions. ``pos_granular``
turns those into an asset's probability; this hands the rates themselves to a reader who
wants to ask what the odds would be under a different cut, or how thin the sample under a
figure is.

Three reads, kept apart because they are different kinds of evidence:

- **The published table.** Every rate the study prints for a transition, with its n and
  the figure it was transcribed from. A cut under ``pos_granular.MIN_N`` transitions is
  marked thin, as the model treats it, and still shown.
- **One asset's placement.** Where the book has placed an asset at a gate, the chain it
  used, the cuts it qualified for, the ones it refused and why, and the legs either side
  of the next readout. This is ``pos_granular``'s own answer, unaltered.
- **The book's own record.** How the catalysts this book has tracked actually resolved.
  It is a count, not a rate: tens of events, most of them unknown because no result was
  announced inside the window, and the known ones lean positive for the reason
  ``comparable_readouts`` gives. It is here so nobody mistakes the published rate for
  something the book has tested. ``call_log.score`` is where the test will be read once
  enough gates have resolved with a call on record.
"""

from __future__ import annotations

import db
import pos_granular

SOURCE = ("BIO, Informa Pharma Intelligence and QLS Advisors, Clinical Development Success "
          "Rates and Contributing Factors 2011-2020, February 2021")
TRANSITION_LABELS = {"p1_to_p2": "Phase 1 to Phase 2", "p2_to_p3": "Phase 2 to Phase 3",
                     "p3_to_nda": "Phase 3 to filing", "nda_to_approval": "filing to approval"}


def table(transition: str | None = None, cut: str | None = None,
          group: str | None = None, path=None) -> dict:
    """The published rates, narrowed by transition, cut and a group name fragment."""
    wanted = (group or "").strip().lower()
    rows = []
    for (row_cut, row_group, row_transition), value in sorted(
            pos_granular.transitions(path).items()):
        if transition and row_transition != transition:
            continue
        if cut and row_cut != cut:
            continue
        if wanted and wanted not in row_group.lower():
            continue
        rows.append({"cut": row_cut, "group": row_group, "transition": row_transition,
                     "transition_label": TRANSITION_LABELS.get(row_transition),
                     "pos": value["pos"], "n": value["n"],
                     "thin": value["n"] < pos_granular.MIN_N,
                     "figure": value["source"]})
    cuts = sorted({r["cut"] for r in rows})
    return {"source": SOURCE, "window": "1 January 2011 to 30 November 2020",
            "thin_below_n": pos_granular.MIN_N, "cuts": cuts, "rows": rows,
            "note": ("A rate is the share of programmes that advanced from one phase to the "
                     "next. Cuts overlap, so rates from two cuts are not multiplied.")}


def for_asset(db_path, asset_id: int) -> dict | None:
    """The book's placement of one asset and the legs of its next gate. None where the
    asset is not on file. ``placement`` is None where the gate model does not apply: a
    marketed product, an asset before Phase 2, or a company the model does not place."""
    conn = db.get_connection(db_path)
    try:
        asset = conn.execute(
            """SELECT a.id, COALESCE(a.brand_name, a.generic_name, a.internal_code) AS name,
                      a.is_marketed, c.ticker
                 FROM assets a JOIN companies c ON c.id = a.owner_company_id
                WHERE a.id = ?""", (asset_id,)).fetchone()
        if asset is None:
            return None
        import product_areas
        area = product_areas.area_for(conn, asset_id)
        phase = pos_granular._phase(conn, asset_id)
        scalars = pos_granular._base_scalars(conn, asset_id)
        gathered = pos_granular._gather(conn, asset_id, area=area, phase=phase,
                                        scalars=scalars)
        placement = (pos_granular.resolve(conn, asset_id,
                                          **pos_granular._resolve_args(gathered))
                     if gathered is not None else None)
        legs = pos_granular.legs_for_asset(conn, asset_id, area=area, phase=phase,
                                           scalars=scalars)
    finally:
        conn.close()
    return {"asset_id": asset_id, "name": asset["name"], "ticker": asset["ticker"],
            "marketed": bool(asset["is_marketed"]), "area": area, "phase": phase,
            "placement": placement, "next_gate": legs, "source": SOURCE}


def record(db_path=None) -> dict:
    """How this book's own tracked catalysts resolved, as counts by type and outcome."""
    conn = db.get_connection(db_path)
    try:
        resolved = [dict(r) for r in conn.execute(
            """SELECT cat.catalyst_type AS type, res.outcome, COUNT(DISTINCT cat.id) AS n
                 FROM catalyst_resolutions res JOIN catalysts cat ON cat.id = res.catalyst_id
                GROUP BY cat.catalyst_type, res.outcome ORDER BY 1, 2""")]
        read = [dict(r) for r in conn.execute(
            """SELECT phase, outcome, COUNT(*) AS n FROM trial_readouts
                WHERE outcome IN ('positive', 'negative')
                GROUP BY phase, outcome ORDER BY 1, 2""")]
    finally:
        conn.close()
    return {
        "catalysts_resolved": resolved,
        "readouts_read": read,
        "note": ("Counts, not rates. An unknown is a catalyst whose date passed with no "
                 "result the book could find, and announced results lean positive, so "
                 "neither list measures a success rate. The gate calls are scored in "
                 "/calls/scores as they resolve."),
    }
