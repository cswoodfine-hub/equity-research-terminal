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


# Words that mark a headline rather than a company. A counterparty is read off a
# headline, and a headline runs on: "Ouro Medicines to further expand" and "Tubulis
# adding potentially best-in-class antibody-drug" both arrived as company names, and
# the first of them is malformed enough that the registry answers 400 to it.
_HEADLINE_WORDS = {
    "to", "and", "with", "for", "in", "on", "as", "by", "after", "ahead", "adding",
    "expand", "further", "strengthen", "advance", "boost", "maximize", "maximise",
    "potentially", "best", "class", "deal", "buy", "buyout", "stake", "shares",
}
MAX_WORDS = 4          # a company name is short; a headline is not

# A word the whole industry shares. Alone it is not a company, it is the noun half of a
# thousand of them, and the registry's lead-sponsor query matches on substring: a search
# for "Therapeutics" returns MediLink, Abbisko, Juncell, Corcept, Mirati and Cullinan,
# and every one of their studies was then filed under Pfizer. That single word put 1,394
# other sponsors' trials on Pfizer's pipeline and made it read ten times any peer. A
# place name does the same for a university: "Massachusetts" finds Massachusetts General.
_GENERIC_ALONE = {
    "therapeutics", "pharmaceuticals", "pharmaceutical", "pharma", "biosciences",
    "bioscience", "biotechnology", "biotechnologies", "biotech", "biopharma",
    "biopharmaceuticals", "sciences", "science", "medicines", "medicine", "health",
    "healthcare", "laboratories", "labs", "oncology", "diagnostics", "genomics",
    "bio", "inc", "corp", "corporation", "ltd", "limited", "plc", "holdings", "group",
    "massachusetts", "california", "texas", "boston", "cambridge", "london",
}


def _plausible(name: str) -> bool:
    """Whether a counterparty name is specific enough to search a registry with."""
    name = (name or "").strip()
    if len(name) < 8:
        return False
    words = name.split()
    if len(words) > MAX_WORDS:
        return False
    if any(w.lower().strip(",.") in _HEADLINE_WORDS for w in words):
        return False
    # A name that is only industry words names no company: "Therapeutics" on its own,
    # or "Bio Sciences". The registry matches on substring, so one of these searches
    # returns every sponsor in the field.
    bare = [w.lower().strip(",.") for w in words]
    if all(w in _GENERIC_ALONE for w in bare):
        return False
    # Two words is specific enough. One word has to be long: AtaiBeckley names one
    # company and Engage names a verb.
    return len(words) >= 2 or len(name) >= 10


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
