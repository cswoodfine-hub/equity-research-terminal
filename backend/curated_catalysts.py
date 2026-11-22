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

A readout the registry does date, and the company dates later, is not a second event. A
row that fills ``guides_nct`` says which registry studies its date is for, and the loader
writes that date onto each study's own derived readout (``guided_date`` and its source,
migration 110) and leaves the registry's ``expected_date`` where it is. No second
catalyst is written, and one an earlier file wrote under the same title is withdrawn.
Biogen's TOPAZ-1 and TOPAZ-2 completed in September 2026 and report "in the first half
of December": one row, two studies, each keeping both dates. A readout closed unknown
while the company's date is still ahead goes back to pending, since unknown says a
window closed with nothing found and the window is the company's. Where the book holds
no derived readout for any study named, the row is written as a catalyst of its own, so
the date is not lost. The file is the record: a study no row guides any longer has its
guided date taken off. A cohort or an interim inside a study (ACHIEVE, PREVAIL,
HARMONi-3) is an event of its own and leaves the column empty.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "curated_catalysts.csv"
_MOVABLE = ("expected_date", "date_confidence", "description", "source_url")
_NCT = re.compile(r"NCT\d{8}")
_GUIDED = ("guided_date", "guided_confidence", "guided_source_url", "guided_note")
_RESOLVED = ("met", "missed")
# The kinds of row that are an FDA decision, as applications.FILED_KINDS names them.
_DECISIONS = ("PDUFA", "regulatory decision")


def names_study(row: dict) -> bool:
    """True where a row names a registry study in its text or its link."""
    return bool(_NCT.search((row.get("description") or "") + " " + (row.get("source_url") or "")))


def guided_ncts(row: dict) -> list:
    """The registry studies a row's date is for, as its ``guides_nct`` column names them."""
    return _NCT.findall(row.get("guides_nct") or "")


def _guide(conn, company_id: int, r: dict, today: dt.date) -> tuple:
    """Write the row's date onto the derived readout of each study it guides.

    (studies found, rows changed). The registry's own date is never touched. A readout
    already met or missed is the record of what happened and keeps what it has."""
    wanted = {"guided_date": r["expected_date"] or None,
              "guided_confidence": r["date_confidence"] or None,
              "guided_source_url": r["source_url"] or None,
              "guided_note": r["description"] or None}
    found = changed = 0
    for nct in guided_ncts(r):
        for cat in conn.execute(
                "SELECT id, status, guided_date, guided_confidence, guided_source_url,"
                "       guided_note FROM catalysts"
                " WHERE company_id = ? AND catalyst_type = 'data readout'"
                "   AND is_curated = 0 AND description = ?", (company_id, nct)).fetchall():
            found += 1
            status = cat["status"] or "pending"
            if status in _RESOLVED:
                continue
            moved = {k: v for k, v in wanted.items() if (cat[k] or None) != v}
            # Unknown is a window that closed with nothing found. The window is the
            # company's, and while it is open the readout is still to come.
            if (status == "unknown" and wanted["guided_date"]
                    and wanted["guided_date"] >= today.isoformat()):
                moved["status"] = "pending"
            if moved:
                sets = ", ".join(f"{k} = ?" for k in moved)
                conn.execute(f"UPDATE catalysts SET {sets}, updated_at = datetime('now')"
                             " WHERE id = ?", (*moved.values(), cat["id"]))
                changed += 1
    return found, changed


def _release_unguided(conn, guided: set) -> int:
    """Take the guided date off a study no row of the file guides any longer."""
    gone = 0
    for cat in conn.execute(
            "SELECT id, description, status FROM catalysts WHERE guided_date IS NOT NULL"
            "   AND catalyst_type = 'data readout' AND is_curated = 0").fetchall():
        if cat["description"] in guided or (cat["status"] or "pending") in _RESOLVED:
            continue
        sets = ", ".join(f"{k} = NULL" for k in _GUIDED)
        conn.execute(f"UPDATE catalysts SET {sets}, updated_at = datetime('now')"
                     " WHERE id = ?", (cat["id"],))
        gone += 1
    return gone


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


def _product(title: str) -> str:
    """The product a decision's title names, normalised: the text before "PDUFA",
    "decision" or "action date", as applications.parse_title reads it."""
    import applications
    return _norm(applications.parse_title(title)[0])


def _withdraw_copies(conn, company_id: int, kept: int, r: dict, asset_id) -> int:
    """Delete the machine-read copies of the decision the file names. Returns how many.

    pdufa.py writes a row per filing that states a goal date, and a company restates
    its date in later 8-Ks: Summit's ivonescimab PDUFA of 2026-11-14 arrived twice, from
    the January acceptance and from the September AstraZeneca 8-K, so the one decision
    stood twice on the calendar. The file's row is the record of that decision, so a
    pending machine-read row of the same company, date and product (or asset) is the
    same event and goes, as derive_readouts withdraws a stale derived readout. A curated
    or resolved row is never touched."""
    if r["catalyst_type"] not in _DECISIONS:
        return 0
    marks = ",".join("?" * len(_DECISIONS))
    product = _product(r["title"])
    gone = 0
    for row in conn.execute(
            f"SELECT id, title, asset_id FROM catalysts WHERE company_id = ?"
            f"   AND catalyst_type IN ({marks}) AND expected_date = ? AND id <> ?"
            f"   AND is_curated = 0 AND COALESCE(status, 'pending') = 'pending'",
            (company_id, *_DECISIONS, r["expected_date"], kept)).fetchall():
        same_asset = asset_id is not None and row["asset_id"] == asset_id
        if same_asset or (product and _product(row["title"]) == product):
            conn.execute("DELETE FROM catalysts WHERE id = ?", (row["id"],))
            gone += 1
    return gone


def load(conn, path: Path | None = None, today: dt.date | None = None) -> dict:
    """Write the file's catalysts into the book. {"written", "updated", "guided",
    "withdrawn", "skipped"}; "guided" counts the registry readouts given, or moved to,
    a company's date."""
    today = today or dt.date.today()
    out = {"written": 0, "updated": 0, "guided": 0, "withdrawn": 0, "skipped": []}
    guided: set = set()
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
        if r["catalyst_type"] == "data readout" and guided_ncts(r):
            guided.update(guided_ncts(r))
            found, changed = _guide(conn, company["id"], r, today)
            if found:
                out["guided"] += changed
                # The row an earlier file wrote for this date, as a catalyst of its
                # own: the study's readout carries the date now, so the copy goes.
                cur = conn.execute(
                    "DELETE FROM catalysts WHERE company_id = ? AND catalyst_type = ?"
                    "   AND title = ? AND is_curated = 1"
                    "   AND COALESCE(status, 'pending') = 'pending'",
                    (company["id"], r["catalyst_type"], r["title"]))
                out["withdrawn"] += cur.rowcount
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
            cur = conn.execute(
                "INSERT INTO catalysts (company_id, asset_id, asset_indication_id,"
                " catalyst_type, expected_date, date_confidence, title, description,"
                " is_curated, source_url, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'pending')",
                (company["id"], asset_id, link, r["catalyst_type"], r["expected_date"],
                 r["date_confidence"] or None, r["title"], r["description"],
                 r["source_url"] or None))
            out["written"] += 1
            out["withdrawn"] += _withdraw_copies(conn, company["id"], cur.lastrowid, r,
                                                 asset_id)
            continue
        if (existing["status"] or "pending") != "pending":
            continue
        out["withdrawn"] += _withdraw_copies(conn, company["id"], existing["id"], r,
                                             asset_id or existing["asset_id"])
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
    _release_unguided(conn, guided)
    return out
