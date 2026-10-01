"""Drivers and risks: what could move a company next, as rows and their copy.

One list serves two tabs. Catalysts draws all of it (company-scorecard.md 1.5) and Key
insights draws the first three Drivers as Next (1.3), so the two can never disagree about
what comes first. Pure: no Streamlit, no API. It reads three payloads the page already
holds:

- ``GET /companies/{T}/comps-context`` for the events of the next 12 months and the
  competition rows behind the crowded-pool risks;
- ``scorecard.companies[T]`` of ``GET /comps/valuation`` for the exclusivity losses of the
  next 24 months, each with its share of revenue (6.1);
- the change feed (``GET /changes?ticker=T``) for readout slips.

Drivers are ranked the way the Comps view ranked its Catalysts ahead (core.js
``compareCatalysts``), with one change: a valued readout under ``DRIVER_MIN_PCT`` of the
price is ranked by date, so a $0.05 asset no longer outranks a large marketed drug's
readout. A row leads with its value a share only where the event decides an unapproved
asset's value; a readout for a marketed drug leads with its month, because the drug's
whole value is not at stake on one new indication.

Risks are number first and under 15 words each: exclusivity losses, Phase 3 readouts that
slipped, and patient pools the model says are crowded.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from typing import Optional

# Bumped on a change a page must see. A running server does not re-import a module that
# sits under a dot-directory, as a worktree does, so the page reloads one behind this.
REVISION = 3

DRIVER_MIN_PCT = 0.01      # a valued readout under this share of the price is ranked by date
SLIP_MIN_DAYS = 90         # a readout slip this long or longer, detected in the last 90 days
SLIP_LOOKBACK_DAYS = 90
SLIP_MAX_ROWS = 2
RISK_MAX_ROWS = 5
# Exclusivity rows shown when slips and pools need the room: the next loss, then the
# largest by share of revenue, still printed by date. The rest fold under "Show n more".
EXCLUSIVITY_SHOWN_MIN = 3
RISK_MAX_WORDS = 14        # every risk row is under 15 words
LOE_HORIZON_MONTHS = 24
POOL_KEEP_MAX = 0.90       # core.js POOL_KEEP_MAX: keeping at most this share is rationed
COMPETITION_MIN_PCT = 0.02  # core.js COMPETITION_MIN_PCT: the indication's value, share of price
DRIVERS_SHOWN = 5
CONTEXT_SCHEMA = 1

REGULATORY_KINDS = ("PDUFA", "regulatory decision", "AdCom", "EMA decision")
LATE_PHASES = ("Phase 3", "Phase 2/3")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MID = " · "
GAP = "  "                 # between a row's lead and its text, as the drawings print it
ELLIPSIS = "…"

# --- copy (company-scorecard.md 8.1) ---------------------------------------------------
SECTION_TITLE = "Drivers and risks"
SECTION_BASIS = "events in 12 months, exclusivity losses in 24 · model output marked"
DRIVERS_TITLE = "Drivers"
RISKS_TITLE = "Risks"
EMPTY = "No dated event or exclusivity loss on file for {T}."
CONTEXT_FAILED = "The events for {T} did not load: {error}."

# Proper names MeSH descriptors carry; they keep their capital in prose (core.js).
_EPONYMS = frozenset((
    "alzheimer", "parkinson", "crohn", "hodgkin", "huntington", "duchenne", "cushing",
    "sjogren", "behcet", "castleman", "waldenstrom", "fabry", "gaucher", "pompe",
    "kawasaki", "graves", "paget", "raynaud", "tourette", "wilms", "ewing", "kaposi",
    "burkitt", "merkel", "barrett", "dravet", "rett", "angelman", "marfan", "niemann",
    "hirschsprung", "addison", "meniere", "guillain", "barre", "lennox", "gastaut",
    "prader", "willi", "friedreich", "charcot", "marie", "stargardt", "leber",
    "hashimoto", "takayasu", "bowen"))

_NCT = re.compile(r"NCT\d{8}")
_SLIP = re.compile(r"slips\s+(\d{4}-\d{2}(?:-\d{2})?)\s*->\s*(\d{4}-\d{2}(?:-\d{2})?)")
_SLIP_DAYS = re.compile(r"slipped\s+(\d+)d")
_ISO = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?")
_BRACKETS = re.compile(r"\s*\([^)]*\)")
_PHASE_PREFIX = re.compile(r"^(Phase \d(?:/\d)?|Early Phase 1),\s*")


# --- small helpers ---------------------------------------------------------------------
def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def _as_date(v) -> Optional[dt.date]:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    m = _ISO.match(str(v or ""))
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
    except ValueError:
        return None


def _add_months(d: dt.date, months: int) -> dt.date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return dt.date(year, month, day)
        except ValueError:
            continue
    return dt.date(year, month, 28)


def _whole_pct(p: float) -> int:
    """Half up, as JavaScript's Math.round, so both sides print the same percent."""
    return int(math.floor(abs(p) * 100 + 0.5 + 1e-9))


def _pct_share(p: float) -> str:
    """A share of revenue: one decimal, two significant figures below 0.1%."""
    v = abs(p) * 100
    if 0 < v < 0.05:
        return f"{v:.2g}%"
    return f"{v:.1f}%"


def _usd(v: float) -> str:
    return f"${v:,.2f}"


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _article(n: int) -> str:
    """"a" or "an" before a whole number read aloud: an 8, an 11, an 18, an 80."""
    s = str(int(round(abs(n))))
    return "an" if (s.startswith("8") or s in ("11", "18")
                    or re.fullmatch(r"1[18]\d{3}", s)) else "a"


def _words(s: str) -> int:
    return len(str(s or "").split())


def _cut_words(s: str, max_words: int) -> str:
    words = str(s or "").split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max(1, max_words)]) + ELLIPSIS


def _cut_chars(s: str, limit: int) -> str:
    s = str(s or "").strip()
    return s if len(s) <= limit else s[:limit - 1].rstrip() + ELLIPSIS


def product_name(name) -> str:
    """The product's name with anything in brackets dropped (8.2): "Trikafta (Copackaged)"
    prints "Trikafta"."""
    return _BRACKETS.sub("", str(name or "")).strip()


def _indication_word(word: str) -> str:
    out = []
    for part in word.split("-"):
        bare = re.sub(r"[^A-Za-z0-9]", "", re.sub(r"['’]s$", "", part))
        if not bare:
            out.append(part)
        elif re.fullmatch(r"[A-Z0-9]+", bare):          # HIV, IGA, the B of B-Cell, a number
            out.append(part)
        elif bare[0].isupper() and bare[0].isascii() and bare.lower() in _EPONYMS:
            out.append(part)
        else:
            out.append(part.lower())
    return "-".join(out)


def indication_prose(name) -> str:
    """The stored MeSH name with its comma-separated parts reversed, in lower case
    ("Pulmonary Disease, Chronic Obstructive" -> "chronic obstructive pulmonary disease").
    Acronyms and proper names keep their capitals. Port of core.js ``indicationProse``."""
    parts = [p.strip() for p in str(name or "").split(",") if p.strip()]
    words = " ".join(reversed(parts)).split()
    return " ".join(_indication_word(w) for w in words)


def indication_title(name) -> str:
    s = indication_prose(name)
    return s[:1].upper() + s[1:]


def month_text(value) -> Optional[str]:
    """"Jan 2028" from "2028-01-10" or "2028-01"."""
    m = _ISO.match(str(value or ""))
    if not m:
        return None
    mo = int(m.group(2))
    return f"{MONTHS[mo - 1]} {m.group(1)}" if 1 <= mo <= 12 else None


def day_text(value) -> Optional[str]:
    """"8 Sep 2027" from "2027-09-08"; the month alone when the source gives no day."""
    m = _ISO.match(str(value or ""))
    if not m:
        return None
    mo = int(m.group(2))
    if not 1 <= mo <= 12:
        return None
    if m.group(3) is None:
        return f"{MONTHS[mo - 1]} {m.group(1)}"
    return f"{int(m.group(3))} {MONTHS[mo - 1]} {m.group(1)}"


# --- the context -----------------------------------------------------------------------
def context_error(context) -> Optional[str]:
    """None when the comps-context answer can be read, else why not, in a few words."""
    if not isinstance(context, dict):
        return "no answer"
    if context.get("error") is not None:
        return str(context["error"]).rstrip(".") or "no answer"
    if context.get("schema") != CONTEXT_SCHEMA:
        return f"schema {context.get('schema')!r}, expected {CONTEXT_SCHEMA}"
    cat = context.get("catalysts")
    if not isinstance(cat, dict) or not isinstance(cat.get("items"), list):
        return "the answer carries no catalysts"
    return None


def _items(context) -> list:
    if context_error(context) is not None:
        return []
    return [it for it in context["catalysts"]["items"] if isinstance(it, dict)]


# --- Drivers ---------------------------------------------------------------------------
def _is_regulatory(it: dict) -> bool:
    return it.get("regulatory") is True or it.get("kind") in REGULATORY_KINDS


def _is_late_readout(it: dict) -> bool:
    return "readout" in str(it.get("kind") or "").lower() and it.get("phase") in LATE_PHASES


def _unapproved_value(it: dict) -> Optional[float]:
    """The share of price an unapproved asset carries, when the event decides it and it is
    worth DRIVER_MIN_PCT or more; else None."""
    asset = it.get("asset") if isinstance(it.get("asset"), dict) else None
    value = it.get("asset_value") if isinstance(it.get("asset_value"), dict) else None
    if not asset or asset.get("is_marketed") or not value:
        return None
    pct = _num(value.get("pct_of_price"))
    if pct is None or pct < DRIVER_MIN_PCT or _num(value.get("per_share")) is None:
        return None
    return pct


def _stake_pct(it: dict) -> Optional[float]:
    stake = it.get("stake") if isinstance(it.get("stake"), dict) else None
    return _num(stake.get("pct_of_price")) if stake else None


def tier(it: dict) -> int:
    """0 a priced stake, 1 regulatory, 2 a late-stage readout deciding an unapproved asset
    worth DRIVER_MIN_PCT of the price or more, 3 other late-stage readouts, 4 the rest."""
    if _stake_pct(it) is not None:
        return 0
    if _is_regulatory(it):
        return 1
    if _is_late_readout(it):
        return 2 if _unapproved_value(it) is not None else 3
    return 4


def _sort_key(it: dict):
    t = tier(it)
    inner = 0.0
    if t == 0:
        inner = -_stake_pct(it)
    elif t == 2:
        inner = -_unapproved_value(it)
    try:
        ident = int(it.get("id"))
    except (TypeError, ValueError):
        ident = 0
    return (t, inner, str(it.get("date") or ""), ident)


def event_text(it: dict) -> str:
    """"Phase 3 readout", "PDUFA date", as core.js ``catalystEvent``."""
    k = str(it.get("kind") or "").lower()
    if k == "data readout":
        return f"{it['phase']} readout" if it.get("phase") else "data readout"
    if k == "pdufa":
        return "PDUFA date"
    if k == "adcom":
        return "advisory committee"
    if k == "regulatory decision":
        return "regulatory decision"
    if k == "ema decision":
        return "EMA decision"
    return k or "event"


def date_parts(it: dict) -> tuple:
    """(text, estimated, precision). "est." marks a registry estimate, printed to its month;
    a month the registry gives without a day prints as the month; a stated day prints whole."""
    iso = str(it.get("date") or "")
    m = _ISO.match(iso)
    conf = it.get("date_confidence")
    estimated = conf == "estimated"
    if not m or not 1 <= int(m.group(2)) <= 12:
        return "date not on file", estimated, None
    year, mo = m.group(1), int(m.group(2))
    prec = it.get("date_precision") or ("day" if m.group(3) else "month")
    if prec == "day" and not m.group(3):
        prec = "month"
    if prec == "quarter":
        text = f"Q{(mo + 2) // 3} {year}"
    elif prec == "half":
        text = f"H{1 if mo <= 6 else 2} {year}"
    elif prec == "month" or estimated:
        text = f"{MONTHS[mo - 1]} {year}"
    else:
        text = f"{int(m.group(3))} {MONTHS[mo - 1]} {year}"
    return (f"est. {text}" if estimated else text), estimated, prec


def _lead_value(it: dict, t: int) -> tuple:
    """(per_share, pct_of_price, kind) for a row that leads with a value, else Nones. A
    priced stake leads with its size; an event that decides an unapproved asset's value
    (a regulatory date or a late-stage readout) with the asset's value."""
    if t == 0:
        stake = it["stake"]
        per_share = _num(stake.get("per_share"))
        if per_share is not None:
            return abs(per_share), _stake_pct(it), "stake"
    if t in (1, 2) and _unapproved_value(it) is not None:
        return _num(it["asset_value"]["per_share"]), _unapproved_value(it), "asset_value"
    return None, None, None


def _asset_name(it: dict) -> str:
    asset = it.get("asset") if isinstance(it.get("asset"), dict) else None
    if asset and product_name(asset.get("name")):
        # As the scorecard's lines print it (8.2): "Trikafta (Copackaged)" is "Trikafta".
        return product_name(asset["name"])
    return _cut_chars(_PHASE_PREFIX.sub("", str(it.get("title") or "")), 48) or event_text(it)


def rank_events(context: dict) -> list:
    """comps-context catalysts, one row per asset, in the order of core.js compareCatalysts:
    tier 0 a priced stake (largest share of price first), 1 regulatory, 2 a late-stage
    readout of an unapproved asset valued at DRIVER_MIN_PCT of the price or more (largest
    first), 3 other late-stage readouts, 4 the rest; inside tiers 1, 3 and 4 by date, then
    id. An asset's row is its first event in that order; ``more`` counts the others.

    Each row: {lead, asset, event, indication, date_text, estimated, per_share, source}
    plus ``text`` (the row after its lead), ``line`` (lead and text), ``tier``, ``id``,
    ``asset_id``, ``date``, ``precision``, ``pct_of_price``, ``value_kind`` ("stake",
    "asset_value" or None), ``model`` (the lead is model output), ``more``, ``title``,
    ``nct_id``, ``curated``."""
    groups: dict = {}
    for it in sorted(_items(context), key=_sort_key):
        asset = it.get("asset") if isinstance(it.get("asset"), dict) else None
        key = f"a{asset['id']}" if asset and asset.get("id") is not None else f"e{it.get('id')}"
        groups.setdefault(key, []).append(it)
    rows = []
    for events in groups.values():
        it = events[0]
        t = tier(it)
        asset = it.get("asset") if isinstance(it.get("asset"), dict) else None
        name = _asset_name(it)
        event = event_text(it)
        ind = it.get("indication") if isinstance(it.get("indication"), dict) else None
        indication = indication_prose(ind.get("name")) if ind and ind.get("name") else None
        date_text, estimated, precision = date_parts(it)
        per_share, pct, value_kind = _lead_value(it, t)
        body = [name, event] + ([indication] if indication else [])
        if per_share is not None:
            lead = _usd(per_share)
            text = MID.join(body + [date_text])
        else:
            lead = date_text
            text = MID.join(body)
        rows.append({
            "lead": lead, "asset": name, "event": event, "indication": indication,
            "date_text": date_text, "estimated": estimated, "per_share": per_share,
            "source": it.get("source_url") or None,
            "text": text, "line": f"{lead}{GAP}{text}", "tier": t, "id": it.get("id"),
            "asset_id": asset.get("id") if asset else None, "date": it.get("date"),
            "precision": precision, "pct_of_price": pct, "value_kind": value_kind,
            "model": per_share is not None, "more": len(events) - 1,
            "title": it.get("title") or None, "nct_id": it.get("nct_id") or None,
            "curated": bool(it.get("is_curated")),
        })
    return rows


def drivers_basis(k: int) -> str:
    """"25 assets in 12 months"."""
    return f"{k} {_plural(k, 'asset', 'assets')} in 12 months"


def more_label(n: int) -> str:
    return f"Show {n} more"


# --- Risks -----------------------------------------------------------------------------
def _fit(lead: str, template: str, name: str) -> str:
    """The template with ``{name}`` filled, the name cut so lead and text stay under 15
    words."""
    fixed = _words(lead) + _words(template.replace("{name}", "X")) - 1
    room = max(1, RISK_MAX_WORDS - fixed)
    return template.replace("{name}", _cut_words(name, room))


def _risk(kind: str, lead: str, text: str, **extra) -> dict:
    row = {"kind": kind, "lead": lead, "text": text, "line": f"{lead}{GAP}{text}",
           "words": _words(lead) + _words(text)}
    row.update(extra)
    return row


def exclusivity_rows(company, today) -> list:
    """The exclusivity losses of the next 24 months from ``scorecard.companies[T]``, earliest
    first, the larger share first on a shared day: "5.6% of revenue  Lynparza exclusivity
    ends 8 Sep 2027". A loss with no share on
    file leads with its date instead, so the row still starts with a number."""
    if not isinstance(company, dict):
        return []
    today = _as_date(today) or dt.date.today()
    end = _add_months(today, LOE_HORIZON_MONTHS)
    found = []
    for r in company.get("exclusivity_losses") or []:
        if not isinstance(r, dict):
            continue
        when = _as_date(r.get("date"))
        name = product_name(r.get("asset"))
        if when is None or not name or when < today or when > end:
            continue
        found.append((when, name, r))
    # The payload's own order (company_score): date, then the larger share of revenue
    # first, the payload's order on a full tie. So the first row here is the strip's
    # "next exclusivity loss" on Key insights, never a smaller loss on the same day.
    found.sort(key=lambda x: (x[0], -(_num(x[2].get("share_of_revenue")) or 0)))
    rows = []
    for when, name, r in found:
        share = _num(r.get("share_of_revenue"))
        # The payload's own text first: ``share_of_revenue`` is already rounded to four
        # places, and formatting it again can land a tenth away from the strip and the
        # panel (PFE's Adcetris read 1.5% here and 1.4% there).
        share_text = r.get("share_text") if isinstance(r.get("share_text"), str) else None
        if share_text is None and share is not None:
            share_text = _pct_share(share)
        date_s = day_text(r.get("date"))
        if share_text:
            lead = f"{share_text} of revenue"
            text = _fit(lead, "{name} exclusivity ends " + date_s, name)
        else:
            lead = date_s
            text = _fit(lead, "{name} exclusivity ends", name)
        rows.append(_risk("exclusivity", lead, text, asset=name, date=when.isoformat(),
                          share_of_revenue=share, share_text=share_text,
                          basis=r.get("basis"), model=False))
    return rows


def _slip(item: dict) -> Optional[dict]:
    headline = str(item.get("headline") or "")
    nct = _NCT.search(headline)
    moved = _SLIP.search(headline)
    if not nct or not moved:
        return None
    days = None
    said = _SLIP_DAYS.search(str(item.get("reason") or ""))
    if said:
        days = int(said.group(1))
    else:
        old, new = _as_date(moved.group(1)), _as_date(moved.group(2))
        if old and new:
            days = (new - old).days
    if days is None:
        return None
    return {"nct_id": nct.group(0), "old": moved.group(1), "new": moved.group(2), "days": days}


def slip_rows(feed, today, ticker: Optional[str] = None) -> list:
    """Phase 3 readouts that slipped SLIP_MIN_DAYS or more, detected in the last 90 days:
    "241 days  NCT06455449 readout slips to Jan 2028". The feed rates a Phase 3 slip over
    30 days high and every other slip medium (materiality.slip_significance), so a high
    ``date_slip`` is a Phase 3 readout. At most two, one per trial, newest first, longer
    first on a shared day."""
    today = _as_date(today) or dt.date.today()
    since = today - dt.timedelta(days=SLIP_LOOKBACK_DAYS)
    best: dict = {}
    for item in feed or []:
        if not isinstance(item, dict) or item.get("change_type") != "date_slip":
            continue
        if item.get("significance") != "high":
            continue
        if ticker and item.get("ticker") and item.get("ticker") != ticker:
            continue
        seen = _as_date(item.get("detected_at") or item.get("date"))
        if seen is None or seen < since or seen > today:
            continue
        s = _slip(item)
        if s is None or s["days"] < SLIP_MIN_DAYS:
            continue
        key = (-seen.toordinal(), -s["days"], s["nct_id"])
        if s["nct_id"] not in best or key < best[s["nct_id"]][0]:
            best[s["nct_id"]] = (key, seen, s)
    rows = []
    for key, seen, s in sorted(best.values(), key=lambda x: x[0])[:SLIP_MAX_ROWS]:
        to = month_text(s["new"])
        lead = f"{s['days']:,} days"
        rows.append(_risk("slip", lead, f"{s['nct_id']} readout slips to {to}",
                          nct_id=s["nct_id"], days=s["days"], old=s["old"], new=s["new"],
                          detected=seen.isoformat(), model=False))
    return rows


def pool_rows(context) -> list:
    """Indications whose shared patient pool rations the company's own forecast, the
    core.js pool rule (comps-valuation.md 12.3): company_pool.keeps at or under 0.90 and
    the indication worth 2% of the price or more. "73% kept  Obesity: 2 candidates in a
    19-drug pool (model)". In the context's order, largest modelled value first."""
    if not isinstance(context, dict):
        return []
    comp = context.get("competition")
    if not isinstance(comp, dict) or comp.get("covered") is False:
        return []
    rows = []
    for r in comp.get("indications") or []:
        if not isinstance(r, dict) or not isinstance(r.get("indication"), dict):
            continue
        pool = r.get("pool") if isinstance(r.get("pool"), dict) else None
        cp = r.get("company_pool") if (r.get("crowding") and isinstance(r.get("company_pool"), dict)) else None
        value = r.get("value") if isinstance(r.get("value"), dict) else {}
        pct = _num(value.get("pct_of_price"))
        if not cp or not pool or pct is None or pct < COMPETITION_MIN_PCT:
            continue
        k = _num(cp.get("claimants")) or 0
        n = _num(pool.get("pooled_claimants"))
        if n is None:
            n = _num(pool.get("claimants"))
        keeps = _num(cp.get("keeps"))
        if k < 1 or n is None or _num(pool.get("patients")) is None or keeps is None \
                or keeps > POOL_KEEP_MAX:
            continue
        k, n = int(k), int(n)
        name = indication_title(r["indication"].get("name"))
        lead = f"{_whole_pct(keeps)}% kept"
        template = ("{name}: " + f"{k} {_plural(k, 'candidate', 'candidates')} in "
                    f"{_article(n)} {n}-drug pool (model)")
        rows.append(_risk("pool", lead, _fit(lead, template, name),
                          indication=name, indication_id=r["indication"].get("id"),
                          keeps=keeps, candidates=k, pool_drugs=n, pct_of_price=pct,
                          model=True))
    return rows


def _pick_exclusivity(rows: list, room: int) -> tuple:
    """(shown, folded): the next loss always, since the Key insights strip names it, then
    the largest by share of revenue until ``room`` rows, all still in date order. So PFE
    shows Eliquis at 12.7% of revenue rather than the fifth small loss by date."""
    if len(rows) <= room:
        return list(rows), []
    keep = {0}
    rest = sorted(range(1, len(rows)),
                  key=lambda i: (-(rows[i].get("share_of_revenue") or 0), i))
    keep.update(rest[:max(0, room - 1)])
    return ([r for i, r in enumerate(rows) if i in keep],
            [r for i, r in enumerate(rows) if i not in keep])


def risk_parts(company: dict, context: dict, feed: list, today) -> tuple:
    """(shown, folded). Shown: exclusivity losses of the next 24 months from
    scorecard.companies[T].exclusivity_losses, then readout slips from the feed (change
    type date_slip rated high, so Phase 3, SLIP_MIN_DAYS or more, detected in the last 90
    days, at most two, newest first, longer first on a shared day), then crowded pools from
    context.competition (company_pool.keeps at or under 0.90 and the indication worth 2%
    of the price or more, the core.js pool rule). At most five rows, each under 15 words
    and number first. Exclusivity keeps at least EXCLUSIVITY_SHOWN_MIN of them, more when
    slips and pools leave room, chosen as ``_pick_exclusivity`` says. Folded: every row
    left out, in the same order, for a "Show n more" under the list.

    Each row: {kind ("exclusivity", "slip", "pool"), lead, text, line, words, model} and the
    figures behind it."""
    ticker = None
    if isinstance(company, dict) and company.get("ticker"):
        ticker = company["ticker"]
    elif isinstance(context, dict) and context.get("ticker"):
        ticker = context["ticker"]
    if today is None and isinstance(context, dict):
        today = context.get("today")
    excl = exclusivity_rows(company, today)
    others = slip_rows(feed, today, ticker) + pool_rows(context)
    room = max(EXCLUSIVITY_SHOWN_MIN, RISK_MAX_ROWS - len(others))
    excl_shown, excl_folded = _pick_exclusivity(excl, room)
    rows = excl_shown + others
    return rows[:RISK_MAX_ROWS], excl_folded + rows[RISK_MAX_ROWS:]


def risks(company: dict, context: dict, feed: list, today) -> list:
    """The Risks rows shown, at most five (``risk_parts`` has the rule and the rest)."""
    return risk_parts(company, context, feed, today)[0]


# --- the section -----------------------------------------------------------------------
def section(ticker: str, context: dict, company: Optional[dict], feed: list,
            today=None, shown: int = DRIVERS_SHOWN) -> dict:
    """Everything the Catalysts tab prints for Drivers and risks, as rows and strings.

    {title, basis, state ("ok", "empty", "error"), message, drivers: {title, basis, rows,
    shown, more, more_label}, risks: {title, rows, more, more_label}}. A list with no row
    is left for the caller to skip; with both empty the state is "empty" and the message
    the one muted line. A context that did not load still lets the Risks read the
    scorecard and feed."""
    events = rank_events(context)
    risk_rows, risk_more = risk_parts(company, context, feed, today)
    problem = context_error(context)
    if problem is not None and not risk_rows:
        state, message = "error", CONTEXT_FAILED.format(T=ticker, error=problem)
    elif not events and not risk_rows:
        state, message = "empty", EMPTY.format(T=ticker)
    else:
        state, message = "ok", (CONTEXT_FAILED.format(T=ticker, error=problem)
                                if problem is not None else None)
    rest = events[shown:]
    return {
        "title": SECTION_TITLE, "basis": SECTION_BASIS, "state": state, "message": message,
        "drivers": {"title": DRIVERS_TITLE, "basis": drivers_basis(len(events)),
                    "rows": events, "shown": events[:shown], "more": rest,
                    "more_label": more_label(len(rest)) if rest else None},
        "risks": {"title": RISKS_TITLE, "rows": risk_rows, "more": risk_more,
                  "more_label": more_label(len(risk_more)) if risk_more else None},
    }
