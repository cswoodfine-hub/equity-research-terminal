"""Regulatory submissions announced in the news, recorded as dated catalysts.

The calendar held readouts and FDA decision dates and nothing in between, so the moment
an asset actually left Phase 3 was invisible. A submission is the event the whole
p3_to_nda gate is about: the company stopped running the trial and filed. It is also
what starts the review clock that launch_timing reads, so the date matters beyond the
headline.

Detection follows auto_resolve's rule and for the same reason. The press feed carries
"Company submits New Drug Application" beside "Company remains on track to submit an NDA
in the first half of 2027", and the second is a plan, not an event. An intention to
submit is rejected before anything else is tested, so a guided milestone never lands as
a thing that happened.

What is recorded is the announcement, dated to the day it was made, with the headline
kept verbatim and the press URL as the row's identity. Nothing here derives a decision
date: the FDA review clock in data/fda_review_clock.csv is a goal, the commitment letter
is explicit that it runs from a filing date the company does not announce, and
launch_timing already reads it as a flag that reaches no valuation. A second guess at a
PDUFA date, sitting beside the ones pdufa.py reads out of the filings themselves, would
be the worse number winning on volume.
"""

from __future__ import annotations

import re

import db

SOURCE_KINDS = ("press_regulatory", "press_approval", "press_data_readout")
CATALYST_TYPE = "regulatory submission"

# Tested first and wins outright: a plan to file is not a filing. This is most of what
# the regulatory feed says about submissions.
INTENT = re.compile(
    r"\b(?:plans?|expects?|intends?|aims?|on track|anticipat\w+|plan(?:ning|ned)|plans to"
    r"|plan to|plan for|targeting|plans for|will (?:submit|file)|to (?:submit|file)"
    r"|plans? submission|expected (?:submission|filing))\b", re.I)

# What was filed. The group names the application so the title can say it.
FILED = re.compile(
    r"\b(?:submit(?:s|ted)|complet(?:es|ed) (?:the )?submission of|"
    r"announce[sd]? (?:the )?submission of|file[sd]?)\b[^.]{0,60}?"
    r"\b(?P<kind>new drug application|biologics?[- ]license application|"
    r"supplemental new drug application|supplemental biologics?[- ]license application|"
    r"marketing authorisation application|marketing authorization application|"
    r"s?nda|s?bla|maa)\b", re.I)

# Acceptance is a second, later event on the same application and is worth its own row:
# the clock the FDA runs starts here, not at receipt.
ACCEPTED = re.compile(
    r"\b(?:fda|ema|chmp)\b[^.]{0,40}\baccept(?:s|ed)\b[^.]{0,60}?"
    r"\b(?P<kind>new drug application|biologics?[- ]license application|"
    r"s?nda|s?bla|maa|application|submission)\b"
    r"|\b(?P<kind2>new drug application|biologics?[- ]license application|s?nda|s?bla)\b"
    r"[^.]{0,40}\baccepted (?:for|by)\b", re.I)

_TIDY = {
    "nda": "NDA", "bla": "BLA", "snda": "sNDA", "sbla": "sBLA", "maa": "MAA",
    "new drug application": "NDA", "biologics license application": "BLA",
    "biologic license application": "BLA",
    "supplemental new drug application": "sNDA",
    "supplemental biologics license application": "sBLA",
    "supplemental biologic license application": "sBLA",
    "marketing authorisation application": "MAA",
    "marketing authorization application": "MAA",
    "application": "application", "submission": "application",
}


def _tidy(kind: str | None) -> str:
    key = re.sub(r"[-\s]+", " ", (kind or "")).strip().lower()
    return _TIDY.get(key, (kind or "application").upper())


def classify(headline: str | None) -> tuple[str | None, str | None, str | None]:
    """(stage, application, the words that decided it), or nothing.

    ``stage`` is "submitted" or "accepted". A plan to file returns nothing, which is the
    common case and the point.
    """
    text = (headline or "").strip()
    if not text:
        return None, None, None
    if INTENT.search(text):
        return None, None, None
    hit = ACCEPTED.search(text)
    if hit:
        kind = hit.groupdict().get("kind") or hit.groupdict().get("kind2")
        return "accepted", _tidy(kind), hit.group(0)
    hit = FILED.search(text)
    if hit:
        return "submitted", _tidy(hit.group("kind")), hit.group(0)
    return None, None, None


def _found(conn, since: str) -> list[dict]:
    rows = conn.execute(
        f"""SELECT entity_key, new_value AS headline, change_type, detected_at
              FROM changes
             WHERE change_type IN ({', '.join('?' * len(SOURCE_KINDS))})
               AND detected_at >= ?
             ORDER BY detected_at""", list(SOURCE_KINDS) + [since]).fetchall()
    out = []
    for r in rows:
        who, _, url = str(r["entity_key"] or "").partition("|")
        stage, kind, words = classify(r["headline"])
        if stage is None or not url:
            continue
        out.append({"ticker": who.strip().upper(), "url": url,
                    "headline": r["headline"], "stage": stage, "application": kind,
                    "words": words, "on": str(r["detected_at"])[:10]})
    return out


def _asset_named(conn, ticker: str, headline: str):
    """The company's asset the headline names, where exactly one is named."""
    rows = conn.execute(
        """SELECT a.id, a.brand_name, a.generic_name FROM assets a
             JOIN companies c ON c.id = a.owner_company_id WHERE c.ticker = ?""",
        (ticker,)).fetchall()
    hit = []
    for r in rows:
        for name in (r["brand_name"], r["generic_name"]):
            name = (name or "").strip()
            if len(name) >= 4 and re.search(rf"\b{re.escape(name)}\b", headline, re.I):
                hit.append((r["id"], name))
                break
    return hit[0] if len(hit) == 1 else (None, None)


def derive(db_path=None, since_days: int = 180) -> dict:
    """Record every announced submission as a catalyst. Idempotent on the press URL.

    A row the analyst has accepted (is_curated=1) is left alone: their judgement outranks
    the derivation, the rule derive_readouts already follows.
    """
    import datetime as dt
    since = (dt.datetime.now(dt.timezone.utc).date()
             - dt.timedelta(days=since_days)).isoformat()
    conn = db.get_connection(db_path)
    written = updated = skipped = 0
    try:
        tickers = {r["ticker"]: r["id"] for r in conn.execute(
            "SELECT id, ticker FROM companies")}
        for item in _found(conn, since):
            company_id = tickers.get(item["ticker"])
            if company_id is None:
                skipped += 1
                continue
            asset_id, named = _asset_named(conn, item["ticker"], item["headline"])
            title = (f"{named} {item['application']} {item['stage']}" if named
                     else f"{item['application']} {item['stage']}")
            description = (f"{item['headline']}  [matched \"{item['words']}\"]")
            existing = conn.execute(
                "SELECT id, is_curated FROM catalysts WHERE source_url = ?"
                " AND catalyst_type = ?", (item["url"], CATALYST_TYPE)).fetchone()
            if existing is not None:
                if existing["is_curated"]:
                    skipped += 1
                    continue
                conn.execute(
                    """UPDATE catalysts SET expected_date = ?, title = ?,
                           description = ?, asset_id = ?, updated_at = datetime('now')
                         WHERE id = ?""",
                    (item["on"], title, description, asset_id, existing["id"]))
                updated += 1
                continue
            conn.execute(
                """INSERT INTO catalysts
                       (company_id, asset_id, catalyst_type, expected_date,
                        date_confidence, title, description, is_curated, source_url,
                        status)
                   VALUES (?, ?, ?, ?, 'confirmed', ?, ?, 0, ?, 'pending')""",
                (company_id, asset_id, CATALYST_TYPE, item["on"], title, description,
                 item["url"]))
            written += 1
        conn.commit()
    finally:
        conn.close()
    return {"written": written, "updated": updated, "skipped": skipped}
