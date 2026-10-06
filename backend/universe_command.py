"""The Universe tab's command centre: one company in focus against its cohort, in one read.

The redesigned Universe tab (AstraZeneca first) draws eight rankings, a price against
value map, a company board with the next 90 days, the week's material items ranked, rates
against the company's value, Medicare and exclusivity exposure, approvals and readouts on
one axis, a year of prices and the policy calendar. Each of those already has a module;
this assembles them so the page makes one read rather than about thirty, and does the few
things no route serves yet: daily closes for the whole cohort ending on the latest close,
the week's move, the rate and currency paths, short names for dated events and the week's
items ranked by a stated rule.

Two layers, so the rules can be tested without a book:

- ``read_sources`` reads every input from the modules and the database.
- ``assemble`` is pure: sources in, payload out. Nothing in it reads a clock, a file or
  the network.

Nothing is estimated here. A field a source does not carry is null, and the page says
"no free data" rather than drawing it as zero.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import statistics

import db

SCHEMA = 1
WINDOWS = (("1m", "1 month"), ("3m", "3 months"), ("1y", "1 year"))
WINDOW_LABEL = dict(WINDOWS)
# Words for the lead line: "in a month", "in three months", "in a year".
WINDOW_WORDS = {"1m": "in a month", "3m": "in three months", "1y": "in a year"}
DEFAULT_WINDOW = "1y"
# The week's news and the ranked list read the same seven days /headlines reads.
NEWS_DAYS = 7
# The board's radar: today and the 89 days after it.
AHEAD_DAYS = 90
# The approvals and readouts lanes run six months ahead of today.
LANE_MONTHS = 6
# A year of daily closes for the small multiples and the dialog, plus a margin so the
# first close of the year is on file.
CLOSES_DAYS = 372
# Rate and currency paths: about a quarter, enough to see the 30-day move in its context.
PATH_DAYS = 97
RATE_SERIES = ("DGS10", "DFII10", "T10YIE", "BAMLC0A3CAEY")
RATE_LABEL = {"DGS10": "10-year Treasury", "DFII10": "10-year real",
              "T10YIE": "Breakeven", "BAMLC0A3CAEY": "Single-A yield"}
FX_BASES = ("CHF", "DKK", "EUR", "GBP")
BENCHMARK = "XLV"
# The ranked list keeps this many items.
WEEK_ITEMS = 8
# Change types that count as company news on the board, and the glyph each draws as.
MATERIAL = {"efficacy_supplement": "approval", "new_approval": "approval",
            "press_approval": "approval", "press_data_readout": "readout",
            "press_deal": "deal", "PDUFA": "regulatory"}

_PHASE_RE = re.compile(r"\bphase\s*(2\s*/\s*3|II\s*/\s*III|1\s*/\s*2|I\s*/\s*II|3|III|2|II|1|I)\b",
                       re.I)
# The phase a release says its data come from: "52-Week Phase 2 Data from Ongoing Phase 2/3
# AMETHYST Study" reports Phase 2 data, whatever the study is called.
_DATA_PHASE_RE = re.compile(r"\bphase\s*(3|III|2|II)\s+(?:data|results?)\b", re.I)
_PRESENTS_RE = re.compile(r"\b(?:to|will)\s+(?:present|showcase|highlight|share|unveil)\b",
                          re.I)
_CODE_RE = re.compile(r"\b[A-Z]{2,5}-?\d{3,7}[A-Z]?\b")
_MONEY_RE = re.compile(r"\$\s*([\d.,]+)\s*(bn|billion|m|million)\b", re.I)
_NAME_TAIL = re.compile(
    r"(?:,?\s+(?:PLC|plc|Inc\.?|Incorporated|AG|A/S|S\.A\.|SA|N\.V\.|NV|Ltd\.?|Limited|"
    r"Corporation|Corp\.?|Company|Co\.|Holding|Holdings|Aktiengesellschaft|and|&))+$")


# --------------------------------------------------------------------------- helpers
def _iso(value) -> str | None:
    return str(value)[:10] if value else None


def _date(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def short_company(name: str | None, ticker: str = "") -> str:
    """The company as a sentence names it: "AstraZeneca PLC" reads "AstraZeneca",
    "Eli Lilly and Company" reads "Eli Lilly". The ticker where no name is on file."""
    name = (name or "").strip()
    if not name:
        return ticker
    out = _NAME_TAIL.sub("", name).strip(" ,")
    return out or name


def phase_of(title: str | None) -> str | None:
    """The phase a catalyst title states, as p1/p2/p3. Phase 2/3 reads as Phase 3 and
    Phase 1/2 as Phase 2, the convention the charts already use. None where none."""
    head = (title or "").split(",")[0]
    m = _PHASE_RE.search(head)
    if not m:
        return None
    p = m.group(1).upper().replace(" ", "")
    if p in ("3", "III", "2/3", "II/III"):
        return "p3"
    if p in ("2", "II", "1/2", "I/II"):
        return "p2"
    return "p1"


def data_phase(text: str | None) -> str | None:
    """The phase a readout announcement reports, from its own words: "Phase 2 data from
    a Phase 2/3 study" is Phase 2. "3", "2" or None where the text names no phase."""
    text = text or ""
    m = _DATA_PHASE_RE.search(text)
    if m:
        return "3" if m.group(1).upper() in ("3", "III") else "2"
    m = _PHASE_RE.search(text)
    if not m:
        return None
    p = m.group(1).upper().replace(" ", "")
    return "3" if p in ("3", "III", "2/3", "II/III") else "2"


def short_event(title: str | None, conditions=None) -> str:
    """A short name for a dated event, read off its registry title.

    The catalysts table carries "Phase 3, Truqap" where the trial maps to an asset and the
    whole registry title where it does not. A short remainder is the asset and is kept; a
    long one gives its compound code if it names one, else the first condition the
    registry lists, else its first words. Never invented: every word comes from the title
    or the trial row.
    """
    title = (title or "").strip()
    head, _, rest = title.partition(", ")
    if not rest:
        rest, head = head, ""
    rest = rest.strip()
    if " PDUFA" in rest:
        rest = rest.split(" PDUFA")[0]
        return rest[:1].upper() + rest[1:]
    if len(rest) <= 22:
        return rest
    code = _CODE_RE.search(rest)
    if code:
        return code.group(0)
    for cond in conditions or []:
        cond = str(cond).strip()
        if cond:
            word = cond.split(",")[0]
            words = word.split()
            return " ".join(words[:2]) if len(" ".join(words[:2])) <= 22 else words[0]
    words = [w for w in re.split(r"\s+", rest) if w]
    out = ""
    for w in words:
        if len(out) + len(w) + 1 > 22:
            break
        out = (out + " " + w).strip()
    return out or rest[:22]


def _money_usd(text: str | None) -> float | None:
    """'$8bn' or '$600 million' as USD, None where the text states no amount."""
    m = _MONEY_RE.search(text or "")
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = m.group(2).lower()
    return value * (1e9 if unit in ("bn", "billion") else 1e6)


def application_type(number: str | None) -> str | None:
    """NDA, BLA or ANDA, read off the application number's prefix. None where the number
    carries no prefix: the type is not guessed."""
    m = re.match(r"\s*(ANDA|NDA|BLA)", number or "", re.I)
    return m.group(1).upper() if m else None


def policy_short(item: dict) -> str:
    """A label short enough to sit on the policy calendar. The full title stays in the
    hover. Read off the title's own words by a few stated rules; the fallback is the
    title's first words."""
    title = item.get("title") or ""
    doc = item.get("doc_type") or ""
    low = title.lower()
    year = re.search(r"Contract Year (\d{4})", title)
    if year:
        return f"CY{year.group(1)} {'final rule' if doc == 'Rule' else 'proposed rule'}"
    if "negotiation program" in low and "guidance" in low:
        return "Negotiation " + ("draft" if "draft" in low else "final") + " guidance"
    if "negotiation program" in low and doc == "Proposed Rule":
        return "Negotiation proposed rule"
    if "request for information" in low:
        tail = title.split(";")[-1].strip().split()
        words = [w for w in tail if w.lower() not in ("standards", "and", "relevant",
                                                       "reasonable", "medicare", "part", "d")]
        return (" ".join(words[-2:]).lower() + " RFI").strip().capitalize()
    if "onshoring" in low:
        return "Onshoring agreements"
    if "reduction of tariffs" in low:
        return "Tariff reduction, patented products"
    if "specialty pharmaceuticals" in low:
        return "Specialty pharmaceuticals guidance"
    if "request for public comments" in low and "section 232" in low:
        return "Section 232 comment request"
    for prefix in ("Medicare Program; ", "Medicare and Medicaid Programs; ", "Notice of "):
        if title.startswith(prefix):
            title = title[len(prefix):]
    words = title.split()
    out = ""
    for w in words:
        if len(out) + len(w) + 1 > 30:
            break
        out = (out + " " + w).strip()
    return out[:1].upper() + out[1:].lower() if out else ""


def note_rate_move(note: dict | None) -> dict | None:
    """The rate move the stored note measured on the company, read off its own sentence:
    the move in basis points, the level it was measured from, the change in equity per
    share, the two values and the two dates compared. None where the note carries no such
    sentence, so nothing is shown rather than anything restated."""
    body = (note or {}).get("body") or ""
    m = re.search(r"10-year Treasury is ([\d.]+)%, (\d+)bp (above|below) the ([\d.]+)%", body)
    n = re.search(r"equity per share (falls|rises) ([\d.]+)%, from (\d[\d,]*(?:\.\d+)?) to "
                  r"(\d[\d,]*(?:\.\d+)?)", body)
    d = re.search(r"Dates compared: (\d{4}-\d{2}-\d{2}) and (\d{4}-\d{2}-\d{2})", body)
    if not (m and n and d):
        return None
    sign = -1.0 if n.group(1) == "falls" else 1.0
    return {"level": float(m.group(1)) / 100, "move_bp": float(m.group(2)) * (
                1 if m.group(3) == "above" else -1),
            "anchor": float(m.group(4)) / 100,
            "change_pct": sign * float(n.group(2)) / 100,
            "before": float(n.group(3).replace(",", "")),
            "now": float(n.group(4).replace(",", "")),
            "from": d.group(1), "to": d.group(2),
            "generated_at": _iso((note or {}).get("generated_at"))}


def _month_end(day: dt.date) -> dt.date:
    nxt = (day.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return nxt - dt.timedelta(days=1)


def _add_months(day: dt.date, months: int) -> dt.date:
    y, m = divmod(day.month - 1 + months, 12)
    year, month = day.year + y, m + 1
    return dt.date(year, month, min(day.day, _month_end(dt.date(year, month, 1)).day))


# --------------------------------------------------------------------------- sources
def _closes(conn, tickers, start: str, end: str) -> dict:
    out = {t: [] for t in tickers}
    marks = ",".join("?" * len(tickers))
    for r in conn.execute(
            f"""SELECT c.ticker, substr(p.as_of, 1, 10) AS d, p.close FROM prices p
                  JOIN companies c ON c.id = p.company_id
                 WHERE c.ticker IN ({marks}) AND p.interval = '1d' AND p.close IS NOT NULL
                   AND substr(p.as_of, 1, 10) > ? AND substr(p.as_of, 1, 10) <= ?
                 ORDER BY c.ticker, p.as_of""", (*tickers, start, end)):
        rows = out[r["ticker"]]
        if rows and rows[-1][0] == r["d"]:
            rows[-1] = [r["d"], round(r["close"], 4)]
        else:
            rows.append([r["d"], round(r["close"], 4)])
    return out


def _benchmark(conn, start: str, end: str) -> list:
    return [[r["d"], round(r["adjclose"], 4)] for r in conn.execute(
        """SELECT substr(as_of, 1, 10) AS d, adjclose FROM benchmark_prices
            WHERE symbol = ? AND adjclose IS NOT NULL
              AND substr(as_of, 1, 10) > ? AND substr(as_of, 1, 10) <= ?
            ORDER BY as_of""", (BENCHMARK, start, end))]


def _paths(conn, since: str) -> dict:
    rates = {s: [[_iso(r["as_of"]), r["value"]] for r in conn.execute(
        "SELECT as_of, value FROM market_rates WHERE series = ? AND as_of >= ? ORDER BY as_of",
        (s, since))] for s in RATE_SERIES}
    fx = {b: [[_iso(r["as_of"]), r["rate"]] for r in conn.execute(
        """SELECT as_of, rate FROM fx_rates WHERE base = ? AND quote = 'USD' AND as_of >= ?
            ORDER BY as_of""", (b, since))] for b in FX_BASES}
    return {"rates": rates, "fx": fx}


def _trials(conn, ncts) -> dict:
    ncts = sorted({n for n in ncts if n})
    out = {}
    for i in range(0, len(ncts), 400):
        chunk = ncts[i:i + 400]
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(
                f"""SELECT nct_id, title, phase, overall_status, enrollment, conditions
                      FROM trials WHERE nct_id IN ({marks})""", chunk):
            row = dict(r)
            try:
                row["conditions"] = json.loads(row["conditions"] or "[]")
            except (TypeError, ValueError):
                row["conditions"] = []
            out[row["nct_id"]] = row
    return out


def _approvals(conn, since: str) -> list:
    return [{"ticker": r["ticker"], "label": r["brand_name"] or r["generic_name"] or "",
             "date": r["approval_date"], "application_number": r["application_number"]}
            for r in conn.execute(
                """SELECT c.ticker, a.brand_name, a.generic_name, ap.approval_date,
                          ap.application_number
                     FROM approvals ap JOIN assets a ON a.id = ap.asset_id
                     JOIN companies c ON c.id = a.owner_company_id
                    WHERE ap.approval_date IS NOT NULL AND ap.approval_date >= ?
                    ORDER BY ap.approval_date""", (since,))]


def _valuation():
    """The Comps valuation payload with its scorecard: the last one the API computed, or
    a fresh build where none is held."""
    import response_cache
    held = response_cache.cached_json("/comps/valuation")
    if held is not None:
        return held
    import comps_valuation
    import company_score
    payload = comps_valuation.build()
    payload["scorecard"] = company_score.build(payload)
    return payload


def _fair_value(ticker: str):
    """The company's value lenses as the API last computed them. Inside the API a cold
    read is left to the warmer rather than paid in this one (it values every peer and
    runs to most of a minute); outside it, with no cache to read, it is computed."""
    import response_cache
    held = response_cache.cached_json(f"/companies/{ticker}/fair-value")
    if held is not None or response_cache.enabled():
        return held
    import fair_value
    return fair_value.company(None, ticker)


def read_sources(ticker: str, today: dt.date | None = None, db_path=None,
                 part: str = "all") -> dict:
    """Every input the page draws, read from the modules that own it. ``part="focal"``
    reads only what the company dialog needs."""
    import asset_revenue
    import comps
    import insights
    import trial_readouts

    today = today or dt.date.today()
    ticker = ticker.upper()
    src: dict = {"today": today.isoformat(), "ticker": ticker}
    src["valuation"] = _valuation()
    records = {r["ticker"]: r for r in src["valuation"].get("companies") or []}
    focal = records.get(ticker) or {}
    engine = focal.get("engine")
    cohort = sorted(t for t, r in records.items() if engine and r.get("engine") == engine)
    if ticker not in cohort:
        cohort = sorted(set(cohort) | {ticker})
    src["cohort"] = cohort
    start = (today - dt.timedelta(days=CLOSES_DAYS)).isoformat()
    conn = db.get_connection(db_path)
    try:
        src["closes"] = _closes(conn, cohort, start, today.isoformat())
        src["benchmark"] = _benchmark(conn, start, today.isoformat())
        src["relative"] = comps.relative_performance(conn=conn, ticker=ticker)
        src["fair_value"] = _fair_value(ticker)
        src["rar_focal"] = asset_revenue.build_revenue_at_risk(db_path, ticker)
        src["readouts"] = trial_readouts.recent(db_path, ticker, today=today, limit=40)
        src["note"] = insights.latest_note(db_path, ticker=ticker)
        import catalysts
        import slippage
        import whatchanged
        src["catalysts"] = catalysts.list_catalysts(db_path, within_days=365)
        src["slippage"] = slippage.build(db_path).get("summary") or []
        src["changes"] = [] if part == "focal" else whatchanged.build_feed(db_path, days=30)
        ncts = [c.get("description") for c in src["catalysts"]
                if (c.get("description") or "").startswith("NCT")]
        ncts += re.findall(r"NCT\d{8}", " ".join(
            r.get("headline") or "" for r in src["changes"]
            if r.get("change_type") == "date_slip"))
        src["trials"] = _trials(conn, ncts)
        import ira
        src["rar"] = asset_revenue.build_universe_at_risk(db_path).get("rows") or []
        src["ira"] = {t: ira.company_view(conn, t) for t in (cohort if part != "focal"
                                                             else [ticker])}
        src["approvals"] = _approvals(conn, f"{today.year}-01-01")
        if part == "focal":
            return src
        import headlines
        import markets
        from fetchers import policy_fedreg
        src["headlines"] = headlines.build(db_path, tickers=cohort, days=NEWS_DAYS)
        src["markets"] = markets.build(db_path, days=30)
        src["paths"] = _paths(conn, (today - dt.timedelta(days=PATH_DAYS)).isoformat())
        src["policy"] = policy_fedreg.recent(db_path, days=730)
    finally:
        conn.close()
    return src


# --------------------------------------------------------------------------- assemble
def _relative(record: dict) -> dict:
    rel = ((record.get("detail") or {}).get("relative") or record.get("relative") or {})
    out = {}
    for key, _label in WINDOWS:
        w = rel.get(key) or {}
        out[key] = {"rel": _finite(w.get("relative_pct")), "own": _finite(w.get("company_pct")),
                    "covers": w.get("covers_window")}
    return out


def _company(record: dict, score: dict) -> dict:
    m = record.get("market") or {}
    model = record.get("model") or {}
    street = ((record.get("street") or {}).get("price_target")) or {}
    hc = record.get("healthcare") or {}
    ratings = street.get("ratings") or {}
    cap = m.get("market_cap_usd_m")
    price = m.get("price")
    target = street.get("value")
    rng = model.get("range_today") or [None, None]
    return {
        "ticker": record["ticker"], "name": record.get("name") or record["ticker"],
        "short": short_company(record.get("name"), record["ticker"]),
        "region": record.get("region"), "currency": record.get("reporting_currency"),
        "price": price, "price_as_of": m.get("price_as_of"),
        "change_1d": m.get("change_1d"), "change_5d": m.get("change_5d"),
        "close_5d_as_of": m.get("close_5d_as_of"),
        "range_52w": m.get("range_52w"), "ttm_change": m.get("ttm_change"),
        "cap_usd_bn": cap / 1000.0 if cap is not None else None, "beta": m.get("beta"),
        "rel": _relative(record),
        "model": {"state": model.get("state"), "rating": model.get("rating"),
                  "upside": model.get("upside_12m"), "forward_12m": model.get("forward_12m"),
                  "value_today": model.get("fair_value_per_share"),
                  "low_today": rng[0], "high_today": rng[1]},
        "street": {"value": target, "low": street.get("low"), "high": street.get("high"),
                   "as_of": street.get("as_of"),
                   "buy": ratings.get("buy"), "hold": ratings.get("hold"),
                   "sell": ratings.get("sell"),
                   "upside": (target / price - 1.0) if target and price else None},
        "catalysts_12m": hc.get("catalysts_12m"), "late_trials": hc.get("late_trials"),
        "score": {"score": score.get("score"), "rank": score.get("rank"),
                  "ranked_of": score.get("ranked_of"), "rank_range": score.get("rank_range")},
    }


def _in_ahead(c: dict, start: dt.date, end: dt.date) -> str:
    """'in' when a catalyst falls inside start..end, 'left' when it is dated only to a
    month that runs past end, else 'out'."""
    d = c.get("expected_date") or ""
    if c.get("date_confidence") == "month" or len(d) == 7:
        m0 = _date(d[:7] + "-01")
        if m0 is None:
            return "out"
        m1 = _month_end(m0)
        if m1 < start:
            return "out"
        if m1 <= end:
            return "in"
        return "left" if m0 <= end else "out"
    day = _date(d)
    return "in" if day and start <= day <= end else "out"


def _event(c: dict, trials: dict) -> dict:
    nct = c.get("description") if (c.get("description") or "").startswith("NCT") else None
    trial = trials.get(nct) or {}
    d = c.get("expected_date") or ""
    month = c.get("date_confidence") == "month" or len(d) == 7
    return {"id": c.get("id"), "ticker": c.get("ticker"), "date": d[:7] if month else d[:10],
            "month": month, "confidence": c.get("date_confidence"),
            "firm": c.get("date_confidence") in ("confirmed", "stated"),
            "type": c.get("catalyst_type"),
            "regulatory": (c.get("catalyst_type") or "") != "data readout",
            "phase": phase_of(c.get("title")), "title": c.get("title"), "nct": nct,
            "short": short_event(c.get("title"), trial.get("conditions")),
            "conditions": trial.get("conditions") or [], "enrollment": trial.get("enrollment"),
            "trial_title": trial.get("title"), "url": c.get("source_url")}


def _news(headlines: list, changes: list, cohort, since: str) -> dict:
    """The week's news by company: the headlines' own items plus the feed's material
    types, without counting one event twice."""
    news = {t: [] for t in cohort}
    for h in headlines:
        t = h.get("ticker")
        if t not in news:
            continue
        text = (h.get("headline") or "")
        text = text[len(t) + 1:] if text.startswith(t + " ") else text
        news[t].append({"kind": h.get("kind"), "date": _iso(h.get("date")), "text": text})
    held = {(t, n["kind"]) for t in news for n in news[t]}
    for r in changes:
        t = r.get("ticker")
        if t not in news or r.get("kind") != "change":
            continue
        if (_iso(r.get("detected_at")) or _iso(r.get("date")) or "") < since:
            continue
        kind = MATERIAL.get(r.get("change_type"))
        if r.get("change_type") == "date_slip" and r.get("significance") == "high":
            kind = "slip"
        if not kind or (kind in ("approval", "readout", "deal") and (t, kind) in held):
            continue
        text = r.get("headline") or ""
        text = text[len(t) + 1:] if text.startswith(t + " ") else text
        news[t].append({"kind": kind, "date": _iso(r.get("date")), "text": text})
    return news


def _day_move(closes: list, day: str):
    """Close on ``day`` against the close before it, None where either is missing."""
    for i, (d, c) in enumerate(closes):
        if d == day:
            return (c / closes[i - 1][1] - 1.0) if i > 0 and closes[i - 1][1] else None
        if d > day:
            # The first session on or after a non-trading day.
            return (c / closes[i - 1][1] - 1.0) if i > 0 and closes[i - 1][1] else None
    return None


def _week_items(src: dict, companies: dict, events: list, ticker: str,
                today: dt.date) -> list:
    """The week ranked by a stated rule: deals with a stated value by value, the rate
    move the book is priced on, Phase 3 results, deals with no value, Phase 2 results,
    label expansions grouped, the focal company's largest slip (else the largest), then the
    next firm FDA date inside 30 days. Each item carries its own figure and date."""
    since = (today - dt.timedelta(days=NEWS_DAYS)).isoformat()
    closes = src.get("closes") or {}
    heads = src.get("headlines") or []
    feed = src.get("changes") or []
    items = []

    def move(t, day):
        return _day_move(closes.get(t) or [], day) if day else None

    # Deals with a stated value, largest first.
    priced = []
    for h in heads:
        if h.get("kind") != "deal":
            continue
        t = h["ticker"]
        body = (h.get("headline") or "")[len(t) + 1:]
        terms = {p.get("label"): p.get("value") for p in h.get("summary") or []}
        value = _money_usd(h.get("figure"))
        up, ms = _money_usd(terms.get("Upfront")), _money_usd(terms.get("Milestones"))
        party = terms.get("Counterparty")
        party_t = next((u for u, c in companies.items() if party and u != t
                        and c["short"].split()[0].lower() == party.split()[0].lower()), None)
        day = _iso(h.get("date"))
        moves = [(t, move(t, day))] + ([(party_t, move(party_t, day))] if party_t else [])
        priced.append({"kind": "deal", "tag": "deal", "tickers": [t] + ([party_t] if party_t else []),
                       "head": (body[:1].upper() + body[1:] + (f": {h['detail']}" if h.get("detail") else "")),
                       "fig": h.get("figure"), "value_usd": value, "date": day,
                       "mini": {"type": "deal", "upfront": up, "milestones": ms},
                       "rows": [[p.get("label"), p.get("value")] for p in h.get("summary") or []]
                               + [[f"Day move, {day}", [[u, mv] for u, mv in moves]]],
                       "url": h.get("url"), "src": "/headlines (deal)"})
    priced.sort(key=lambda i: -(i["value_usd"] or 0))
    items += [i for i in priced if i["value_usd"]]
    unpriced_heads = [i for i in priced if not i["value_usd"]]

    # The rate move the book is priced on: the latest 10-year flag of the week.
    rate_flags = sorted([r for r in feed if r.get("kind") == "market"
                         and r.get("change_type") == "rate_move"
                         and (_iso(r.get("detected_at") or r.get("date")) or "") >= since],
                        key=lambda r: r.get("date") or "")
    rates = {r["series"]: r for r in (src.get("markets") or {}).get("rates") or []}
    if rate_flags and rates.get("DGS10"):
        r10 = rates["DGS10"]
        path = [[d, v] for d, v in ((src.get("paths") or {}).get("rates") or {}).get("DGS10", [])]
        last = rate_flags[-1]
        rows = [["Level", {"value": r10.get("value"), "as_of": r10.get("as_of"),
                           "change_bp": r10.get("change_bp"), "from": r10.get("change_from")}],
                ["Flags this week", [[_iso(f.get("date")), f.get("headline")] for f in rate_flags]]]
        for s in ("DFII10", "T10YIE"):
            if rates.get(s) and rates[s].get("change_bp") is not None:
                rows.append([RATE_LABEL[s], {"change_bp": rates[s]["change_bp"],
                                             "from": rates[s].get("change_from"),
                                             "as_of": rates[s].get("as_of")}])
        items.append({"kind": "market", "tag": "rates", "tickers": ["ALL"],
                      "head": last.get("headline"), "fig_bp": r10.get("change_bp"),
                      "fig_sub": "30 days", "date": _iso(last.get("date")),
                      "mini": {"type": "spark", "values": [v for _d, v in path]},
                      "rows": rows, "url": None, "src": "/markets, /changes (rate_move)"})

    # Readouts from the headlines, by the phase the announcement reports. A notice that
    # data will be presented is not a result and is left to the board's news glyphs.
    readouts = []
    for h in heads:
        if h.get("kind") != "readout":
            continue
        t = h["ticker"]
        body = (h.get("headline") or "")[len(t) + 1:]
        if _PRESENTS_RE.search(body):
            continue
        ph = data_phase(body)
        day = _iso(h.get("date"))
        readouts.append({"kind": "readout" if ph != "2" else "readout2",
                         "tag": f"phase {ph}" if ph else "result", "tickers": [t],
                         "head": body, "fig_move": move(t, day), "date": day, "phase": ph,
                         "mini": {"type": "stock", "ticker": t, "marks": [day]},
                         "rows": [["Read out of", "the company's own announcement"],
                                  ["Day move", [[t, move(t, day)]]]],
                         "url": h.get("url"), "src": "/headlines (readout)"})
    items += [r for r in readouts if r["phase"] != "2"]

    # Deals with no stated value: the feed's press deals of the week, and any headline deal
    # that came without a figure. A filing on the same company in the week folds in.
    filings = {h["ticker"]: h for h in heads if h.get("kind") == "filing"}
    for r in feed:
        if r.get("change_type") != "press_deal" or r.get("ticker") not in companies:
            continue
        if (_iso(r.get("detected_at") or r.get("date")) or "") < since:
            continue
        t = r["ticker"]
        if any(t in i["tickers"] for i in items if i["kind"] == "deal"):
            continue
        text = (r.get("headline") or "")[len(t) + 1:]
        text = re.sub(r"\s+", " ", text).strip()
        day = _iso(r.get("date"))
        rows = [["Announced value", None], ["Announced", day]]
        marks = [day]
        if t in filings:
            f = filings[t]
            rows.append([f"{f.get('figure') or 'Filing'}", _iso(f.get("date"))])
            marks.append(_iso(f.get("date")))
        rows.append(["Day move", [[t, move(t, day)]]])
        items.append({"kind": "deal", "tag": "deal", "tickers": [t], "head": text,
                      "fig": None, "value_usd": None, "date": day,
                      "mini": {"type": "stock", "ticker": t, "marks": marks},
                      "rows": rows, "url": (filings.get(t) or {}).get("url"),
                      "src": "/changes (press_deal), /headlines (filing)"})
    items += unpriced_heads
    items += [r for r in readouts if r["phase"] == "2"]

    # Label expansions of the week, one row.
    supps = [r for r in feed if r.get("change_type") == "efficacy_supplement"
             and r.get("ticker") in companies
             and (_iso(r.get("detected_at") or r.get("date")) or "") >= since]
    if supps:
        brands, dates, rows, tickers = [], [], [], []
        for r in supps:
            text = r.get("headline") or ""
            m = re.search(r"efficacy supplement: (.+?) approved (\d{4}-\d{2}-\d{2})", text)
            if not m:
                continue
            brands.append(m.group(1))
            dates.append(m.group(2))
            rows.append([r["ticker"], f"{m.group(1)} approved {m.group(2)}"])
            if r["ticker"] not in tickers:
                tickers.append(r["ticker"])
        if brands:
            items.append({"kind": "approval", "tag": "approval", "tickers": tickers,
                          "brands": brands, "fig_n": len(brands), "date": max(dates),
                          "mini": {"type": "dates", "dates": sorted(dates)},
                          "rows": rows + [["Seen", _iso(max(_iso(r.get("date")) for r in supps))]],
                          "url": None, "src": "/changes (efficacy_supplement)"})

    # A slip: the focal company's largest of the week, else the largest.
    slips = []
    for r in feed:
        if r.get("change_type") != "date_slip" or r.get("significance") != "high":
            continue
        if r.get("ticker") not in companies:
            continue
        if (_iso(r.get("detected_at") or r.get("date")) or "") < since:
            continue
        m = re.search(r"(NCT\d{8}).*?(\d{4}-\d{2}-\d{2})\s*->\s*(\d{4}-\d{2}-\d{2})",
                      r.get("headline") or "")
        if not m:
            continue
        a, b = _date(m.group(2)), _date(m.group(3))
        if not (a and b) or b <= a:
            continue
        slips.append({"ticker": r["ticker"], "nct": m.group(1), "was": m.group(2),
                      "now": m.group(3), "days": (b - a).days, "seen": _iso(r.get("date"))})
    if slips:
        own = [s for s in slips if s["ticker"] == ticker]
        s = max(own or slips, key=lambda s: s["days"])
        trial = (src.get("trials") or {}).get(s["nct"]) or {}
        items.append({"kind": "slip", "tag": "slip", "tickers": [s["ticker"]],
                      "slip": s, "head_title": trial.get("title"),
                      "phase": trial.get("phase"), "date": s["seen"],
                      "mini": {"type": "slip", "was": s["was"], "now": s["now"]},
                      "rows": [["Study", s["nct"]], ["Was", s["was"]], ["Now", s["now"]]],
                      "url": f"https://clinicaltrials.gov/study/{s['nct']}",
                      "src": "/changes (date_slip)"})

    # The next firm FDA date inside 30 days.
    end30 = today + dt.timedelta(days=30)
    firm = [e for e in events if e["firm"] and e["regulatory"] and not e["month"]
            and _date(e["date"]) and today <= _date(e["date"]) <= end30]
    if firm:
        e = min(firm, key=lambda e: e["date"])
        items.append({"kind": "regulatory", "tag": "ahead", "tickers": [e["ticker"]],
                      "event": e, "n_firm": len(firm),
                      "days": (_date(e["date"]) - today).days, "date": e["date"],
                      "mini": {"type": "countdown", "days": (_date(e["date"]) - today).days,
                               "of": 30},
                      "rows": [["Date", f"{e['date']}, {e['confidence']}"]],
                      "url": e.get("url"), "src": "/catalysts"})
    for i, it in enumerate(items[:WEEK_ITEMS], 1):
        it["rank"] = i
    return items[:WEEK_ITEMS]


def _lead(companies: dict, window: str) -> dict:
    us = [c["rel"][window]["own"] for c in companies.values() if c.get("region") == "US"]
    eu = [c["rel"][window]["own"] for c in companies.values() if c.get("region") == "Europe"]
    own = {t: c["rel"][window]["own"] for t, c in companies.items()
           if c["rel"][window]["own"] is not None}
    return {"us_median": _median(us), "us_n": len([v for v in us if v is not None]),
            "eu_median": _median(eu), "eu_n": len([v for v in eu if v is not None]),
            "own": own}


def assemble(src: dict, ticker: str, window: str = DEFAULT_WINDOW,
             part: str = "all") -> dict:
    """The page's payload from its sources. Pure."""
    ticker = ticker.upper()
    window = window if window in WINDOW_LABEL else DEFAULT_WINDOW
    today = _date(src["today"])
    val = src.get("valuation") or {}
    sc = val.get("scorecard") or {}
    sc_companies = sc.get("companies") or {}
    records = {r["ticker"]: r for r in val.get("companies") or []}
    cohort = [t for t in src.get("cohort") or [] if t in records]
    companies = {t: _company(records[t], sc_companies.get(t) or {}) for t in cohort}
    focal_rec = sc_companies.get(ticker) or {}
    cohort_id = focal_rec.get("cohort")
    cohort_meta = (sc.get("cohorts") or {}).get(cohort_id) or {}

    closes = src.get("closes") or {}
    bench = src.get("benchmark") or []
    price_date = max((c["price_as_of"] for c in companies.values() if c.get("price_as_of")),
                     default=None)
    # XLV over the week, on its adjusted close: the same five sessions as change_5d.
    xlv_week = None
    xb = [r for r in bench if price_date and r[0] <= price_date]
    if len(xb) > 5 and xb[-6][1]:
        xlv_week = {"change": xb[-1][1] / xb[-6][1] - 1.0, "from": xb[-6][0], "to": xb[-1][0]}

    trials = src.get("trials") or {}
    start, end = today, today + dt.timedelta(days=AHEAD_DAYS - 1)
    cats = src.get("catalysts") or []
    in90 = [c for c in cats if c.get("ticker") in companies and _in_ahead(c, start, end) == "in"]
    left = [c for c in cats if c.get("ticker") in companies and _in_ahead(c, start, end) == "left"]
    events = sorted((_event(c, trials) for c in in90),
                    key=lambda e: (e["date"] if not e["month"] else e["date"] + "-99", e["ticker"]))
    for t, c in companies.items():
        c["n90"] = sum(1 for e in events if e["ticker"] == t)
        slip = next((s for s in src.get("slippage") or [] if s.get("ticker") == t), None)
        c["slip"] = ({"moved": slip.get("trials_moved"), "slipped": slip.get("slipped"),
                      "pulled_in": slip.get("pulled_in"), "median_days": slip.get("median_days"),
                      "on_file": True} if slip else
                     {"moved": 0, "slipped": 0, "pulled_in": 0, "median_days": None,
                      "on_file": False})

    rel = src.get("relative") or {}
    windows = {k: {"label": lab, "xlv": (rel.get(k) or {}).get("benchmark_pct"),
                   "first": (rel.get(k) or {}).get("first_as_of"),
                   "last": (rel.get(k) or {}).get("last_as_of")} for k, lab in WINDOWS}

    fv = src.get("fair_value") or {}
    rating = fv.get("rating") if isinstance(fv.get("rating"), dict) else {}
    rar_f = src.get("rar_focal") or {}
    buckets = []
    for b in rar_f.get("buckets") or []:
        for row in b.get("covered") or []:
            buckets.append({"brand": row.get("brand_name"), "loe": row.get("loe"),
                            "basis": row.get("basis"), "revenue": row.get("revenue"),
                            "fiscal_year": row.get("fiscal_year"), "year": b.get("year")})
    year0 = f"{today.year}-01-01"
    readouts = [{"drug": r.get("drug"), "phase": r.get("phase"), "outcome": r.get("outcome"),
                 "date": _iso(r.get("event_date")), "quote": r.get("quote")}
                for r in src.get("readouts") or [] if (_iso(r.get("event_date")) or "") >= year0]
    deals = (focal_rec.get("facts") or {}).get("deals") or {}
    focal = {
        "ticker": ticker,
        "name": (companies.get(ticker) or {}).get("name") or ticker,
        "short": (companies.get(ticker) or {}).get("short") or ticker,
        "fair_value": {"ok": bool(fv.get("ok")), "price_date": fv.get("price_date"),
                       "close": fv.get("close"),
                       "lenses": [{"key": l.get("key"), "lens": l.get("lens"), "low": l.get("low"),
                                   "mid": l.get("mid"), "high": l.get("high"),
                                   "basis": l.get("basis")} for l in fv.get("lenses") or []],
                       "rating": {k: rating.get(k) for k in (
                           "rating", "value_today", "low_today", "high_today", "forward_12m",
                           "forward_low", "forward_high", "upside_12m", "cost_of_equity")}},
        "loe_first": buckets[:3],
        "readouts": readouts,
        "pillars": {p: {"score": (v or {}).get("score"), "median": (v or {}).get("median")}
                    for p, v in (focal_rec.get("pillars") or {}).items()},
        "positives": [{"text": p.get("text"), "source": p.get("source")}
                      for p in focal_rec.get("positives") or []],
        "negatives": [{"text": p.get("text"), "source": p.get("source")}
                      for p in focal_rec.get("negatives") or []],
        "deals": {"n": deals.get("n"), "count_text": deals.get("count_text"),
                  "chip": deals.get("chip")},
        "note_rate": note_rate_move(src.get("note")),
        "events": [e for e in events if e["ticker"] == ticker],
        "approvals": [{**a, "application_type": application_type(a.get("application_number"))}
                      for a in src.get("approvals") or [] if a.get("ticker") == ticker],
    }
    out = {
        "schema": SCHEMA, "complete": bool(val.get("complete", True)) and bool(cohort),
        "ticker": ticker, "window": window, "today": today.isoformat(),
        "price_date": price_date, "windows": windows,
        "cohort": {"id": cohort_id, "label": cohort_meta.get("label"),
                   "noun": cohort_meta.get("noun"), "n": len(cohort),
                   "medians": cohort_meta.get("medians") or {}},
        "tickers": sorted(cohort, key=lambda t: -(companies[t]["cap_usd_bn"] or 0)),
        "companies": companies, "focal": focal, "xlv_week": xlv_week,
        "closes": {t: closes.get(t) or [] for t in cohort}, "benchmark": bench,
        "benchmark_symbol": BENCHMARK,
    }
    rar = {r["ticker"]: r for r in src.get("rar") or []}
    for t, c in companies.items():
        r = rar.get(t) or {}
        c["loe"] = {"share_5y": r.get("share_5y"), "at_risk_5y_usd": r.get("at_risk_5y_usd"),
                    "priced_total_usd": r.get("priced_total_usd")}
        if t not in (src.get("ira") or {}):
            continue
        iv = (src.get("ira") or {}).get(t) or {}
        ex = iv.get("exposure") or {}
        seen, selected = set(), []
        for s in iv.get("selected") or []:
            key = (s.get("brand"), s.get("ipay"))
            if key in seen:
                continue
            seen.add(key)
            selected.append({"brand": s.get("brand"), "ipay": s.get("ipay"),
                             "ceiling_cut": s.get("ceiling_cut")})
        c["ira"] = {"share": ex.get("share"), "part_d_spending": ex.get("part_d_spending"),
                    "revenue_usd": ex.get("revenue_usd"), "spending_years": ex.get("spending_years"),
                    "selected": selected, "reason": iv.get("reason") or ex.get("reason")}
    if part == "focal":
        return out

    since = (today - dt.timedelta(days=NEWS_DAYS)).isoformat()
    news = _news(src.get("headlines") or [], src.get("changes") or [], cohort, since)
    for t, c in companies.items():
        c["news"] = news.get(t) or []

    lane_end = _add_months(today, LANE_MONTHS)
    lane_events = [_event(c, trials) for c in cats if c.get("ticker") in companies
                   and _in_ahead(c, today, lane_end) == "in"]
    approvals = [{**a, "application_type": application_type(a.get("application_number"))}
                 for a in src.get("approvals") or [] if a.get("ticker") in companies]

    markets = src.get("markets") or {}
    paths = src.get("paths") or {}
    reporters: dict = {}
    for t in cohort:
        reporters.setdefault(companies[t].get("currency"), []).append(t)
    mk = {"rates": [{**r, "label": RATE_LABEL.get(r.get("series"), r.get("series")),
                     "path": (paths.get("rates") or {}).get(r.get("series")) or []}
                    for r in markets.get("rates") or []],
          "fx": [{**f, "path": (paths.get("fx") or {}).get(f.get("base")) or [],
                  "reporters": reporters.get(f.get("base")) or []}
                 for f in markets.get("fx") or []],
          "benchmarks": markets.get("benchmarks") or [], "days": markets.get("days")}

    events_policy = []
    for r in src.get("changes") or []:
        if r.get("kind") != "policy" or r.get("ticker") not in companies:
            continue
        text = r.get("headline") or ""
        if r.get("change_type") == "ira_selected":
            m = re.search(r"IPAY (\d{4}): (.+)$", text)
            events_policy.append({"date": _iso(r.get("date")), "ticker": r["ticker"],
                                  "kind": "selected",
                                  "drug": m.group(2).strip() if m else None,
                                  "year": int(m.group(1)) if m else None})
        elif r.get("change_type") == "ira_deselected":
            m = re.search(r"deselected (.+?) from Medicare", text)
            events_policy.append({"date": _iso(r.get("date")), "ticker": r["ticker"],
                                  "kind": "deselected",
                                  "drug": m.group(1).split(";")[0].strip() if m else None,
                                  "year": None})
    policy_items = [{**p, "short": policy_short(p)} for p in src.get("policy") or []]

    out.update({
        "lead": {k: _lead(companies, k) for k, _l in WINDOWS},
        "events": events, "events_left_off": len(left),
        "events_window": {"start": start.isoformat(), "end": end.isoformat()},
        "week_items": _week_items(src, companies, events, ticker, today),
        "week_since": since,
        "lanes": {"start": f"{today.year}-01-01", "end": lane_end.isoformat(),
                  "events": lane_events, "approvals": approvals},
        "markets": mk,
        "policy": {"items": policy_items, "events": events_policy},
    })
    return out


def build(ticker: str = "AZN", window: str = DEFAULT_WINDOW, today: dt.date | None = None,
          db_path=None, part: str = "all") -> dict | None:
    """The payload for one company in focus, or None for a ticker the book does not hold."""
    ticker = (ticker or "").upper()
    conn = db.get_connection(db_path)
    try:
        known = conn.execute("SELECT 1 FROM companies WHERE ticker = ?", (ticker,)).fetchone()
    finally:
        conn.close()
    if not known:
        return None
    src = read_sources(ticker, today=today, db_path=db_path, part=part)
    return json.loads(json.dumps(assemble(src, ticker, window, part=part), default=str),
                      parse_constant=lambda _c: None)
