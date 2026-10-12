"""The sponsor names a company acquired, so its bought pipeline reads as its own.

Lilly acquired eight companies in the first half of 2026. None of their studies appear
under Lilly in ClinicalTrials.gov, because the registry lists a study under the sponsor
who registered it and that record is updated late or never: Centessa still sponsors six
studies in its own name months after the deal closed.

The deals table already holds those names, so the trial fetches ask for them too. Only
acquisitions count. A licensing deal moves rights to one compound and leaves the trials
with the licensor, so treating a licensing counterparty as a sponsor would take another
company's pipeline and file it here.

Four guards, because a counterparty name is free text read off a headline. A name that is
one short word is refused, since "Engage" or "Firefly" as a lead sponsor matches things
that have nothing to do with the deal. A headline is believed only when it names this
company before the company bought: the news search for Structure Therapeutics returned
"BioMarin acquires Amicus Therapeutics" and "Day One Completes Acquisition of Mersana
Therapeutics", an older parser filed both as Structure's acquisitions, and every active
Amicus, Mersana and Vidya study was then fetched as Structure's pipeline. A study is only
kept when the registry's own lead sponsor begins with the name searched for, because a
company registers its studies in its own name and a name found inside another sponsor's
("University of Connecticut", "Belun Technology Company") is a coincidence. And the
studies already filed through a name these guards now refuse are moved to the company
that did buy the sponsor, or released when no company in the universe did
(``release``).
"""

from __future__ import annotations

import datetime as dt
import json
import re

import company_names
import ctgov
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
_INDUSTRY_WORDS = {
    "therapeutics", "pharmaceuticals", "pharmaceutical", "pharma", "biosciences",
    "bioscience", "biotechnology", "biotechnologies", "biotech", "biopharma",
    "biopharmaceuticals", "sciences", "science", "medicines", "medicine", "health",
    "healthcare", "laboratories", "labs", "oncology", "diagnostics", "genomics",
    "bio", "inc", "corp", "corporation", "ltd", "limited", "plc", "holdings", "group",
}
# "J&J to acquire Connecticut biotech" filed Connecticut as the company J&J bought, and
# the University of Connecticut's studies became six Johnson & Johnson programmes.
_PLACE_WORDS = {
    "massachusetts", "california", "texas", "boston", "cambridge", "london",
    "connecticut",
}
_GENERIC_ALONE = _INDUSTRY_WORDS | _PLACE_WORDS


def _plausible(name: str, generic=None) -> bool:
    """Whether a counterparty name is specific enough to search a registry with."""
    generic = _GENERIC_ALONE if generic is None else generic
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
    if all(w in generic for w in bare):
        return False
    # Two words is specific enough. One word has to be long: AtaiBeckley names one
    # company and Engage names a verb.
    return len(words) >= 2 or len(name) >= 10


def own_names(conn, ticker: str) -> set:
    """What a headline or the registry calls this company: its ticker, its legal name with
    and without the suffix, its first word, its press names and its registry sponsor."""
    row = conn.execute("SELECT name, ctgov_sponsor FROM companies WHERE ticker = ?",
                       (ticker.upper(),)).fetchone()
    if row is None:
        return set()
    legal = (row["name"] or "").strip()
    names = {ticker.upper(), legal, company_names.bare(legal),
             *company_names.press_names(ticker.upper(), legal)}
    first = company_names.bare(legal).split()[0] if legal else ""
    if len(first) >= 4 and first.lower() not in _GENERIC_ALONE:
        names.add(first)
    names |= {p.strip() for p in (row["ctgov_sponsor"] or "").split("|") if p.strip()}
    return {n for n in names if n}


def _first(text: str, names) -> int | None:
    """Where the earliest of these names starts in the text, as a whole word."""
    hits = [m.start() for n in names if n
            for m in [re.search(rf"(?<![\w&-]){re.escape(n.lower())}(?![\w&-])", text)]
            if m]
    return min(hits) if hits else None


def names_acquirer(quote: str, names, counterparty: str) -> bool:
    """Whether a headline names this company before the company it bought.

    "BioMarin acquires Amicus Therapeutics" is BioMarin's deal whoever searched for it,
    "Lilly buys AtaiBeckley to challenge J&J" is not Johnson & Johnson's, and "Crystal
    Crop Protection acquires Ethoxysulfuron assets from Bayer AG" names Bayer as the
    seller. The acquirer leads an acquisition headline; a company named after the target,
    or not at all, did not buy it.
    """
    text = (quote or "").lower()
    own = _first(text, names)
    if own is None:
        return False
    party = (counterparty or "").strip()
    target = _first(text, [party, company_names.bare(party),
                           party.split()[0] if party else ""])
    return target is None or own < target


def _acquisitions(conn, ticker: str, today=None) -> list:
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=WITHIN_DAYS)).isoformat()
    return conn.execute(
        """
        SELECT d.counterparty, d.quote, d.accession, d.is_curated FROM deals d
          JOIN companies c ON c.id = d.company_id
         WHERE c.ticker = ? AND d.deal_type = 'acquisition'
           AND d.counterparty IS NOT NULL
           AND COALESCE(d.event_date, '') >= ?
        """, (ticker.upper(), cutoff)).fetchall()


def _trusted(row, names) -> bool:
    """A deal this company's own filing states, one the analyst entered, or a headline
    that names this company as the buyer."""
    if row["accession"] or row["is_curated"]:
        return True
    return names_acquirer(row["quote"], names, row["counterparty"])


def for_company(db_path=None, ticker: str = "", today=None) -> list:
    """Every company this one has acquired recently, by the name it traded under."""
    conn = db.get_connection(db_path)
    try:
        names = own_names(conn, ticker)
        rows = _acquisitions(conn, ticker, today)
    finally:
        conn.close()
    found = [r["counterparty"].strip() for r in rows
             if _plausible(r["counterparty"]) and _trusted(r, names)]
    return sorted(dict.fromkeys(found))


def _searched_before(conn, ticker: str, today=None) -> list:
    """Every name a fetch may have searched for this company under the older rules: any
    acquisition counterparty, believed or not, that was not an industry word alone."""
    return sorted({r["counterparty"].strip() for r in _acquisitions(conn, ticker, today)
                   if _plausible(r["counterparty"], _INDUSTRY_WORDS)})


def _lead_starts(lead: str, name: str) -> bool:
    lead, core = (lead or "").lower().strip(), company_names.bare(name).lower()
    if not core or not lead.startswith(core):
        return False
    rest = lead[len(core):]
    return not rest or not (rest[0].isalnum())


def sponsored_by(study: dict, names) -> str | None:
    """The searched name the registry agrees sponsored this study, or None.

    The query matches loosely, so the answer is checked against the study's own lead
    sponsor: a search for "Ajax Therapeutics" that returns a study led by someone else
    has found a coincidence, not an acquisition. The lead sponsor must begin with the
    name, since a company registers in its own name ("Centessa Pharmaceuticals (UK)
    Limited") and a name inside another sponsor's is someone else's study.
    """
    lead = (((study.get("protocolSection") or {}).get("sponsorCollaboratorsModule")
             or {}).get("leadSponsor") or {}).get("name") or ""
    for name in names:
        if _lead_starts(lead, name):
            return lead
    return None


def _own_terms(conn, ticker: str) -> list:
    row = conn.execute("SELECT ctgov_sponsor FROM companies WHERE ticker = ?",
                       (ticker,)).fetchone()
    value = (row["ctgov_sponsor"] or "").strip() if row else ""
    terms = [p.strip() for p in value.split("|") if p.strip()]
    if not terms and ctgov.SPONSOR_LEAD.get(ticker):
        terms = [ctgov.SPONSOR_LEAD[ticker]]
    return terms


def misfiled(db_path=None, today=None) -> list:
    """The studies a company holds through an acquired name the guards now refuse.

    A study is misfiled when its lead sponsor contains a name this company's fetch may
    have searched, does not begin with any name it still searches, and is not led under
    the company's own registry name. Each comes with the one other company whose
    acquisition it is, or None when no company in the universe bought that sponsor.
    """
    conn = db.get_connection(db_path)
    try:
        companies = [dict(r) for r in conn.execute(
            "SELECT id, ticker FROM companies ORDER BY ticker")]
        accepted = {c["id"]: for_company(db_path, c["ticker"], today) for c in companies}
        out = []
        for company in companies:
            before = _searched_before(conn, company["ticker"], today)
            if not before:
                continue
            terms = [t.lower() for t in _own_terms(conn, company["ticker"])]
            keep = accepted[company["id"]]
            for table in ("trials", "completed_trials"):
                for row in conn.execute(
                        f"SELECT nct_id, lead_sponsor, asset_id FROM {table}"
                        "  WHERE sponsor_company_id = ?", (company["id"],)):
                    lead = row["lead_sponsor"] or ""
                    low = lead.lower()
                    if not any(n.lower() in low for n in before):
                        continue
                    if any(t and t in low for t in terms):
                        continue
                    if any(_lead_starts(lead, n) for n in keep):
                        continue
                    owners = [c for c in companies if c["id"] != company["id"]
                              and any(_lead_starts(lead, n) for n in accepted[c["id"]])]
                    out.append({"table": table, "nct_id": row["nct_id"],
                                "lead_sponsor": lead, "asset_id": row["asset_id"],
                                "from_id": company["id"], "from": company["ticker"],
                                "to_id": owners[0]["id"] if len(owners) == 1 else None,
                                "to": owners[0]["ticker"] if len(owners) == 1 else None})
        return out
    finally:
        conn.close()


def release(db_path=None, today=None) -> dict:
    """Move each misfiled study to the company that bought its sponsor, or release it.

    Run after the trials are fetched and before the pipeline is derived, like the
    seller-kept programmes. A moved or released study loses its asset too, so the mapping
    that follows binds it under its rightful sponsor or not at all. Snapshotted first.
    Idempotent: a moved study is no longer under a name its holder refuses.
    """
    moves = misfiled(db_path, today)
    if not moves:
        return {"moved": 0, "released": 0}
    conn = db.get_connection(db_path)
    try:
        by_company: dict[str, list] = {}
        for move in moves:
            by_company.setdefault(move["from"], []).append(
                {k: move[k] for k in ("table", "nct_id", "lead_sponsor", "asset_id", "to")})
        for ticker, rows in sorted(by_company.items()):
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload)"
                " VALUES ('acquired_sponsors', 'company', ?, ?)",
                (ticker, json.dumps({"misfiled": rows})))
        for move in moves:
            conn.execute(
                f"UPDATE {move['table']} SET sponsor_company_id = ?, asset_id = NULL"
                "  WHERE nct_id = ?", (move["to_id"], move["nct_id"]))
        conn.commit()
    finally:
        conn.close()
    moved = sum(1 for m in moves if m["to_id"])
    return {"moved": moved, "released": len(moves) - moved}
