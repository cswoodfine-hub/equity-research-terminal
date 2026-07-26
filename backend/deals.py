"""M&A, licensing and collaboration deals, read from the filings that announce them.

A deal reshapes a portfolio more than almost anything else, but a US 8-K names only the
category of the event, "Material agreement signed", not the party or the price. Those
live in the EX-99 press release the 8-K attaches; a foreign filer's 6-K carries the
release in its body. This reads them out, the same way the trial-readout and PDUFA
extractors read theirs.

The model is a reader, not a source. A filing counts as a deal only when it announces
the company entering, agreeing, completing or terminating an acquisition, licence,
collaboration or divestiture with a named party, that party appears in the text, and the
sentence quoted for it appears too. A deal value is kept only when it appears verbatim,
so no number is ever invented. Anything short of that is read and recorded as no deal so
it is not fetched again, but never becomes an event.

Without a model the module does nothing and says so; the note then simply has no deals,
which is the honest state rather than an invented one.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
import urllib.request

import db
import llm
import pdufa                     # reuse strip_html, parse_reply and the fatal-error test

LOOKBACK_DAYS = 400              # a deal stays the story for a year, longer than a readout
# gemini-flash-latest thinks before it answers; at a small budget the reasoning eats it
# all and the JSON truncates mid-field. A budget caps the reasoning and the ceiling is
# set well above it, so the whole record comes back.
MAX_TOKENS = 2048
THINKING_BUDGET = 256
_TIMEOUT_S = 30
MAX_PER_RUN = 300

# A filing whose title could be a deal: the US item-mapped titles (item 1.01 "Material
# agreement", item 2.01 "Acquisition or disposition") and the descriptive language a
# foreign 6-K uses. Broad on purpose; the model decides and marks the rest as no deal.
_DEAL_TITLE = re.compile(
    r"material agreement|acquisition or disposition|\bacqui|\bmerger|tender offer|"
    r"licen[sc]|collaborat|deal with|to acquire|divest|takeover|to buy", re.I)
# A cheap local gate before the model: the text must read like a deal announcement.
HINT = re.compile(
    r"acqui|merger|to acquire|tender offer|licens|collaborat|definitive agreement|"
    r"per share|upfront|milestone|equity value|enterprise value|all-cash", re.I)

_DEAL_TYPES = ("acquisition", "licensing", "collaboration", "divestiture")

SYSTEM_PROMPT = """You read a company's filing or press release and decide whether it \
announces a business-development deal: an acquisition, a licensing deal, a collaboration \
or a divestiture, and you extract its terms.

Return JSON only, no prose:
{"found": bool,
 "deal_type": "acquisition" or "licensing" or "collaboration" or "divestiture" or null,
 "counterparty": str or null, "value": str or null, "area": str or null,
 "quote": str or null}

Rules, in order of importance:
1. found is true ONLY when the text announces the company entering, agreeing, completing \
or terminating a deal with another NAMED party. A routine supply, manufacturing, debt or \
financing agreement, an internal reorganisation, a clinical result or a product launch \
is not a deal; return {"found": false}.
2. deal_type is "acquisition" when the company buys or merges with another company or its \
assets, "licensing" when it in-licenses or out-licenses a compound or technology, \
"collaboration" for a partnership or alliance, "divestiture" when it sells a business or \
asset.
3. counterparty is the other party, written exactly as the text writes it.
4. value is the single headline figure if the text states one, copied exactly and \
nothing more, for example "$7 billion" or "$72.50 per share"; not the whole consideration \
clause, and null when none is stated. Never compute or estimate it.
5. area is a short phrase for what the deal is for: the target's focus, therapeutic area, \
asset or modality, taken from the text.
6. quote is one sentence copied verbatim from the text that announces the deal."""


def _get(url: str) -> str:
    user_agent = (os.getenv("SEC_USER_AGENT") or "").strip()
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT is not set; EDGAR blocks anonymous requests")
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
        return resp.read().decode("utf-8", "replace")


def exhibit_url(primary_url: str, get=_get) -> str | None:
    """The EX-99 press-release document in the filing's folder, where a US 8-K keeps the
    deal release, or None. Read from the accession index."""
    base = "/".join(primary_url.split("/")[:-1])
    try:
        index = json.loads(get(base + "/index.json"))
    except Exception:
        return None
    for item in index.get("directory", {}).get("item", []):
        name = item.get("name", "")
        if re.search(r"ex.?99", name, re.I) and name.lower().endswith(
                (".htm", ".html", ".txt")):
            return f"{base}/{name}"
    return None


def deal_text(filing: dict, get=_get) -> str:
    """The text most likely to carry the terms. A US 8-K cover names the item category
    but not the party, so the EX-99 press release it attaches is preferred whenever there
    is one; a foreign 6-K carries the release in its own body."""
    if filing["form_type"] == "8-K":
        exhibit = exhibit_url(filing["url"], get)
        if exhibit:
            return pdufa.strip_html(get(exhibit))
    return pdufa.strip_html(get(filing["url"]))


def candidates(db_path=None, lookback_days: int = LOOKBACK_DAYS, today=None) -> list[dict]:
    """Recent 8-K and 6-K filings whose title could be a deal, not yet read."""
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=lookback_days)).isoformat()
    conn = db.get_connection(db_path)
    try:
        seen = {r["accession"] for r in conn.execute("SELECT accession FROM deals")}
        rows = [dict(r) for r in conn.execute(
            """
            SELECT f.accession, f.form_type, f.filed_date, f.url, f.title, f.company_id
              FROM filings f
             WHERE f.form_type IN ('8-K', '6-K') AND f.filed_date >= ?
               AND f.url IS NOT NULL AND f.url <> ''
               AND f.filed_date <= date('now', '-2 days')
             ORDER BY f.filed_date DESC
            """, (cutoff,))]
    finally:
        conn.close()
    return [r for r in rows
            if r["accession"] not in seen and _DEAL_TITLE.search(r["title"] or "")]


def parse_reply(raw: str) -> dict | None:
    return pdufa.parse_reply(raw)


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def validate(reply: dict | None, document: str) -> dict | None:
    """The classified deal, or None on any failure.

    The party and the quoted sentence must both be found in the document, so a name the
    model produced from its own knowledge cannot become an event, and a value is kept
    only when it appears verbatim, so a price is never rounded or invented."""
    if not reply or not reply.get("found"):
        return None
    deal_type = (reply.get("deal_type") or "").strip().lower()
    if deal_type not in _DEAL_TYPES:
        return None
    counterparty = (reply.get("counterparty") or "").strip()
    quote = (reply.get("quote") or "").strip()
    haystack = _normalise(document)
    if not counterparty or _normalise(counterparty) not in haystack:
        return None
    needle = _normalise(quote)
    if len(needle) < 25 or needle[:120] not in haystack:
        return None
    value = (reply.get("value") or "").strip() or None
    if value and _normalise(value) not in haystack:   # never keep an unverifiable price
        value = None
    area = (reply.get("area") or "").strip() or None
    return {"deal_type": deal_type, "counterparty": counterparty, "value": value,
            "area": area, "quote": quote}


def _classify(document: str, filing: dict, complete) -> dict | None:
    user = (f"Company filing type: {filing['form_type']}\nFiled: {filing['filed_date']}\n\n"
            f"Filing text:\n{document[:pdufa._MAX_CHARS]}\n\n"
            "Does this announce an acquisition, licensing, collaboration or divestiture?")
    reply = complete(SYSTEM_PROMPT, user, MAX_TOKENS, thinking_budget=THINKING_BUDGET)
    return validate(parse_reply(reply), document)


def _store(conn, filing: dict, result: dict | None) -> None:
    conn.execute(
        """
        INSERT INTO deals
            (accession, company_id, deal_type, counterparty, value, area, event_date,
             quote, source_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(accession) DO NOTHING
        """,
        (filing["accession"], filing["company_id"],
         result["deal_type"] if result else "none",
         result["counterparty"] if result else None,
         result["value"] if result else None, result["area"] if result else None,
         filing["filed_date"], result["quote"] if result else None, filing["url"]))


def extract(db_path=None, limit: int = MAX_PER_RUN, today=None) -> dict:
    """Read candidate filings and record the deals found. Idempotent: a filing already
    read is skipped, so a re-run costs only new filings."""
    if llm.provider() is None:
        return {"status": "no key", "read": 0, "deals": 0,
                "detail": "No model provider configured, so no deals were classified."}
    read = found = 0
    errors: list[str] = []
    for filing in candidates(db_path, today=today)[:limit]:
        try:
            document = deal_text(filing)
        except Exception as exc:
            errors.append(f"{filing['accession']}: {exc}")
            continue
        result = None
        if HINT.search(document):
            try:
                result = _classify(document, filing, llm.complete)
            except Exception as exc:
                if pdufa.is_fatal(exc):
                    errors.append(f"model: {exc}")
                    break
                continue
        conn = db.get_connection(db_path)
        try:
            _store(conn, filing, result)
            conn.commit()
        finally:
            conn.close()
        read += 1
        if result:
            found += 1
        time.sleep(0.3)                # polite to EDGAR and under the model's rate limit
    return {"status": "ok", "read": read, "deals": found, "errors": errors}
