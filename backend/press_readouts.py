"""Phase 2 and Phase 3 results read out of the companies' own press releases.

``trial_readouts`` reads the 8-K and 6-K filings that announce a result, and that is the
whole of its register. It misses two things. A company that files neither: Roche and
Bayer are SEC-free, and Roche alone carried 30 of the 271 readouts due in the last two
years. And a release the company published but did not furnish to the SEC, or furnished
weeks later: AstraZeneca publishes every result on astrazeneca.com and has the most
unresolved readouts in the book. The news table already holds those releases, fetched
from the investor-relations feeds and pages; 438 of them carry a result in the title and
none had been read as a readout.

This reads them, through the same classifier and the same validation as the filings:
the drug and the result sentence must appear in the text the model read, or the row is
recorded as none. A release that restates a result already labelled from a filing, the
same company, drug and phase within a few days, is recorded as a duplicate and never a
second event, because the resolver treats each announcement as one result.

The page is fetched directly with the browser-shaped agent the feed fetcher uses, and
where a site refuses or returns a shell, once more through the Jina reader the press-page
fetcher already depends on.
"""

from __future__ import annotations

import datetime as dt
import re
import time
import urllib.request

import db
import llm
import pdufa
import trial_readouts
from fetchers import press_ir, press_page

SOURCE = "press"
SOURCES = ("press_ir", "press_page")
LOOKBACK_DAYS = trial_readouts.LOOKBACK_DAYS
MAX_PER_RUN = 150
DUPLICATE_DAYS = 10          # a release and its filing can sit a week apart
_TIMEOUT_S = 30
# A page shorter than this is a shell or an interstitial, not a release.
_SHELL_CHARS = 1_500

# The title gate, wider than the body hint because a headline compresses: "significantly
# improved progression-free survival" is a result; "met" alone is not.
TITLE_HINT = re.compile(
    r"phase (?:3|iii|2|ii)\b|top-?line|primary endpoint|met (?:its|the|all)|did not meet|"
    r"failed to meet|significantly (?:improv|reduc|increas)|superiority|statistically"
    # A head-to-head win said as a comparison: "delivered greater A1C reduction and more
    # than double the weight loss of Ozempic" announced TRANSCEND-T2D-2 and passed none
    # of the words above, so the release was never read.
    r"|head-to-head|\bgreater (?:\w+ ){0,3}(?:reduction|weight loss|improvement)"
    r"|\bmore (?:than (?:double|twice|triple) )?(?:the )?weight loss\b|\bsuperior\b"
    r"|\boutperform", re.I)
# Where a release's opening ends: its "About" sections, which list the programme's other
# studies and would name more than the one reported. A page read as flat text has no
# line breaks, so "About" followed by a capitalised name counts too, past the first
# paragraphs.
_ABOUT = re.compile(r"\n\s*(?:#+\s*|\*\*)?About\b|\bAbout (?=[A-Z0-9])")
LEAD_CHARS = 4000
_LEAD_MIN = 400


QUOTE_BACK = 1500


def lead_of(document: str, anchors=(), quote: str | None = None) -> str:
    """The opening of a release, past the site's navigation, up to its first "About"
    section, at most LEAD_CHARS. It starts QUOTE_BACK characters before the result
    sentence the classifier quoted, where the page holds it, since the study is named in
    the paragraphs around the result; else where the headline (or the drug's name) first
    appears. A page's own title sits above its menus, so the quote is the surer start."""
    text = document or ""
    low = text.lower()
    start, floor = 0, _LEAD_MIN
    head = " ".join(str(quote or "").split())[:60].lower()
    if len(head) >= 20 and head in low:
        anchors = ()
        start = max(0, low.index(head) - QUOTE_BACK)
        # The opening runs at least to the result: an "About" in the menus above it is
        # not the end of the release.
        floor = max(_LEAD_MIN, low.index(head) - start + len(head))
    for anchor in anchors:
        anchor = " ".join(str(anchor or "").split())[:60].lower()
        if len(anchor) >= 4 and anchor in low:
            start = low.index(anchor)
            break
    text = text[start:]
    cut = next((m for m in _ABOUT.finditer(text) if m.start() >= floor), None)
    return (text[:cut.start()] if cut else text)[:LEAD_CHARS]


def key(news_id: int) -> str:
    return f"news:{int(news_id)}"


def _get(url: str) -> str:
    """The release, directly or through the reader. The direct fetch uses the feed
    fetcher's browser-shaped agent, which is what AstraZeneca's site answers."""
    try:
        request = urllib.request.Request(url, headers={**press_ir.HEADERS, "Accept": "text/html"})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            text = pdufa.strip_html(resp.read().decode("utf-8", "replace"))
        if len(text) >= _SHELL_CHARS:
            return text
    except Exception:  # noqa: BLE001  the reader is the second attempt
        pass
    return press_page._read(url)


def candidates(db_path=None, lookback_days: int = LOOKBACK_DAYS, today=None) -> list[dict]:
    """Releases with a result in the title, newest first, not yet read."""
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=lookback_days)).isoformat()
    conn = db.get_connection(db_path)
    try:
        seen = {r["accession"] for r in conn.execute(
            "SELECT accession FROM trial_readouts WHERE accession LIKE 'news:%'")}
        marks = ",".join("?" * len(SOURCES))
        rows = [dict(r) for r in conn.execute(
            f"""SELECT n.id, n.company_id, n.title, n.url, n.published_at AS filed_date,
                       c.ticker
                  FROM news n JOIN companies c ON c.id = n.company_id
                 WHERE n.source IN ({marks}) AND n.published_at >= ?
                   AND n.url IS NOT NULL AND n.url <> ''
                 ORDER BY n.published_at DESC""", (*SOURCES, cutoff))]
    finally:
        conn.close()
    return [r for r in rows if key(r["id"]) not in seen and TITLE_HINT.search(r["title"] or "")]


def _duplicate_of(conn, company_id, result: dict, day: str):
    """A labelled row for the same company, drug and phase within DUPLICATE_DAYS: the
    filing this release was furnished as, or the release the filing carried."""
    lo = (dt.date.fromisoformat(day[:10]) - dt.timedelta(days=DUPLICATE_DAYS)).isoformat()
    hi = (dt.date.fromisoformat(day[:10]) + dt.timedelta(days=DUPLICATE_DAYS)).isoformat()
    want = trial_readouts._normalise(result["drug"])
    for r in conn.execute(
            """SELECT accession, drug FROM trial_readouts
                WHERE company_id = ? AND phase = ? AND outcome IN ('positive', 'negative')
                  AND event_date BETWEEN ? AND ?""", (company_id, result["phase"], lo, hi)):
        have = trial_readouts._normalise(r["drug"])
        if have and (have in want or want in have):
            return r["accession"]
    return None


def _store(conn, row: dict, result: dict | None, duplicate: str | None,
           lead: str | None = None) -> None:
    outcome = "duplicate" if duplicate else (result["outcome"] if result else "none")
    conn.execute(
        """INSERT INTO trial_readouts
               (accession, company_id, drug, phase, outcome, event_date, quote, source_url,
                source, read_from, lead)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'release', ?)
           ON CONFLICT(accession) DO NOTHING""",
        (key(row["id"]), row["company_id"],
         result["drug"] if result else None, result["phase"] if result else None,
         outcome, str(row["filed_date"])[:10],
         (f"duplicate of {duplicate}: " if duplicate else "") + (result["quote"] if result else "")
         if result else None,
         row["url"], SOURCE, lead))


def extract(db_path=None, limit: int = MAX_PER_RUN, today=None, get=None) -> dict:
    """Read the candidate releases and record the results found. Idempotent."""
    if llm.provider() is None:
        return {"status": "no key", "read": 0, "positive": 0, "negative": 0, "duplicate": 0,
                "detail": "No model provider configured, so no press releases were read."}
    get = get or _get
    read = pos = neg = dup = 0
    errors: list[str] = []
    for row in candidates(db_path, today=today)[:limit]:
        try:
            document = get(row["url"])[:pdufa._MAX_CHARS]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{key(row['id'])}: {exc}")
            continue
        result = None
        if trial_readouts.HINT.search(document):
            try:
                result = trial_readouts._classify(document, row, llm.complete)
            except Exception as exc:  # noqa: BLE001
                if pdufa.is_fatal(exc):
                    errors.append(f"model: {exc}")
                    break
                continue
        conn = db.get_connection(db_path)
        try:
            duplicate = _duplicate_of(conn, row["company_id"], result, row["filed_date"]) if result else None
            _store(conn, row, result, duplicate,
                   lead_of(document, (row.get("title"), (result or {}).get("drug")),
                           (result or {}).get("quote")))
            conn.commit()
        finally:
            conn.close()
        read += 1
        if duplicate:
            dup += 1
        elif result and result["outcome"] == "positive":
            pos += 1
        elif result and result["outcome"] == "negative":
            neg += 1
        time.sleep(0.5)
    return {"status": "ok", "read": read, "positive": pos, "negative": neg,
            "duplicate": dup, "errors": errors}


def fill_leads(db_path=None, get=None, limit: int = 60, days: int = 120) -> dict:
    """Fetch the opening of each release a result was read from before the opening was
    kept, newest first: the page alone, no model. A page that does not answer is left
    for the next run."""
    get = get or _get
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    conn = db.get_connection(db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT t.accession, t.source_url, t.drug, t.quote, n.title FROM trial_readouts t
                 LEFT JOIN news n ON 'news:' || n.id = t.accession
                WHERE t.source = ? AND t.lead IS NULL
                  AND t.outcome IN ('positive', 'negative', 'none')
                  AND t.source_url IS NOT NULL AND t.event_date >= ?
                ORDER BY t.event_date DESC LIMIT ?""", (SOURCE, since, limit))]
    finally:
        conn.close()
    filled, errors = 0, []
    for r in rows:
        try:
            lead = lead_of(get(r["source_url"])[:pdufa._MAX_CHARS], (r["title"], r["drug"]),
                           r["quote"])
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{r['accession']}: {exc}")
            continue
        conn = db.get_connection(db_path)
        try:
            conn.execute("UPDATE trial_readouts SET lead = ? WHERE accession = ?",
                         (lead, r["accession"]))
            conn.commit()
        finally:
            conn.close()
        filled += 1
        time.sleep(0.3)
    return {"filled": filled, "errors": errors}
