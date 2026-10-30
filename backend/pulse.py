"""Reading the daily biopharma pulse's files.

The pulse is a scheduled Claude run that searches the trade press each weekday morning,
ranks what it finds in three tiers and emails the briefing. It also commits the items as
``data/pulse/YYYY-MM-DD.json`` to the ``claude/pulse-feed`` branch:

    {"pulse_date": "2026-10-30",
     "read": "Three to five sentences on the sector.",
     "items": [{"tier": 1, "kind": "deal",
                "headline": "Lilly buys Verve for $1.0bn upfront",
                "detail": "One or two lines on the numbers and why it matters.",
                "url": "https://www.fiercebiotech.com/...",
                "published": "2026-10-29",
                "companies": ["Eli Lilly", "Verve Therapeutics"],
                "tickers": ["LLY", "VERV"]}]}

It is an AI-written summary of what the press says, so an item is kept only where it
cites the article it summarises, and nothing in it is read as a number: the headline and
detail are text to show beside the link, never a deal term or a date to act on.
"""

from __future__ import annotations

import datetime as dt
import re

import company_names

KINDS = ("deal", "readout", "approval", "rejection", "regulatory", "financing", "ipo",
         "policy", "earnings", "leadership", "restructuring", "conference", "market",
         "other")
# What an item is worth in the change feed, by tier. A tier is the pulse's own ranking.
SIGNIFICANCE = {1: "high", 2: "medium", 3: "low"}
_URL = re.compile(r"^https?://[^\s/]+\.[^\s]+$")
_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


def _date(text) -> str | None:
    try:
        return dt.date.fromisoformat(str(text or "")[:10]).isoformat()
    except ValueError:
        return None


def date_of(filename: str) -> str | None:
    """The briefing date a file's name carries, or None for any other file."""
    found = _FILE.match(filename)
    return _date(found.group(1)) if found else None


def parse(payload: dict, filename: str) -> tuple[dict | None, list[str]]:
    """({pulse_date, read, items}, problems) for one file. A file whose date does not
    match its name is refused whole; an item without a headline or a link is dropped and
    named in the problems, since a summary with no source is not evidence of anything."""
    problems = []
    named = date_of(filename)
    stated = _date((payload or {}).get("pulse_date"))
    if not named or stated != named:
        return None, [f"{filename}: pulse_date {stated} does not match the file name"]
    items, seen = [], set()
    for i, raw in enumerate(payload.get("items") or []):
        if not isinstance(raw, dict):
            problems.append(f"{filename} item {i}: not an object")
            continue
        headline = " ".join(str(raw.get("headline") or "").split())
        url = str(raw.get("url") or "").strip()
        if not headline or not _URL.match(url):
            problems.append(f"{filename} item {i}: no headline or no link")
            continue
        if url in seen:
            continue
        seen.add(url)
        tier = raw.get("tier")
        kind = str(raw.get("kind") or "").strip().lower()
        published = _date(raw.get("published"))
        # A source dated after the briefing is a misread date, not a scoop.
        if published and published > named:
            published = None
        items.append({
            "tier": tier if tier in (1, 2, 3) else None,
            "kind": kind if kind in KINDS else "other",
            "headline": headline,
            "detail": " ".join(str(raw.get("detail") or "").split()) or None,
            "url": url, "published": published,
            "companies": [str(c).strip() for c in raw.get("companies") or [] if str(c).strip()],
            "tickers": [str(t).strip().upper() for t in raw.get("tickers") or []
                        if str(t).strip()]})
    read = " ".join(str(payload.get("read") or "").split()) or None
    return {"pulse_date": named, "read": read, "items": items}, problems


def universe_index(conn) -> dict:
    """{key: company_id} for matching an item to the universe: each ticker, US ADR
    ticker, legal name, and the names a headline uses, all lower cased."""
    out = {}
    for r in conn.execute("SELECT id, ticker, name, us_adr_ticker FROM companies"):
        for key in (r["ticker"], r["us_adr_ticker"], r["name"],
                    company_names.bare(r["name"]),
                    *company_names.press_names(r["ticker"], r["name"])):
            if key:
                out.setdefault(key.strip().lower(), r["id"])
    return out


def match(item: dict, index: dict) -> list[int]:
    """The universe companies an item names, by its tickers or its company names, each
    compared whole: "Merck KGaA" is not Merck & Co."""
    found = []
    for key in item["tickers"] + item["companies"]:
        company_id = index.get(key.strip().lower())
        if company_id is not None and company_id not in found:
            found.append(company_id)
    return found
