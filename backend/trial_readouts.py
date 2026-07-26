"""Phase 2 and Phase 3 trial readouts, classified from the filings that announce them.

A pivotal readout is the biggest catalyst in drug development and it carries a sign: the
trial met its primary endpoint or it did not. No free source labels these, so this reads
them out of the 8-K and 6-K press releases that announce them. Foreign filers put the
release in the 6-K itself; a US 8-K attaches it as an exhibit, so when the 8-K cover
carries no result language the EX-99 exhibit is fetched instead.

The model is a reader, not a source, the same as in the PDUFA extractor. A filing counts
as a readout only when it states the result of a Phase 2 or Phase 3 trial, the drug it
names appears in the text, and the sentence the model quotes for the result appears in
the text too. Anything short of that, a trial merely starting, a submission, an approval,
a Phase 1 result, is read and recorded as no readout so it is not fetched again, but is
never turned into a signed event.

Without a model the module does nothing and says so; the backtest then has no readout
signal, which is the honest state rather than an invented one.
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
import pdufa                     # reuse strip_html and the fatal-error test

LOOKBACK_DAYS = 950              # about 2.6 years, so measured events keep a forward window
# gemini-flash-latest thinks before it answers; at a small budget the reasoning eats it
# all and the JSON truncates, which silently loses a real readout to a "none". The budget
# is set well above the capped reasoning so the whole record comes back.
MAX_TOKENS = 2048
THINKING_BUDGET = 256
_TIMEOUT_S = 30
MAX_PER_RUN = 400               # cap the filings read in one pass

# Only the item types a result is announced under, so earnings and governance 8-Ks are
# not fetched at all. 6-K has no item taxonomy, so all are candidates.
_EIGHTK_HINT = re.compile(r"regulation fd|other events", re.I)
# Cheap local gate before the model: the filing must read like a trial result.
HINT = re.compile(
    r"primary endpoint|top-?line|met the|did not meet|failed to meet|"
    r"statistically significant|phase 3|phase iii|phase 2|phase ii", re.I)
_RESULT_WORDS = re.compile(
    r"primary endpoint|top-?line|statistically significant|met|did not meet|failed", re.I)

SYSTEM_PROMPT = """You read a company's press release or filing and decide whether it \
announces the topline or primary-endpoint result of a Phase 2 or Phase 3 clinical trial, \
and whether the result was positive or negative.

Return JSON only, no prose:
{"found": bool, "drug": str or null, "phase": 2 or 3 or null,
 "outcome": "positive" or "negative" or null, "quote": str or null}

Rules, in order of importance:
1. found is true ONLY when the text reports the RESULT of a Phase 2 or Phase 3 trial: \
that it met or did not meet its primary endpoint, or showed or failed to show a \
statistically significant effect. A trial that is starting, enrolling, ongoing, \
submitted to a regulator, or approved is not a readout; return {"found": false}.
2. outcome is "positive" when the trial met its primary endpoint or showed a \
statistically significant benefit, "negative" when it did not meet the endpoint or failed.
3. phase is 2 or 3, exactly as the text states. A Phase 1 result or an unstated phase is \
not in scope; return {"found": false}.
4. drug is the product, written exactly as the text writes it.
5. quote is one sentence copied verbatim from the text that states the result."""


def _get(url: str) -> str:
    user_agent = (os.getenv("SEC_USER_AGENT") or "").strip()
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT is not set; EDGAR blocks anonymous requests")
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
        return resp.read().decode("utf-8", "replace")


def exhibit_url(primary_url: str, get=_get) -> str | None:
    """The EX-99 press-release document in the filing's folder, where a US 8-K keeps the
    release, or None. Read from the accession index."""
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


def readout_text(filing: dict, get=_get) -> str:
    """The text most likely to carry the result: the primary document, or for a US 8-K
    whose cover has no result language, the EX-99 exhibit it points to."""
    text = pdufa.strip_html(get(filing["url"]))
    if filing["form_type"] == "8-K" and not HINT.search(text):
        exhibit = exhibit_url(filing["url"], get)
        if exhibit:
            text = pdufa.strip_html(get(exhibit))
    return text


def candidates(db_path=None, lookback_days: int = LOOKBACK_DAYS, today=None) -> list[dict]:
    """Recent 8-K (Reg FD / Other events) and 6-K filings that might announce a result."""
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=lookback_days)).isoformat()
    conn = db.get_connection(db_path)
    try:
        seen = {r["accession"] for r in conn.execute(
            "SELECT accession FROM trial_readouts")}
        rows = [dict(r) for r in conn.execute(
            """
            SELECT f.accession, f.form_type, f.filed_date, f.url, f.title, f.company_id,
                   c.ticker
              FROM filings f JOIN companies c ON c.id = f.company_id
             WHERE f.form_type IN ('8-K', '6-K') AND f.filed_date >= ?
               AND f.url IS NOT NULL AND f.url <> '' AND f.filed_date <= date('now', '-2 days')
             ORDER BY f.filed_date DESC
            """,
            (cutoff,))]
    finally:
        conn.close()
    return [r for r in rows if r["accession"] not in seen
            and (r["form_type"] == "6-K" or _EIGHTK_HINT.search(r["title"] or ""))]


def parse_reply(raw: str) -> dict | None:
    return pdufa.parse_reply(raw)


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def validate(reply: dict | None, document: str) -> dict | None:
    """The classified readout as {drug, phase, outcome, quote}, or None on any failure.

    The phase and outcome must be in scope, and the drug and the result sentence must be
    found in the document, so a label the model produced from its own knowledge cannot
    become an event."""
    if not reply or not reply.get("found"):
        return None
    try:
        phase = int(reply.get("phase"))
    except (ValueError, TypeError):
        return None
    outcome = (reply.get("outcome") or "").strip().lower()
    if phase not in (2, 3) or outcome not in ("positive", "negative"):
        return None
    drug = (reply.get("drug") or "").strip()
    quote = (reply.get("quote") or "").strip()
    haystack = _normalise(document)
    needle = _normalise(quote)
    if not drug or _normalise(drug) not in haystack:
        return None
    if len(needle) < 25 or needle[:120] not in haystack or not _RESULT_WORDS.search(quote):
        return None
    return {"drug": drug, "phase": phase, "outcome": outcome, "quote": quote}


def _classify(document: str, filing: dict, complete) -> dict | None:
    user = (f"Company: {filing['ticker']}\nFiled: {filing['filed_date']}\n\n"
            f"Filing text:\n{document[:pdufa._MAX_CHARS]}\n\n"
            "Does this announce a Phase 2 or Phase 3 trial result?")
    reply = complete(SYSTEM_PROMPT, user, MAX_TOKENS, thinking_budget=THINKING_BUDGET)
    return validate(parse_reply(reply), document)


def _store(conn, filing: dict, result: dict | None) -> None:
    conn.execute(
        """
        INSERT INTO trial_readouts
            (accession, company_id, drug, phase, outcome, event_date, quote, source_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(accession) DO NOTHING
        """,
        (filing["accession"], filing["company_id"],
         result["drug"] if result else None, result["phase"] if result else None,
         result["outcome"] if result else "none", filing["filed_date"],
         result["quote"] if result else None, filing["url"]))


def extract(db_path=None, limit: int = MAX_PER_RUN, today=None) -> dict:
    """Read candidate filings and record the Phase 2/3 readouts found. Idempotent: a
    filing already read is skipped, so a re-run costs only new filings."""
    if llm.provider() is None:
        return {"status": "no key", "read": 0, "positive": 0, "negative": 0,
                "detail": "No model provider configured, so no trial readouts were "
                          "classified; the backtest has no readout signal."}
    read = pos = neg = 0
    errors: list[str] = []
    for filing in candidates(db_path, today=today)[:limit]:
        try:
            document = readout_text(filing)
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
        if result and result["outcome"] == "positive":
            pos += 1
        elif result and result["outcome"] == "negative":
            neg += 1
        time.sleep(0.3)                # polite to EDGAR and under the model's rate limit
    return {"status": "ok", "read": read, "positive": pos, "negative": neg,
            "errors": errors}


def recent(db_path=None, ticker: str = "", today=None, within_days: int = 400,
           limit: int = 6) -> list[dict]:
    """Signed Phase 2/3 readouts for a ticker, most recent first, for the Key insights
    tab: the drug, the phase, the sign, the date and the sentence that carried it."""
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=within_days)).isoformat()
    conn = db.get_connection(db_path)
    try:
        row = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                           (ticker.upper(),)).fetchone()
        if not row:
            return []
        rows = conn.execute(
            """
            SELECT drug, phase, outcome, event_date, quote FROM trial_readouts
             WHERE company_id = ? AND outcome IN ('positive', 'negative')
                   AND event_date >= ?
             ORDER BY event_date DESC LIMIT ?
            """, (row["id"], cutoff, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
