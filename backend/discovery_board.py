"""The Discovery tab's payload: the alerts raised on new research papers, and the papers.

Two reads over what the daily Europe PMC fetch stored (``fetchers/papers_europepmc.py``)
and what ``diff._diff_discovery`` raised from it. Nothing is computed here that is not
already in the tables: a rank is the stored share turned into "top 3%", and a lab is the
seeded row. A database from before Discovery, or one the fetch has not reached yet,
gives empty lists and says so.
"""

from __future__ import annotations

import json
import sqlite3

import db
import discovery
import materiality

LABEL = "Discovery (early research, ranked by a model)"
SORTS = {"feas": "feas_pct DESC", "comm": "comm_pct DESC",
         "date": "COALESCE(indexed, published) DESC"}
ALERT_NAMES = {"discovery_paper_top": "Top paper",
               "discovery_lab_paper": "Ranked lab published",
               "discovery_lab_stage": "Lab reached a later model",
               "discovery_lab_company": "Lab's first company co-author"}
PAPER_LIMIT = 200


def _list(text) -> list:
    try:
        return json.loads(text) if text else []
    except ValueError:
        return []


def _paper(row, labs) -> dict:
    lab = labs.get(row["lab_id"])
    try:
        reasons = json.loads(row["reasons"]) if row["reasons"] else None
    except ValueError:
        reasons = None
    return {
        "id": row["id"], "title": row["title"], "published": row["published"],
        "indexed": row["indexed"], "journal": row["journal"],
        "preprint": bool(row["preprint"]), "authors": row["authors"],
        "senior_author": row["senior_author"], "institution": row["institution"],
        "lab": ({"id": lab["id"], "name": lab["name"], "rank": lab["rank"]} if lab else None),
        "lab_match": row["lab_match"], "areas": _list(row["areas"]),
        "modalities": _list(row["modalities"]), "stage": row["stage"],
        "stage_name": discovery.STAGE_NAMES.get(row["stage"]),
        "company_author": (None if row["company_author"] is None
                           else bool(row["company_author"])),
        "feas_pct": row["feas_pct"], "comm_pct": row["comm_pct"],
        "feas_top": discovery.top_share(row["feas_pct"]),
        "comm_top": discovery.top_share(row["comm_pct"]),
        "reasons": reasons, "url": discovery.paper_url(row["id"]),
        "doi": row["doi"], "pmid": row["pmid"]}


def _basis(conn) -> dict:
    """What the ranks stand on: how many lab heads, ranked when, by which model, and
    when Europe PMC was last read."""
    labs = conn.execute(
        "SELECT COUNT(*) AS n, MAX(ranked_as_of) AS d FROM discovery_labs").fetchone()
    last = conn.execute(
        "SELECT captured_at, payload FROM snapshots WHERE source = 'europepmc'"
        " AND entity_type = 'feed' AND json_extract(payload, '$.fetch_kind') = 'live'"
        " ORDER BY id DESC LIMIT 1").fetchone()
    held = conn.execute(
        "SELECT COUNT(*) FROM discovery_papers WHERE feas_pct IS NULL").fetchone()[0]
    scorer = discovery.scorer()
    read = json.loads(last["payload"]) if last else {}
    return {"labs": labs["n"], "labs_ranked_as_of": labs["d"],
            "model_version": scorer.version if scorer else None,
            "last_read": last["captured_at"] if last else None,
            "last_read_records": read.get("records"),
            "held_without_abstract": held,
            "top_paper_share": round((1 - materiality.DISCOVERY_TOP_PCT) * 100),
            "lab_rank_limit": materiality.DISCOVERY_LAB_RANK,
            "alert_days": materiality.DISCOVERY_ALERT_DAYS}


def _empty(**extra) -> dict:
    return {"label": LABEL, "basis": None, **extra}


def alerts(db_path=None, days: int = 14) -> dict:
    """The alerts of the last ``days`` days, newest first and high before medium within
    a day, each with the paper it is about and, where there is one, the lab."""
    conn = db.get_connection(db_path)
    try:
        try:
            labs = {r["id"]: r for r in conn.execute("SELECT * FROM discovery_labs")}
        except sqlite3.OperationalError:
            return _empty(days=days, alerts=[])
        papers = {r["id"]: r for r in conn.execute("SELECT * FROM discovery_papers")}
        out = []
        for r in conn.execute(
                "SELECT id, entity_type, entity_key, field, old_value, new_value,"
                " change_type, significance, detected_at FROM changes"
                " WHERE entity_type IN ('paper', 'lab') AND detected_at >= datetime('now', ?)"
                " ORDER BY date(detected_at) DESC,"
                " CASE significance WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id",
                (f"-{int(days)} days",)):
            lab = labs.get(r["entity_key"].split("|")[0]) if r["entity_type"] == "lab" else None
            paper = papers.get(r["field"])
            out.append({
                "id": r["id"], "date": r["detected_at"][:10], "kind": r["change_type"],
                "kind_name": ALERT_NAMES.get(r["change_type"], r["change_type"]),
                "significance": r["significance"], "headline": r["new_value"],
                "before": r["old_value"], "paper_id": r["field"],
                "url": discovery.paper_url(r["field"]),
                "lab": ({"id": lab["id"], "name": lab["name"], "rank": lab["rank"],
                         "institutions": _list(lab["institutions"])} if lab else None),
                "paper": _paper(paper, labs) if paper else None})
        return {"label": LABEL, "basis": _basis(conn), "days": days, "alerts": out}
    finally:
        conn.close()


def papers(db_path=None, days: int = 30, sort: str = "feas") -> dict:
    """The scored papers indexed in the last ``days`` days, best first on ``sort``
    (feas, comm or date). A paper still waiting for its abstract is counted, not listed."""
    order = SORTS.get(sort) or SORTS["feas"]
    conn = db.get_connection(db_path)
    try:
        try:
            labs = {r["id"]: r for r in conn.execute("SELECT * FROM discovery_labs")}
        except sqlite3.OperationalError:
            return _empty(days=days, sort=sort, total=0, papers=[])
        since = f"-{int(days)} days"
        total = conn.execute(
            "SELECT COUNT(*) FROM discovery_papers WHERE feas_pct IS NOT NULL"
            " AND COALESCE(indexed, published) >= date('now', ?)", (since,)).fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM discovery_papers WHERE feas_pct IS NOT NULL"
            f" AND COALESCE(indexed, published) >= date('now', ?) ORDER BY {order}, id"
            f" LIMIT {PAPER_LIMIT}", (since,)).fetchall()
        return {"label": LABEL, "basis": _basis(conn), "days": days,
                "sort": sort if sort in SORTS else "feas", "total": total,
                "papers": [_paper(r, labs) for r in rows]}
    finally:
        conn.close()
