"""M&A, licensing and collaboration deals, read from the filings that announce them.

A deal reshapes a portfolio more than almost anything else, but a US 8-K names only the
category of the event, "Material agreement signed", not the party or the price. Those
live in the press release the 8-K attaches; a foreign filer's 6-K carries the release in
its body; and a company can also fold several acquisitions into a line of its quarterly
earnings release. This reads them out, the same way the trial-readout and PDUFA
extractors read theirs.

The model is a reader, not a source. A deal counts only when the text announces the
company entering, agreeing, completing or terminating an acquisition, licence,
collaboration or divestiture with a named party, that party appears in the text, and the
sentence quoted for it appears too. A value is kept only when it appears verbatim, so no
number is ever invented. A filing that announces none is recorded as read so it is not
fetched again.

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
# gemini-flash-latest thinks before it answers, and one filing can carry several deals, so
# the budget must cover the reasoning and a list. The reasoning is capped and the ceiling
# set well above it, so the whole list comes back rather than truncating mid-field.
MAX_TOKENS = 3072
THINKING_BUDGET = 512
_TIMEOUT_S = 30
MAX_PER_RUN = 300

# A filing whose title could carry a deal: the US item-mapped titles for a material
# agreement or a completed acquisition, an other-events or an earnings 8-K (deals get
# folded into both), and the descriptive language a foreign 6-K uses. Broad on purpose;
# the text gate and the model decide, and a filing with no deal is marked read.
_DEAL_TITLE = re.compile(
    r"material agreement|acquisition or disposition|other events|results of operations|"
    r"\bacqui|\bmerger|tender offer|licen[sc]|collaborat|deal with|to acquire|divest|"
    r"takeover|to buy", re.I)
# A cheap local gate before the model: the text must read like a deal announcement.
HINT = re.compile(
    r"acqui|merger|to acquire|tender offer|licens|collaborat|definitive agreement|"
    r"per share|upfront|milestone|equity value|enterprise value|all-cash", re.I)
# Documents in a filing folder that are never the press release: the XBRL viewer renders,
# the index and header stubs, and the summary and metadata.
_SKIP_DOC = re.compile(r"^r\d+\.htm|index|headers|filingsummary|metalinks", re.I)

_DEAL_TYPES = ("acquisition", "licensing", "collaboration", "divestiture")

SYSTEM_PROMPT = """You read a company's filing or press release and list every \
business-development deal it ANNOUNCES: an acquisition, a licensing deal, a collaboration \
or a divestiture the company is entering, agreeing, completing or terminating. An \
earnings release can announce several at once, so return all of them.

Return JSON only, no prose:
{"deals": [{"deal_type": "acquisition" or "licensing" or "collaboration" or \
"divestiture", "counterparty": str, "value": str or null, "area": str or null, \
"quote": str}]}
Return {"deals": []} when the text announces none.

Rules, in order of importance:
1. Include a deal ONLY when the text announces the company itself entering, agreeing, \
completing or terminating it with another NAMED party. A retrospective mention of a past \
deal, a routine supply, manufacturing, debt or financing agreement, a clinical result or \
a product launch is not a deal to include.
2. deal_type is "acquisition" when the company buys or merges with another company or its \
assets, "licensing" when it in-licenses or out-licenses a compound or technology, \
"collaboration" for a partnership or alliance, "divestiture" when it sells a business or \
asset.
3. counterparty is the other party, written exactly as the text writes it.
4. value is the single headline figure for that deal if the text states one, copied \
exactly and nothing more, for example "$7 billion" or "$72.50 per share"; null when the \
text states none for it. Never compute or estimate it.
5. area is a short phrase for what that deal is for: the target's focus, therapeutic \
area, asset or modality, taken from the text.
6. quote is one sentence copied verbatim from the text that announces that deal."""


def _get(url: str) -> str:
    user_agent = (os.getenv("SEC_USER_AGENT") or "").strip()
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT is not set; EDGAR blocks anonymous requests")
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
        return resp.read().decode("utf-8", "replace")


def press_release_url(primary_url: str, get=_get) -> str | None:
    """The press-release document in the filing folder. It is preferred by name when one
    is called ex99, and otherwise is the largest content document, since a press release
    dwarfs the 8-K cover; the XBRL renders, index and metadata are skipped. This finds a
    release named descriptively, such as an earnings release, which a name match misses."""
    base = "/".join(primary_url.split("/")[:-1])
    primary_name = primary_url.split("/")[-1].lower()
    try:
        index = json.loads(get(base + "/index.json"))
    except Exception:
        return None
    largest, largest_size = None, -1
    for item in index.get("directory", {}).get("item", []):
        name = item.get("name", "")
        low = name.lower()
        if not low.endswith((".htm", ".html")) or low == primary_name or _SKIP_DOC.search(low):
            continue
        if re.search(r"ex.?99", low):
            return f"{base}/{name}"
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if size > largest_size:
            largest, largest_size = f"{base}/{name}", size
    return largest


def deal_text(filing: dict, get=_get) -> str:
    """The text most likely to carry the terms: for a US 8-K the press release it
    attaches, and for a foreign 6-K its own body, which is the release."""
    if filing["form_type"] == "8-K":
        release = press_release_url(filing["url"], get)
        if release:
            return pdufa.strip_html(get(release))
    return pdufa.strip_html(get(filing["url"]))


def candidates(db_path=None, lookback_days: int = LOOKBACK_DAYS, today=None) -> list[dict]:
    """Recent 8-K and 6-K filings whose title could carry a deal, not yet read."""
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=lookback_days)).isoformat()
    conn = db.get_connection(db_path)
    try:
        seen = {r["accession"] for r in conn.execute(
            "SELECT DISTINCT accession FROM deals")}
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


def _party_key(counterparty: str) -> str:
    """The first significant word of a party, the stable handle for de-duplication."""
    tokens = re.findall(r"[a-z0-9]{3,}", (counterparty or "").lower())
    return tokens[0] if tokens else (counterparty or "").lower()


def _validate_one(deal: dict, haystack: str) -> dict | None:
    deal_type = (deal.get("deal_type") or "").strip().lower()
    if deal_type not in _DEAL_TYPES:
        return None
    counterparty = (deal.get("counterparty") or "").strip()
    quote = (deal.get("quote") or "").strip()
    if not counterparty or _normalise(counterparty) not in haystack:
        return None
    needle = _normalise(quote)
    if len(needle) < 25 or needle[:120] not in haystack:
        return None
    value = (deal.get("value") or "").strip() or None
    if value and _normalise(value) not in haystack:   # never keep an unverifiable price
        value = None
    area = (deal.get("area") or "").strip() or None
    return {"deal_type": deal_type, "counterparty": counterparty, "value": value,
            "area": area, "quote": quote}


def validate(reply: dict | None, document: str) -> list[dict]:
    """The deals in the reply that are grounded in the document, de-duplicated on the
    party. A deal a filing does not support drops out; a name or price the model produced
    from its own knowledge cannot become an event."""
    if not reply or not isinstance(reply.get("deals"), list):
        return []
    haystack = _normalise(document)
    out, seen = [], set()
    for deal in reply["deals"]:
        valid = _validate_one(deal or {}, haystack)
        if not valid:
            continue
        key = _party_key(valid["counterparty"])
        if key not in seen:
            seen.add(key)
            out.append(valid)
    return out


def _classify(document: str, filing: dict, complete) -> list[dict]:
    user = (f"Company filing type: {filing['form_type']}\nFiled: {filing['filed_date']}\n\n"
            f"Filing text:\n{document[:pdufa._MAX_CHARS]}\n\n"
            "List every acquisition, licensing, collaboration or divestiture announced.")
    reply = complete(SYSTEM_PROMPT, user, MAX_TOKENS, thinking_budget=THINKING_BUDGET)
    return validate(parse_reply(reply), document)


def _store(conn, filing: dict, results: list[dict]) -> None:
    """One row per deal, or a single 'none' row so the filing is marked read. The
    accession is not unique, so a re-insert is prevented by the read-once guard in
    ``candidates`` rather than a conflict clause."""
    if not results:
        conn.execute(
            "INSERT INTO deals (accession, company_id, deal_type, event_date, source_url)"
            " VALUES (?, ?, 'none', ?, ?)",
            (filing["accession"], filing["company_id"], filing["filed_date"],
             filing["url"]))
        return
    for r in results:
        conn.execute(
            """
            INSERT INTO deals
                (accession, company_id, deal_type, counterparty, value, area, event_date,
                 quote, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (filing["accession"], filing["company_id"], r["deal_type"], r["counterparty"],
             r["value"], r["area"], filing["filed_date"], r["quote"], filing["url"]))


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
        results: list[dict] = []
        if HINT.search(document):
            try:
                results = _classify(document, filing, llm.complete)
            except Exception as exc:
                if pdufa.is_fatal(exc):
                    errors.append(f"model: {exc}")
                    break
                continue
        conn = db.get_connection(db_path)
        try:
            _store(conn, filing, results)
            conn.commit()
        finally:
            conn.close()
        read += 1
        found += len(results)
        time.sleep(0.3)                # polite to EDGAR and under the model's rate limit
    return {"status": "ok", "read": read, "deals": found, "errors": errors}
