"""Biologic loss of exclusivity, derived for the valuation.

A small molecule's cliff is in the Orange Book; a biologic's is not published anywhere
free. This builds one from two things already on file. The floor is the 12-year BPCIA
reference-product exclusivity, counted from the earliest approval: a biosimilar cannot
enter before it, so it is a hard minimum and needs no model. The refinement is the
patent or biosimilar-entry year the company states in its own 10-K risk factors, read
over the LLM seam. The effective date is the later of the two, since patents can protect
a biologic past its 12-year exclusivity but never bring a biosimilar in before it, and
that same rule turns the disclosure into a check on itself: a disclosed year below the
floor is a misread and is dropped in favour of the floor.

Like the PDUFA extractor, the model here is a reader, not a source. Every disclosed year
must come with a sentence copied from the filing that names the brand and the year, and
the brand must be one we asked about. Without a model the whole layer still runs and
returns the floor, so the valuation degrades to the conservative number rather than to
nothing.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time

import db
import llm

# A free-tier model rate-limits a burst of calls, so the per-company reads are spaced.
_SLEEP_S = 5
STATUTORY_YEARS = 12                 # BPCIA reference-product exclusivity
MAX_HORIZON_YEARS = 25               # a cliff more than 25 years out is a misread
_MAX_CHARS = 60_000
# Generous, because a Gemini 2.5 "thinking" model spends output tokens on reasoning
# before the JSON, and a tight budget returns a truncated findings list.
MAX_TOKENS = 3000

SYSTEM_PROMPT = """You read a pharmaceutical company's risk factors and report, for each \
name in the name list, the year its United States patents or regulatory exclusivity \
expire, or the year biosimilar or generic competition is expected to begin. The list \
gives each product's brand and generic name; the text may use either.

Return JSON only, no prose:
{"findings": [{"brand": str, "year": int, "quote": str}]}

Rules, in order of importance:
1. Only report a year the text states for that product. If the text gives no year for a \
product, leave it out. A year you know from outside the text is wrong here.
2. "quote" must be copied verbatim from the text, one sentence, naming the product and \
the year.
3. Report the year US exclusivity is lost or biosimilar or generic competition begins, \
not a launch year, an approval year, or a date outside the United States.
4. If several years are given for one product, report the latest, since protection runs \
until the last of them.
5. "brand" must be one of the names in the list, spelled exactly as it appears there."""


def statutory_floor_year(approval_date: str | None) -> int | None:
    """The 12-year BPCIA exclusivity floor from an approval date. None when the date is
    missing or unparseable, so nothing is invented from a blank."""
    try:
        return int(str(approval_date)[:4]) + STATUTORY_YEARS
    except (ValueError, TypeError):
        return None


def parse_reply(raw: str) -> list[dict]:
    """The model's findings list, or empty when the reply is unusable. Never raises."""
    if not raw:
        return []
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return []
    try:
        payload = json.loads(match.group(0))
    except (ValueError, TypeError):
        return []
    findings = payload.get("findings") if isinstance(payload, dict) else None
    return [f for f in findings if isinstance(f, dict)] if findings else []


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def validate_finding(finding: dict, document: str, name_map: dict,
                     today=None) -> dict | None:
    """A finding reduced to {brand, year, quote}, or None when it fails a check.

    The name must resolve to a product we asked about, by brand or generic; the year must
    parse and sit in a plausible forward window; and the quote must be a run of the
    document that names the year, so a number the model supplied from its own knowledge
    cannot get through. brand is the canonical brand, not the name the model echoed."""
    today = today or dt.date.today()
    brand = name_map.get(_normalise(finding.get("brand") or ""))
    if not brand:
        return None
    try:
        year = int(finding.get("year"))
    except (ValueError, TypeError):
        return None
    if not today.year <= year <= today.year + MAX_HORIZON_YEARS:
        return None
    quote = (finding.get("quote") or "").strip()
    needle = _normalise(quote)
    haystack = _normalise(document)
    if len(needle) < 25 or needle[:120] not in haystack or str(year) not in quote:
        return None                       # the year must be in a sentence from the filing
    return {"brand": brand, "year": year, "quote": quote}


def extract_disclosed(text: str, names: dict, complete=None) -> dict:
    """{brand: {year, quote}} for the products a 10-K discloses a cliff year for, keyed on
    the canonical brand and keeping the latest year when several are stated. ``names`` maps
    each display name, a brand or a generic, to its brand. Empty without a model or a
    match."""
    complete = complete or (llm.complete if llm.provider() is not None else None)
    if complete is None or not text or not names:
        return {}
    norm_map = {_normalise(display): brand for display, brand in names.items()}
    user = ("Name list: " + ", ".join(sorted(names)) + "\n\nFiling text:\n"
            + text[:_MAX_CHARS]
            + "\n\nReport a cliff year for each product the text gives one for.")
    reply = None
    for attempt in range(2):
        try:
            reply = complete(SYSTEM_PROMPT, user, MAX_TOKENS)
            break
        except Exception:                 # a rate limit clears on the next window
            if attempt == 0:
                time.sleep(20)
    if reply is None:
        return {}                         # a model outage leaves the floor in place
    out = {}
    for finding in parse_reply(reply):
        valid = validate_finding(finding, text, norm_map)
        # Keep the latest year for a product, since protection runs until the last one.
        if valid and valid["year"] > out.get(valid["brand"], {}).get("year", 0):
            out[valid["brand"]] = {"year": valid["year"], "quote": valid["quote"]}
    return out


def _targets(conn):
    """Revenue-bearing biologics that the valuation cannot already price on a published
    non-orphan Orange or Purple Book date, grouped by company."""
    rows = conn.execute(
        """
        SELECT c.id AS company_id, c.ticker, a.id AS asset_id, a.brand_name,
               a.generic_name,
               (SELECT MIN(ap.approval_date) FROM approvals ap
                 WHERE ap.asset_id = a.id) AS first_approval
          FROM assets a
          JOIN companies c ON c.id = a.owner_company_id
         WHERE a.brand_name IS NOT NULL
           AND LOWER(COALESCE(a.modality, '')) LIKE 'bio%'
           AND EXISTS (SELECT 1 FROM asset_revenue r WHERE r.asset_id = a.id
                         AND r.period = 'FY')
           AND COALESCE((SELECT MAX(e.expiry_date) FROM exclusivities e
                          WHERE e.asset_id = a.id
                            AND e.protection_type != 'orphan exclusivity'), '') = ''
        """
    ).fetchall()
    by_company: dict[int, dict] = {}
    for row in rows:
        entry = by_company.setdefault(row["company_id"],
                                      {"ticker": row["ticker"], "assets": []})
        entry["assets"].append({"asset_id": row["asset_id"],
                                "brand": row["brand_name"],
                                "generic": row["generic_name"],
                                "first_approval": row["first_approval"]})
    return by_company


def _names_map(assets) -> dict:
    """{display name: brand} over each product's brand and generic, so the model can name
    a product either way and the finding still resolves to the brand."""
    names = {}
    for asset in assets:
        names[asset["brand"]] = asset["brand"]
        if asset.get("generic"):
            names[asset["generic"]] = asset["brand"]
    return names


def _latest_10k_text(conn, company_id: int):
    """The risk factors and harvested patent passages of the company's latest 10-K, joined,
    with the filing url. This is where a stated biologic cliff year lives."""
    row = conn.execute(
        "SELECT MAX(filed_date) AS d FROM filing_sections"
        " WHERE company_id = ? AND form_type = '10-K'", (company_id,)).fetchone()
    if not row or not row["d"]:
        return None
    parts = conn.execute(
        "SELECT fs.section, fs.text, f.url FROM filing_sections fs"
        " LEFT JOIN filings f ON f.accession = fs.accession"
        " WHERE fs.company_id = ? AND fs.form_type = '10-K' AND fs.filed_date = ?"
        "   AND fs.section IN ('risk_factors', 'patents')",
        (company_id, row["d"])).fetchall()
    if not parts:
        return None
    text = "\n\n".join(p["text"] for p in parts if p["text"])
    url = next((p["url"] for p in parts if p["url"]), None)
    return {"text": text, "source_url": url}


def derive(db_path=None, complete=None, today=None) -> dict:
    """Derive and store a biologic LOE per target asset. Idempotent on the asset.

    The floor is set for every target from its approval; the disclosed year is added when
    a model reads one out of the company's latest 10-K, from its risk factors and the
    patent passages harvested from it. The effective date is the later of the two.
    """
    today = today or dt.date.today()
    has_model = complete is not None or llm.provider() is not None
    conn = db.get_connection(db_path)
    derived = disclosed_used = 0
    try:
        targets = _targets(conn)
        for company_id, info in targets.items():
            disclosed, source_url = {}, None
            rf = _latest_10k_text(conn, company_id)
            if rf and has_model:
                disclosed = extract_disclosed(rf["text"], _names_map(info["assets"]),
                                              complete)
                source_url = rf["source_url"]
                if complete is None:          # a real provider call; space under its limit
                    time.sleep(_SLEEP_S)
            for asset in info["assets"]:
                floor = statutory_floor_year(asset["first_approval"])
                found = disclosed.get(asset["brand"])
                # A disclosure is sticky: once read from a 10-K it is kept, so a later
                # run the model rate-limited does not wipe it back to the floor. A fresh
                # disclosure overrides the stored one.
                prior = conn.execute(
                    "SELECT disclosed_year, evidence, source_url, is_curated"
                    " FROM biologic_loe WHERE asset_id = ?",
                    (asset["asset_id"],)).fetchone()
                # A curated row is an analyst's reading of the filing and outranks this
                # reader's. Keytruda's 10-K says biosimilar competition could begin in
                # December 2028; the sentence also names the 2029 patent expiries, and
                # the regex took those. The table has had an is_curated column for this
                # since it was created and the upsert below never consulted it.
                if prior and prior["is_curated"]:
                    continue
                if found:
                    disclosed_year, evidence, src = found["year"], found["quote"], source_url
                elif prior and prior["disclosed_year"] is not None:
                    disclosed_year = prior["disclosed_year"]
                    evidence, src = prior["evidence"], prior["source_url"]
                else:
                    disclosed_year, evidence, src = None, None, None
                years = [y for y in (floor, disclosed_year) if y is not None]
                if not years:
                    continue              # neither an approval nor a disclosure: no basis
                loe_year = max(years)
                if floor and disclosed_year:
                    basis = "10-K and statutory floor"
                elif disclosed_year:
                    basis = "10-K disclosure"
                else:
                    basis = "statutory floor"
                conn.execute(
                    """
                    INSERT INTO biologic_loe
                        (asset_id, loe_year, loe_date, basis, floor_year,
                         disclosed_year, evidence, source_url, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(asset_id) DO UPDATE SET
                        loe_year = excluded.loe_year, loe_date = excluded.loe_date,
                        basis = excluded.basis, floor_year = excluded.floor_year,
                        disclosed_year = excluded.disclosed_year,
                        evidence = excluded.evidence, source_url = excluded.source_url,
                        fetched_at = datetime('now')
                    """,
                    (asset["asset_id"], loe_year, f"{loe_year}-06-30", basis, floor,
                     disclosed_year, evidence, src))
                derived += 1
                disclosed_used += 1 if disclosed_year else 0
        conn.commit()
    finally:
        conn.close()
    status = "ok" if has_model else "floor only (no model configured)"
    return {"status": status, "derived": derived, "from_disclosure": disclosed_used}
