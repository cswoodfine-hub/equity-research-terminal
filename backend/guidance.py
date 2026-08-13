"""Management guidance read out of the filings already on file.

The street's numbers are gated behind a paid key; the company's own are not. Every
quarter the earnings release states what management expects for the year, and those
releases are already in ``filing_sections``: 619 sections mention guidance, and the
usable ones are the EX-99.1 exhibits, the 6-K bodies and the MD&A. Risk factors are
excluded outright, because their 242 mentions are forward-looking-statement boilerplate
and would drown the real rows.

The design is pdufa.py's, and the same rule holds: the model is a reader, not a source.
Nothing it returns is trusted on its own. The quote must appear in the section text, the
period must be a real nearby year, the numbers must parse, and a range must be a range.
A company that guides in growth is recorded in growth: converting "8-14% at constant
exchange rates" onto a reported base the company did not use would be arithmetic on top
of a caveat, so RevenueGrowth is a metric of its own rather than a derivation.

Every row lands with the verbatim sentence in ``note`` and the filing date as ``as_of``,
so a guidance figure can always be traced to the words it came from. With no model
provider configured the module does nothing and says so.
"""

from __future__ import annotations

import json
import re

import db
import llm
import pdufa

MAX_TOKENS = 1200
SOURCE = "guidance"
LOOKBACK_DAYS = 400
SECTIONS = ("exhibit", "body", "mdna")
_WINDOW = 2400          # characters around the guidance language sent to the model

# Cheap check before any call is spent: the section has to talk about the year ahead.
HINT = re.compile(r"guidance|outlook for|full[- ]year (?:outlook|expectations)"
                  r"|we (?:now )?expect", re.I)

SYSTEM_PROMPT = """You extract financial guidance figures from company filings.

Return JSON only, no prose, matching:
{"found": bool, "items": [{"metric": "Revenue" or "EPS" or "RevenueGrowth",
 "period": "FY2026", "low": number, "high": number, "currency": "USD" or "DKK" or
 "EUR" or null, "quote": str}]}

Rules, in order of importance:
1. Only report figures the text states as the company's own guidance or outlook. A
   figure you know from elsewhere is wrong here. No guidance stated: {"found": false}.
2. "quote" must be copied verbatim from the text, one sentence, containing the figures.
3. Revenue and EPS are absolute amounts in the stated currency (write 63.5 billion as
   63500000000). RevenueGrowth is a percentage range (write 8-14% as low 8, high 14)
   with currency null; use it when the company guides in growth rather than amounts.
4. A point estimate has low equal to high.
5. "period" is the fiscal year the guidance is for, e.g. "FY2026".
6. Analyst estimates quoted in the text are not guidance. Prior-year actuals are not
   guidance."""


def candidates(db_path=None, lookback_days: int = LOOKBACK_DAYS) -> list[dict]:
    """Sections worth reading, newest first, that the ledger has not seen."""
    marks = ",".join("?" * len(SECTIONS))
    conn = db.get_connection(db_path)
    try:
        return [dict(r) for r in conn.execute(
            f"""SELECT fs.company_id, c.ticker, fs.accession, fs.section,
                       fs.form_type, fs.filed_date, fs.text
                  FROM filing_sections fs
                  JOIN companies c ON c.id = fs.company_id
                 WHERE fs.section IN ({marks})
                   AND fs.filed_date >= date('now', ?)
                   AND NOT EXISTS (SELECT 1 FROM guidance_scans g
                                    WHERE g.accession = fs.accession
                                      AND g.section = fs.section)
                 ORDER BY fs.filed_date DESC""",
            (*SECTIONS, f"-{int(lookback_days)} days"))]
    finally:
        conn.close()


def excerpt(text: str, window: int = _WINDOW) -> str | None:
    """The stretch of a section around its guidance language, or None without any.

    A 60,000-character exhibit is mostly tables; the sentence that guides sits in a
    paragraph the hint finds, and the model reads a window rather than the document.
    """
    match = HINT.search(text or "")
    if not match:
        return None
    start = max(0, match.start() - window // 3)
    return text[start:start + window]


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


def validate(reply: dict | None, document: str, filed_year: int) -> list[dict]:
    """The items that survive the gates. The model is a reader, not a source.

    Each check asks the same question pdufa's do: is this in the document, or did it
    come from somewhere else?
    """
    if not reply or not reply.get("found"):
        return []
    haystack = _normalise(document)
    out = []
    for item in reply.get("items") or []:
        if not isinstance(item, dict):
            continue
        metric = (item.get("metric") or "").strip()
        if metric not in ("Revenue", "EPS", "RevenueGrowth"):
            continue
        period = (item.get("period") or "").strip()
        match = re.fullmatch(r"FY(20\d\d)", period)
        if not match or not (filed_year - 1 <= int(match.group(1)) <= filed_year + 2):
            continue                   # guidance speaks to nearby years, nothing else
        try:
            low, high = float(item.get("low")), float(item.get("high"))
        except (TypeError, ValueError):
            continue
        if low > high or low < 0:
            continue
        if metric == "RevenueGrowth" and high > 100:
            continue                   # a growth range is percent, not an amount
        quote = (item.get("quote") or "").strip()
        needle = _normalise(quote)
        if len(needle) < 25 or needle[:120] not in haystack:
            continue                   # a quote the section does not contain
        out.append({"metric": metric, "period": period, "low": low, "high": high,
                    "value": (low + high) / 2.0,
                    "currency": (item.get("currency") or "").strip() or None,
                    "quote": quote})
    return out


def _ask(document: str, ticker: str, filed_date: str, complete=None) -> dict | None:
    complete = complete or llm.complete
    user = (f"Company: {ticker}\nFiled: {filed_date}\n\nFiling text:\n{document}\n\n"
            "Extract the company's stated guidance.")
    return parse_reply(complete(SYSTEM_PROMPT, user, MAX_TOKENS))


def extract(db_path=None, limit: int = 20, complete=None) -> dict:
    """Read unscanned guidance-bearing sections and write what survives the gates.

    Every section is read at most once, ledgered in guidance_scans, so the model spend
    is bounded to new filings. Returns a summary the refresh can report.
    """
    if complete is None and llm.provider() is None:
        return {"status": "no key", "read": 0, "found": 0, "errors": [],
                "detail": "No model provider is configured, so no guidance was "
                          "extracted. The street view carries reported figures and "
                          "any curated rows only."}

    read = found = 0
    errors: list[str] = []
    for section in candidates(db_path):
        if read >= limit:
            break
        window = excerpt(section["text"] or "")
        conn = db.get_connection(db_path)
        try:
            if window is None:
                conn.execute("INSERT OR IGNORE INTO guidance_scans (accession,"
                             " section, found) VALUES (?, ?, 0)",
                             (section["accession"], section["section"]))
                conn.commit()
                continue
            read += 1
            try:
                reply = _ask(window, section["ticker"], section["filed_date"],
                             complete)
            except Exception as exc:
                errors.append(f"{section['ticker']} {section['accession']}: {exc}")
                if pdufa.is_fatal(exc):
                    break
                continue
            items = validate(reply, window, int(section["filed_date"][:4]))
            for item in items:
                conn.execute(
                    """INSERT OR IGNORE INTO consensus_estimates
                           (company_id, metric, period, value, low, high, currency,
                            source, as_of, note)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (section["company_id"], item["metric"], item["period"],
                     item["value"], item["low"], item["high"], item["currency"],
                     SOURCE, section["filed_date"], item["quote"]))
                found += 1
            conn.execute("INSERT OR IGNORE INTO guidance_scans (accession, section,"
                         " found) VALUES (?, ?, ?)",
                         (section["accession"], section["section"],
                          1 if items else 0))
            conn.commit()
        finally:
            conn.close()
    return {"status": "ok", "read": read, "found": found, "errors": errors}
