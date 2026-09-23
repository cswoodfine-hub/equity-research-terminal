"""PDUFA dates extracted from 8-K and 6-K filings.

No free calendar of FDA decision dates exists, so the only route is the filings that
announce them: a company whose application is accepted files an 8-K saying so, and the
goal date is usually in the text. This module finds those filings, reads the document,
and asks the configured model (see llm) for the date.

The whole design assumes the model will sometimes be wrong, so nothing it returns is
trusted on its own:

* The date must parse, sit in the future, and fall inside a plausible review window.
  A PDUFA date more than three years out is not a PDUFA date.
* The product name it returns must appear in the filing text. A name the model supplied
  from its own knowledge rather than from the document is the exact failure this guards
  against, and it is the difference between extraction and invention.
* The quoted sentence it returns must appear in the filing text too, near-verbatim. If
  the model cannot point at where it read the date, the row is dropped.

Rows land with ``is_curated = 0`` and the filing URL as evidence, so every one can be
traced back to the document it came from and checked.

With no model provider configured the module does nothing and says so. The app runs
without one; the calendar carries registry readouts alone, which is what it did before.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
import urllib.request

import catalysts
import db
import llm

MAX_TOKENS = 1200
SOURCE = "8-K extraction"

# How far back to look for filings worth reading, and how far ahead a goal date may sit.
LOOKBACK_DAYS = 400
MAX_HORIZON_DAYS = 1100          # a review runs months, not years; three years is a typo
_TIMEOUT_S = 30
# EDGAR asks for under 10 requests a second. The gate now admits every untitled 6-K, so
# the fetch loop is several hundred documents on a full run rather than a few dozen, and
# the polite pause that was optional at that size is not optional at this one.
_FETCH_PAUSE_S = 0.15
_MAX_CHARS = 60_000              # an 8-K body is small; this is a guard, not a budget

# Filings worth spending a call on. An 8-K about results of operations never carries a
# goal date, and reading every filing would be most of them.
#
# The title is an SEC item description, which only a domestic 8-K reliably carries. A
# foreign private issuer files a 6-K whose title is the form name and nothing else, so
# gating on the title alone discarded every one of them unread: of 429 big pharma 8-K
# and 6-K filings in a 400 day window only 35 passed, and AstraZeneca, GSK, Novo,
# Novartis, Sanofi and Regeneron passed none at all. Those are six of the companies whose
# regulatory news this exists to find, which is why the gate now has three doors.
WORTH_READING = re.compile(
    r"other event|material agreement|regulation fd|material impairment|"
    r"material definitive", re.I)

# A 6-K cover carrying no item description. Its title says only what form it is, so the
# title cannot decide anything and the document itself has to be read. The body check in
# extract() is what actually refuses these, and it costs one fetch rather than a model
# call.
UNTITLED_6K = re.compile(r"^\s*(?:\d+\s*[-:]?\s*)?(?:form\s*)?6-?k\s*:?\s*$", re.I)

# Titles that are never a regulatory announcement. Only consulted for an untitled 6-K,
# never to override a positive signal, so widening the gate cannot lose a filing the
# narrower one already read.
NEVER_READING = re.compile(
    r"total voting rights|transaction in own shares|director/pdmr|holding\(s\) in company|"
    r"director or officer change|results of operations|annual report|"
    r"filing of form 20-f|notice of|publication of|block listing|share buy-?back|"
    r"rule 10b5-1|prospectus|proxy|agm\b|annual general meeting", re.I)

# Words that appear in a filing announcing an acceptance. Checked against the document
# text before the model is called at all, which is what keeps the call count sane.
REGULATORY_HINT = re.compile(
    r"PDUFA|prescription drug user fee|target action date|goal date|"
    r"accepted (?:the )?(?:our )?(?:new drug|biologics licen[cs]e|supplemental)|"
    r"priority review|BsUFA", re.I)

SYSTEM_PROMPT = """You extract FDA decision dates from SEC filings.

Return JSON only, no prose, matching:
{"found": bool, "date": "YYYY-MM-DD" or null, "product": str or null,
 "indication": str or null, "quote": str or null}

Rules, in order of importance:
1. Only report a date the filing states. If the filing does not give a specific FDA
   action date, return {"found": false}. A date you know from elsewhere is wrong here.
2. "quote" must be copied verbatim from the filing, one sentence, containing the date.
3. "product" must be written exactly as the filing writes it.
4. A PDUFA date, target action date, or goal date is what you are looking for. A
   submission date, an acceptance date, or a data readout is not. If the filing gives
   only the date the application was submitted or accepted, return {"found": false}.
5. If several are given, take the one for the application the filing is announcing."""


def strip_html(raw: str) -> str:
    """Filing text from an EDGAR HTML document. Crude on purpose: the model only needs
    the prose, and a parser dependency for this would be a poor trade."""
    text = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&#8217;", "'").replace("&#8220;", '"')
                .replace("&#8221;", '"').replace("&#146;", "'"))
    return re.sub(r"\s+", " ", text).strip()[:_MAX_CHARS]


def candidates(db_path=None, lookback_days: int = LOOKBACK_DAYS,
               today=None) -> list[dict]:
    """Filings recent enough and of a kind that might announce a goal date."""
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=lookback_days)).isoformat()
    conn = db.get_connection(db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            """
            SELECT f.id, f.accession, f.form_type, f.filed_date, f.title, f.url,
                   c.ticker
              FROM filings f JOIN companies c ON c.id = f.company_id
             WHERE f.form_type IN ('8-K', '6-K') AND f.filed_date >= ?
               AND f.url IS NOT NULL AND f.url <> ''
             ORDER BY f.filed_date DESC
            """,
            (cutoff,),
        )]
    finally:
        conn.close()
    return [r for r in rows if worth_reading(r["form_type"], r["title"])]


def worth_reading(form_type: str | None, title: str | None) -> bool:
    """Whether a filing is worth fetching. Pure, so the gate can be argued with.

    Three doors, in order. A title that states a regulatory event is taken whatever the
    form, which is how an all-capitals 6-K cover reading "BEPIROVIRSEN PRIORITY REVIEW
    US FILING ACCEPTANCE" gets read. A title that is only the form name is taken because
    it says nothing either way and the body has to settle it. Everything else needs the
    SEC item description an 8-K carries. A title on the refusal list is taken by none of
    the three.
    """
    text = (title or "").strip()
    # A positive signal is never overridden by the refusal list. An 8-K titled "Results
    # of operations, Other events" carries both, and refusing it on the first half is
    # how a widened gate would quietly lose filings the narrow one already read.
    if REGULATORY_HINT.search(text) or WORTH_READING.search(text):
        return True
    if (form_type or "").upper().replace("-", "") == "6K" and (
            not text or UNTITLED_6K.match(text)):
        return not NEVER_READING.search(text)
    return False


def _fetch(url: str) -> str:
    user_agent = (os.getenv("SEC_USER_AGENT") or "").strip()
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT is not set; EDGAR blocks anonymous requests")
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
        return resp.read().decode("utf-8", "replace")


def exhibit_url(primary_url: str, get=None) -> str | None:
    """The EX-99 press-release document in the filing's folder, or None.

    A filing's primary document is often only a cover sheet. Novo Nordisk's 6-K cover is
    4,239 characters of address and check boxes and Sanofi's is 1,229, with the
    announcement itself in an attached exhibit. Reading the cover alone is why a run over
    585 filings found nineteen worth reading: it was looking at envelopes.
    """
    get = get or _fetch
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


def filing_text(filing: dict, get=None) -> str:
    """The text most likely to carry a goal date: the primary document, or the EX-99
    exhibit where the primary carries no regulatory language.

    Applies to a 6-K as well as an 8-K. Restricting the fallback to domestic filings is
    what kept every foreign filer's announcement out of reach, and a foreign filer is
    exactly who files a bare cover.
    """
    get = get or _fetch
    text = strip_html(get(filing["url"]))
    if REGULATORY_HINT.search(text):
        return text
    exhibit = exhibit_url(filing["url"], get)
    if exhibit:
        time.sleep(_FETCH_PAUSE_S)
        return strip_html(get(exhibit))
    return text


def parse_reply(raw: str) -> dict | None:
    """The model's JSON, or None when it is unusable. Never raises."""
    if not raw:
        return None
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def validate(reply: dict | None, document: str, today=None,
             max_horizon_days: int = MAX_HORIZON_DAYS) -> dict | None:
    """The extracted row, or None when it fails any check.

    This is the part that matters. The model is a reader here, not a source, and every
    check below asks the same question: is this in the document, or did it come from
    somewhere else?
    """
    today = today or dt.date.today()
    if not reply or not reply.get("found"):
        return None
    try:
        when = dt.date.fromisoformat(str(reply.get("date") or "")[:10])
    except (ValueError, TypeError):
        return None
    if not today <= when <= today + dt.timedelta(days=max_horizon_days):
        return None            # already passed, or too far out to be a review date

    product = (reply.get("product") or "").strip()
    haystack = _normalise(document)
    if not product or _normalise(product) not in haystack:
        return None            # a name the filing does not use is a name from elsewhere

    quote = (reply.get("quote") or "").strip()
    # Match on a run of the quote rather than the whole of it, since whitespace and
    # entity handling differ between the document and what the model echoes back.
    needle = _normalise(quote)
    if len(needle) < 25 or needle[:120] not in haystack:
        return None

    return {"date": when.isoformat(), "product": product,
            "indication": (reply.get("indication") or "").strip() or None,
            "quote": quote}


def is_fatal(exc: Exception) -> bool:
    """True when an error will hit every call, not just this one.

    A key that is unset, revoked, out of credit, or rate limited fails identically on
    the next filing, so retrying the other twenty-nine spends an EDGAR fetch each to
    collect the same message. A timeout or a malformed document is per-filing and the
    loop should carry on past it.
    """
    import urllib.error

    # Gemini comes back as an HTTP status: 401/403 is the key, 429 is the quota or rate
    # limit. On the free tier a 429 keeps firing across a fast loop, so stopping beats
    # spending an EDGAR fetch per filing to collect the same refusal.
    if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 429):
        return True
    # Anthropic comes back as a typed SDK error.
    name = type(exc).__name__
    if name in ("AuthenticationError", "PermissionDeniedError", "RateLimitError"):
        return True
    text = str(exc).lower()
    return any(phrase in text for phrase in
               ("credit balance", "quota", "billing", "invalid x-api-key",
                "authentication_error", "api_key_invalid", "api key not valid",
                "invalid api key", "resource_exhausted", "permission_denied",
                "http 401", "http 403", "http 429"))


def _ask(document: str, filing: dict) -> dict | None:
    user = (f"Company: {filing['ticker']}\n"
            f"Filed: {filing['filed_date']} ({filing['form_type']})\n\n"
            f"Filing text:\n{document}\n\nExtract the FDA decision date.")
    return parse_reply(llm.complete(SYSTEM_PROMPT, user, MAX_TOKENS))


def extract(db_path=None, limit: int = 25, today=None) -> dict:
    """Read candidate filings and write the PDUFA dates found. Returns a summary.

    Every filing is read at most once: the URL is the catalyst's identity, so a row that
    already exists is skipped rather than re-extracted, which keeps the API cost to new
    filings only.
    """
    today = today or dt.date.today()
    if llm.provider() is None:
        return {"status": "no key", "read": 0, "found": 0, "errors": [],
                "detail": "No model provider is configured (set GROQ_API_KEY, "
                          "GEMINI_API_KEY or ANTHROPIC_API_KEY), so no PDUFA dates were "
                          "extracted. The calendar carries registry readouts only."}

    conn = db.get_connection(db_path)
    try:
        seen = {row["source_url"] for row in conn.execute(
            "SELECT source_url FROM catalysts WHERE source_url IS NOT NULL")}
    finally:
        conn.close()

    read = found = 0
    errors: list[str] = []
    for filing in candidates(db_path, today=today):
        if read >= limit:
            break
        if filing["url"] in seen:
            continue
        try:
            time.sleep(_FETCH_PAUSE_S)
            document = filing_text(filing)
        except Exception as exc:               # a filing that will not fetch is skipped
            errors.append(f"{filing['ticker']} {filing['accession']}: {exc}")
            continue
        # The cheap check first. Most 8-Ks say nothing about a review, and reading them
        # with the model would be paying for a no.
        if not REGULATORY_HINT.search(document):
            continue
        read += 1
        try:
            row = validate(_ask(document, filing), document, today=today)
        except Exception as exc:
            errors.append(f"{filing['ticker']} {filing['accession']}: {exc}")
            if is_fatal(exc):
                return {"status": "api unavailable", "read": read, "found": found,
                        "errors": errors,
                        "detail": f"Stopped after the first call: {exc}. Every "
                                  "remaining filing would fail the same way."}
            continue
        if row is None:
            continue
        title = f"{row['product']} PDUFA"
        if row["indication"]:
            title += f", {row['indication']}"
        catalysts.add_catalyst(
            db_path, filing["ticker"], "PDUFA", row["date"], title,
            description=row["quote"], is_curated=0, source_url=filing["url"],
            date_confidence="confirmed")
        found += 1
    return {"status": "ok", "read": read, "found": found, "errors": errors}
