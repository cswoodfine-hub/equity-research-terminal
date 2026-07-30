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
import deal_terms
import therapeutic_areas
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
"announced_date": str or null, "quote": str}]}
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
6. announced_date is the date the company announced this deal, taken from the text and \
written as YYYY-MM-DD; null when the text states no date for it. Do not infer or estimate \
a date.
7. quote is one sentence copied verbatim from the text that announces that deal."""


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


def _grounded_date(value, document: str) -> str | None:
    """A YYYY-MM-DD date the model returned, kept only when it appears in the filing in a
    common written form, so an announcement date is read from the text, never invented.
    Returns the ISO date or None."""
    try:
        date = dt.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None
    month = date.strftime("%B")
    forms = (f"{month} {date.day}, {date.year}", f"{month} {date.day}",
             f"{date.day} {month} {date.year}", f"{date.day} {month}",
             date.isoformat(), f"{date.month}/{date.day}/{date.year}")
    low = document.lower()
    return date.isoformat() if any(form.lower() in low for form in forms) else None


def _party_key(counterparty: str) -> str:
    """The first significant word of a party, the stable handle for de-duplication."""
    tokens = re.findall(r"[a-z0-9]{3,}", (counterparty or "").lower())
    return tokens[0] if tokens else (counterparty or "").lower()


def _validate_one(deal: dict, haystack: str, document: str) -> dict | None:
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
    # The model is asked for "value" and the table stores "announced_value": one name
    # for the model's reply, another for a number that is announced consideration and
    # never cash. The rename happens here, at the seam.
    return {"deal_type": deal_type, "counterparty": counterparty,
            "announced_value": value,
            "area": area, "announced_date": _grounded_date(deal.get("announced_date"),
                                                           document), "quote": quote}


def validate(reply: dict | None, document: str) -> list[dict]:
    """The deals in the reply that are grounded in the document, de-duplicated on the
    party. A deal a filing does not support drops out; a name, price or date the model
    produced from its own knowledge cannot become an event."""
    if not reply or not isinstance(reply.get("deals"), list):
        return []
    haystack = _normalise(document)
    out, seen = [], set()
    for deal in reply["deals"]:
        valid = _validate_one(deal or {}, haystack, document)
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
        # A headline recorded this deal first, from the news source, which reads the
        # parties off a press release. The filing is the company's own account of the
        # same deal, so it replaces the headline rather than sitting beside it.
        if r["counterparty"]:
            conn.execute(
                "DELETE FROM deals WHERE accession IS NULL AND company_id = ?"
                "  AND LOWER(COALESCE(counterparty, '')) = LOWER(?)",
                (filing["company_id"], r["counterparty"]))
        # The announcement date read from the release when it is on or before the filing
        # date, otherwise the filing date. The market saw the deal on the earlier of the
        # two, and a date later than the filing is not the announcement.
        announced = r.get("announced_date")
        event_date = (announced if announced and announced <= filing["filed_date"]
                      else filing["filed_date"])
        conn.execute(
            """
            INSERT INTO deals
                (accession, company_id, deal_type, counterparty, announced_value,
                 announced_value_source, area, event_date, quote, source_url)
            VALUES (?, ?, ?, ?, ?,
                    CASE WHEN ? IS NULL THEN NULL ELSE 'filing' END, ?, ?, ?, ?)
            """,
            (filing["accession"], filing["company_id"], r["deal_type"], r["counterparty"],
             r["announced_value"], r["announced_value"], r["area"], event_date,
             r["quote"], filing["url"]))


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


# --- reading deals for the note and the Key insights tab -----------------
_DEAL_VERB = {"acquisition": "Acquired", "licensing": "Licensing deal with",
              "collaboration": "Collaboration with", "divestiture": "Divested to"}
# The headline figure inside a stored value, which sometimes carries the whole
# consideration clause; the reader wants the number, not the paragraph.
_VALUE_HEAD = re.compile(
    r"\$[\d.,]+\s*(?:billion|million|bn|mn|per\s*share|/\s*share)", re.I)


def short_value(value: str | None) -> str | None:
    if not value:
        return None
    match = _VALUE_HEAD.search(value)
    if match:
        return match.group(0)
    return value if len(value) <= 40 else None


_MAGNITUDE = {"billion": 1e9, "bn": 1e9, "b": 1e9,
              "million": 1e6, "mn": 1e6, "m": 1e6}
_AMOUNT = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*(billion|bn|b|million|mn|m)\b", re.I)


def deal_area(deal: dict) -> str | None:
    """The therapeutic area a deal lands in, or None when its words name no disease.

    Read through the same classifier the trials use, so a deal and the pipeline it joins
    are described in one vocabulary rather than two. Both the stated area and the
    announcing sentence are given to it, since a headline often names the disease where
    the area names only the modality.

    A modality is not a disease: "in vivo CAR-T cell therapies" says how, not what, and
    comes back None rather than being guessed into oncology.
    """
    text = " ".join(str(deal.get(f) or "") for f in ("area", "quote")).strip()
    if not text:
        return None
    area = therapeutic_areas.classify([text])
    return None if area == therapeutic_areas.OTHER else area


def announced_usd(text: str | None) -> float | None:
    """The announced consideration as a number, or None when the text states none.

    Derived from the words, never a substitute for them: "up to $3.8 billion" becomes
    3.8e9 for sorting and totalling, and the "up to" survives in the text beside it. A
    per-share price is not a deal size, so it is left as None rather than read as one.
    """
    if not text or re.search(r"per\s*share|/\s*share", text, re.I):
        return None
    match = _AMOUNT.search(text)
    if not match:
        return None
    try:
        amount = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return amount * _MAGNITUDE[match.group(2).lower()]


def short_party(counterparty: str | None) -> str:
    """The name trimmed of a trailing corporate structure, so "X, (Y Group), through its
    subsidiary Z" reads as the name it is known by. Only a long value is trimmed."""
    counterparty = (counterparty or "").strip()
    if len(counterparty) <= 50:
        return counterparty
    head = re.split(r"[,(]", counterparty, 1)[0].strip()
    return head or counterparty[:50]


def recent_rows(conn, cid: int, today=None, within_days: int = 400,
                limit: int = 6) -> list[dict]:
    """The company's recent deals, one per counterparty. A deal filed more than once
    (agreed, completed, recapped in earnings) is de-duplicated on the party, keeping the
    earliest date, when the market first saw it, and the announced value from whichever
    filing states it. That value is the consideration an announcement stated, milestones
    and all, and is never the cash the cash flow statement reports.

    Where the press release stated the structure, the four commitments ride along too, so
    a reader sees what is being paid now against what is contingent rather than one figure
    standing for both.
    """
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=within_days)).isoformat()
    rows = conn.execute(
        """
        SELECT deal_type, counterparty, announced_value, announced_value_source,
               area, event_date, event_date_source, source_url, article_url,
               upfront_usd, equity_usd, milestones_usd, option_usd, total_usd,
               headline_usd, terms_evidence
          FROM deals
         WHERE company_id = ? AND deal_type IN
               ('acquisition', 'licensing', 'collaboration', 'divestiture')
               AND counterparty IS NOT NULL AND event_date IS NOT NULL
         ORDER BY event_date ASC
        """, (cid,)).fetchall()
    merged: dict = {}
    for r in rows:
        key = _party_key(r["counterparty"])
        deal = merged.get(key)
        if deal is None:
            merged[key] = {"deal_type": r["deal_type"],
                           "counterparty": short_party(r["counterparty"]),
                           "announced_value": r["announced_value"],
                           "announced_value_source": r["announced_value_source"],
                           "area": r["area"], "event_date": r["event_date"],
                           "event_date_source": r["event_date_source"],
                           "source_url": r["source_url"],
                           "article_url": r["article_url"],
                           "terms": {f: r[f + "_usd"] for f in deal_terms.FIELDS},
                           "headline_usd": r["headline_usd"],
                           "terms_evidence": r["terms_evidence"]}
        else:
            deal["article_url"] = deal["article_url"] or r["article_url"]
            if not deal["announced_value"] and r["announced_value"]:
                deal["announced_value"] = r["announced_value"]
                deal["announced_value_source"] = r["announced_value_source"]
            deal["area"] = deal["area"] or r["area"]
            # The filing that states the terms is often not the one that announced it:
            # a deal arrives on a wire and its structure lands with the 8-K.
            if not deal["headline_usd"] and r["headline_usd"]:
                deal["terms"] = {f: r[f + "_usd"] for f in deal_terms.FIELDS}
                deal["headline_usd"] = r["headline_usd"]
                deal["terms_evidence"] = r["terms_evidence"]
    kept = [d for d in merged.values() if (d["event_date"] or "") >= cutoff]
    for deal in kept:
        deal["announced_value"] = short_value(deal["announced_value"])
        deal["announced_usd"] = announced_usd(deal["announced_value"])
        deal["terms_summary"] = deal_terms.summary(deal["terms"])
        # The stated structure is the better figure where there is one: a wire's "$2.58
        # billion" is the option price, and the deal is also 785m of cash today.
        if deal["headline_usd"]:
            deal["announced_usd"] = deal["headline_usd"]
    kept.sort(key=lambda d: d["event_date"] or "", reverse=True)
    return kept[:limit]


def deal_line(deal: dict) -> str:
    """One deal as a sentence for the note.

    The structure where the filing gave one, because "for $2.58 billion" and "785m
    upfront of which 465m is equity, and 2.58bn only on the option" are different
    sentences about the same deal and only the second is one a reader can act on.
    """
    parts = [f"{_DEAL_VERB.get(deal['deal_type'], 'Deal with')} {deal['counterparty']}"]
    if deal.get("terms_summary"):
        parts.append(f"for {deal['terms_summary']}")
    elif deal.get("announced_value"):
        parts.append(f"for {deal['announced_value']}")
    if deal.get("area"):
        parts.append(f"({deal['area']})")
    return " ".join(parts) + f", {(deal['event_date'] or '')[:10]}."


def recent(db_path=None, ticker: str = "", today=None, within_days: int = 400,
           limit: int = 6) -> list[dict]:
    """Recent deals for a ticker, structured for the Key insights tab."""
    conn = db.get_connection(db_path)
    try:
        row = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                           (ticker.upper(),)).fetchone()
        return recent_rows(conn, row["id"], today, within_days, limit) if row else []
    finally:
        conn.close()


# --- the terms behind the headline -----------------------------------------------------

# How far either side of a deal's date to look for the filing that carries its terms. A
# news wire runs the headline the morning of the 8-K; a deal recapped in an earnings
# release can be a few days out.
TERMS_WINDOW_DAYS = 5

# The counterparty has to appear in the document, or the terms belong to another deal. J&J
# furnished two press releases with one 8-K on the same day, Firefly at 1bn and Sail at
# 2.58bn, and a match on the filing alone would have given each the other's numbers.
_PARTY_HEAD = re.compile(r"^[A-Za-z0-9&'\-\. ]+?(?=\s*(?:,|\(|Inc|LLC|Ltd|plc|AG|SE|N\.V|$))")


def party_head(counterparty: str) -> str:
    """The distinctive part of a party's name, for finding it in a document."""
    match = _PARTY_HEAD.match((counterparty or "").strip())
    head = (match.group(0) if match else counterparty or "").strip(" ,.")
    return head


def terms_documents(conn, company_id: int, event_date: str) -> list:
    """The stored filing text around a deal's date that could carry its terms.

    Reads what the filing-text fetcher already stored rather than going back to the
    network, so this costs nothing and runs whatever the refresh order.
    """
    if not event_date:
        return []
    day = (event_date or "")[:10]
    start = (dt.date.fromisoformat(day) - dt.timedelta(days=TERMS_WINDOW_DAYS)).isoformat()
    end = (dt.date.fromisoformat(day) + dt.timedelta(days=TERMS_WINDOW_DAYS)).isoformat()
    return [dict(r) for r in conn.execute(
        "SELECT accession, form_type, filed_date, section, text FROM filing_sections"
        "  WHERE company_id = ? AND (section LIKE 'exhibit%' OR section = 'body')"
        "    AND filed_date BETWEEN ? AND ? AND text IS NOT NULL"
        "  ORDER BY (section LIKE 'exhibit%') DESC, filed_date",
        (company_id, start, end))]


def enrich(db_path=None) -> dict:
    """Fill in the payment structure of every deal that has none.

    A deal caught from a news headline arrives with a counterparty and nothing else. The
    press release furnished with the same day's 8-K states what it pays, and that text is
    already stored, so the two are matched on the party's name appearing in the document.
    """
    conn = db.get_connection(db_path)
    filled = 0
    try:
        pending = conn.execute(
            "SELECT id, company_id, counterparty, event_date FROM deals"
            "  WHERE headline_usd IS NULL AND counterparty IS NOT NULL").fetchall()
        for deal in pending:
            head = party_head(deal["counterparty"])
            if len(head) < 3:
                continue
            for document in terms_documents(conn, deal["company_id"], deal["event_date"]):
                if head.lower() not in (document["text"] or "").lower():
                    continue
                terms = deal_terms.parse(document["text"])
                size = deal_terms.headline(terms)
                if size is None:
                    continue
                conn.execute(
                    "UPDATE deals SET upfront_usd = ?, equity_usd = ?, milestones_usd = ?,"
                    "  option_usd = ?, total_usd = ?, headline_usd = ?,"
                    "  terms_evidence = ?, terms_source = ? WHERE id = ?",
                    (terms["upfront"], terms["equity"], terms["milestones"],
                     terms["option"], terms["total"], size, terms["evidence"],
                     document["accession"], deal["id"]))
                filled += 1
                break
        conn.commit()
    finally:
        conn.close()
    return {"filled": filled}
