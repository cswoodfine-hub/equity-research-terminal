"""Readouts a company has announced that the book did not read, entered by hand.

The resolver closes a readout on an announced result it can match: the same company,
drug and phase, inside a window that ends 45 days after the registry date. That leaves
three kinds of result on the calendar as overdue or unknown. One announced outside the
window: Capricor's HOPE-3 reached primary completion in June 2025 and its topline came
in December. One the reader labelled but could not place among sibling studies. And one
no reader saw at all, because the release sat on a site the feeds do not carry.

``data/announced_readouts.csv`` is the record of those, one row a study: the registry
number, met or missed, the day the company announced it, the sentence that states the
result and the page it stands on. ``load`` closes the study's derived readout with that
outcome, dated by the announcement, and writes the resolution to the ledger as
``hand`` and not automated, which is the source the ledger's schema has named since it
was made and no writer used. It lives in the repo for the reason the curated catalysts
do: a resolution written in one book lives only there.

The row is keyed on the trial and nothing else. It is not written to
``trial_readouts``, because most of these announcements are already there under their
filing, and a second row would count one announcement twice in the event study and
offer it to a sibling study on the resolver's next run.

A row that is not a plain result is not for this file. A study that met one of two
primary endpoints, or met in a subgroup and not in everyone, is the analyst's call and
is resolved in the terminal. A readout that is still pending or unknown is closed; one
already met or missed is the book's own and is never overturned from here: the same
outcome is counted as held, the other is skipped and said.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
from pathlib import Path

import catalyst_outcomes

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "announced_readouts.csv"
OUTCOMES = ("met", "missed")
SOURCE = "hand"
BASIS = ("a result the company announced, entered by hand with the sentence that states "
         "it and the page it stands on")
_NCT = re.compile(r"NCT\d{8}")


def rows(path: Path | None = None) -> list[dict]:
    with open(path or CSV_PATH, newline="", encoding="utf-8") as handle:
        return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(handle)]


def problem(row: dict, today: dt.date | None = None) -> str | None:
    """Why a row cannot be taken, or None. A result with no sentence or no page is a
    claim, not a record."""
    if not _NCT.fullmatch(row.get("nct_id") or ""):
        return "a result must name its study by registry number"
    if row.get("outcome") not in OUTCOMES:
        return "the outcome must be met or missed"
    try:
        day = dt.date.fromisoformat(row.get("event_date") or "")
    except ValueError:
        return "the announcement must carry its day"
    if day > (today or dt.date.today()):
        return "the announcement is dated ahead of today"
    if not row.get("quote") or not (row.get("source_url") or "").startswith("http"):
        return "a result must carry the sentence that states it and its source"
    return None


def evidence(row: dict) -> str:
    return f"{row['source_url']}: {row['quote']}"


def load(conn, path: Path | None = None, today: dt.date | None = None) -> dict:
    """Close the readouts the file names. {"resolved", "held", "skipped"}."""
    today = today or dt.date.today()
    out = {"resolved": 0, "held": 0, "skipped": []}

    def skip(row, why):
        out["skipped"].append({"nct_id": row.get("nct_id"), "why": why})

    for r in rows(path):
        why = problem(r, today)
        if why:
            skip(r, why)
            continue
        company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                               (r["ticker"],)).fetchone()
        if company is None:
            skip(r, f"no company {r['ticker']}")
            continue
        # A derived readout carries its trial's registry number as its description.
        found = conn.execute(
            "SELECT id, company_id, status FROM catalysts"
            " WHERE catalyst_type = 'data readout' AND description = ? ORDER BY id",
            (r["nct_id"],)).fetchall()
        if not found:
            skip(r, f"no readout on the calendar for {r['nct_id']}")
            continue
        for cat in found:
            status = cat["status"] or "pending"
            if cat["company_id"] != company["id"]:
                skip(r, f"the readout for {r['nct_id']} is not {r['ticker']}'s")
            elif status == r["outcome"]:
                out["held"] += 1
            elif status in OUTCOMES:
                skip(r, f"the book already holds {r['nct_id']} as {status}")
            else:
                text = evidence(r)
                conn.execute(
                    """INSERT OR IGNORE INTO catalyst_resolutions
                           (catalyst_id, outcome, event_date, resolved_at, source, evidence,
                            basis, automated, dedupe)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                    (cat["id"], r["outcome"], r["event_date"], today.isoformat(), SOURCE,
                     text, BASIS, text))
                catalyst_outcomes._close(conn, cat["id"], r["outcome"], r["event_date"], today)
                out["resolved"] += 1
    return out
