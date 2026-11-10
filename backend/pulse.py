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

From schema 2 an item also says which companies it is about and how, in the
terminal's own tickers, read from ``data/pulse_universe.json`` (``pulse_universe.py``):

    {"schema": 2, "pulse_date": "2026-11-10", "read": "...",
     "items": [{"event_key": "bayn:asundexian:fda-approval",
                "first_reported": "2026-11-09", "update": false,
                "tier": 1, "kind": "approval", "phase": null,
                "headline": "...", "detail": "...", "url": "...",
                "published": "2026-11-09",
                "entities": [{"ticker": "BAYN", "name": "Bayer", "role": "subject"},
                             {"ticker": "BMY", "name": "Bristol Myers Squibb",
                              "role": "read_across"}],
                "assets": ["asundexian"], "others": [],
                "companies": ["Bayer", "Bristol Myers Squibb"],
                "tickers": ["BAYN", "BMY"]}]}

``event_key`` is the same on every day a story runs, so a repeat is one story and not
two; ``role`` says whether the item is about the company (subject), names it as the other
side (party) or matters to it only by read-across. ``companies`` and ``tickers`` stay, so
a reader of schema 1 still reads a schema 2 file. A ticker is only ever taken if the
terminal holds it: a wrong one is dropped and reported, never guessed at.

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
# How an item names a company, strongest first: the story is about it, it is the other
# side of the story, or the story matters to it by read-across only.
ROLES = ("subject", "party", "read_across")
PHASES = ("1", "1/2", "2", "2/3", "3")
_KEY = re.compile(r"[^a-z0-9:./-]+")
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
        first = _date(raw.get("first_reported"))
        if first and first > named:
            first = None
        entities = []
        for e in raw.get("entities") or []:
            if not isinstance(e, dict):
                continue
            role = re.sub(r"[\s-]+", "_", str(e.get("role") or "").strip().lower())
            if not (e.get("ticker") or e.get("name")):
                continue
            entities.append({"ticker": str(e.get("ticker") or "").strip().upper() or None,
                             "name": " ".join(str(e.get("name") or "").split()) or None,
                             # A role the file does not spell is no claim about the
                             # company, so it is the weakest, not the strongest.
                             "role": role if role in ROLES else "read_across"})
        key = _KEY.sub("-", str(raw.get("event_key") or "").strip().lower()).strip("-")
        # "Phase 2b" is a Phase 2 to the ranked feed, which sorts by the phase alone.
        phase = re.sub(r"(?<=\d)[AB]$", "", str(raw.get("phase") or "").strip().upper()
                       .replace("PHASE", "").replace(" ", ""))
        tickers = [str(t).strip().upper() for t in raw.get("tickers") or [] if str(t).strip()]
        names = [str(c).strip() for c in raw.get("companies") or [] if str(c).strip()]
        for e in entities:
            if e["ticker"] and e["ticker"] not in tickers:
                tickers.append(e["ticker"])
            if e["name"] and e["name"] not in names:
                names.append(e["name"])
        items.append({
            "event_key": key[:120] or None, "first_reported": first,
            "update": raw.get("update") is True,
            "phase": phase if phase in PHASES else None,
            "entities": entities,
            "assets": [str(a).strip() for a in raw.get("assets") or [] if str(a).strip()],
            "tier": tier if tier in (1, 2, 3) else None,
            "kind": kind if kind in KINDS else "other",
            "headline": headline,
            "detail": " ".join(str(raw.get("detail") or "").split()) or None,
            "url": url, "published": published,
            "companies": names, "tickers": tickers})
    read = " ".join(str(payload.get("read") or "").split()) or None
    return {"pulse_date": named, "read": read, "items": items}, problems


def universe_index(conn) -> dict:
    """{key: company_id} for matching an item to the universe: each ticker, US ADR
    ticker, legal name, and the names a headline uses, all lower cased."""
    out = {}
    for r in conn.execute("SELECT id, ticker, name, us_adr_ticker FROM companies"):
        for key in (r["ticker"], r["us_adr_ticker"], r["name"],
                    company_names.bare(r["name"]),
                    *company_names.press_names(r["ticker"], r["name"]),
                    *company_names.PRESS_ALIASES.get(r["ticker"], ())):
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


def ticker_index(conn) -> dict:
    """{ticker: company_id} for each ticker and US ADR ticker the terminal holds, and
    nothing else: a schema 2 entity names its company by this alone."""
    out = {}
    for r in conn.execute("SELECT id, ticker, us_adr_ticker FROM companies"):
        for key in (r["ticker"], r["us_adr_ticker"]):
            if key:
                out.setdefault(key.strip().upper(), r["id"])
    return out


def asset_index(conn) -> dict:
    """{asset name: company_id} for the brand names, generic names and codes that one
    universe company alone owns, lower cased. A name two companies share (a generic, a
    co-marketed brand) is left out, so it can never tie an item to the wrong one."""
    owners: dict = {}
    for r in conn.execute(
            "SELECT owner_company_id, brand_name, generic_name, internal_code FROM assets"
            " WHERE owner_company_id IS NOT NULL"):
        for name in (r["brand_name"], r["generic_name"], r["internal_code"]):
            name = (name or "").strip().lower()
            if len(name) >= 4:
                owners.setdefault(name, set()).add(r["owner_company_id"])
    return {name: next(iter(ids)) for name, ids in owners.items() if len(ids) == 1}


def match_roles(item: dict, index: dict, tickers: dict | None = None,
                assets: dict | None = None) -> tuple[list[tuple[int, str]], list[str]]:
    """([(company_id, role)], problems) for one item, strongest role first.

    A schema 2 entity is taken by its ticker where the terminal holds it, else by its name
    compared whole. Entities are meant for universe companies only (everyone else goes
    in ``others``), so one that is neither is reported and dropped, never guessed at. An item with no entities
    (schema 1) is matched as before, every company it names a subject. Where nothing ties
    the item to the universe, an asset only one universe company owns names its owner."""
    found: dict = {}
    problems = []

    def take(company_id, role):
        held = found.get(company_id)
        if held is None or ROLES.index(role) < ROLES.index(held):
            found[company_id] = role

    if item.get("entities"):
        for e in item["entities"]:
            company_id = None
            if e["ticker"] and tickers is not None:
                company_id = tickers.get(e["ticker"])
            if company_id is None and e["name"]:
                company_id = index.get(e["name"].lower())
            if company_id is not None:
                take(company_id, e["role"])
            else:
                problems.append(f"{e['ticker'] or e['name']} is not a company the terminal "
                                f"holds; left untied")
    else:
        for company_id in match(item, index):
            take(company_id, "subject")
    if not found and assets:
        for name in item.get("assets") or []:
            company_id = assets.get(name.strip().lower())
            if company_id is not None:
                take(company_id, "subject")
    ordered = sorted(found.items(), key=lambda kv: ROLES.index(kv[1]))
    return ordered, problems
