"""Hand-entered catalysts kept in the repo, so every book carries them.

An FDA decision a filing dates but no feed publishes (Novo's CagriSema in Q4 2026, its
denecimig after the FDA extended the review, GSK's Jemperli in rectal cancer) is entered
by hand. Entered in one book it lived only there: the cloud refresh rebuilds its book
from data/history, which the local book never writes, so the cloud's gate calls priced
those assets as if no decision were on file. ``data/curated_catalysts.csv`` is the
record and ``load`` puts it into whichever book runs the refresh.

A row is the company's catalyst of that type under that title. One the book lacks is
written, curated and pending, joined to its asset by name and to its indication by name
where the file gives one. One still pending whose date, its precision, its text or its
source the file has since changed is moved to the file's. A resolved row (met, missed,
passed) is the book's own and is never touched, and neither is a book row the file does
not name.

The title must read "<product> decision, <indication>" or "<product> PDUFA,
<indication>": the indication rebuild releases every catalyst's indication link each
run and applications.resolve re-joins it from the title, so a title it cannot parse
loses the link overnight and the asset drops off its approval gate.

A readout the registry does not date is entered the same way, as a "data readout" that
names its asset and its study's NCT number. Dyne's ACHIEVE registrational cohort reads
out in Q1 2027 inside a study the registry dates to 2029, and the accelerated filing
rests on it; stated legs whose sources cite that study are priced on the row
(forecast_view.catalyst_stakes). Its title is free text, since resolve parses only a
decision's, and its asset link is one the nightly rebuild does not release. A readout
naming no study is skipped and said, because nothing could tie it to a trial.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "curated_catalysts.csv"
_MOVABLE = ("expected_date", "date_confidence", "description", "source_url")
_NCT = re.compile(r"NCT\d{8}")


def names_study(row: dict) -> bool:
    """True where a row names a registry study in its text or its link."""
    return bool(_NCT.search((row.get("description") or "") + " " + (row.get("source_url") or "")))


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def rows(path: Path | None = None) -> list[dict]:
    with open(path or CSV_PATH, newline="", encoding="utf-8") as handle:
        return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(handle)]


def _asset(conn, company_id: int, name: str):
    """The one asset of the company carrying ``name`` as its generic, brand or code."""
    wanted = _norm(name)
    hits = {r["id"] for r in conn.execute(
        "SELECT id, generic_name, brand_name, internal_code FROM assets"
        " WHERE owner_company_id = ?", (company_id,))
        if wanted and wanted in {_norm(r["generic_name"]), _norm(r["brand_name"]),
                                 _norm(r["internal_code"])}}
    return hits.pop() if len(hits) == 1 else None


def _link(conn, asset_id: int, indication: str):
    if not indication:
        return None
    row = conn.execute(
        "SELECT ai.id FROM asset_indications ai JOIN indications i"
        "  ON i.id = ai.indication_id WHERE ai.asset_id = ? AND lower(i.name) = lower(?)"
        " ORDER BY ai.is_lead DESC LIMIT 1", (asset_id, indication)).fetchone()
    return row["id"] if row else None


def load(conn, path: Path | None = None) -> dict:
    """Write the file's catalysts into the book. {"written", "updated", "skipped"}."""
    out = {"written": 0, "updated": 0, "skipped": []}
    for r in rows(path):
        company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                               (r["ticker"],)).fetchone()
        if company is None:
            out["skipped"].append({"title": r["title"], "why": f"no company {r['ticker']}"})
            continue
        if r["catalyst_type"] == "data readout" and not (r["asset"] and names_study(r)):
            out["skipped"].append({"title": r["title"],
                                   "why": "a readout must name its asset and its study"})
            continue
        # A row naming no asset is written unjoined: applications.resolve joins it
        # from the title once the asset exists (Intellia's lonvo-z had none).
        asset_id = _asset(conn, company["id"], r["asset"]) if r["asset"] else None
        if r["asset"] and asset_id is None:
            out["skipped"].append({"title": r["title"],
                                   "why": f"no single asset named {r['asset']}"})
            continue
        link = _link(conn, asset_id, r["indication"]) if asset_id else None
        # A filer restates a date under the same title (Capricor's August PDUFA moved to
        # November): the row already on the file's date is the one, else the latest.
        found = conn.execute(
            "SELECT id, status, asset_id, asset_indication_id, expected_date,"
            "       date_confidence, description, source_url FROM catalysts"
            " WHERE company_id = ? AND catalyst_type = ? AND title = ?"
            " ORDER BY expected_date = ? DESC, expected_date DESC, id DESC",
            (company["id"], r["catalyst_type"], r["title"], r["expected_date"])).fetchall()
        existing = found[0] if found else None
        if existing is None:
            conn.execute(
                "INSERT INTO catalysts (company_id, asset_id, asset_indication_id,"
                " catalyst_type, expected_date, date_confidence, title, description,"
                " is_curated, source_url, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'pending')",
                (company["id"], asset_id, link, r["catalyst_type"], r["expected_date"],
                 r["date_confidence"] or None, r["title"], r["description"],
                 r["source_url"] or None))
            out["written"] += 1
            continue
        if (existing["status"] or "pending") != "pending":
            continue
        moved = {k: (r[k] or None) for k in _MOVABLE if (existing[k] or None) != (r[k] or None)}
        if asset_id is not None and existing["asset_id"] != asset_id:
            moved["asset_id"] = asset_id
        if existing["asset_indication_id"] is None and link is not None:
            moved["asset_indication_id"] = link
        if moved:
            sets = ", ".join(f"{k} = ?" for k in moved)
            conn.execute(f"UPDATE catalysts SET {sets}, updated_at = datetime('now')"
                         " WHERE id = ?", (*moved.values(), existing["id"]))
            out["updated"] += 1
    return out
