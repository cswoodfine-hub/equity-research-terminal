"""The Universe tab's command centre: the week across the group, in one read.

The redesigned Universe tab (AstraZeneca first) leads with the week's news across the
cohort: the week's items ranked by a stated rule (the lead story is rank 1), a company
board with each company's week move, news count and next dated event, the group from cheap
to expensive on the model's upside and a grid of every change. Under them sit the
approvals and readouts, a year of prices, rates and currencies, Medicare and exclusivity,
the policy calendar and the company picked against the group, and the company dialog
reads ``part="focal"``. Each of those already has a module; this assembles them so the
page makes one read rather than about thirty, and does the few things no route serves yet:
daily closes for the whole cohort ending on the latest close, the week's move, the rate
and currency paths, short names for dated events and the week itself. No rule of the week
reads the company picked, so the page reads the same whichever it is.

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
# The ranked feed keeps this many items; the page shows as many as fit its column.
WEEK_ITEMS = 16
# The ranked feed's look-ahead items: Phase 3 primary completions due inside 14 days and
# listed patents and exclusivities ending inside 60.
DUE_DAYS = 14
LOE_DAYS = 60
# The slips item lists this many of the week's longest high slips in its rows.
SLIP_ROWS = 6
# A filing no reader opens: the voting-rights and share-admission notices and a bare cover
# form ("6-K: FORM 6-K", "6-K: 6-K"). Left out of the ranked feed and the grid, and
# counted, so the page can say how many it dropped.
_ROUTINE_FILING_RE = re.compile(
    r"TOTAL VOTING RIGHTS|ADMISSION OF FURTHER SECURITIES|BLOCK LISTING|"
    r"TRANSACTION IN OWN SHARES|DIRECTOR/PDMR|^\s*(?:FORM\s+)?\d{1,2}-K\s*$", re.I)
# A trial completion move: the study and the two dates, either a day or a month.
_SLIP_RE = re.compile(r"(NCT\d{8}).*?(\d{4}-\d{2}(?:-\d{2})?)\s*->\s*(\d{4}-\d{2}(?:-\d{2})?)")
# The day a results announcement names for its call: "Conference Call Oct. 29".
_MONTH_DAY_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\b")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# A filed press release's own title, where the deal's terms were read off its exhibit:
# "Exhibit 99.1 Press Release <title> •".
_EXHIBIT_TITLE_RE = re.compile(r"Press Release\s+(.+?)\s+•")
_EXHIBIT_NO_RE = re.compile(r"\bEX-(99\.\d+)\b")
# Words too common in deal announcements to tie a filing to a deal by.
_DEAL_COMMON = {"announces", "announce", "completes", "complete", "strategic", "investment",
                "clinical", "collaboration", "advance", "equity", "leading", "strategy",
                "cancer", "agreement", "global", "therapeutics", "pharmaceuticals", "plc",
                "combination", "with", "license", "licensing", "acquire", "acquisition"}
# The grid of every change: one row per kind, every change type of the week in exactly one
# row, or left out (catalysts, LOE and market rows are not changes of the week).
GRID_KINDS = (("deal", "Deals"), ("result", "Results and data notices"),
              ("fda", "FDA approvals"), ("slip", "Trial dates slipped"),
              ("company", "Filings and company news"),
              ("routine", "Labels and registry updates"))
_GRID_OF = {"press_deal": "deal", "press_data_readout": "result",
            "press_approval": "fda", "efficacy_supplement": "fda", "new_approval": "fda",
            "press_regulatory": "fda", "date_slip": "slip",
            "new_filing": "company", "material event": "company", "press_results": "company",
            "leadership_change": "company",
            "label_change": "routine", "status_change": "routine", "date_change": "routine",
            "enrollment_change": "routine", "design_change": "routine",
            "endpoint_change": "routine"}
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
# A compound code: AZD0901, BMS-986278, and the eight-digit Pfizer and J&J codes
# (PF-07275315, JNJ-95597528) the seven-digit limit used to miss. A three-digit code may
# take a space ("ABP 234", Amgen's biosimilar); a year after an acronym ("ESMO 2026") has
# four digits and does not.
_CODE_RE = re.compile(r"\b[A-Z]{2,5}(?:-?\d{3,8}| \d{3})[A-Z]?\b")
# A nonproprietary drug name, by the WHO stem it ends in (-mab, -tinib, -glutide, -siran,
# -vec ...): "A Study of Milvexian..." names no stem, but "Study of Ianalumab Versus
# Placebo" does. Four letters at least before the stem, so "beta" or "cel" alone never
# match. Measured on every catalyst title in the book: each word it took is a drug.
_INN_RE = re.compile(
    r"\b[A-Za-z][a-z]{3,}(?:mab|nib|ciclib|parib|lisib|degib|zomib|tide|stat|vir|gene|"
    r"vec|cel|dotin|tecan|xaban|gatran|gliflozin|gliptin|sartan|platin|taxel|rubicin|"
    r"rsen|siran|cept|kinra|tug|lutamide|rexant|bart)\b")
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


def short_event_basis(title: str | None, conditions=None) -> tuple[str, str]:
    """A short name for a dated event, read off its registry title, and what it names.

    The catalysts table carries "Phase 3, Truqap" where the trial maps to an asset and the
    whole registry title where it does not. A short remainder is the asset and is kept
    ("asset"). A long one gives the first drug it names, a compound code or a
    nonproprietary name ("drug"); else the first condition the registry lists
    ("condition"); else its first words ("title"). Never invented: every word comes from
    the title or the trial row.
    """
    title = (title or "").strip()
    head, _, rest = title.partition(", ")
    if not rest:
        rest, head = head, ""
    rest = rest.strip()
    if " PDUFA" in rest:
        rest = rest.split(" PDUFA")[0]
        return rest[:1].upper() + rest[1:], "drug"
    # "bepirovirsen PDUFA, treatment of adults with chronic hepatitis B": the asset is the
    # word before PDUFA, not the indication after the comma.
    if head.endswith(" PDUFA") and head[:-6].strip():
        name = head[:-6].strip()
        return name[:1].upper() + name[1:], "drug"
    if len(rest) <= 22:
        return rest, "asset"
    named = [m for m in (_CODE_RE.search(rest), _INN_RE.search(rest)) if m]
    if named:
        word = min(named, key=lambda m: m.start()).group(0)
        return word[:1].upper() + word[1:], "drug"
    for cond in conditions or []:
        cond = str(cond).strip()
        if cond:
            # The registry joins some conditions with ";" as well as ",".
            words = re.split(r"[,;]", cond)[0].split()
            two = " ".join(words[:2])
            return (two if len(two) <= 22 else words[0]), "condition"
    words = [w for w in re.split(r"\s+", rest) if w]
    out = ""
    for w in words:
        if len(out) + len(w) + 1 > 22:
            break
        out = (out + " " + w).strip()
    return out or rest[:22], "title"


def short_event(title: str | None, conditions=None) -> str:
    """The short name alone (see short_event_basis)."""
    return short_event_basis(title, conditions)[0]


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
        what = " ".join(words[-2:]).lower()
        return (what[:1].upper() + what[1:] + " RFI").strip()
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


def _deal_rows(conn, tickers, since: str) -> list:
    """The deals table's rows for the cohort since ``since``: the stored announcing
    headline (``quote``, verbatim) and where it came from, so a deal on the ranked feed
    can carry its source's own words."""
    marks = ",".join("?" * len(tickers))
    return [dict(r) for r in conn.execute(
        f"""SELECT c.ticker, d.counterparty, d.event_date, d.quote, d.source_url,
                   d.article_url, d.terms_source, d.event_date_source
              FROM deals d JOIN companies c ON c.id = d.company_id
             WHERE c.ticker IN ({marks}) AND d.event_date >= ?
             ORDER BY d.event_date""", (*tickers, since))]


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
        import forecast_view
        # Which of the company's dated events the model prices, and the swing a share;
        # the dialog's "at stake" column reads it, so an unpriced event says so.
        src["stakes"] = forecast_view.catalyst_stakes(db_path, ticker)
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
        src["deal_rows"] = _deal_rows(conn, cohort,
                                      (today - dt.timedelta(days=2 * NEWS_DAYS)).isoformat())
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
    short, basis = short_event_basis(c.get("title"), trial.get("conditions"))
    d = c.get("expected_date") or ""
    month = c.get("date_confidence") == "month" or len(d) == 7
    return {"id": c.get("id"), "ticker": c.get("ticker"), "date": d[:7] if month else d[:10],
            "month": month, "confidence": c.get("date_confidence"),
            "firm": c.get("date_confidence") in ("confirmed", "stated"),
            "type": c.get("catalyst_type"),
            "regulatory": (c.get("catalyst_type") or "") != "data readout",
            "phase": phase_of(c.get("title")), "title": c.get("title"), "nct": nct,
            "short": short, "short_basis": basis,
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


def _seen(r: dict) -> str:
    """When the book first saw a row: detected_at, else the row's own date."""
    return _iso(r.get("detected_at")) or _iso(r.get("date")) or ""


def _strip_ticker(text: str | None, ticker: str | None) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[len(ticker) + 1:] if ticker and text.startswith(ticker + " ") else text


def _first_day(iso: str) -> dt.date | None:
    """A day, or the first day of a month-only date."""
    return _date(iso if len(iso or "") == 10 else f"{iso}-01")


def _dshort(iso) -> str:
    """'5 Oct', or the month alone for a month-only date."""
    d = _date(iso)
    if d:
        return f"{d.day} {_MONTHS[d.month - 1]}"
    m = _first_day(str(iso or "")[:7])
    return _MONTHS[m.month - 1] if m else str(iso or "")


def _dlong(iso) -> str:
    """'25 May 2028', or 'May 2028' for a month-only date."""
    d = _date(iso)
    if d and len(str(iso)) >= 10:
        return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"
    m = _first_day(str(iso or "")[:7])
    return f"{_MONTHS[m.month - 1]} {m.year}" if m else str(iso or "")


def _slip(r: dict) -> dict | None:
    """A date_slip row's study and its two dates, either a day or a month: the days
    between (a month-only date counts from its first day), whether either date is a month
    only, and the feed's own significance (high is a Phase 3 moved more than 30 days,
    materiality.slip_significance). None where the row states no later date."""
    m = _SLIP_RE.search(r.get("headline") or "")
    if not m:
        return None
    was, now = m.group(2), m.group(3)
    a, b = _first_day(was), _first_day(now)
    if not (a and b) or b <= a:
        return None
    return {"ticker": r.get("ticker"), "nct": m.group(1), "was": was, "now": now,
            "days": (b - a).days, "month": len(was) == 7 or len(now) == 7,
            "seen": _seen(r), "high": r.get("significance") == "high", "moves": 1}


def _span(s: dict) -> str:
    """A slip's size as the page words it: in days under 120, in months from 120 days,
    and in months whenever either date is a month only."""
    if s["month"] or s["days"] >= 120:
        a, b = _first_day(s["was"]), _first_day(s["now"])
        months = (b.year - a.year) * 12 + b.month - a.month
        if months >= 1:
            return f"{months} month{'' if months == 1 else 's'}"
    return f"{s['days']} day{'' if s['days'] == 1 else 's'}"


_FIELD_WORDS = {"enrollment_change": "enrolment", "design_change": "design",
                "endpoint_change": "endpoints"}


def _row_text(r: dict) -> tuple[str, bool]:
    """A week row as the page words it, and whether the words are the source's own.

    A press headline or a filing title stays as the source wrote it, the leading ticker
    the feed adds dropped. The rows the diff engine writes are re-worded: a slip as its
    study, size and new date; an efficacy supplement as the brand approved; a label as
    its brand and version; a registry change as its study and what changed."""
    t = r.get("ticker")
    text = _strip_ticker(r.get("headline"), t)
    ct = r.get("change_type")
    if ct == "date_slip":
        s = _slip(r)
        if s:
            return f"{s['nct']} completion slips {_span(s)}, to {_dlong(s['now'])}", False
    elif ct == "efficacy_supplement":
        m = re.search(r"efficacy supplement: (.+?) approved (\d{4}-\d{2}-\d{2})", text)
        if m:
            return f"{m.group(1)} efficacy supplement approved {_dlong(m.group(2))}", False
    elif ct == "label_change":
        m = re.search(r"label: (.+?) revised to version (\d+)", text)
        if m:
            return f"{m.group(1)} label revised, version {m.group(2)}", False
    elif ct == "status_change":
        m = re.search(r"trial (NCT\d{8}): status .+? -> (.+)$", text)
        if m:
            return f"{m.group(1)} now {m.group(2).lower()}", False
    elif ct == "date_change":
        m = re.search(r"trial (NCT\d{8}): primary completion \S+ -> (\S+)", text)
        if m:
            return f"{m.group(1)} completion moves to {_dlong(m.group(2))}", False
    elif ct in _FIELD_WORDS:
        m = re.search(r"trial (NCT\d{8})", text)
        if m:
            return f"{m.group(1)} {_FIELD_WORDS[ct]} changed", False
    verbatim = ct in ("press_data_readout", "press_approval", "press_deal", "press_results",
                      "press_regulatory", "new_filing", "material event")
    return text, verbatim


def _routine_filing(r: dict) -> bool:
    """A filing no reader opens (see _ROUTINE_FILING_RE), read off its title."""
    if r.get("change_type") not in ("new_filing", "material event"):
        return False
    body = _strip_ticker(r.get("headline"), r.get("ticker"))
    return bool(_ROUTINE_FILING_RE.search(body.split(": ", 1)[-1]))


def _week_rows(feed: list, cohort, since: str, today: str) -> list:
    """The week's change rows for the cohort: the one set the grid, the board's news and
    the ranked feed's counts read.

    A row is in when its kind is change or filing, its ticker is in the cohort, it was
    first seen (detected_at, else its own date) between ``since`` and ``today``, and its
    own date is no more than seven days before ``since``: an approval dated the Thursday
    before and first read on Saturday is this week's news, a July 8-K first read this
    week is not. A filing the feed carries twice (as a new filing and as a material event)
    is taken once. Catalyst, LOE, market and policy rows are not changes of the week."""
    floor = (_date(since) - dt.timedelta(days=NEWS_DAYS)).isoformat()
    out, held = [], set()
    for r in feed:
        if r.get("kind") not in ("change", "filing") or r.get("ticker") not in cohort:
            continue
        seen = _seen(r)
        if not (since <= seen <= today):
            continue
        if (_iso(r.get("date")) or seen) < floor:
            continue
        key = (r.get("ticker"), _iso(r.get("date")),
               _strip_ticker(r.get("headline"), r.get("ticker")))
        if r.get("change_type") in ("new_filing", "material event"):
            if key in held:
                continue
            held.add(key)
        out.append(r)
    return out


def _distinct_words(text: str | None, own: str | None = "") -> set:
    """The words of five letters or more that can tie a filing to a deal: not the common
    words of a deal announcement and not the company's own name."""
    words = set(re.findall(r"[a-z]{5,}", (text or "").lower()))
    return words - _DEAL_COMMON - set(re.findall(r"[a-z]{5,}", (own or "").lower()))


def _fold_filings(deal: dict, rows: list, companies: dict, folded: set) -> None:
    """Add to a deal the week's filings by its parties that name it: a filing that is not
    routine and shares a distinctive word with the deal's head (AstraZeneca's three
    Summit 6-Ks fold into its Summit deal). Each folded row is marked in ``folded`` so it
    is not listed again as a filing."""
    for t in deal["tickers"]:
        mark = _distinct_words(deal.get("head"), (companies.get(t) or {}).get("name"))
        if not mark:
            continue
        for r in rows:
            if r.get("ticker") != t or id(r) in folded or _routine_filing(r):
                continue
            if r.get("change_type") not in ("new_filing", "material event"):
                continue
            body = _strip_ticker(r.get("headline"), t)
            if mark & _distinct_words(body, (companies.get(t) or {}).get("name")):
                folded.add(id(r))
                deal.setdefault("folded", []).append(
                    {"ticker": t, "date": _iso(r.get("date")), "text": body})
                deal["rows"].append([f"Filed {_dshort(r.get('date'))}", body])


def _deal_quote(h: dict, deal_rows: list) -> tuple:
    """A priced deal's source title, quoted verbatim, and where it is from: the filed
    press release's own title where the terms were read off its exhibit ("Exhibit 99.1
    Press Release <title> •"); else the stored announcing headline of a deal the book read
    from the news. (None, None) where neither is on file: no deck is drawn."""
    ev = h.get("evidence") or ""
    m = _EXHIBIT_TITLE_RE.search(ev)
    if m:
        ex = _EXHIBIT_NO_RE.search(ev)
        return (m.group(1).strip(), "the press release, filed as exhibit " + ex.group(1)
                if ex else "the filed press release")
    day = _iso(h.get("date"))
    for d in deal_rows:
        if d.get("ticker") == h.get("ticker") and _iso(d.get("event_date")) == day \
                and d.get("quote") and d.get("event_date_source") == "news" \
                and not d.get("terms_source"):
            return d["quote"].strip(), "the headline as published"
    return None, None


def _ev_name(e: dict) -> str:
    """A dated event's drug, or its condition's study where the registry title names no
    drug."""
    if e.get("short_basis") in ("condition", "title"):
        cond = re.split(r"[;(]", ((e.get("conditions") or [""])[0] or e.get("short") or ""))[0]
        return f"{cond.strip()} study" if cond.strip() else "a study"
    return e.get("short") or e.get("title") or ""


def _week_items(src: dict, companies: dict, events: list, today: dt.date,
                rows: list | None = None) -> list:
    """The week across the group, ranked by a stated rule that never reads the company in
    focus, so the feed is the same whichever company is picked:

    1. Deals with a stated value, largest first (the headlines' deals). Each carries its
       terms, both parties' day moves, the filings it folds in (_fold_filings) and its
       source's own title where one is on file (_deal_quote).
    2. The rate move the book is priced on, when the 10-year was flagged this week: the
       10-year's level and 30-day move and the single-A yield beside it, from /markets;
       the week's flags in the rows.
    3. Phase 3 results, from the companies' own announcements. A notice that data will
       be presented is not a result (item 9).
    4. Deals with no stated value: the feed's press deals and headline deals with no
       figure, each folding in its filings.
    5. Phase 2 results.
    6. The week's label expansions (efficacy supplements), one item.
    7. The week's trial completion slips across the group, one item: the count of studies
       whose date slipped, the longest high slips (a Phase 3 moved more than 30 days)
       named, the rest counted. A study moved twice in the week is one slip, first date
       to last.
    8. The next firm FDA date inside 30 days.
    9. Notices that data will be presented.
    10. Results dates the companies announced, the call's day read from the text.
    11. Filings a reader would open: not routine and not folded into a deal, one item.
    12. US labels revised, one item.
    13. Phase 3 primary completions estimated inside DUE_DAYS, one item.
    14. Listed patents and exclusivities ending inside LOE_DAYS, one item.

    Every item carries ``verbatim`` (its head is the source's own words), its own figure
    and date; at most WEEK_ITEMS are kept, ranked from 1."""
    since = (today - dt.timedelta(days=NEWS_DAYS)).isoformat()
    closes = src.get("closes") or {}
    heads = src.get("headlines") or []
    feed = src.get("changes") or []
    if rows is None:
        rows = _week_rows(feed, companies, since, today.isoformat())
    deal_rows = src.get("deal_rows") or []
    folded: set = set()
    items = []

    def move(t, day):
        return _day_move(closes.get(t) or [], day) if day else None

    # 1. Deals with a stated value, largest first.
    priced = []
    for h in heads:
        if h.get("kind") != "deal" or h.get("ticker") not in companies:
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
        quote, quote_src = _deal_quote(h, deal_rows)
        priced.append({"kind": "deal", "tag": "deal", "tickers": [t] + ([party_t] if party_t else []),
                       "head": (body[:1].upper() + body[1:] + (f": {h['detail']}" if h.get("detail") else "")),
                       "verbatim": False,
                       "fig": h.get("figure"), "value_usd": value, "date": day,
                       "terms": {"upfront": terms.get("Upfront"),
                                 "milestones": terms.get("Milestones"),
                                 "counterparty": party},
                       "parties": [{"ticker": u, "short": companies[u]["short"]}
                                   for u in [t] + ([party_t] if party_t else [])],
                       "quote": quote, "quote_src": quote_src,
                       "mini": {"type": "deal", "upfront": up, "milestones": ms},
                       "rows": [[p.get("label"), p.get("value")] for p in h.get("summary") or []]
                               + [[f"Day move, {day}", [[u, mv] for u, mv in moves]]],
                       "url": h.get("url"), "src": "/headlines (deal)"})
    priced.sort(key=lambda i: -(i["value_usd"] or 0))
    for d in priced:
        if d["value_usd"]:
            _fold_filings(d, rows, companies, folded)
    items += [i for i in priced if i["value_usd"]]
    unpriced_heads = [i for i in priced if not i["value_usd"]]

    # 2. The rate move the book is priced on: the latest 10-year flag of the week.
    rate_flags = sorted([r for r in feed if r.get("kind") == "market"
                         and r.get("change_type") == "rate_move"
                         and since <= (_iso(r.get("detected_at") or r.get("date")) or "")],
                        key=lambda r: r.get("date") or "")
    markets = src.get("markets") or {}
    rates = {r["series"]: r for r in markets.get("rates") or []}
    if rate_flags and rates.get("DGS10"):
        r10 = rates["DGS10"]
        path = [[d, v] for d, v in ((src.get("paths") or {}).get("rates") or {}).get("DGS10", [])]
        last = rate_flags[-1]
        rows_ = [["Level", {"value": r10.get("value"), "as_of": r10.get("as_of"),
                            "change_bp": r10.get("change_bp"), "from": r10.get("change_from")}],
                 ["Flags this week", [[_iso(f.get("date")), f.get("headline")] for f in rate_flags]]]
        for s in ("DFII10", "T10YIE", "BAMLC0A3CAEY"):
            if rates.get(s) and rates[s].get("change_bp") is not None:
                rows_.append([RATE_LABEL[s], {"change_bp": rates[s]["change_bp"],
                                              "from": rates[s].get("change_from"),
                                              "as_of": rates[s].get("as_of")}])
        head = last.get("headline")
        days = markets.get("days") or 30
        if r10.get("value") is not None and r10.get("change_bp") is not None:
            bp = r10["change_bp"]
            head = (f"10-year Treasury {r10['value'] * 100:.2f}%, "
                    f"{'up' if bp > 0 else 'down' if bp < 0 else 'flat'}"
                    + (f" {abs(bp):.0f}bp" if bp else "") + f" in {days} days")
            ca = rates.get("BAMLC0A3CAEY") or {}
            if ca.get("value") is not None and ca.get("change_bp") is not None:
                cb = ca["change_bp"]
                head += (f"; single-A yield {ca['value'] * 100:.2f}%, "
                         f"{'up' if cb > 0 else 'down' if cb < 0 else 'flat'}"
                         + (f" {abs(cb):.0f}bp" if cb else ""))
        items.append({"kind": "market", "tag": "rates", "tickers": ["ALL"], "verbatim": False,
                      "head": head, "fig_bp": r10.get("change_bp"),
                      "fig_sub": f"{days} days", "date": _iso(last.get("date")),
                      "mini": {"type": "spark", "values": [v for _d, v in path]},
                      "rows": rows_, "url": None, "src": "/markets, /changes (rate_move)"})

    # 3 and 5. Readouts from the headlines, by the phase the announcement reports.
    readouts = []
    for h in heads:
        if h.get("kind") != "readout" or h.get("ticker") not in companies:
            continue
        t = h["ticker"]
        body = (h.get("headline") or "")[len(t) + 1:]
        if _PRESENTS_RE.search(body):
            continue
        ph = data_phase(body)
        day = _iso(h.get("date"))
        readouts.append({"kind": "readout" if ph != "2" else "readout2",
                         "tag": f"phase {ph}" if ph else "result", "tickers": [t],
                         "head": body, "verbatim": True, "fig_move": move(t, day),
                         "date": day, "phase": ph,
                         "mini": {"type": "stock", "ticker": t, "marks": [day]},
                         "rows": [["Read out of", "the company's own announcement"],
                                  ["Day move", [[t, move(t, day)]]]],
                         "url": h.get("url"), "src": "/headlines (readout)"})
    items += [r for r in readouts if r["phase"] != "2"]

    # 4. Deals with no stated value: the feed's press deals of the week, and any headline
    # deal that came without a figure. The company's filings that name the deal fold in.
    for r in feed:
        if r.get("change_type") != "press_deal" or r.get("ticker") not in companies:
            continue
        if (_iso(r.get("detected_at") or r.get("date")) or "") < since:
            continue
        t = r["ticker"]
        if any(t in i["tickers"] for i in items if i["kind"] == "deal"):
            continue
        text = _strip_ticker(r.get("headline"), t)
        day = _iso(r.get("date"))
        deal = {"kind": "deal", "tag": "deal", "tickers": [t], "head": text,
                "verbatim": True, "fig": None, "value_usd": None, "date": day,
                "parties": [{"ticker": t, "short": companies[t]["short"]}],
                "rows": [["Announced value", None], ["Announced", day]],
                "url": None, "src": "/changes (press_deal)"}
        _fold_filings(deal, rows, companies, folded)
        deal["rows"].append(["Day move", [[t, move(t, day)]]])
        deal["mini"] = {"type": "stock", "ticker": t,
                        "marks": [day] + [f["date"] for f in deal.get("folded") or []]}
        items.append(deal)
    for d in unpriced_heads:
        _fold_filings(d, rows, companies, folded)
    items += unpriced_heads
    items += [r for r in readouts if r["phase"] == "2"]

    # 6. Label expansions of the week, one item.
    supps = [r for r in feed if r.get("change_type") == "efficacy_supplement"
             and r.get("ticker") in companies
             and (_iso(r.get("detected_at") or r.get("date")) or "") >= since]
    if supps:
        brands, dates, rows_, tickers = [], [], [], []
        for r in supps:
            m = re.search(r"efficacy supplement: (.+?) approved (\d{4}-\d{2}-\d{2})",
                          r.get("headline") or "")
            if not m:
                continue
            brands.append(m.group(1))
            dates.append(m.group(2))
            rows_.append([r["ticker"], f"{m.group(1)} approved {m.group(2)}"])
            if r["ticker"] not in tickers:
                tickers.append(r["ticker"])
        if brands:
            items.append({"kind": "approval", "tag": "approval", "tickers": tickers,
                          "verbatim": False,
                          "brands": brands, "fig_n": len(brands), "date": max(dates),
                          "mini": {"type": "dates", "dates": sorted(dates)},
                          "rows": rows_ + [["Seen", _iso(max(_iso(r.get("date")) for r in supps))]],
                          "url": None, "src": "/changes (efficacy_supplement)"})

    # 7. The week's slips across the group, a study moved twice taken first date to last.
    studies: dict = {}
    for r in rows:
        if r.get("change_type") != "date_slip":
            continue
        s = _slip(r)
        if not s:
            continue
        k = (s["ticker"], s["nct"])
        if k not in studies:
            studies[k] = s
            continue
        o = studies[k]
        was = min((o["was"], s["was"]), key=lambda v: _first_day(v))
        now = max((o["now"], s["now"]), key=lambda v: _first_day(v))
        studies[k] = {**o, "was": was, "now": now,
                      "days": (_first_day(now) - _first_day(was)).days,
                      "month": len(was) == 7 or len(now) == 7, "high": o["high"] or s["high"],
                      "seen": max(o["seen"], s["seen"]), "moves": o["moves"] + 1}
    if studies:
        trials = src.get("trials") or {}
        all_ = sorted(studies.values(), key=lambda s: (not s["high"], -s["days"]))
        high = [s for s in all_ if s["high"]]
        lead = high or all_
        top = lead[0]
        n, k = len(all_), len(high)
        head = (f"{n} trial completion date{'' if n == 1 else 's'} slipped, "
                + (f"{k} of them Phase 3 by more than 30 days; the longest, "
                   f"{top['ticker']} {top['nct']}, by {_span(top)}" if k else
                   "none a Phase 3 by more than 30 days"))
        shown = lead[:SLIP_ROWS]
        rows_ = []
        for s in shown:
            ph = (trials.get(s["nct"]) or {}).get("phase")
            rows_.append([f"{s['ticker']} {s['nct']}",
                          f"{_span(s)}, {_dlong(s['was'])} to {_dlong(s['now'])}"
                          + (f", {ph}" if ph else "")
                          + (f", moved {s['moves']} times" if s["moves"] > 1 else "")])
        if n > len(shown):
            rows_.append(["The rest", f"{n - len(shown)} more, earlier phases or a Phase 3 "
                                      f"by 30 days or less" if high else
                                      f"{n - len(shown)} more"])
        items.append({"kind": "slips", "tag": "slips", "verbatim": False,
                      "tickers": list(dict.fromkeys(s["ticker"] for s in lead[:3])),
                      "head": head, "fig": str(n), "fig_sub": "slipped",
                      "n_high": k, "date": max(s["seen"] for s in all_),
                      "mini": {"type": "slipbars",
                               "rows": [[s["ticker"], s["days"]] for s in lead[:3]]},
                      "rows": rows_, "url": None, "src": "/changes (date_slip)"})

    # 8. The next firm FDA date inside 30 days.
    end30 = today + dt.timedelta(days=30)
    firm = [e for e in events if e["firm"] and e["regulatory"] and not e["month"]
            and _date(e["date"]) and today <= _date(e["date"]) <= end30]
    if firm:
        e = min(firm, key=lambda e: e["date"])
        items.append({"kind": "regulatory",
                      "tag": "PDUFA" if (e.get("type") or "").upper() == "PDUFA" else "FDA date",
                      "tickers": [e["ticker"]],
                      "verbatim": False, "event": e, "n_firm": len(firm),
                      "days": (_date(e["date"]) - today).days, "date": e["date"],
                      "mini": {"type": "countdown", "days": (_date(e["date"]) - today).days,
                               "of": 30},
                      "rows": [["Date", f"{e['date']}, {e['confidence']}"]],
                      "url": e.get("url"), "src": "/catalysts"})

    # 9. Notices that data will be presented.
    for r in rows:
        if r.get("change_type") == "press_data_readout" \
                and _PRESENTS_RE.search(r.get("headline") or ""):
            t = r["ticker"]
            items.append({"kind": "notice", "tag": "notice", "tickers": [t],
                          "verbatim": True, "head": _strip_ticker(r.get("headline"), t),
                          "fig": _dshort(r.get("date")), "fig_sub": "announced",
                          "date": _iso(r.get("date")),
                          "rows": [["Announced", _iso(r.get("date"))],
                                   ["What it is", "a notice that data will be presented, "
                                                  "not a result"]],
                          "url": None, "src": "/changes (press_data_readout)"})

    # 10. Results dates, the call's day read from the announcement.
    for r in rows:
        if r.get("change_type") != "press_results":
            continue
        t = r["ticker"]
        body = _strip_ticker(r.get("headline"), t)
        said = _date(r.get("date"))
        call = None
        m = _MONTH_DAY_RE.search(body)
        if m and said:
            try:
                call = dt.date(said.year, _MONTHS.index(m.group(1)[:3]) + 1, int(m.group(2)))
            except ValueError:
                call = None
            if call and call < said - dt.timedelta(days=30):
                call = call.replace(year=said.year + 1)
        items.append({"kind": "earnings", "tag": "earnings", "tickers": [t],
                      "verbatim": True, "head": body,
                      "fig": _dshort(call.isoformat()) if call else _dshort(r.get("date")),
                      "fig_sub": "call" if call else "announced",
                      "call": call.isoformat() if call else None, "date": _iso(r.get("date")),
                      "rows": [["Announced", _iso(r.get("date"))]]
                              + ([["Call", f"{call.isoformat()}, as the announcement states"]]
                                 if call else []),
                      "url": None, "src": "/changes (press_results)"})

    # 11. Filings a reader would open, one item.
    routine = [r for r in rows if _routine_filing(r)]
    forms = sorted([r for r in rows if r.get("change_type") in ("new_filing", "material event")
                    and not _routine_filing(r) and id(r) not in folded],
                   key=lambda r: r.get("date") or "", reverse=True)
    if forms:
        texts = [_strip_ticker(r.get("headline"), r["ticker"]) for r in forms]
        items.append({"kind": "filing", "tag": "filings", "verbatim": False,
                      "tickers": list(dict.fromkeys(r["ticker"] for r in forms)),
                      "head": "; ".join(texts), "fig": str(len(forms)), "fig_sub": "filed",
                      "date": _iso(forms[0].get("date")),
                      "rows": [[f"{r['ticker']} {_dshort(r.get('date'))}", x]
                               for r, x in zip(forms, texts)],
                      "note": (f"{len(routine)} routine filing{'' if len(routine) == 1 else 's'}"
                               " left out: voting rights, share admissions, cover forms."
                               if routine else None),
                      "url": None, "src": "/changes (new_filing)"})

    # 12. Labels revised, one item.
    labs = sorted([r for r in rows if r.get("change_type") == "label_change"],
                  key=lambda r: r.get("date") or "", reverse=True)
    if labs:
        last = _iso(labs[0].get("date"))
        by: dict = {}
        for r in labs:
            by.setdefault(r["ticker"], []).append(_row_text(r)[0])
        latest = [re.sub(r" label revised.*$", "", _row_text(r)[0]) for r in labs
                  if _iso(r.get("date")) == last]
        n = len(labs)
        items.append({"kind": "labels", "tag": "labels", "verbatim": False,
                      "tickers": sorted(by, key=lambda t: -len(by[t]))[:3],
                      "head": (f"{n} US label{'' if n == 1 else 's'} revised; "
                               f"{len(latest)} on {_dshort(last)}: {', '.join(latest)}"),
                      "fig": str(n), "fig_sub": "revised", "date": last,
                      "rows": [[t, "; ".join(v)] for t, v in
                               sorted(by.items(), key=lambda kv: -len(kv[1]))],
                      "url": None, "src": "/changes (label_change, openFDA)"})

    # 13. Phase 3 primary completions estimated inside DUE_DAYS.
    end_due = today + dt.timedelta(days=DUE_DAYS)
    due = sorted([e for e in events if not e["month"] and e.get("phase") == "p3"
                  and _date(e["date"]) and today <= _date(e["date"]) <= end_due],
                 key=lambda e: (e["date"], e["ticker"]))
    if due:
        n = len(due)
        items.append({"kind": "due", "tag": "due", "verbatim": False,
                      "tickers": list(dict.fromkeys(e["ticker"] for e in due)),
                      "head": (f"{n} Phase 3 trial{'' if n == 1 else 's'} reach{'es' if n == 1 else ''} "
                               f"estimated primary completion by {_dshort(end_due.isoformat())}, "
                               f"{_ev_name(due[0])} first"),
                      "fig": str(n), "fig_sub": f"in {DUE_DAYS} days", "date": due[0]["date"],
                      "mini": {"type": "dates", "dates": [e["date"] for e in due],
                               "a": today.isoformat(), "b": end_due.isoformat()},
                      "rows": [[f"{_dshort(e['date'])} {e['ticker']}", _ev_name(e)
                                + (f", {e['conditions'][0]}" if e.get("conditions")
                                   and e.get("short_basis") not in ("condition", "title") else "")
                                + (f", {e['enrollment']:,} enrolled" if e.get("enrollment") else "")]
                               for e in due],
                      "note": "Estimated primary completion dates from the registry, not "
                              "result dates.",
                      "url": None, "src": "/catalysts (ClinicalTrials.gov)"})

    # 14. Listed patents and exclusivities ending inside LOE_DAYS.
    end_loe = today + dt.timedelta(days=LOE_DAYS)
    loe = sorted([r for r in feed if r.get("change_type") == "loe"
                  and r.get("ticker") in companies and _date(r.get("date"))
                  and today <= _date(r.get("date")) <= end_loe],
                 key=lambda r: (r.get("date") or "", r.get("ticker") or ""))
    if loe:
        def what(r):
            return re.sub(r"^LOE: ", "", _strip_ticker(r.get("headline"), r["ticker"]))
        first = re.sub(r" \((?:NDA|BLA|ANDA)\d+\).*$", "", what(loe[0]))
        n = len(loe)
        items.append({"kind": "loe", "tag": "LOE", "verbatim": False,
                      "tickers": list(dict.fromkeys(r["ticker"] for r in loe)),
                      "head": (f"{n} patent{'' if n == 1 else 's'} and exclusivities end by "
                               f"{_dshort(end_loe.isoformat())}, {first} first on "
                               f"{_dshort(loe[0].get('date'))}"),
                      "fig": str(n), "fig_sub": f"in {LOE_DAYS} days",
                      "date": _iso(loe[0].get("date")),
                      "mini": {"type": "dates", "dates": [_iso(r.get("date")) for r in loe],
                               "a": today.isoformat(), "b": end_loe.isoformat()},
                      "rows": [[f"{_dshort(r.get('date'))} {r['ticker']}", what(r)] for r in loe],
                      "url": None, "src": "/changes (loe, Orange and Purple Books)"})

    for i, it in enumerate(items[:WEEK_ITEMS], 1):
        it["rank"] = i
    return items[:WEEK_ITEMS]


def _next_event(mine: list) -> dict | None:
    """A company's next dated event on the board: the first firm FDA date in the 90 days,
    else the first FDA date, else the first Phase 3, else the first dated event. A
    month-only date sorts at its month's end. None where nothing is dated."""
    ordered = sorted(mine, key=lambda e: e["date"] + ("-99" if e["month"] else ""))
    for keep in (lambda e: e["regulatory"] and e["firm"], lambda e: e["regulatory"],
                 lambda e: e.get("phase") == "p3", lambda e: True):
        hit = [e for e in ordered if keep(e)]
        if hit:
            e = hit[0]
            return {k: e.get(k) for k in ("date", "month", "firm", "confidence", "regulatory",
                                          "type", "phase", "short", "short_basis", "title")} \
                | {"name": _ev_name(e)}
    return None


def _week_block(src: dict, companies: dict, events: list, today: dt.date, rows: list,
                items: list, tickers: list) -> dict:
    """What the page reads beside the ranked feed. Every rule here is independent of the
    company in focus.

    - ``grid``: every change of the week (_week_rows) by company and kind (GRID_KINDS),
      each a list of {date, text, verbatim, type}, newest first. A routine filing is left
      out and counted in ``routine_filings``. A headline deal counts once under each
      party it names; a filing folded into a deal counts under deals. An efficacy
      supplement is left out where the company's own press release of the week announces
      the same brand's approval, so one approval is one change.
    - ``kinds``: the count of each kind across the group.
    - ``news``: per company, the board's news: its deals, results and data notices, FDA
      approvals, filings and company news, and its high slips (a Phase 3 moved more than
      30 days). A filing folded into a deal is that deal, so it is not counted again.
      Labels, registry updates and the other slips are counted in the grid and are not
      news.
    - ``next``: per company, the board's next dated event (_next_event).
    - ``value_order``: the cohort from the most model upside to the least, the companies
      with no model value last, in market-cap order (the ribbon)."""
    since = (today - dt.timedelta(days=NEWS_DAYS)).isoformat()
    grid = {t: {k: [] for k, _l in GRID_KINDS} for t in tickers}
    folded = {(f["ticker"], f["date"], f["text"]) for it in items if it.get("kind") == "deal"
              for f in it.get("folded") or []}
    press_approved = {}
    for r in rows:
        if r.get("change_type") == "press_approval":
            press_approved.setdefault(r["ticker"], []).append((r.get("headline") or "").lower())
    routine = 0
    for r in rows:
        t, ct = r["ticker"], r.get("change_type")
        if _routine_filing(r):
            routine += 1
            continue
        kind = _GRID_OF.get(ct)
        if not kind or t not in grid:
            continue
        text, verbatim = _row_text(r)
        if ct == "efficacy_supplement":
            m = re.search(r"efficacy supplement: (.+?) approved", r.get("headline") or "")
            if m and any(m.group(1).lower() in h for h in press_approved.get(t, [])):
                continue
        fold = (t, _iso(r.get("date")), text) in folded
        grid[t]["deal" if fold else kind].append(
            {"date": _iso(r.get("date")), "text": text, "verbatim": verbatim, "type": ct,
             "high": r.get("significance") == "high", "folded": fold})
    for it in items:
        if it.get("kind") == "deal" and it.get("value_usd"):
            for t in it.get("tickers") or []:
                if t in grid:
                    grid[t]["deal"].append({"date": it.get("date"), "text": it.get("head"),
                                            "verbatim": False, "type": "deal", "high": True,
                                            "folded": False})
    for t in grid:
        for k in grid[t]:
            grid[t][k].sort(key=lambda x: x["date"] or "", reverse=True)
    news = {t: sorted([{"kind": k, **x} for k in ("deal", "result", "fda", "company", "slip")
                       for x in grid[t][k]
                       if (k != "slip" or x["high"]) and not x["folded"]],
                      key=lambda x: x["date"] or "", reverse=True) for t in grid}
    nxt = {t: _next_event([e for e in events if e["ticker"] == t]) for t in tickers}
    up = {t: (companies[t].get("model") or {}).get("upside") for t in tickers}
    order = sorted([t for t in tickers if up[t] is not None], key=lambda t: -up[t]) \
        + [t for t in tickers if up[t] is None]
    return {"since": since, "to": today.isoformat(), "grid": grid,
            "kinds": {k: sum(len(grid[t][k]) for t in grid) for k, _l in GRID_KINDS},
            "kind_labels": dict(GRID_KINDS), "routine_filings": routine,
            "news": news, "next": nxt, "value_order": order}


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
    stakes = {}
    for r in (src.get("stakes") or {}).get("priced") or []:
        stakes[r.get("id")] = {"priced": True, "per_share": _finite(r.get("per_share")),
                               "share_swing_usd_m": _finite(r.get("share_swing"))}
    for r in (src.get("stakes") or {}).get("unpriced") or []:
        stakes[r.get("id")] = {"priced": False, "per_share": None,
                               "missing": r.get("missing") or []}
    focal_events = [{**e, "stake": stakes.get(e["id"])} for e in events
                    if e["ticker"] == ticker]
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
        "events": focal_events,
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
    # The week across the group: one set of rows, the ranked feed over it, then the grid,
    # the board's news and next dates and the ribbon's order. None of it reads the company
    # in focus.
    week_rows = _week_rows(src.get("changes") or [], companies, since, today.isoformat())
    week_items = _week_items(src, companies, events, today, week_rows)

    out.update({
        "lead": {k: _lead(companies, k) for k, _l in WINDOWS},
        "events": events, "events_left_off": len(left),
        "events_window": {"start": start.isoformat(), "end": end.isoformat()},
        "week_items": week_items,
        "week": _week_block(src, companies, events, today, week_rows, week_items,
                            out["tickers"]),
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
