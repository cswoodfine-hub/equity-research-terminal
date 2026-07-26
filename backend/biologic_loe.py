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
brand named in the brand list, the year its United States patents or regulatory \
exclusivity expire, or the year biosimilar or generic competition is expected to begin.

Return JSON only, no prose:
{"findings": [{"brand": str, "year": int, "quote": str}]}

Rules, in order of importance:
1. Only report a year the text states for that brand. If the text gives no year for a \
brand, leave it out. A year you know from outside the text is wrong here.
2. "quote" must be copied verbatim from the text, one sentence, naming the brand and \
the year.
3. Report the year US exclusivity is lost or biosimilar or generic competition begins, \
not a launch year, an approval year, or a date outside the United States.
4. "brand" must be spelled exactly as it appears in the brand list."""


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


def validate_finding(finding: dict, document: str, brands: list[str],
                     today=None) -> dict | None:
    """A finding reduced to {brand, year, quote}, or None when it fails a check.

    The brand must be one we asked about, the year must parse and sit in a plausible
    forward window, and the quote must be a run of the document that names the year, so a
    number the model supplied from its own knowledge cannot get through."""
    today = today or dt.date.today()
    brand_raw = (finding.get("brand") or "").strip()
    brand = next((b for b in brands if _normalise(b) == _normalise(brand_raw)), None)
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


def extract_disclosed(text: str, brands: list[str], complete=None) -> dict:
    """{brand: {year, quote}} for the brands a 10-K discloses a cliff year for. Empty
    when no model is configured or nothing validates."""
    complete = complete or (llm.complete if llm.provider() is not None else None)
    if complete is None or not text or not brands:
        return {}
    user = ("Brand list: " + ", ".join(brands) + "\n\nRisk factors text:\n"
            + text[:_MAX_CHARS] + "\n\nReport a cliff year for each brand the text gives "
            "one for.")
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
        valid = validate_finding(finding, text, brands)
        if valid:
            out[valid["brand"]] = {"year": valid["year"], "quote": valid["quote"]}
    return out


def _targets(conn):
    """Revenue-bearing biologics that the valuation cannot already price on a published
    non-orphan Orange or Purple Book date, grouped by company."""
    rows = conn.execute(
        """
        SELECT c.id AS company_id, c.ticker, a.id AS asset_id, a.brand_name,
               (SELECT MIN(ap.approval_date) FROM approvals ap
                 WHERE ap.asset_id = a.id) AS first_approval
          FROM assets a
          JOIN companies c ON c.id = a.owner_company_id
         WHERE a.brand_name IS NOT NULL
           AND LOWER(COALESCE(a.modality, '')) LIKE 'bio%'
           AND EXISTS (SELECT 1 FROM asset_revenue r WHERE r.asset_id = a.id)
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
                                "first_approval": row["first_approval"]})
    return by_company


def _latest_risk_factors(conn, company_id: int):
    return conn.execute(
        "SELECT text, source_url FROM ("
        "  SELECT fs.text AS text, f.url AS source_url, fs.filed_date FROM filing_sections fs"
        "  LEFT JOIN filings f ON f.accession = fs.accession"
        "  WHERE fs.company_id = ? AND fs.form_type = '10-K' AND fs.section = 'risk_factors'"
        "  ORDER BY fs.filed_date DESC LIMIT 1)",
        (company_id,)).fetchone()


def derive(db_path=None, complete=None, today=None) -> dict:
    """Derive and store a biologic LOE per target asset. Idempotent on the asset.

    The floor is set for every target from its approval; the disclosed year is added when
    a model reads one out of the company's latest 10-K risk factors. The effective date
    is the later of the two.
    """
    today = today or dt.date.today()
    has_model = complete is not None or llm.provider() is not None
    conn = db.get_connection(db_path)
    derived = disclosed_used = 0
    try:
        targets = _targets(conn)
        for company_id, info in targets.items():
            brands = [a["brand"] for a in info["assets"]]
            disclosed, source_url = {}, None
            rf = _latest_risk_factors(conn, company_id)
            if rf and has_model:
                disclosed = extract_disclosed(rf["text"], brands, complete)
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
                    "SELECT disclosed_year, evidence, source_url FROM biologic_loe"
                    " WHERE asset_id = ?", (asset["asset_id"],)).fetchone()
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
