"""The universe read along the modality axis rather than the ticker axis.

Every other view in this terminal answers a question about one company. The questions
that move a sector do not respect that shape: whether the editors are being repriced,
whether cell therapy is consolidating, who else is exposed to the readout that just
failed. Those span companies and are invisible from a company page.

So this aggregates `asset_themes` up to the theme: how many programmes carry it, whose
they are, how far along they are, and what has moved in it lately. The stage mix is the
part worth reading. A theme that is all preclinical and Phase 1 is a story about capital
and patience; one with marketed products in it is a story about revenue, and the same
headline means different things to each.

Nothing here estimates. A theme with no marketed product reports none rather than a
projection, and a company whose assets carry no theme simply does not appear.
"""

from __future__ import annotations

import datetime as dt

import db
import themes

# Ordered as a pipeline reads, so the stage mix is a shape rather than a bag of labels.
PHASE_ORDER = ("Phase 1", "Phase 1/2", "Phase 2", "Phase 2/3", "Phase 3", "Phase 4")

# Marketed sits above every phase, since an approved drug has passed all of them, and a
# programme with no trial on file sits below, since absence of evidence is not stage 1.
STAGE_ORDER = ("No trial on file",) + PHASE_ORDER + ("Marketed",)


def _phase_rank(phase: str | None) -> int:
    """Where a phase sits in the pipeline. Used both to pick an asset's furthest trial
    and to order the stage mix, so the two always agree."""
    try:
        return PHASE_ORDER.index(phase or "")
    except ValueError:
        return -1


def _stage_rank(label: str) -> int:
    try:
        return STAGE_ORDER.index(label)
    except ValueError:
        return -1


def coverage(db_path=None) -> dict:
    """How much of the universe the modality axis actually reaches.

    This has to be shown next to the counts, because the counts are floors rather than
    totals and the difference is the whole reading. Gene editing shows one asset while
    Intellia, Beam, CRISPR and Prime each run several, since their programmes are named
    BEAM-101 and CTX112 and no field we hold says what those are: the registry gives a
    dosing instruction where a description would be, and a code-numbered asset with no
    label makes no claim about itself. Reported as a gap, never filled with a guess.
    """
    conn = db.get_connection(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        tagged = conn.execute(
            "SELECT COUNT(DISTINCT asset_id) FROM asset_themes").fetchone()[0]
        # A company with programmes but no theme on any of them is the visible edge of
        # the gap, and is worth naming rather than leaving as a missing row.
        blind = [dict(r) for r in conn.execute(
            """
            SELECT c.ticker, COUNT(a.id) AS assets
              FROM companies c JOIN assets a ON a.owner_company_id = c.id
             WHERE NOT EXISTS (SELECT 1 FROM asset_themes t WHERE t.asset_id = a.id)
             GROUP BY c.ticker HAVING COUNT(a.id) >= 3
                  AND NOT EXISTS (SELECT 1 FROM asset_themes t2
                                    JOIN assets a2 ON a2.id = t2.asset_id
                                   WHERE a2.owner_company_id = c.id)
             ORDER BY assets DESC LIMIT 12
            """)]
    finally:
        conn.close()
    return {"assets": total, "tagged": tagged,
            "untagged": total - tagged, "companies_untagged": blind}


def build(db_path=None, days: int = 90, today=None) -> list:
    """One row per theme, ordered by how many companies are in it.

    Company count leads rather than asset count, because a theme one company runs forty
    programmes in is a company story, and a theme eight companies run three each in is a
    sector one. The second is what this view exists to find.
    """
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=days)).isoformat()
    conn = db.get_connection(db_path)
    try:
        rows = []
        for theme in themes.theme_names():
            assets = conn.execute(
                """
                SELECT a.id, a.brand_name, a.generic_name, a.internal_code,
                       a.is_marketed, c.ticker, c.name AS company
                  FROM asset_themes t
                  JOIN assets a ON a.id = t.asset_id
                  JOIN companies c ON c.id = a.owner_company_id
                 WHERE t.theme = ?
                """, (theme,)).fetchall()
            if not assets:
                continue
            ids = [a["id"] for a in assets]
            marks = ",".join("?" * len(ids))

            # The most advanced phase each programme has reached. A drug in Phase 1 and
            # Phase 3 at once is a Phase 3 programme; counting every trial would let a
            # company with many small studies dominate the shape.
            best: dict = {}
            for r in conn.execute(
                f"SELECT asset_id, phase FROM trials WHERE asset_id IN ({marks})", ids):
                if _phase_rank(r["phase"]) > _phase_rank(best.get(r["asset_id"])):
                    best[r["asset_id"]] = r["phase"]
            stage: dict = {}
            for asset in assets:
                if asset["is_marketed"]:
                    label = "Marketed"
                else:
                    label = best.get(asset["id"]) or "No trial on file"
                stage[label] = stage.get(label, 0) + 1

            movement = conn.execute(
                f"""
                SELECT COUNT(*) FROM changes ch
                 WHERE ch.entity_type = 'trial' AND ch.detected_at >= ?
                   AND ch.entity_key IN (SELECT nct_id FROM trials
                                          WHERE asset_id IN ({marks}))
                """, (cutoff, *ids)).fetchone()[0]

            by_company: dict = {}
            for asset in assets:
                by_company[asset["ticker"]] = by_company.get(asset["ticker"], 0) + 1
            leaders = sorted(by_company.items(), key=lambda kv: (-kv[1], kv[0]))

            rows.append({
                "theme": theme,
                "parent": themes.PARENTS.get(theme),
                "assets": len(assets),
                "companies": len(by_company),
                "marketed": sum(1 for a in assets if a["is_marketed"]),
                "stage_mix": dict(sorted(stage.items(),
                                         key=lambda kv: -_stage_rank(kv[0]))),
                "changes": movement,
                "top_companies": [{"ticker": t, "assets": n} for t, n in leaders[:6]],
            })
    finally:
        conn.close()
    return sorted(rows, key=lambda r: (-r["companies"], -r["assets"]))


def detail(theme: str, db_path=None, days: int = 90, today=None) -> dict:
    """Every programme carrying one theme, with the evidence for the tag.

    The evidence travels with the row because the tag is a judgement made from text, and
    an analyst who does not believe "this is a radioligand" needs the phrase that said
    so without leaving the page.
    """
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=days)).isoformat()
    conn = db.get_connection(db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            """
            SELECT c.ticker, c.name AS company, a.id AS asset_id,
                   COALESCE(a.brand_name, a.generic_name, a.internal_code) AS name,
                   a.is_marketed, t.evidence, t.source
              FROM asset_themes t
              JOIN assets a ON a.id = t.asset_id
              JOIN companies c ON c.id = a.owner_company_id
             WHERE t.theme = ?
             ORDER BY a.is_marketed DESC, c.ticker
            """, (theme,))]
        for row in rows:
            best = conn.execute(
                "SELECT phase, overall_status, COUNT(*) n FROM trials"
                " WHERE asset_id = ? GROUP BY phase, overall_status", (row["asset_id"],)
            ).fetchall()
            row["phase"] = max((b["phase"] for b in best),
                               key=_phase_rank, default=None)
            row["trials"] = sum(b["n"] for b in best)

        moves = [dict(r) for r in conn.execute(
            """
            SELECT ch.entity_key AS nct_id, ch.change_type, ch.old_value, ch.new_value,
                   ch.significance, ch.detected_at, c.ticker,
                   COALESCE(a.brand_name, a.generic_name, a.internal_code) AS name
              FROM changes ch
              JOIN trials tr ON tr.nct_id = ch.entity_key
              JOIN assets a ON a.id = tr.asset_id
              JOIN asset_themes th ON th.asset_id = a.id
              LEFT JOIN companies c ON c.id = a.owner_company_id
             WHERE th.theme = ? AND ch.entity_type = 'trial' AND ch.detected_at >= ?
             ORDER BY ch.detected_at DESC
             LIMIT 40
            """, (theme, cutoff))]
    finally:
        conn.close()
    return {"theme": theme, "assets": rows, "changes": moves}
