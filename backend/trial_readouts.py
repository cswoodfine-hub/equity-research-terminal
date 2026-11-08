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

A row that found nothing is not final. ``reread`` reads such rows a second time with
the exhibit, because the first reading followed an 8-K to its exhibit only when the
cover lacked the cheap hint and never followed a 6-K, and the resolver lets a result
found later overturn a catalyst it had closed unknown.
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
# A sentence that reports a result as already known is a restatement, not the event.
# The second reading of 461 filings found two in its first eleven labels: a designation
# release "based on data from the LEAP2MONO phase 3 study", filed seven weeks after the
# result itself, and a sentence beginning "As previously reported, the study met its
# primary endpoint". A restatement carries the wrong market date and, matched on drug
# and phase, can settle a sibling catalyst the original announcement already settled.
_RESTATED = re.compile(
    r"previously (?:reported|announced|disclosed|presented)|as announced on|"
    r"(?:is|was|are|were) based on (?:\w+ ){0,4}?(?:data|results|findings) from", re.I)

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
    """The EX-99 press-release document in the filing's folder, or None.

    One implementation, in pdufa, because both readers face the same envelope.
    """
    return pdufa.exhibit_url(primary_url, get)


# A primary document shorter than this is an envelope: Novo Nordisk's 6-K cover runs
# 4,239 characters of address and check boxes, Sanofi's 1,229. The median stored cover
# of a row that found nothing is about 4,000 characters for a 6-K and 2,600 for an 8-K;
# the median exhibit beside it is over 12,000.
ENVELOPE_CHARS = 6_000


def readout_text(filing: dict, get=None) -> tuple[str, str]:
    """(text, read_from) for the filing: the primary document, joined to its EX-99
    exhibit wherever the primary reads as an envelope.

    The exhibit is read for either form. The release is in the exhibit for a US 8-K
    and for most foreign 6-Ks alike, and a cover that mentions "Phase 3" in its item
    description still carries no result sentence, so the test is not the cheap hint
    but whether the cover states a result at all and is long enough to be one. The
    two are joined rather than swapped so a drug named only on the cover still
    validates against the text the model read.
    """
    get = get or _get                 # resolved here so a test can stand in for EDGAR
    text = pdufa.strip_html(get(filing["url"]))
    if len(text) < ENVELOPE_CHARS or not _RESULT_WORDS.search(text):
        exhibit = exhibit_url(filing["url"], get)
        if exhibit:
            body = pdufa.strip_html(get(exhibit))
            if body.strip():
                return (text + "\n\n" + body)[:pdufa._MAX_CHARS], "primary+exhibit"
    return text[:pdufa._MAX_CHARS], "primary"


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
    if _RESTATED.search(quote):
        return None
    return {"drug": drug, "phase": phase, "outcome": outcome, "quote": quote}


def _classify(document: str, filing: dict, complete) -> dict | None:
    user = (f"Company: {filing['ticker']}\nFiled: {filing['filed_date']}\n\n"
            f"Filing text:\n{document[:pdufa._MAX_CHARS]}\n\n"
            "Does this announce a Phase 2 or Phase 3 trial result?")
    reply = complete(SYSTEM_PROMPT, user, MAX_TOKENS, thinking_budget=THINKING_BUDGET)
    return validate(parse_reply(reply), document)


def _store(conn, filing: dict, result: dict | None, read_from: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO trial_readouts
            (accession, company_id, drug, phase, outcome, event_date, quote, source_url,
             read_from)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(accession) DO NOTHING
        """,
        (filing["accession"], filing["company_id"],
         result["drug"] if result else None, result["phase"] if result else None,
         result["outcome"] if result else "none", filing["filed_date"],
         result["quote"] if result else None, filing["url"], read_from))


def _relabel(conn, accession: str, result: dict | None, read_from: str, today) -> None:
    """A second reading of a row that found nothing. The label is written only where
    the row still says none, so a result already on file is never overwritten, and
    the row is stamped either way so it is read again by nobody."""
    if result:
        conn.execute(
            """UPDATE trial_readouts SET drug = ?, phase = ?, outcome = ?, quote = ?,
                      read_from = ?, reread_at = ?
                WHERE accession = ? AND outcome = 'none'""",
            (result["drug"], result["phase"], result["outcome"], result["quote"],
             read_from, today.isoformat(), accession))
    else:
        conn.execute("UPDATE trial_readouts SET read_from = ?, reread_at = ?"
                     " WHERE accession = ? AND outcome = 'none'",
                     (read_from, today.isoformat(), accession))


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
            document, read_from = readout_text(filing)
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
            _store(conn, filing, result, read_from)
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


def unread(db_path=None, today=None) -> list[dict]:
    """Rows that found nothing and have not been read again, those a catalyst is
    waiting on first.

    A readout catalyst closed unknown, or pending past its date, names the window in
    which its result would have been announced; a "none" filing by the same company
    inside that window is the one whose second reading can change a score, so those
    come first and the rest follow in date order. The window is the resolver's own:
    EARLY_DAYS before the catalyst's date to LATE_DAYS after it, and the import is
    local so the resolver, which imports this module, is not imported back.
    """
    import catalyst_outcomes as co
    conn = db.get_connection(db_path)
    try:
        rows = {r["accession"]: dict(r) for r in conn.execute(
            """SELECT tr.accession, tr.company_id, tr.event_date, f.form_type,
                      f.filed_date, f.url, f.title, c.ticker
                 FROM trial_readouts tr
                 JOIN filings f ON f.accession = tr.accession
                 JOIN companies c ON c.id = tr.company_id
                WHERE tr.outcome = 'none' AND tr.reread_at IS NULL
                  AND tr.read_from IS NULL""")}
        waiting: set = set()
        for cat in conn.execute(
                """SELECT company_id, expected_date FROM catalysts
                    WHERE catalyst_type = 'data readout'
                      AND status IN ('unknown', 'pending') AND expected_date IS NOT NULL
                      AND expected_date < date('now')"""):
            window = co.date_window(cat["expected_date"])
            if not window:
                continue
            lo, hi = co._shift(window[0], -co.EARLY_DAYS), co._shift(window[1], co.LATE_DAYS)
            for r in conn.execute(
                    """SELECT accession FROM trial_readouts
                        WHERE company_id = ? AND event_date BETWEEN ? AND ?""",
                    (cat["company_id"], lo, hi)):
                waiting.add(r["accession"])
    finally:
        conn.close()
    ordered = sorted(rows.values(),
                     key=lambda r: (r["accession"] not in waiting, r["event_date"] or ""))
    for r in ordered:
        r["waited_on"] = r["accession"] in waiting
    return ordered


def reread(db_path=None, limit: int = MAX_PER_RUN, today=None) -> dict:
    """Read the rows that found nothing a second time, with the exhibit.

    The first reading of 1,287 filings followed an 8-K to its EX-99 exhibit only when
    the cover lacked the cheap hint, and never followed a 6-K at all, so a quarter of
    them were read from an envelope. This reads each such row once more through
    ``readout_text`` as it now stands, and the same classifier and the same validation
    decide what it says: the drug and the result sentence must be in the text the
    model read, or the row stays none. A row read before is stamped and not read again,
    whatever was found. Rows a catalyst is waiting on come first.
    """
    today = today or dt.date.today()
    if llm.provider() is None:
        return {"status": "no key", "read": 0, "positive": 0, "negative": 0,
                "detail": "No model provider configured, so no readout rows were read "
                          "again."}
    read = pos = neg = waited = 0
    errors: list[str] = []
    for filing in unread(db_path, today=today)[:limit]:
        try:
            document, read_from = readout_text(filing)
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
            _relabel(conn, filing["accession"], result, read_from, today)
            conn.commit()
        finally:
            conn.close()
        read += 1
        waited += int(filing["waited_on"])
        if result and result["outcome"] == "positive":
            pos += 1
        elif result and result["outcome"] == "negative":
            neg += 1
        time.sleep(0.3)
    return {"status": "ok", "read": read, "waited_on": waited, "positive": pos,
            "negative": neg, "errors": errors}


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
