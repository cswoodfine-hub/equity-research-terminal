"""What ClinicalTrials.gov says became of the trials the calendar is waiting on.

A trial stopped for futility is the result the filings least often carry: a company
announces a positive readout and lets a quiet termination speak for itself on the
registry. The pipeline fetch asks the registry for live studies only, so a trial that
stops keeps its last live status here and its catalyst sits pending until the grace
period closes it unknown. This asks the registry directly, by NCT id, about every
derived readout that has fallen due and is pending or unknown, and records three things.

A termination or withdrawal whose stated reason is efficacy, futility, or an interim
analysis that found no benefit, is a negative readout pinned to its trial, with the
registry's own sentence as the quote and the registry's last update as its date. A stop
for any other stated reason, enrolment, funding, a sponsor decision, is not a result and
is not recorded as one; the trial's status is brought up to date so the derivation
withdraws the row as it does for any stopped study. And a date that moved is written
to the trial so the resolver's own slip tier sees it.

The date is the registry's, which follows the event by days to months. A resolution
dated this way is marked by its source so that the gate scoring does not take a call
made after the trial had in fact stopped as a prediction.
"""

from __future__ import annotations

import datetime as dt
import re
import time

import db
import ctgov
from fetchers import trials_ctgov
from fetchers.trial_results import get_json

SOURCE = "registry"
BATCH = 20
_PAUSE_S = 0.5
# Statuses the registry uses for a study that will not read out.
STOPPED = ("TERMINATED", "WITHDRAWN", "SUSPENDED")
# A stop for the result's sake. The registry's whyStopped is free text; these are the
# words sponsors use when the interim or the data decided it.
_FOR_RESULT = re.compile(
    r"futilit|lack of efficacy|insufficient efficacy|no (?:clinical )?benefit|"
    r"did not (?:meet|achieve|demonstrate)|failed to (?:meet|demonstrate|show)|"
    r"efficacy (?:boundary|threshold)|not (?:expected|likely) to (?:meet|reach|achieve)|"
    r"interim analysis|primary endpoint", re.I)
# Words that say the stop was something else, even where a result word appears.
_NOT_RESULT = re.compile(
    r"enrol|recruit|business|strategic|portfolio|funding|financial|sponsor decision|"
    r"covid|supply|manufactur|safety|adverse|tolerab", re.I)

FIELDS = "|".join((
    "protocolSection.identificationModule.nctId",
    "protocolSection.statusModule.overallStatus",
    "protocolSection.statusModule.whyStopped",
    "protocolSection.statusModule.primaryCompletionDateStruct",
    "protocolSection.statusModule.lastUpdatePostDateStruct",
    "protocolSection.statusModule.resultsFirstPostDateStruct",
))


def key(nct: str, day: str) -> str:
    return f"registry:{nct}:{day}"


def classify_stop(status: str | None, why: str | None) -> str | None:
    """'negative' for a stop the registry attributes to the result; 'stopped' for a
    stop for any other reason; None for a study that is still going or has finished."""
    if (status or "").upper() not in STOPPED:
        return None
    text = why or ""
    if _FOR_RESULT.search(text) and not _NOT_RESULT.search(text):
        return "negative"
    return "stopped"


def due(conn) -> list[dict]:
    """Derived readouts fallen due, pending or unknown, with the trial they point at."""
    return [dict(r) for r in conn.execute(
        """SELECT c.id, c.company_id, c.description AS nct, c.expected_date, c.status
             FROM catalysts c
            WHERE c.catalyst_type = 'data readout' AND c.is_curated = 0
              AND c.status IN ('pending', 'unknown')
              AND c.description LIKE 'NCT%' AND c.expected_date < date('now')""")]


def parse(payload: dict) -> list[dict]:
    out = []
    for study in payload.get("studies") or []:
        section = study.get("protocolSection") or {}
        status = section.get("statusModule") or {}
        out.append({
            "nct_id": (section.get("identificationModule") or {}).get("nctId"),
            "status": status.get("overallStatus"),
            "why": status.get("whyStopped"),
            "primary_completion_date": trials_ctgov._date(status.get("primaryCompletionDateStruct")),
            "last_update": trials_ctgov._date(status.get("lastUpdatePostDateStruct")),
            "results_posted": trials_ctgov._date(status.get("resultsFirstPostDateStruct")),
        })
    return out


def extract(db_path=None, today=None, get=get_json) -> dict:
    """Ask the registry about every due readout and record what it says. Idempotent: a
    termination is keyed on the trial and the registry's update date."""
    today = today or dt.date.today()
    conn = db.get_connection(db_path)
    try:
        rows = due(conn)
        by_nct = {r["nct"]: r for r in rows}
    finally:
        conn.close()
    asked = negative = stopped = moved = 0
    errors: list[str] = []
    ids = sorted(by_nct)
    for start in range(0, len(ids), BATCH):
        chunk = ids[start:start + BATCH]
        try:
            studies = parse(get(ctgov.STUDIES_URL, {"filter.ids": ",".join(chunk),
                                                     "fields": FIELDS, "pageSize": BATCH}))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{chunk[0]}..: {exc}")
            continue
        conn = db.get_connection(db_path)
        try:
            for s in studies:
                cat = by_nct.get(s["nct_id"])
                if cat is None:
                    continue
                asked += 1
                status_text = trials_ctgov._humanize_status(s["status"])
                cur = conn.execute(
                    """UPDATE trials SET overall_status = ?, primary_completion_date = ?,
                              last_update_posted = ?, fetched_at = datetime('now')
                        WHERE nct_id = ? AND (COALESCE(overall_status, '') <> ?
                               OR COALESCE(primary_completion_date, '') <> ?)""",
                    (status_text, s["primary_completion_date"], s["last_update"], s["nct_id"],
                     status_text or "", s["primary_completion_date"] or ""))
                moved += cur.rowcount
                verdict = classify_stop(s["status"], s["why"])
                if verdict == "negative":
                    day = s["last_update"] or today.isoformat()
                    cur = conn.execute(
                        """INSERT INTO trial_readouts
                               (accession, company_id, drug, phase, outcome, event_date, quote,
                                source_url, source, nct_id, read_from)
                           VALUES (?, ?, NULL, NULL, 'negative', ?, ?, ?, ?, ?, 'registry')
                           ON CONFLICT(accession) DO NOTHING""",
                        (key(s["nct_id"], day), cat["company_id"], day,
                         f"{status_text}: {s['why']}", ctgov_url(s["nct_id"]), SOURCE, s["nct_id"]))
                    negative += cur.rowcount
                elif verdict == "stopped":
                    stopped += 1
            conn.commit()
        finally:
            conn.close()
        time.sleep(_PAUSE_S)
    return {"status": "ok", "due": len(ids), "asked": asked, "negative": negative,
            "stopped": stopped, "trials_updated": moved, "errors": errors}


def ctgov_url(nct: str) -> str:
    return f"https://clinicaltrials.gov/study/{nct}"
