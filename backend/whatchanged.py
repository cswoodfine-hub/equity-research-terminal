"""What-changed feed (the rules layer).

Merges recently detected changes (diff engine), upcoming catalysts (<=60 days), and
near-term loss of exclusivity into one list ranked by significance then date. The
optional note layer that summarises this per company lives in ``insights.py``.
"""

from __future__ import annotations

import json
import re

import db
import edgar_items
import materiality

_SIG_RANK = {"high": 0, "medium": 1, "low": 2}

# What sets an LOE date, said briefly. Only reference product exclusivity and patents
# gate a competitor; orphan exclusivity covers a single orphan indication and expires
# without the product losing anything, so it must never read as a bare LOE date.
SHORT_BASIS = {
    "patent": "patent",
    "regulatory exclusivity": "regulatory exclusivity",
    "orphan exclusivity": "orphan exclusivity",
    "reference product exclusivity": "reference product exclusivity",
    "interchangeable exclusivity": "interchangeable exclusivity",
}


def _trial_headline(ticker, entity_key, change_type, old, new):
    tag = f"{ticker} " if ticker else ""
    if change_type == "status_change":
        return f"{tag}trial {entity_key}: status {old} -> {new}"
    if change_type == "date_slip":
        return f"{tag}trial {entity_key}: primary completion slips {old} -> {new}"
    if change_type == "date_change":
        return f"{tag}trial {entity_key}: primary completion {old} -> {new}"
    if change_type in ("phase_advance", "phase_regress"):
        return f"{tag}trial {entity_key}: {old} -> {new}"
    return f"{tag}trial {entity_key}: {change_type}"


def _event_dates(conn) -> dict:
    """When each approval and filing actually happened, keyed by its natural key.

    The changes table records when we first saw something, which is not when it
    happened. Saphnelo was approved 2026-04-24 and first seen on 2026-07-18, and the
    feed was showing the later date as though it were the approval. For an analyst the
    event date is the fact; our detection time is bookkeeping.
    """
    dates = {}
    for r in conn.execute("SELECT application_number, approval_date FROM approvals"):
        if r["approval_date"]:
            dates[("approval", r["application_number"])] = r["approval_date"]
    for r in conn.execute("SELECT accession, filed_date FROM filings"):
        if r["filed_date"]:
            dates[("filing", r["accession"])] = r["filed_date"]
    # A leadership change happened when the 8-K was filed, not when we first read it.
    # The first run reads a year of filings at once, so without this the whole history
    # arrives dated today and buries what actually happened today.
    for r in conn.execute(
        "SELECT c.ticker, l.accession, l.filed_date FROM leadership_changes l"
        "  JOIN companies c ON c.id = l.company_id"
        " WHERE l.filed_date IS NOT NULL"):
        dates[("company", f"{r['ticker']}|{r['accession']}")] = r["filed_date"]
    # A press release happened on the day the company published it. The first run for a
    # company reads its whole archive at once, so without this the recent ones would all
    # arrive dated today.
    for r in conn.execute(
        "SELECT c.ticker, n.url, n.published_at FROM news n"
        "  JOIN companies c ON c.id = n.company_id"
        " WHERE n.source = 'press_ir' AND n.published_at IS NOT NULL"):
        dates[("company", f"{r['ticker']}|{r['url']}")] = r["published_at"]
    return dates


def _recent_changes(conn, days):
    nct_ticker = {
        r["nct_id"]: r["ticker"]
        for r in conn.execute(
            "SELECT t.nct_id, c.ticker FROM trials t LEFT JOIN companies c ON t.sponsor_company_id = c.id"
        )
    }
    event_dates = _event_dates(conn)
    items = []
    for r in conn.execute(
        """
        SELECT id, entity_type, entity_key, field, old_value, new_value, change_type,
               significance, detected_at
          FROM changes
         WHERE detected_at >= datetime('now', ?)
        """,
        (f"-{int(days)} days",),
    ):
        date_key = (r["entity_type"], r["entity_key"])
        if r["entity_type"] == "trial":
            ticker = nct_ticker.get(r["entity_key"])
            headline = _trial_headline(ticker, r["entity_key"], r["change_type"],
                                       r["old_value"], r["new_value"])
        elif r["entity_type"] == "company":
            # A company change keeps the ticker in its key rather than in the headline,
            # so the prefix is added here: reading the ticker off the first word, the
            # way a filing headline allows, would make "Chief" the company. The key is
            # "TICKER|accession", because the accession is what dates the event.
            # Sarepta filed the same chief executive departure twice, five months
            # apart, and a key without it collapsed them onto one date.
            ticker = r["entity_key"].split("|")[0]
            # A leadership change stores a fragment ("Chief Executive Officer
            # departure") that reads as a sentence once lowered. A press release stores
            # the company's own headline, where the case is carrying drug names, so it
            # is printed as written.
            if (r["change_type"] or "").startswith("press_"):
                headline = f"{ticker} {r['new_value']}"
            else:
                headline = f"{ticker} {(r['new_value'] or '').lower()}"
            date_key = ("company", r["entity_key"])
        else:  # filing / approval headlines already carry the ticker prefix
            ticker = (r["new_value"] or "").split(" ", 1)[0] or None
            headline = r["new_value"]
        # A trial change has no date of its own beyond when the registry was updated,
        # so it keeps the detection time. An approval and a filing both do.
        happened = event_dates.get(date_key)
        items.append({
            "kind": "change", "significance": r["significance"],
            "date": happened or r["detected_at"], "detected_at": r["detected_at"],
            "ticker": ticker, "change_type": r["change_type"], "headline": headline,
            "change_id": r["id"],  # ties a generated note back to its evidence
            # The rule that flagged it, printable beside the item.
            "reason": materiality.change_reason(r["change_type"], r["old_value"],
                                                r["new_value"]),
        })
    return items


def _catalyst_detail(row) -> str | None:
    """The trial behind a derived readout, as a fact line for the note.

    The feed headline is one clipped row of a list; the note can carry the whole thing.
    A derived readout stores the trial's NCT id in ``description``, which joins to the
    trial and its mapped asset, so the note can name the phase, the enrolment, the
    indication, and the identifier rather than paraphrasing a truncated title.
    """
    if not row["nct_id"] or not (row["nct_id"] or "").startswith("NCT"):
        return None                         # a PDUFA row, whose title already suffices
    parts = []
    drug = row["brand_name"] or row["generic_name"]
    if drug:
        parts.append(f"drug {drug}")
    if row["phase"]:
        parts.append(row["phase"].lower())
    if row["overall_status"]:
        parts.append(row["overall_status"].lower())
    if row["enrollment"]:
        parts.append(f"{row['enrollment']} enrolled")
    try:
        conditions = ", ".join(json.loads(row["conditions"] or "[]")[:3])
    except (ValueError, TypeError):
        conditions = ""
    if conditions:
        parts.append(f"in {conditions}")
    # The date's own certainty. An estimated readout moves; an actual one has happened.
    precision = {"month": "month only, no day given", "estimated": "estimated date",
                 "confirmed": "confirmed date"}.get(row["date_confidence"], "")
    if precision:
        parts.append(precision)
    detail = "; ".join(parts)
    return (f"[{row['nct_id']}: {detail}. Full title: {row['title']}]"
            if detail else f"[{row['nct_id']}. Full title: {row['title']}]")


_NCT = re.compile(r"^NCT\d{8}$")


def _catalyst_url(nct_id, source_url) -> str | None:
    """The page behind a catalyst. A trial readout is derived from a registry record, so
    the registry page is the primary source; anything else links to what announced it."""
    if nct_id and _NCT.match(str(nct_id).strip()):
        return f"https://clinicaltrials.gov/study/{str(nct_id).strip()}"
    return source_url or None


def _upcoming_catalysts(conn, within_days, ticker=None):
    soon_threshold = _date_offset(conn, materiality.CATALYST_SOON_DAYS)
    sql = """
        SELECT c.ticker, cat.catalyst_type, cat.expected_date, cat.title,
               cat.date_confidence, cat.description AS nct_id, cat.source_url,
               t.phase, t.overall_status, t.enrollment, t.conditions,
               a.brand_name, a.generic_name
          FROM catalysts cat JOIN companies c ON cat.company_id = c.id
          LEFT JOIN trials t ON t.nct_id = cat.description
          LEFT JOIN assets a ON a.id = cat.asset_id
         WHERE cat.status = 'pending' AND cat.expected_date >= date('now')
           AND cat.expected_date <= date('now', ?)
    """
    params = [f"+{int(within_days)} days"]
    if ticker:
        sql += " AND c.ticker = ?"
        params.append(ticker.upper())
    items = []
    for r in conn.execute(sql, params):
        soon = r["expected_date"] <= soon_threshold
        # A Phase 2 readout is a real but earlier signal, so it holds at medium even when
        # near and never outranks a late-stage readout or a regulatory date. A PDUFA and
        # other non-trial catalysts have no phase and keep the soon-is-high rule.
        early = (r["phase"] or "").startswith(("Phase 1", "Phase 2"))
        significance = "medium" if early else ("high" if soon else "medium")
        items.append({
            "kind": "catalyst", "significance": significance,
            "date": r["expected_date"], "ticker": r["ticker"],
            "change_type": r["catalyst_type"],
            # The stored title is whole; a feed line is one row of a list, so it is
            # cut here rather than in the table it came from.
            "headline": (f"{r['ticker']} {r['catalyst_type']}: "
                         f"{_clip(r['title'])} ({r['expected_date']})"),
            # The full trial fact, for the note; the feed view ignores it.
            "detail": _catalyst_detail(r),
            "reason": (f"inside {materiality.CATALYST_SOON_DAYS} days" if soon
                       else None),
            # Where the catalyst can be read in full: the registry page for a trial
            # readout, and whatever announced the rest. A curated row with no source
            # links nowhere rather than to a search.
            "url": _catalyst_url(r["nct_id"], r["source_url"]),
        })
    return items


def _near_term_loe(conn, months, limit, ticker=None):
    """Nearest upcoming LOE, capped at ``limit``.

    The cap is applied inside the query, so narrowing to a company gives that company's
    nearest expiries. Filtering a globally-capped list instead would silently drop a
    company whose LOE falls outside the universe-wide top ``limit``.
    """
    horizon = _date_offset(conn, months * 30)
    sql = """
        SELECT c.ticker, a.brand_name, a.modality, a.internal_code,
               MAX(e.expiry_date) AS loe,
               (SELECT x.protection_type FROM exclusivities x
                 WHERE x.asset_id = a.id
                 ORDER BY x.expiry_date DESC, x.protection_type
                 LIMIT 1) AS loe_basis
          FROM assets a JOIN exclusivities e ON e.asset_id = a.id
          JOIN companies c ON a.owner_company_id = c.id
    """
    params = []
    if ticker:
        sql += " WHERE c.ticker = ?"
        params.append(ticker.upper())
    sql += """
         GROUP BY a.id
        HAVING loe >= date('now') AND loe <= ?
         ORDER BY loe LIMIT ?
    """
    params += [horizon, limit]
    items = []
    for r in conn.execute(sql, params):
        # A brand can hold several applications, one per formulation, each with its own
        # expiry. Naming the application keeps two Corlanor rows distinguishable instead
        # of reading as the same product listed twice.
        code = f" ({r['internal_code']})" if r["internal_code"] else ""
        basis = SHORT_BASIS.get(r["loe_basis"], r["loe_basis"] or "unknown")
        items.append({
            "kind": "loe", "significance": "medium", "date": r["loe"], "ticker": r["ticker"],
            "change_type": "loe", "modality": r["modality"], "loe_basis": r["loe_basis"],
            # The basis is in the headline because orphan exclusivity reads as a loss of
            # exclusivity date without it, and it is not one.
            "headline": (f"{r['ticker']} LOE: {r['brand_name']}{code} "
                         f"{basis} expires {r['loe']}"),
            "reason": f"LOE inside {materiality.LOE_WINDOW_MONTHS} months",
        })
    return items


def _material_filings(conn, days, ticker=None):
    """Recent 8-K items that move an investment case: M&A, agreements, impairments.

    These are in the feed on their own merit rather than only as diffs. A completed
    acquisition filed six weeks ago is still the most important thing about a company,
    whether or not this particular refresh was the one that first saw it.
    """
    sql = """
        SELECT c.ticker, f.form_type, f.filed_date, f.title, f.url
          FROM filings f JOIN companies c ON f.company_id = c.id
         WHERE f.filed_date >= date('now', ?)
    """
    params = [f"-{int(days)} days"]
    if ticker:
        sql += " AND c.ticker = ?"
        params.append(ticker.upper())
    items = []
    for r in conn.execute(sql, params):
        if not edgar_items.is_material_title(r["title"]):
            continue
        items.append({
            "kind": "filing", "significance": "high", "date": r["filed_date"],
            "ticker": r["ticker"], "change_type": "material event",
            "url": r["url"],
            "headline": f"{r['ticker']} {r['form_type']}: {r['title']}",
            "reason": f"material {r['form_type']} item",
        })
    return items


def _date_offset(conn, days):
    return conn.execute("SELECT date('now', ?)", (f"+{int(days)} days",)).fetchone()[0]


def _clip(text, limit: int = 90) -> str:
    """A title cut to a feed line. Presentation, so it lives with the feed."""
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def build_feed(db_path=None, days=30, catalyst_days=60,
               loe_months=materiality.LOE_WINDOW_MONTHS, loe_limit=15,
               filing_days=120, ticker=None):
    """The ranked feed. Pass ``ticker`` to narrow it to one company (used by notes)."""
    conn = db.get_connection(db_path)
    try:
        items = (
            _recent_changes(conn, days)
            + _material_filings(conn, filing_days, ticker)
            + _upcoming_catalysts(conn, catalyst_days, ticker)
            + _near_term_loe(conn, loe_months, loe_limit, ticker)
        )
    finally:
        conn.close()
    if ticker:
        # Catalysts and LOE are already narrowed in SQL. Changes carry no ticker column
        # (it is derived from the headline), so they are filtered here; that query has
        # no LIMIT, so nothing is lost by filtering after the fact.
        want = ticker.upper()
        items = [it for it in items if (it.get("ticker") or "").upper() == want]
    items.sort(key=_rank)
    return items


def _rank(item):
    """Significance first, then date read in the direction that matters for the kind.

    Changes already happened, so the most recent is the most interesting. Catalysts and
    LOE have not happened yet, so the soonest is. Sorting every kind the same way put
    the furthest-out expiry at the top, which is the least urgent item in the feed.
    """
    date = (item.get("date") or "")[:10]
    ordinal = int(date.replace("-", "")) if date[:4].isdigit() else 0
    backwards = item.get("kind") in ("change", "filing")
    return (_SIG_RANK.get(item.get("significance"), 3), -ordinal if backwards else ordinal)
