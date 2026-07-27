"""The sponsor names a company acquired, so its bought pipeline reads as its own.

Lilly acquired eight companies in the first half of 2026. None of their studies appear
under Lilly in ClinicalTrials.gov, because the registry lists a study under the sponsor
who registered it and that record is updated late or never: Centessa still sponsors six
studies in its own name months after the deal closed.

The deals table already holds those names, so the trial fetches ask for them too. Only
acquisitions count. A licensing deal moves rights to one compound and leaves the trials
with the licensor, so treating a licensing counterparty as a sponsor would take another
company's pipeline and file it here.

Two guards, because a counterparty name is free text read off a headline. A name that is
one short word is refused, since "Engage" or "Firefly" as a lead sponsor matches things
that have nothing to do with the deal. And a study is only kept when the registry's own
lead sponsor name contains the name searched for, which the query alone does not
guarantee.
"""

from __future__ import annotations

import datetime as dt

import db

# How far back to look. An old acquisition has had its registry records moved across, so
# asking for it costs a request and returns the acquirer's own studies twice.
WITHIN_DAYS = 1825          # five years


def _plausible(name: str) -> bool:
    """Whether a counterparty name is specific enough to search a registry with."""
    name = (name or "").strip()
    if len(name) < 8:
        return False
    return len(name.split()) >= 2 or len(name) >= 12


def for_company(db_path=None, ticker: str = "", today=None) -> list:
    """Every company this one has acquired recently, by the name it traded under."""
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=WITHIN_DAYS)).isoformat()
    conn = db.get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT d.counterparty FROM deals d
              JOIN companies c ON c.id = d.company_id
             WHERE c.ticker = ? AND d.deal_type = 'acquisition'
               AND d.counterparty IS NOT NULL
               AND COALESCE(d.event_date, '') >= ?
            """, (ticker.upper(), cutoff)).fetchall()
    finally:
        conn.close()
    names = [r["counterparty"].strip() for r in rows if _plausible(r["counterparty"])]
    return sorted(dict.fromkeys(names))


def sponsored_by(study: dict, names) -> str | None:
    """The searched name the registry agrees sponsored this study, or None.

    The query matches loosely, so the answer is checked against the study's own lead
    sponsor: a search for "Ajax Therapeutics" that returns a study led by someone else
    has found a coincidence, not an acquisition.
    """
    lead = (((study.get("protocolSection") or {}).get("sponsorCollaboratorsModule")
             or {}).get("leadSponsor") or {}).get("name") or ""
    lead_lower = lead.lower()
    for name in names:
        if name.lower() in lead_lower:
            return lead
    return None
