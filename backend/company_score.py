"""The company scorecard: every company scored from 0 to 100 against a fixed cohort.

The Comps tab opens on one chart of the open company against its peers, Key insights prints
the same scores and lines, and Catalysts reads the same exclusivity losses. All of it is
computed here, once, and rides inside ``GET /comps/valuation`` as ``scorecard``, so every
surface prints the same characters. The method is docs/design/company-scorecard.md,
revision 2, section 2; the output is its section 6.1.

In short:

- Three fixed cohorts (big pharma, commercial-stage biotech and cell and gene,
  clinical-stage biotech and cell and gene), never the peer set a reader edits.
- A measure becomes its mid-rank percentile in the cohort, turned so 100 is the better
  side, and is scored only when two thirds of the cohort have it. A pillar is the mean of
  its measures, pulled toward 50 when some are missing; the company score is the mean of
  the business pillars, pulled the same way. Equal weights.
- Value and momentum are scored the same way and kept out of the company score: they are
  the price, not the business.
- The rank range is where the rank falls in 90 of 100 seeded random weightings.
- Positives and negatives come from the business pillars only.
- Deals are listed as facts, gated, and never scored in this build.

Every input is a field of a ``/comps/valuation`` record or a read of a table the book
already has (``book_inputs``). Nothing is estimated: a value the book does not have is
null with a reason code, and section 8.4's text for it travels beside it.
"""

from __future__ import annotations

import datetime as dt
import math
import random
import re
import statistics
import time

import numpy as np

import approval_dates
import asset_revenue
import db
import deals as deals_module
import fx
import loe
import productivity
from fetchers import deals_news

SCHEMA = 2

SEED = 20261001
DRAWS = 2000
LEVEL = 90                      # the rank range holds 90 of 100 weightings
COVERAGE = 2 / 3                # share of a cohort with a value before a measure is scored
MIN_DISTINCT = 3
POSITIVE_AT = 75
NEGATIVE_AT = 25
REVENUE_FLOOR_USD_M = 100.0     # growth and revenue ratios below it are not meaningful
GROWTH_BASE_FLOOR_USD_M = 10.0
GROWTH_LIMIT = 5.0              # growth beyond 500% a year is not meaningful
EPS_BASE_FLOOR = 0.10
PRODUCT_COVERAGE = (0.60, 1.10)
LOE_DATED_FLOOR = 0.5
DEAL_WINDOW_DAYS = 730
DEAL_LIST_MAX = 8
QUOTE_MAX = 160
EXCLUSIVITY_WINDOW_DAYS = 730
SENTENCE_MAX_WORDS = 30
STRONG_AT, WEAK_AT = 60, 40

MINUS = "−"
TIMES = "×"
EN_DASH = "–"

# ---- cohorts, pillars, metrics -----------------------------------------------------------
COHORTS = {
    "big_pharma": {"label": "Big pharma", "noun": "big pharma"},
    "commercial": {"label": "Commercial biotech and cell and gene",
                   "noun": "commercial-stage biotechs"},
    "clinical": {"label": "Clinical-stage biotech and cell and gene",
                 "noun": "clinical-stage biotechs"},
}
COHORT_ORDER = ("big_pharma", "commercial", "clinical")

PILLARS = {
    "growth": {"label": "Growth", "column": "grow", "kind": "business"},
    "profitability": {"label": "Profitability", "column": "prof", "kind": "business"},
    "balance_sheet": {"label": "Balance sheet", "column": "bal.", "kind": "business"},
    "pipeline": {"label": "Pipeline", "column": "pipe", "kind": "business"},
    "durability": {"label": "Durability", "column": "dur.", "kind": "business"},
    "funding": {"label": "Funding", "column": "fund", "kind": "business"},
    "value": {"label": "Value", "column": "value", "kind": "price"},
    "momentum": {"label": "Momentum", "column": "mom.", "kind": "price"},
}
BUSINESS = frozenset(p for p, o in PILLARS.items() if o["kind"] == "business")

# Each cohort's full list, in display order. A measure that fails the coverage rule leaves
# the scored list (and is named in ``not_scored``); a pillar left with none leaves too.
LISTS = {
    "big_pharma": (
        ("growth", ("rev_growth", "rev_cagr3", "eps_cagr")),
        ("profitability", ("op_margin", "pretax_margin", "fcf_margin")),
        ("balance_sheet", ("nd_ocf", "net_cash_rev")),
        ("pipeline", ("late_compounds", "late_per_rev", "fresh_share")),
        ("durability", ("loe_years", "top_product")),
        ("value", ("pe_ntm", "ev_sales", "fcf_yield")),
        ("momentum", ("rel_1y", "rel_3m")),
    ),
    "commercial": (
        ("growth", ("rev_growth", "rev_cagr3", "eps_cagr")),
        ("profitability", ("op_margin", "pretax_margin", "fcf_margin")),
        ("balance_sheet", ("runway", "share_change")),
        ("pipeline", ("late_compounds", "fresh_share")),
        ("durability", ("loe_years", "top_product")),
        ("value", ("pe_ntm", "mcap_sales", "fcf_yield")),
        ("momentum", ("rel_1y", "rel_3m")),
    ),
    "clinical": (
        ("pipeline", ("mid_late_compounds", "trial_conc")),
        ("funding", ("runway", "share_change")),
        ("value", ("mcap_cash",)),
        ("momentum", ("rel_1y", "rel_3m")),
    ),
}

# id -> label (panel, Compare), better side, unit of ``text``, the short label of the
# Key insights strip's multiple cell
METRICS = {
    "rev_growth": {"label": "Revenue growth", "better": "higher", "unit": "pct1"},
    "rev_cagr3": {"label": "Revenue growth, 3-year CAGR", "better": "higher", "unit": "pct1"},
    "eps_cagr": {"label": "Street EPS growth, FY1 to FY3", "better": "higher", "unit": "pct1"},
    "op_margin": {"label": "Operating margin", "better": "higher", "unit": "pct1"},
    "pretax_margin": {"label": "Pre-tax margin", "better": "higher", "unit": "pct1"},
    "fcf_margin": {"label": "Free cash flow margin", "better": "higher", "unit": "pct1"},
    "nd_ocf": {"label": "Net debt to operating cash flow", "better": "lower", "unit": "mult1"},
    "net_cash_rev": {"label": "Net cash to revenue", "better": "higher", "unit": "mult1"},
    "runway": {"label": "Cash runway", "better": "higher", "unit": "months"},
    "share_change": {"label": "Share count change, 1 year", "better": "lower",
                     "unit": "pct1s"},
    "late_compounds": {"label": "Late-stage compounds", "better": "higher", "unit": "num0"},
    "late_per_rev": {"label": "Late-stage compounds per $10bn revenue", "better": "higher",
                     "unit": "num1"},
    "fresh_share": {"label": "Revenue from launches of the last 5 years", "better": "higher",
                    "unit": "pct0"},
    "loe_years": {"label": "Exclusivity left, revenue-weighted", "better": "higher",
                  "unit": "years"},
    "top_product": {"label": "Revenue from the top product", "better": "lower",
                    "unit": "pct0"},
    "mid_late_compounds": {"label": "Compounds in Phase 2 or later", "better": "higher",
                           "unit": "num0"},
    "trial_conc": {"label": "Trials on the lead asset", "better": "lower", "unit": "pct0"},
    "pe_ntm": {"label": "P/E, next 12 months", "better": "lower", "unit": "mult1",
               "short": "P/E NTM"},
    "ev_sales": {"label": "EV to sales, FY0", "better": "lower", "unit": "mult1",
                 "short": "EV to sales"},
    "mcap_sales": {"label": "Market cap to sales, FY0", "better": "lower", "unit": "mult1",
                   "short": "Market cap to sales"},
    "fcf_yield": {"label": "Free cash flow yield", "better": "higher", "unit": "pct1",
                  "short": "Free cash flow yield"},
    "mcap_cash": {"label": "Market cap to cash", "better": "lower", "unit": "mult1",
                  "short": "Market cap to cash"},
    "rel_1y": {"label": "Against XLV, 1 year", "better": "higher", "unit": "points"},
    "rel_3m": {"label": "Against XLV, 3 months", "better": "higher", "unit": "points"},
}
MARGINS = frozenset({"op_margin", "pretax_margin", "fcf_margin"})
# A positive on these needs the right side of zero (2.12, rule 3).
ABOVE_ZERO = frozenset({"rev_growth", "rev_cagr3", "eps_cagr", "op_margin", "pretax_margin",
                        "fcf_margin", "net_cash_rev"})
BELOW_ZERO = frozenset({"share_change"})
PIPELINE_COUNTS = frozenset({"mid_late_compounds", "trial_conc", "late_compounds",
                             "late_per_rev"})
PRODUCT_METRICS = ("top_product", "loe_years", "fresh_share")

# ---- flags (2.8) ---------------------------------------------------------------------------
# An amber flag that makes a figure not like for like nulls it, with the flag as its reason.
FLAG_NULLS = {
    "derived_operating_income": ("op_margin",),
    "burn_flattered": ("runway",),
    "stale_fiscal_year": ("rev_growth", "rev_cagr3", "op_margin", "pretax_margin",
                          "fcf_margin", "late_per_rev", "net_cash_rev", "ev_sales",
                          "mcap_sales", "fcf_yield"),
    "currency_mismatch": ("rev_growth", "rev_cagr3"),
    # The two below reach their metrics through the flag's field and the market cap basis.
    "estimate_range_wide": (),
    "thin_estimates": (),
    "stale_shares": (),
}
# Amber flags shown beside the figure, never withholding it.
FLAG_SHOWN = frozenset({
    "market_cap_disagreement", "stale_price", "stale_balance_sheet", "includes_minorities",
    "eps_sign_change", "no_consensus", "guidance_fx_unstated", "fiscal_year_end",
    # comps_valuation can emit these two as well: a consensus a few days old and a source
    # that failed in the latest run are dates to show, not figures to withhold.
    "stale_consensus", "source_failed",
})
ESTIMATE_FLAGS = ("estimate_range_wide", "thin_estimates")
# Reason codes whose text carries a figure of the company's own; the payload formats these
# on the metric and on its pillar (``reason_text``) and every other code reads
# ``method.reasons`` as it stands.
PARAMETRISED = frozenset({"partial_product_revenue"})
STALE_SHARE_METRICS = ("ev_sales", "mcap_sales", "fcf_yield", "mcap_cash")

# ---- copy (section 8) ----------------------------------------------------------------------
REASONS = {
    "below_revenue_floor": "Revenue under $100m, so ratios on it are not meaningful",
    "growth_not_meaningful": "Growth on a base under $10m, or beyond 500%, is not meaningful",
    "one_year_only": "One fiscal year on file, so no growth",
    "insufficient_history": "Under four fiscal years on file, so no 3-year growth",
    "eps_base": "Base EPS under 0.10, so EPS growth is not meaningful",
    "eps_base_depressed": ("Next year's consensus is under half of the year after, so "
                           "growth from it is not meaningful"),
    "non_positive_base": "Base EPS at or below zero, so EPS growth is not meaningful",
    "eps_not_positive": "Consensus EPS at or below zero in the next 12 months",
    "no_consensus": "No street estimates on file",
    "no_consensus_otc": "No street estimates on file for this over-the-counter listing",
    "no_revenue": "No revenue filed for FY0",
    "no_debt_line": "No debt line filed, so net debt is not known",
    "burning_cash": "Operating cash flow is negative",
    "not_filed": "Not filed",
    "no_cash_flow": "No cash flow statement on file",
    "dilution_basis_changed": ("Net income changed sign between the two periods, so diluted "
                               "share counts are not comparable"),
    "share_split": ("Share count fell by more than half in a year: a reverse split the book "
                    "cannot see"),
    "share_scale": "Share counts more than twentyfold apart: a scale error",
    "no_pipeline": "No mapped pipeline on file",
    "no_trials": "No trials on file",
    "no_product_revenue": "No product revenue on file",
    "partial_product_revenue": "Product revenue on file covers {c}% of revenue, outside 60% to 110%",
    "under_half_dated": "Under half of product revenue has a dated exclusivity",
    "no_dated_approvals": "No approval dates for the products on file",
    "inferred_dates": "Some product revenue has no approval date of its own",
    "fcf_negative": "Free cash flow is negative, so a yield is not meaningful",
    "no_cash": "No cash on file",
    "short_history": "Under a full window of prices",
    "not_scored_in_cohort": "Not scored: {k} of {n} in the cohort have it",
    "not_applicable": "Does not apply before product revenue",
    "no_free_data": "No free data for any of its measures",
    "too_few_pillars": "{k} of {K} pillars, a score needs {m}",
    "derived_operating_income": ("Operating income is derived, not filed, so it may leave "
                                 "out charges"),
    "estimate_range_wide": "Estimates spread too wide to rank",
    "thin_estimates": "Too few analysts to rank",
    "burn_flattered": "The burn rate on file is understated",
    "stale_fiscal_year": "The latest filed year is more than 15 months old",
    "currency_mismatch": "The years compared are filed in different currencies",
    "stale_shares": "The share count on file is over a year old",
}

HOW_TO_READ = ("How to read it: right is a stronger business than its cohort, up is lower "
               "multiples. The number is the rank in the table. Click a company for its "
               "facts; tick up to three to compare.")
METHOD_LINES = (
    "How it is scored, each from 0 to 100.",
    "Cohort: {label}, {n} companies, the same for every reader. Editing peers changes the "
    "Table view, not the scores.",
    "Each measure: the share of the cohort it beats, ties counted half, turned so 100 is the "
    "better side. A measure counts once two thirds of the cohort have it.",
    "Each pillar: the average of its measures, moved toward the cohort middle when some are "
    "missing.",
    "Company score: the average of the business pillars, moved the same way. It needs {m} "
    "of {K}.",
    "Value and momentum are scored the same way and kept out of the company score: they are "
    "the price, not the business.",
    "Range: where the rank falls in 90 of 100 random weightings of the pillars and their "
    "measures.",
    "Positives and negatives: a business measure in the cohort's top or bottom quarter, at "
    "most one of each a pillar. A few fixed tests add others: runway under two years, one "
    "product over half of revenue, net debt over three times operating cash flow.",
    "Deals are listed, not scored, until the deal records are reviewed.",
    "A figure the data flags as not like for like is not scored. A gap says why.",
)
DEAL_CHIP = "From headlines and filings, not reviewed"

# ---- the deal gate (2.10) ------------------------------------------------------------------
DEAL_TYPES = ("acquisition", "licensing", "collaboration")
_GENERIC = {"therapeutics", "pharmaceuticals", "pharmaceutical", "company", "holdings",
            "group", "biosciences", "biotherapeutics", "inc", "plc", "corporation", "limited",
            "medicines", "biotech", "bio", "sciences", "and"}
NOT_A_DEAL = re.compile(
    r"(?i)\b(?:is an? buy|a buy\b|buy for\b|buy thesis|buy rating|terminat\w*"
    r"|end(?:s|ed)? (?:its |the )?(?:collaboration|agreement|partnership)"
    r"|discontinu\w*|settle\w*|cancel\w*|whereas\b|savings plan|acquires ads\b"
    r"|president acquires|director acquires|wind(?:s|ing)? down)")
NOT_A_NAME = {"biz", "firm", "drug", "rna", "car-t", "pet", "u.s", "us", "u.s.", "us-based",
              "massachusetts", "waltham", "maryland", "boston", "cambridge", "california",
              "china", "japan", "health-tech startup", "heng"}
NON_DRUG = re.compile(
    r"(?i)\b(?:microsoft|nvidia|anthropic|openai|google|amazon|veeva|viz\.ai|hims"
    r"|pocketpills|fujifilm|resilience|targan|ragt|camelina|benchmark genetics|university"
    r"|clinic\b|world health organization|economic development"
    r"|west pharmaceutical services|quantum)")
PLACE_PREFIX = re.compile(r"(?i)^(?:[A-Z][a-z]+-based|US-based|U\.S)")
_NOT_SUBJECT_TAIL = re.compile(r"(?i)\s*(?:holdings|owner|president|director)\b")
_DEAL_VERB = re.compile(r"(?i)\b(?:" + "|".join(v for v, _ in deals_news.DEAL_VERBS) + r")")
_BRACKETS = re.compile(r"\s*\(.*?\)")
_PHASES = ("Phase 1", "Phase 1/2", "Phase 2", "Phase 2/3", "Phase 3")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
           "Dec")


# ---- small pure helpers --------------------------------------------------------------------
def _g(obj, path: str):
    for key in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _date(value) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _mon_year(day: dt.date | None) -> str | None:
    return f"{_MONTHS[day.month - 1]} {day.year}" if day else None


def _day_mon_year(day: dt.date | None) -> str | None:
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}" if day else None


def _day_mon(day: dt.date | None) -> str | None:
    return f"{day.day} {_MONTHS[day.month - 1]}" if day else None


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _minus(text: str) -> str:
    return text.replace("-", MINUS)


def percentile(value, others) -> float | None:
    """Mid-rank percentile of ``value`` among ``others`` (the company excluded from its own
    reference set): the share it beats, ties counted half, 0 to 100. core.js percentileRank."""
    if not others:
        return None
    below = sum(1 for o in others if o < value)
    equal = sum(1 for o in others if o == value)
    return 100.0 * (below + 0.5 * equal) / len(others)


def pull(raw, k: int, K: int):
    """Move a mean of ``k`` of ``K`` scores toward 50: all present keeps it, one of two keeps
    three quarters of its distance, one of three two thirds. None with nothing present."""
    if raw is None or k <= 0 or K <= 0:
        return None
    return 50 + (raw - 50) * (k / (k + 1)) * ((K + 1) / K)


def fmt(metric: str, value) -> str | None:
    """A metric's value as every surface prints it (section 8.2, value formats)."""
    if value is None:
        return None
    unit = METRICS[metric]["unit"]
    if unit == "months":
        return "not burning cash" if value == math.inf else f"{value:.0f} months"
    if unit == "pct1":
        pct = value * 100
        return _minus(f"{pct:.0f}%" if abs(value) >= 1 else f"{pct:.1f}%")
    if unit == "pct1s":
        pct = value * 100
        return _minus(f"{pct:+.0f}%" if abs(value) >= 1 else f"{pct:+.1f}%")
    if unit == "pct0":
        return _minus(f"{value * 100:.0f}%")
    if unit == "mult1":
        return _minus(f"{value:.1f}{TIMES}")
    if unit == "num1":
        return _minus(f"{value:.1f}")
    if unit == "num0":
        return _minus(f"{value:.0f}")
    if unit == "years":
        return f"{value:.1f} years"
    if unit == "points":
        return _minus(f"{value * 100:+.0f} points")
    return str(value)


def reason_text(code: str | None, **params) -> str | None:
    if not code:
        return None
    text = REASONS.get(code)
    if text is None:
        return None
    try:
        return text.format(**params) if params else text
    except (KeyError, IndexError):
        return text


def _round(value, places: int = 4):
    return None if value is None or not math.isfinite(value) else round(value, places)


# ---- pure readers of book rows -------------------------------------------------------------
def product_rows(rows: list[dict], fy: int) -> list[dict]:
    """One fiscal year's revenue rows (period FY), largest first, an exact duplicate (same
    value and unit) counted once: VRTX's Trikafta is on file twice."""
    year = [r for r in rows if r.get("fiscal_year") == fy and (r.get("period") or "FY") == "FY"
            and r.get("value") is not None]
    year.sort(key=lambda r: (-r["value"], r.get("asset_id") or 0))
    kept: list[dict] = []
    for row in year:
        if any(k.get("unit") == row.get("unit")
               and abs(k["value"] - row["value"]) < 1e-6 * max(1.0, abs(row["value"]))
               for k in kept):
            continue
        kept.append(row)
    return kept


def share_change(quarters, years, net_income) -> tuple:
    """(change, reason, basis) of the diluted weighted share count over a year.

    ``quarters`` and ``years``: [(period_end, count)] with counts above zero; ``net_income``:
    {"Q": {period_end: value}, "FY": {...}}. The latest quarter over the quarter 345 to 385
    days before it; else the last two fiscal years. Null when net income changed sign between
    the two periods (a diluted count adds options and convertibles only in a profit), below
    half (a reverse split) or above twenty times (a scale error)."""
    def judge(new, old, ni):
        end_new, count_new = new
        end_old, count_old = old
        ratio = count_new / count_old
        n1, n0 = ni.get(end_new), ni.get(end_old)
        if n1 is not None and n0 is not None and (n1 >= 0) != (n0 >= 0):
            return None, "dilution_basis_changed", [end_old, end_new]
        if ratio < 0.5:
            return None, "share_split", [end_old, end_new]
        if ratio > 20:
            return None, "share_scale", [end_old, end_new]
        return ratio - 1, None, [end_old, end_new]

    q = sorted(((str(e)[:10], v) for e, v in quarters or [] if v and v > 0), reverse=True)
    if q:
        last = q[0]
        d1 = _date(last[0])
        prior = [r for r in q if abs((d1 - _date(r[0])).days - 365) <= 20]
        if prior:
            return judge(last, prior[0], (net_income or {}).get("Q") or {})
    fy = sorted(((str(e)[:10], v) for e, v in years or [] if v and v > 0), reverse=True)[:2]
    if len(fy) == 2:
        return judge(fy[0], fy[1], (net_income or {}).get("FY") or {})
    return None, "not_filed", None


def loe_years(rows: list[dict], loe_map: dict, today) -> tuple:
    """(years, reason): exclusivity left on the rows, weighted by their USD revenue, a past
    date counting 0. Null when under half of that revenue has a date."""
    today = _date(today)
    total = sum(r["usd_m"] for r in rows if r.get("usd_m") is not None)
    dated = [(r["usd_m"], _date((loe_map.get(r.get("asset_id")) or {}).get("date")))
             for r in rows if r.get("usd_m") is not None]
    dated = [(v, d) for v, d in dated if d is not None]
    dated_sum = sum(v for v, _ in dated)
    if not total or dated_sum / total < LOE_DATED_FLOOR:
        return None, "under_half_dated"
    years = sum(v * max(0.0, (d - today).days / 365.25) for v, d in dated) / dated_sum
    return years, None


def _names_of(company: dict) -> set:
    name = company.get("name") or ""
    out = {name, company.get("ticker") or "", (name.split() or [""])[0]} - {"The", "A", ""}
    for word in re.split(r"[\s,]+", name):
        word = word.strip(".,()")
        if len(word) >= 5 and word.lower() not in _GENERIC:
            out.add(word)
    return out


def _subject(company: dict, quote: str) -> bool:
    """The company is the subject: its name, ticker or a distinctive word of its name, not
    followed by "Holdings", "owner", "president" or "director", with a deal verb within
    four words of it."""
    for name in _names_of(company):
        pattern = r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])"
        for match in re.finditer(pattern, quote, re.I):
            tail = quote[match.end():]
            if _NOT_SUBJECT_TAIL.match(tail):
                continue
            verb = _DEAL_VERB.search(tail)
            if verb and len(tail[:verb.start()].split()) <= 4:
                return True
    return False


def gate_deals(rows: list[dict], company: dict, today=None) -> list[dict]:
    """The deal events of section 2.10 from the company's ``deals`` rows, newest first.

    Kept: acquisitions, licences and collaborations with a counterparty (inside 730 days of
    ``today`` when given). Dropped: a quote that is not a deal (a rating, an ending, a
    settlement, a cancellation, a recital, an officer's share purchase), a counterparty that
    is not a party (a place, a generic noun, a technology, sales-channel, manufacturing,
    crop, animal health, university or public body), and on the news route commentary,
    another company's deal, or a headline whose subject is not the company. One row per
    deal event: a news row within 3 days of a kept row, or rows sharing a distinctive
    counterparty word within 180 days, are one event, and a filing row wins over a news
    row. Each row keeps its counterparty, which the payload never prints."""
    today = _date(today)
    cutoff = today - dt.timedelta(days=DEAL_WINDOW_DAYS) if today else None
    ordered = sorted(rows, key=lambda r: (str(r.get("event_date") or ""), r.get("id") or 0))
    kept: list[dict] = []
    for r in ordered:
        if r.get("deal_type") not in DEAL_TYPES or not r.get("counterparty"):
            continue
        day = _date(r.get("event_date"))
        if day is None or (cutoff and day < cutoff):
            continue
        quote = r.get("quote") or ""
        party = (r.get("counterparty") or "").strip()
        if NOT_A_DEAL.search(quote):
            continue
        if party.lower() in NOT_A_NAME or PLACE_PREFIX.match(party) or len(party) < 3:
            continue
        if NON_DRUG.search(party) or NON_DRUG.search(quote[:80]):
            continue
        filing = bool(r.get("accession"))
        if not filing:
            if (deals_news.COMMENTARY.search(quote) or deals_module.NOT_OUR_DEAL.search(quote)
                    or not deals_module.is_party(party) or not _subject(company, quote)):
                continue
        words = {w for w in re.findall(r"[a-z0-9]{4,}", party.lower()) if w not in _GENERIC}
        route = "filing" if filing else "news"
        row = {"date": day.isoformat(), "type": r["deal_type"], "route": route,
               "counterparty": party,
               "quote": quote if len(quote) <= QUOTE_MAX else quote[:QUOTE_MAX - 1].rstrip() + "…",
               "url": r.get("source_url") or r.get("article_url"), "_d": day, "_w": words}
        twin = next((k for k in kept
                     if (abs((k["_d"] - day).days) <= 3 and "news" in (k["route"], route))
                     or ((words & k["_w"]) and abs((k["_d"] - day).days) <= 180)), None)
        if twin is not None:
            if twin["route"] == "news" and route == "filing":
                kept[kept.index(twin)] = row
            continue
        kept.append(row)
    out = [{k: v for k, v in row.items() if not k.startswith("_")} for row in kept]
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


# ---- reading the book ----------------------------------------------------------------------
def _fy0(rec: dict) -> dict:
    return _g(rec, "periods.FY0") or {}


def _fy_year(rec: dict) -> int | None:
    match = re.match(r"FY(\d{4})", _fy0(rec).get("label") or "")
    return int(match.group(1)) if match else None


def _usd_m(value, unit, rates) -> float | None:
    if value is None:
        return None
    if not unit or unit == "USD":
        return value / 1e6
    rate = rates.get(unit)
    return value * rate / 1e6 if rate else None


def book_inputs(conn, records: list[dict], rates: dict, today) -> dict:
    """Per ticker, the reads of tables the book already has that the records do not carry:
    FY0 operating cash flow and pre-tax income (USD m), share count change with its basis,
    the FY0 product rows (an exact duplicate once) with their exclusivity dates, freshness
    on the revenue year, owned approvals, partner on a marketed asset, gated deal events."""
    today = _date(today) or dt.date.today()
    ids = {r["ticker"]: r["id"] for r in conn.execute("SELECT id, ticker FROM companies")}
    names = {r["ticker"]: r["name"] for r in conn.execute("SELECT ticker, name FROM companies")}
    loe_map = loe.for_assets(conn, exclude_orphan=True)
    name_index = approval_dates.build_name_index(conn)
    cutoff = (today - dt.timedelta(days=DEAL_WINDOW_DAYS)).isoformat()
    out: dict = {}
    for rec in records:
        ticker = rec.get("ticker")
        cid = ids.get(ticker)
        if cid is None:
            continue
        fy0 = _fy0(rec)
        end = _date(fy0.get("period_end"))
        year = _fy_year(rec)

        def fy0_value(metric):
            if not end:
                return None
            row = conn.execute(
                "SELECT value, unit FROM financials WHERE company_id = ? AND metric = ?"
                "   AND period_type = 'FY' AND period_end = ?",
                (cid, metric, end.isoformat())).fetchone()
            return _usd_m(row["value"], row["unit"], rates) if row and row["value"] is not None else None

        shares = {kind: [(r["period_end"], r["value"]) for r in conn.execute(
            "SELECT period_end, value FROM financials WHERE company_id = ?"
            "   AND metric = 'WeightedAverageDilutedShares' AND period_type = ?"
            "   AND value > 0", (cid, kind))] for kind in ("Q", "FY")}
        income = {kind: {r["period_end"][:10]: r["value"] for r in conn.execute(
            "SELECT period_end, value FROM financials WHERE company_id = ?"
            "   AND metric = 'NetIncomeLoss' AND period_type = ?", (cid, kind))}
            for kind in ("Q", "FY")}
        change, change_reason, change_basis = share_change(shares["Q"], shares["FY"], income)

        prods = []
        if year:
            for row in asset_revenue.fy_product_rows(conn, cid, year):
                info = loe_map.get(row["asset_id"]) or {}
                prods.append({"asset_id": row["asset_id"], "name": row["name"],
                              "value": row["value"], "unit": row["unit"],
                              "usd_m": _usd_m(row["value"], row["unit"], rates),
                              "loe_date": info.get("date"), "loe_basis": info.get("basis")})
        fresh = None
        if end:
            got = productivity.portfolio_freshness(conn, cid, rates, today=end,
                                                   name_index=name_index)
            fresh = {k: got.get(k) for k in ("fresh_share", "coverage", "year", "reason",
                                             "inferred_revenue")}
        approvals = [{"asset_id": r["id"], "name": r["name"], "first": r["first"]}
                     for r in conn.execute(
                         """SELECT s.id, COALESCE(s.brand_name, s.generic_name) AS name,
                                   MIN(ap.approval_date) AS first
                              FROM approvals ap JOIN assets s ON s.id = ap.asset_id
                             WHERE s.owner_company_id = ? GROUP BY s.id ORDER BY s.id""",
                         (cid,))]
        partner = [{"asset_id": r["id"], "name": r["name"], "owner": r["owner"]}
                   for r in conn.execute(
                       """SELECT s.id, COALESCE(s.brand_name, s.generic_name) AS name,
                                 c2.ticker AS owner
                            FROM assumptions a JOIN assets s ON s.id = a.asset_id
                            JOIN companies c2 ON c2.id = s.owner_company_id
                           WHERE a.key = 'partner_ticker' AND a.text_value = ?
                             AND s.is_marketed = 1
                           GROUP BY s.id ORDER BY name""", (ticker,))]
        deal_rows = [dict(r) for r in conn.execute(
            """SELECT id, accession, deal_type, counterparty, event_date, quote, source_url,
                      article_url
                 FROM deals WHERE company_id = ? AND event_date >= ?
                  AND counterparty IS NOT NULL
                  AND deal_type IN ('acquisition', 'licensing', 'collaboration')
                ORDER BY event_date, id""", (cid, cutoff))]
        out[ticker] = {
            "ocf_usd_m": fy0_value("CashFlowOperating"),
            "pretax_usd_m": fy0_value("IncomeBeforeTax"),
            "share_change": change, "share_change_reason": change_reason,
            "share_change_basis": change_basis,
            "product_rows": prods, "fresh": fresh,
            "approvals": approvals, "partner_marketed": partner,
            "deals": gate_deals(deal_rows, {"ticker": ticker, "name": names.get(ticker)},
                                today),
        }
    return out


# ---- scoring -------------------------------------------------------------------------------
def cohort_of(rec: dict) -> str | None:
    stage, engine = rec.get("stage"), rec.get("engine")
    if stage == "clinical":
        return "clinical"
    if stage == "commercial" and engine == "pharma":
        return "big_pharma"
    if stage == "commercial" and engine in ("biotech", "cellgene"):
        return "commercial"
    return None


def _flag_nulls(rec: dict) -> dict:
    out: dict = {}
    for flag in rec.get("flags") or []:
        if flag.get("severity") != "amber":
            continue
        code = flag.get("code")
        for metric in FLAG_NULLS.get(code, ()):
            out.setdefault(metric, code)
        if code in ESTIMATE_FLAGS:
            out.setdefault("eps_cagr", code)
            if str(flag.get("field") or "").endswith(("FY1", "FY2", "NTM")):
                out.setdefault("pe_ntm", code)
        if code == "stale_shares" and _g(rec, "market.market_cap_basis") != "diluted_weighted":
            for metric in STALE_SHARE_METRICS:
                out.setdefault(metric, code)
    return out


def _product_gate(rec: dict, inp: dict) -> tuple:
    """(ok, coverage, reason, rows in USD largest first) for the three product measures."""
    rev = _num(_fy0(rec).get("revenue_usd_m"))
    rows = [r for r in inp.get("product_rows") or [] if r.get("usd_m") is not None]
    rows.sort(key=lambda r: -r["usd_m"])
    if not rows:
        return False, None, "no_product_revenue", rows
    coverage = sum(r["usd_m"] for r in rows) / rev if rev and rev > 0 else None
    ok = coverage is not None and PRODUCT_COVERAGE[0] <= coverage <= PRODUCT_COVERAGE[1]
    return ok, coverage, None if ok else "partial_product_revenue", rows


def metric_values(rec: dict, inp: dict, today) -> dict:
    """{metric: (value, reason)} for every metric of 2.3, before the cohort's coverage rule.
    A runway of a company not burning cash is ``math.inf``."""
    fy0 = _fy0(rec)
    rev = _num(fy0.get("revenue_usd_m"))
    mcap = _num(_g(rec, "market.market_cap_usd_m"))
    na = rec.get("na") or {}
    bases = _g(rec, "growth.bases") or {}
    compounds = _g(rec, "detail.pipeline.compounds") or {}
    v: dict = {}

    def growth(key):
        value = _num(_g(rec, "growth." + key))
        if rev is None:
            return None, "no_revenue"
        if rev < REVENUE_FLOOR_USD_M:
            return None, "below_revenue_floor"
        if value is None:
            code = na.get("growth." + key) or "not_filed"
            return None, "growth_not_meaningful" if code == "non_positive_base" else code
        base = [b for b in (bases.get(key) or []) if b is not None]
        if abs(value) > GROWTH_LIMIT or any(b < GROWTH_BASE_FLOOR_USD_M for b in base):
            return None, "growth_not_meaningful"
        return value, None

    v["rev_growth"] = growth("revenue_fy")
    v["rev_cagr3"] = growth("revenue_cagr3")

    e1, e2 = _num(_g(rec, "periods.FY1.eps")), _num(_g(rec, "periods.FY2.eps"))
    cagr = _num(_g(rec, "growth.eps_street_cagr"))
    eps_base = (bases.get("eps_street_cagr") or [None])[0]
    if cagr is None:
        v["eps_cagr"] = (None, na.get("growth.eps_street_cagr") or "no_consensus")
    elif eps_base is None or abs(eps_base) < EPS_BASE_FLOOR:
        v["eps_cagr"] = (None, "eps_base")
    elif e1 is not None and e2 is not None and e2 > 0 and e1 < 0.5 * e2:
        v["eps_cagr"] = (None, "eps_base_depressed")
    else:
        v["eps_cagr"] = (cagr, None)

    def margin(numerator):
        if not rev or rev <= 0:
            return None, "no_revenue"
        if numerator is None:
            return None, "not_filed"
        return numerator / rev, None

    v["op_margin"] = margin(_num(fy0.get("operating_income_usd_m")))
    v["pretax_margin"] = margin(_num(inp.get("pretax_usd_m")))
    v["fcf_margin"] = margin(_num(fy0.get("fcf_usd_m")))

    cash = _num(_g(rec, "ev.cash_usd_m"))
    debt = _num(_g(rec, "ev.total_debt_usd_m"))
    net_debt = _num(_g(rec, "ev.net_debt_usd_m"))
    ocf = _num(inp.get("ocf_usd_m"))
    if na.get("ev.total_debt_usd_m") == "no_debt_line" or debt is None:
        code = na.get("ev.total_debt_usd_m") or "no_debt_line"
        v["nd_ocf"] = (None, code)
        v["net_cash_rev"] = (None, code)
    else:
        if net_debt is not None and ocf is not None and ocf > 0:
            v["nd_ocf"] = (net_debt / ocf, None)
        else:
            v["nd_ocf"] = (None, "burning_cash" if ocf is not None and ocf <= 0 else "not_filed")
        if cash is None:
            v["net_cash_rev"] = (None, "no_cash")
        elif rev is None or rev < REVENUE_FLOOR_USD_M:
            v["net_cash_rev"] = (None, "below_revenue_floor")
        else:
            v["net_cash_rev"] = ((cash - debt) / rev, None)

    if na.get("risk.runway_months") == "not_burning":
        v["runway"] = (math.inf, None)
    else:
        runway = _num(_g(rec, "risk.runway_months"))
        v["runway"] = ((runway, None) if runway is not None
                       else (None, na.get("risk.runway_months") or "not_filed"))
    v["share_change"] = (inp.get("share_change"), inp.get("share_change_reason")
                         if inp.get("share_change") is None else None)
    if v["share_change"][0] is None and not v["share_change"][1]:
        v["share_change"] = (None, "not_filed")

    if compounds:
        late = (compounds.get("Phase 3") or 0) + (compounds.get("Phase 2/3") or 0)
        mid_late = late + (compounds.get("Phase 2") or 0)
        v["late_compounds"] = (late, None)
        v["mid_late_compounds"] = (mid_late, None)
        v["late_per_rev"] = ((late / (rev / 10000.0), None)
                             if rev is not None and rev >= REVENUE_FLOOR_USD_M
                             else (None, "below_revenue_floor"))
    else:
        v["late_compounds"] = v["mid_late_compounds"] = v["late_per_rev"] = (None, "no_pipeline")
    conc = _num(_g(rec, "healthcare.trial_concentration"))
    v["trial_conc"] = ((conc, None) if conc is not None
                       else (None, na.get("healthcare.trial_concentration") or "no_trials"))

    ok, _coverage, gate_reason, rows = _product_gate(rec, inp)
    if ok:
        v["top_product"] = (rows[0]["usd_m"] / rev, None)
        loe_map = {r.get("asset_id"): {"date": r.get("loe_date")} for r in rows}
        v["loe_years"] = loe_years(rows, loe_map, today)
        fresh = inp.get("fresh") or {}
        if fresh.get("inferred_revenue"):
            v["fresh_share"] = (None, "inferred_dates")
        elif _num(fresh.get("fresh_share")) is not None:
            v["fresh_share"] = (fresh["fresh_share"], None)
        else:
            v["fresh_share"] = (None, "no_dated_approvals")
    else:
        for metric in PRODUCT_METRICS:
            v[metric] = (None, gate_reason)

    price, ntm = _num(_g(rec, "market.price")), _num(_g(rec, "periods.NTM.eps"))
    crossing = (e1 is not None and e1 <= 0) or (e2 is not None and e2 <= 0)
    if ntm is None:
        v["pe_ntm"] = (None, na.get("periods.NTM") if na.get("periods.NTM") in REASONS
                       else "no_consensus")
    elif crossing or ntm <= 0:
        v["pe_ntm"] = (None, "eps_not_positive")
    elif price is None:
        v["pe_ntm"] = (None, "not_filed")
    else:
        v["pe_ntm"] = (price / ntm, None)
    big = rev is not None and rev >= REVENUE_FLOOR_USD_M
    ev = _num(_g(rec, "ev.ev_usd_m"))
    if not big:
        v["ev_sales"] = (None, "no_revenue" if rev is None else "below_revenue_floor")
        v["mcap_sales"] = v["ev_sales"]
    else:
        v["ev_sales"] = ((ev / rev, None) if ev is not None
                         else (None, na.get("ev.ev_usd_m") or "no_debt_line"))
        v["mcap_sales"] = (mcap / rev, None) if mcap is not None else (None, "not_filed")
    fcf = _num(fy0.get("fcf_usd_m"))
    if fcf is None:
        v["fcf_yield"] = (None, "not_filed")
    elif fcf <= 0:
        v["fcf_yield"] = (None, "fcf_negative")
    elif not mcap:
        v["fcf_yield"] = (None, "not_filed")
    else:
        v["fcf_yield"] = (fcf / mcap, None)
    v["mcap_cash"] = ((mcap / cash, None) if cash is not None and cash > 0 and mcap is not None
                      else (None, "no_cash"))
    for metric, key in (("rel_1y", "1y"), ("rel_3m", "3m")):
        rel = _g(rec, "detail.relative." + key) or {}
        pct = _num(rel.get("relative_pct"))
        v[metric] = ((pct, None) if pct is not None and rel.get("covers_window") is not False
                     else (None, "short_history"))

    for metric, code in _flag_nulls(rec).items():
        if metric in v and v[metric][0] is not None:
            v[metric] = (None, code)
    return v


def _rankval(value, metric, small: bool):
    """The value a metric is ranked on: a margin on revenue under the floor ranks last,
    tied with any other such margin."""
    return -math.inf if (metric in MARGINS and small) else value


def _place(value, others_all: list, better: str) -> tuple:
    """('best', '3rd best', 'joint 2nd worst', ...) counted from the nearer end in the
    metric's better direction, and n. ``others_all`` includes the value itself."""
    sign = 1 if better == "higher" else -1
    up = sum(1 for x in others_all if (x - value) * sign > 0)
    down = sum(1 for x in others_all if (x - value) * sign < 0)
    ties = sum(1 for x in others_all if x == value) - 1
    if up <= down:
        pos, word = up + 1, "best"
    else:
        pos, word = down + 1, "worst"
    text = word if pos == 1 else f"{ordinal(pos)} {word}"
    return ("joint " if ties else "") + text, len(others_all)


def rank_range(metric_scores: dict, spec, ranked: list, seed: int = SEED,
               draws: int = DRAWS, level: int = LEVEL) -> dict:
    """{ticker: [lo, hi]}: the ranks the company takes in ``level`` of 100 seeded random
    weightings. Each draw gives every business pillar a weight from a flat Dirichlet and
    each metric inside a pillar likewise, the same weights for every company; the ranked
    set is held fixed, so a company with no score never enters a draw.

    ``metric_scores``: {ticker: {metric: score}}; ``spec``: [(pillar, [metrics])] of the
    cohort's scored business pillars in order; ``ranked``: tickers in rank order."""
    if not ranked:
        return {}
    pillars = [(p, list(ms)) for p, ms in spec]
    n_biz = len(pillars)
    if not n_biz:
        return {t: [i + 1, i + 1] for i, t in enumerate(ranked)}
    # The weights come from Python's generator, in the order the reference script drew them
    # (each draw: every pillar's metric weights, then the pillar weights), so the same seed
    # gives the same ranges; the arithmetic is vectorised over draws and companies, one
    # IEEE operation at a time in the reference's order, so it is bit for bit the same.
    rng = random.Random(seed)
    gamma = rng.gammavariate
    width = max(len(ms) for _p, ms in pillars)
    wm = np.zeros((draws, n_biz, width))
    wp = np.zeros((draws, n_biz))
    for d in range(draws):
        for j, (_p, ms) in enumerate(pillars):
            for i in range(len(ms)):
                wm[d, j, i] = gamma(1.0, 1.0)
        for j in range(n_biz):
            wp[d, j] = gamma(1.0, 1.0)
    # Columns in ticker order, so a stable sort on the score breaks ties by ticker.
    tickers = sorted(ranked)
    n = len(tickers)
    score_m = np.zeros((n, n_biz, width))
    has_m = np.zeros((n, n_biz, width), dtype=bool)
    for c, t in enumerate(tickers):
        for j, (_p, ms) in enumerate(pillars):
            for i, m in enumerate(ms):
                if m in metric_scores[t]:
                    score_m[c, j, i] = metric_scores[t][m]
                    has_m[c, j, i] = True
    num = np.zeros((draws, n))
    den = np.zeros((draws, n))
    k = has_m.any(axis=2).sum(axis=1).astype(float)                    # pillars present
    for j, (_p, ms) in enumerate(pillars):
        wsum = np.zeros((draws, n))
        acc = np.zeros((draws, n))
        for i in range(len(ms)):
            present = has_m[:, j, i]
            w = wm[:, j, i][:, None]
            wsum = wsum + np.where(present[None, :], w, 0.0)
            acc = acc + np.where(present[None, :], w * score_m[:, j, i][None, :], 0.0)
        kk = has_m[:, j, :].sum(axis=1).astype(float)
        got = kk > 0
        KK = float(len(ms))
        with np.errstate(divide="ignore", invalid="ignore"):
            raw = acc / wsum
            value = 50 + (raw - 50) * (kk / (kk + 1))[None, :] * ((KK + 1) / KK)
        weight = wp[:, j][:, None]
        num = num + np.where(got[None, :], weight * value, 0.0)
        den = den + np.where(got[None, :], weight, 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        scores = 50 + (num / den - 50) * (k / (k + 1))[None, :] * ((n_biz + 1) / n_biz)
    scores = np.where(den > 0, scores, 50.0)
    order = np.argsort(-scores, axis=1, kind="stable")
    ranks = np.empty_like(order)
    np.put_along_axis(ranks, order, np.arange(1, n + 1)[None, :].repeat(draws, axis=0), axis=1)
    ranks.sort(axis=0)
    tail = (100 - level) / 200
    lo_i, hi_i = int(tail * draws), min(draws - 1, int((1 - tail) * draws))
    return {t: [int(ranks[lo_i, c]), int(ranks[hi_i, c])] for c, t in enumerate(tickers)}


def _plural(n, one: str, many: str) -> str:
    return one if n is not None and round(n) == 1 else many


def _product_name(name: str | None) -> str:
    return _BRACKETS.sub("", name or "").strip() or (name or "")


def _phrase(metric: str, value, rec: dict, ctx: dict) -> str:
    """The line phrase of section 8.2, number first, with its period."""
    fy = _fy0(rec).get("label") or "FY0"
    text = fmt(metric, value)
    if metric in MARGINS and ctx.get("small"):
        rev = _num(_fy0(rec).get("revenue_usd_m")) or 0.0
        return f"${rev:.1f}m of revenue in {fy}, too little to compare margins"
    if metric == "rev_growth":
        return f"{text} revenue growth in {fy}"
    if metric == "rev_cagr3":
        fym3 = _g(rec, "periods.FYm3.label") or "FY0"
        return f"{text} a year revenue growth, {fym3} to {fy}"
    if metric == "eps_cagr":
        return (f"{text} a year street EPS growth, {_g(rec, 'periods.FY1.label') or 'FY1'} "
                f"to {_g(rec, 'periods.FY3.label') or 'FY3'}")
    if metric == "op_margin":
        return f"{text} operating margin in {fy}"
    if metric == "pretax_margin":
        return f"{text} pre-tax margin in {fy}"
    if metric == "fcf_margin":
        return f"{text} free cash flow margin in {fy}"
    if metric == "nd_ocf":
        return (f"Net cash of {fmt(metric, -value)} operating cash flow" if value < 0
                else f"Net debt of {text} operating cash flow")
    if metric == "net_cash_rev":
        return (f"Net cash of {abs(value):.1f}{TIMES} revenue" if value >= 0
                else f"Net debt of {abs(value):.1f}{TIMES} revenue")
    if metric == "runway":
        return f"{text} of cash runway"
    if metric == "share_change":
        return f"{text} change in share count over a year"
    if metric == "late_compounds":
        return f"{text} late-stage {_plural(value, 'compound', 'compounds')}"
    if metric == "late_per_rev":
        return f"{text} late-stage compounds per $10bn of revenue"
    if metric == "fresh_share":
        since = int(fy[2:]) - 4 if fy[2:].isdigit() else None
        return f"{text} of {fy} product revenue from drugs approved since {since}"
    if metric == "loe_years":
        return f"{text} of exclusivity left on {fy} product revenue"
    if metric == "top_product":
        return f"{text} of {fy} revenue from {_product_name(ctx.get('top_name'))}"
    if metric == "mid_late_compounds":
        return f"{text} {_plural(value, 'compound', 'compounds')} in Phase 2 or later"
    if metric == "trial_conc":
        return f"{text} of trials on the lead asset"
    if metric == "pe_ntm":
        return f"{text} P/E on the next 12 months"
    if metric == "ev_sales":
        return f"{text} EV to {fy} sales"
    if metric == "mcap_sales":
        return f"{text} market cap to {fy} sales"
    if metric == "fcf_yield":
        return f"{text} free cash flow yield"
    if metric == "mcap_cash":
        return f"{text} market cap to cash"
    if metric == "rel_1y":
        return f"{text} against XLV over 1 year"
    if metric == "rel_3m":
        return f"{text} against XLV over 3 months"
    return f"{text} {METRICS[metric]['label'].lower()}"


def _period(metric: str, rec: dict, inp: dict) -> str | None:
    fy = _fy0(rec).get("label")
    if metric in ("rev_growth", "op_margin", "pretax_margin", "fcf_margin", "late_per_rev",
                  "net_cash_rev", "nd_ocf", "fresh_share", "loe_years", "top_product",
                  "ev_sales", "mcap_sales", "fcf_yield"):
        return fy
    if metric == "rev_cagr3":
        fym3 = _g(rec, "periods.FYm3.label")
        return f"{fym3} to {fy}" if fym3 and fy else fy
    if metric == "eps_cagr":
        f1, f3 = _g(rec, "periods.FY1.label"), _g(rec, "periods.FY3.label")
        return f"{f1} to {f3}" if f1 and f3 else None
    if metric == "runway":
        return _g(rec, "risk.runway_basis")
    if metric == "share_change":
        basis = inp.get("share_change_basis")
        if basis:
            return f"{_mon_year(_date(basis[0]))} to {_mon_year(_date(basis[1]))}"
        return None
    if metric == "pe_ntm":
        return "next 12 months"
    if metric == "rel_1y":
        return "1 year"
    if metric == "rel_3m":
        return "3 months"
    return None


def _source(metric: str, rec: dict) -> str:
    fy = _fy0(rec).get("label") or "FY0"
    form = _g(rec, "filer.annual_form")
    filing = f"{fy} {form}" if form else f"{fy} annual report"
    if metric in ("late_compounds", "late_per_rev", "mid_late_compounds", "trial_conc"):
        return "pipeline record"
    if metric in PRODUCT_METRICS:
        return "product revenue on file"
    if metric == "eps_cagr":
        day = _date(_g(rec, "periods.FY1.as_of"))
        return f"consensus of {_day_mon(day)}" if day else "consensus"
    if metric == "share_change":
        return "diluted share counts as filed"
    return filing


def _sentence(ticker: str, res: dict, noun: str) -> str:
    if res["score_raw"] is None:
        return (f"{ticker} is not scored: {res['k']} of {res['K']} pillars have data, and a "
                f"score needs {res['need']}.")
    head = (f"{ticker} scores {round(res['score_raw'])}, {ordinal(res['rank'])} of "
            f"{res['ranked_of']} {noun}, range {res['range_text']}.")
    biz = [(p, raw) for p, raw in res["pillar_raw"].items() if p in BUSINESS and raw is not None]
    strong = [p for p, raw in sorted(biz, key=lambda x: -x[1]) if round(raw) >= STRONG_AT][:2]
    weak = [p for p, raw in sorted(biz, key=lambda x: x[1]) if round(raw) <= WEAK_AT][:2]

    def join(ps):
        return " and ".join(PILLARS[p]["label"].lower() for p in ps)

    tail = " No pillar above 60 or below 40."
    # Over 30 words: drop the second strongest, then the second weakest.
    for s, w in ((strong, weak), (strong[:1], weak), (strong[:1], weak[:1])):
        if s and w:
            tail = f" Strongest on {join(s)}, weakest on {join(w)}."
        elif s:
            tail = f" Strongest on {join(s)}."
        elif w:
            tail = f" Weakest on {join(w)}."
        if len((head + tail).split()) <= SENTENCE_MAX_WORDS:
            break
    return head + tail


def _median(values):
    xs = [x for x in values if x is not None]
    return statistics.median(xs) if xs else None


def score(records: list[dict], inputs: dict, today, seed: int = SEED,
          draws: int = DRAWS) -> dict:
    """Pure. Cohorts, metric values with reasons, coverage, metric scores, pillars, company
    score, rank, rank range, value, momentum, positives, negatives, sentence, facts and the
    chart point, for every company of ``records`` (the ``/comps/valuation`` records) with
    ``inputs`` from ``book_inputs``. Returns the scorecard block less its stamps."""
    today = _date(today) or dt.date.today()
    recs = {r["ticker"]: r for r in records if r.get("ticker")}
    cohort = {t: cohort_of(r) for t, r in recs.items()}
    members = {c: sorted(t for t in recs if cohort[t] == c) for c in COHORT_ORDER}
    lists = {c: [(p, list(ms)) for p, ms in LISTS[c]] for c in COHORT_ORDER}
    listed = {c: {m for _p, ms in LISTS[c] for m in ms} for c in COHORT_ORDER}

    vals: dict = {}
    small: dict = {}
    gates: dict = {}
    for t, rec in recs.items():
        c = cohort[t]
        if c is None:
            continue
        inp = inputs.get(t) or {}
        # Every metric, listed or not: the absolute rules of 2.12 read a figure outside the
        # cohort's list (BMRN's net debt of 4.0x operating cash flow, commercial cohort).
        vals[t] = metric_values(rec, inp, today)
        rev = _num(_fy0(rec).get("revenue_usd_m"))
        small[t] = rev is not None and rev < REVENUE_FLOOR_USD_M
        gates[t] = _product_gate(rec, inp)

    def val(t, m):
        return (vals.get(t) or {}).get(m, (None, None))[0]

    def rv(t, m):
        return _rankval(val(t, m), m, small[t])

    # coverage
    scored_in: dict = {}
    not_scored: dict = {}
    cspec: dict = {}
    for c in COHORT_ORDER:
        n = len(members[c])
        need = math.ceil(COVERAGE * n) if n else 0
        scored_in[c] = set()
        not_scored[c] = []
        cspec[c] = []
        for p, ms in lists[c]:
            keep = []
            for m in ms:
                xs = [val(t, m) for t in members[c] if val(t, m) is not None]
                if n and len(xs) >= need and len(set(xs)) >= MIN_DISTINCT:
                    keep.append(m)
                    scored_in[c].add(m)
                else:
                    not_scored[c].append({
                        "metric": m, "pillar": p, "have": len(xs), "of": n,
                        "text": reason_text("not_scored_in_cohort", k=len(xs), n=n)})
            if keep:
                cspec[c].append((p, keep))

    # metric scores
    mscore: dict = {t: {} for t in vals}
    for c in COHORT_ORDER:
        for _p, ms in cspec[c]:
            for m in ms:
                lower = METRICS[m]["better"] == "lower"
                for t in members[c]:
                    if val(t, m) is None:
                        continue
                    others = [rv(o, m) for o in members[c] if o != t and val(o, m) is not None]
                    pct = percentile(rv(t, m), others)
                    if pct is not None:
                        mscore[t][m] = 100 - pct if lower else pct

    # pillars, company score, rank
    res: dict = {}
    ranked_list: dict = {}
    for c in COHORT_ORDER:
        biz = [p for p, _ms in cspec[c] if p in BUSINESS]
        need = math.ceil(COVERAGE * len(biz)) if biz else 0
        for t in members[c]:
            pillar_raw = {}
            for p, ms in cspec[c]:
                got = [mscore[t][m] for m in ms if m in mscore[t]]
                pillar_raw[p] = pull(statistics.fmean(got), len(got), len(ms)) if got else None
            present = [pillar_raw[p] for p in biz if pillar_raw[p] is not None]
            raw = (pull(statistics.fmean(present), len(present), len(biz))
                   if biz and len(present) >= need else None)
            res[t] = {"cohort": c, "pillar_raw": pillar_raw, "score_raw": raw,
                      "k": len(present), "K": len(biz), "need": need, "rank": None}
        order = sorted((t for t in members[c] if res[t]["score_raw"] is not None),
                       key=lambda t: (-res[t]["score_raw"], t))
        for i, t in enumerate(order):
            res[t]["rank"] = i + 1
        for t in members[c]:
            res[t]["ranked_of"] = len(order)
        ranges = rank_range({t: mscore[t] for t in order},
                            [(p, ms) for p, ms in cspec[c] if p in BUSINESS], order,
                            seed=seed, draws=draws)
        for t in members[c]:
            lo_hi = ranges.get(t)
            res[t]["rank_range"] = lo_hi
            res[t]["range_text"] = (None if not lo_hi else str(lo_hi[0]) if lo_hi[0] == lo_hi[1]
                                    else f"{lo_hi[0]}{EN_DASH}{lo_hi[1]}")
        ranked_list[c] = order

    # cohort medians
    medians: dict = {}
    metric_medians: dict = {}
    for c in COHORT_ORDER:
        med = {"score": _median(res[t]["score_raw"] for t in members[c])}
        for p, _ms in cspec[c]:
            med[p] = _median(res[t]["pillar_raw"].get(p) for t in members[c])
        medians[c] = {k: (round(v) if v is not None else None) for k, v in med.items()}
        metric_medians[c] = {}
        for _p, ms in cspec[c]:
            for m in ms:
                m_med = _median(val(t, m) for t in members[c])
                metric_medians[c][m] = m_med

    # chart sizes
    cap_max = {c: max([_num(_g(recs[t], "market.market_cap_usd_m")) or 0.0
                       for t in members[c]] or [0.0]) for c in COHORT_ORDER}

    companies: dict = {}
    for t, rec in recs.items():
        c = cohort[t]
        if c is None:
            continue
        inp = inputs.get(t) or {}
        r = res[t]
        noun = COHORTS[c]["noun"]
        _ok, coverage, _why, prod_rows = gates[t]
        ctx = {"small": small[t], "top_name": prod_rows[0]["name"] if prod_rows else None}
        partner = inp.get("partner_marketed") or []
        silenced = PIPELINE_COUNTS if (partner and c != "big_pharma") else frozenset()

        # metric entries, by pillar
        pillars_out = {}
        for p, ms in lists[c]:
            scored_list = next((keep for pp, keep in cspec[c] if pp == p), None)
            if scored_list is None:
                continue
            entries = []
            for m in ms:
                value, why = vals[t][m]
                is_scored = m in scored_in[c]
                entry = {"id": m, "value": None, "text": None,
                         "period": _period(m, rec, inp), "score": None, "place": None,
                         "n": None, "reason": why, "scored": is_scored}
                if value is not None:
                    entry["value"] = None if value == math.inf else _round(value)
                    entry["text"] = fmt(m, value)
                    entry["reason"] = None
                    pool = [rv(o, m) for o in members[c] if val(o, m) is not None]
                    entry["place"], entry["n"] = _place(rv(t, m), pool, METRICS[m]["better"])
                    if m in mscore[t]:
                        entry["score"] = round(mscore[t][m], 1)
                    if m in MARGINS and small[t]:
                        entry["note"] = _phrase(m, value, rec, ctx)
                elif why in PARAMETRISED and coverage is not None:
                    # The other codes read their text from method.reasons as they stand.
                    entry["reason_text"] = reason_text(why, c=f"{coverage * 100:.0f}")
                entries.append(entry)
            raw = r["pillar_raw"].get(p)
            k = sum(1 for m in scored_list if m in mscore[t])
            p_reason = None
            if raw is None:
                codes = {vals[t][m][1] for m in scored_list}
                p_reason = codes.pop() if len(codes) == 1 and None not in codes else "no_free_data"
            pillars_out[p] = {
                "score": round(raw) if raw is not None else None,
                "raw": _round(raw, 2), "k": k, "of": len(scored_list),
                "median": medians[c].get(p), "reason": p_reason, "metrics": entries}
            if p_reason:
                # A parametrised code carries the company's own figure on the pillar as on
                # its metrics, or the bar's reason prints the template ("{c}%").
                params = ({"c": f"{coverage * 100:.0f}"}
                          if p_reason in PARAMETRISED and coverage is not None else {})
                pillars_out[p]["reason_text"] = reason_text(p_reason, **params)
            if k < len(scored_list):
                pillars_out[p]["on_text"] = f"on {k} of {len(scored_list)} measures"

        # pillars of the full list that left the cohort's list: facts for the panel
        other = []
        for p, ms in lists[c]:
            if any(pp == p for pp, _k in cspec[c]):
                continue
            for m in ms:
                value, why = vals[t][m]
                params = ({"c": f"{coverage * 100:.0f}"}
                          if why == "partial_product_revenue" and coverage is not None else {})
                item = {"pillar": p, "id": m,
                        "value": None if value in (None, math.inf) else _round(value),
                        "text": fmt(m, value), "period": _period(m, rec, inp),
                        "reason": None if value is not None else why, "scored": False}
                if value is None and params:
                    item["reason_text"] = reason_text(why, **params)
                other.append(item)

        loe_value = vals[t].get("loe_years", (None, None))[0]
        loe_text = f"{fmt('loe_years', loe_value)} of exclusivity left" if loe_value is not None else None
        if "durability" in pillars_out and loe_text:
            pillars_out["durability"]["note"] = loe_text

        # positives and negatives
        lines = []
        for p, ms in cspec[c]:
            if p not in BUSINESS:
                continue
            cands = [(mscore[t][m], m, val(t, m)) for m in ms
                     if m in mscore[t] and m not in silenced
                     and not (m == "runway" and val(t, m) == math.inf)]
            if not cands:
                continue
            for sign, (s, m, v) in (("+", max(cands)), ("-", min(cands))):
                if sign == "+" and (s < POSITIVE_AT or (m in ABOVE_ZERO and v <= 0)
                                    or (m in BELOW_ZERO and v >= 0)):
                    continue
                if sign == "-" and s > NEGATIVE_AT:
                    continue
                pool = [rv(o, m) for o in members[c] if val(o, m) is not None]
                where, n = _place(rv(t, m), pool, METRICS[m]["better"])
                lines.append({"sign": sign, "pillar": p, "metric": m,
                              "strength": round(abs(s - 50), 1),
                              "text": f"{_phrase(m, v, rec, ctx)}, {where} of {n} {noun}",
                              "source": _source(m, rec)})
        have_neg = {x["pillar"] for x in lines if x["sign"] == "-"}
        have_pos = {x["metric"] for x in lines if x["sign"] == "+"}
        scored_pillars = {p for p, _ms in cspec[c]}
        bs = "funding" if c == "clinical" else "balance_sheet"
        runway = val(t, "runway")
        if (runway is not None and runway != math.inf and round(runway) < 24
                and bs in scored_pillars and bs not in have_neg and "runway" not in have_pos):
            lines.append({"sign": "-", "pillar": bs, "metric": "runway", "strength": 49,
                          "text": f"{runway:.0f} months of cash runway, under two years",
                          "source": _source("runway", rec)})
        top = val(t, "top_product")
        if (top is not None and round(top * 100) > 50 and "durability" in scored_pillars
                and "durability" not in have_neg and "top_product" not in have_pos):
            lines.append({"sign": "-", "pillar": "durability", "metric": "top_product",
                          "strength": 48,
                          "text": f"{_phrase('top_product', top, rec, ctx)}, over half",
                          "source": _source("top_product", rec)})
        lev = val(t, "nd_ocf")
        if (lev is not None and round(lev, 1) > 3.0 and bs in scored_pillars
                and bs not in have_neg and "nd_ocf" not in have_pos):
            lines.append({"sign": "-", "pillar": bs, "metric": "nd_ocf", "strength": 47,
                          "text": f"Net debt of {fmt('nd_ocf', lev)} operating cash flow, above 3{TIMES}",
                          "source": _source("nd_ocf", rec)})
        lines.sort(key=lambda x: -x["strength"])
        positives = [{k: v for k, v in x.items() if k != "sign"} for x in lines if x["sign"] == "+"]
        negatives = [{k: v for k, v in x.items() if k != "sign"} for x in lines if x["sign"] == "-"]

        # facts
        multiple = None
        value_list = next((ms for p, ms in cspec[c] if p == "value"), [])
        for m in value_list:
            v = val(t, m)
            if v is not None:
                med = metric_medians[c].get(m)
                multiple = {"metric": m, "value": _round(v), "text": fmt(m, v),
                            "label": METRICS[m].get("short") or METRICS[m]["label"],
                            "median": _round(med), "median_text": fmt(m, med)}
                break
        lead_phase = None
        partner_on = None
        if c == "clinical":
            approvals = sorted((a for a in inp.get("approvals") or [] if a.get("first")),
                               key=lambda a: (a["first"], a.get("name") or ""))
            compounds = _g(rec, "detail.pipeline.compounds") or {}
            highest = next((ph for ph in reversed(_PHASES) if (compounds.get(ph) or 0) > 0), None)
            if approvals:
                newest = approvals[-1]
                day = _date(newest["first"])
                lead_phase = {"phase": "marketed", "brand": newest["name"],
                              "approved": newest["first"][:10],
                              "text": f"Lead asset marketed: {newest['name']}, approved {_mon_year(day)}"}
            elif highest:
                lead_phase = {"phase": highest, "brand": None, "approved": None,
                              "text": f"Lead asset in {highest}"}
        if partner:
            first = partner[0]
            partner_on = {"brand": first["name"], "owner": first["owner"],
                          "text": f"Shares {first['name']}, {first['owner']}'s marketed drug"}
        deal_rows = inp.get("deals") or []
        n_deals = len(deal_rows)
        count_text = ("No deal on file in 24 months." if not n_deals else
                      "1 deal on file in 24 months" if n_deals == 1 else
                      f"{n_deals} deals on file in 24 months")
        firepower = firepower_text = None
        ocf = _num(inp.get("ocf_usd_m"))
        net_debt = _num(_g(rec, "ev.net_debt_usd_m"))
        debt_filed = (rec.get("na") or {}).get("ev.total_debt_usd_m") != "no_debt_line"
        if c in ("big_pharma", "commercial") and ocf is not None and ocf > 0 \
                and net_debt is not None and debt_filed:
            firepower = round(3 * ocf - net_debt)
            firepower_text = (
                f"Could fund about ${firepower / 1000:.1f}bn of deals before net debt reaches "
                "three times operating cash flow." if firepower > 0 else
                "Net debt is already above three times operating cash flow.")
        facts = {
            "multiple": multiple,
            "loe_years_text": loe_text,
            "product_coverage": _round(coverage, 3),
            "product_coverage_text": (f"Product revenue on file: {coverage * 100:.0f}% of "
                                      f"{_fy0(rec).get('label') or 'FY0'} revenue"
                                      if coverage is not None else None),
            "lead_phase": lead_phase,
            "partner_on": partner_on,
            "deals": {"n": n_deals, "count_text": count_text, "chip": DEAL_CHIP,
                      "rows": [{k: d[k] for k in ("date", "type", "route", "quote", "url")}
                               for d in deal_rows[:DEAL_LIST_MAX]]},
            "firepower_usd_m": firepower,
            "firepower_text": firepower_text,
            "other_metrics": other,
        }

        # exclusivity losses of the next 24 months, any cohort
        rev = _num(_fy0(rec).get("revenue_usd_m"))
        horizon = today + dt.timedelta(days=EXCLUSIVITY_WINDOW_DAYS)
        losses = []
        for row in prod_rows:
            day = _date(row.get("loe_date"))
            if day is None or not (today < day <= horizon):
                continue
            share = row["usd_m"] / rev if rev and rev > 0 else None
            losses.append({"asset": _product_name(row["name"]), "asset_id": row.get("asset_id"),
                           "date": day.isoformat(), "date_text": _day_mon_year(day),
                           "share_of_revenue": _round(share, 4),
                           "share_text": (f"{share * 100:.1f}%" if share is not None else None),
                           "fy": _fy0(rec).get("label"), "basis": row.get("loe_basis")})
        losses.sort(key=lambda x: (x["date"], -(x["share_of_revenue"] or 0)))

        value_raw = r["pillar_raw"].get("value")
        mom_raw = r["pillar_raw"].get("momentum")
        mcap = _num(_g(rec, "market.market_cap_usd_m"))
        chart = None
        if r["score_raw"] is not None and value_raw is not None:
            size = (100 * math.sqrt(mcap / cap_max[c]) if mcap and cap_max[c] else None)
            chart = {"x": _round(r["score_raw"], 2), "y": _round(value_raw, 2),
                     "size": _round(size, 1), "complete": r["k"] == r["K"]}
        reason = None
        if r["score_raw"] is None:
            reason = "too_few_pillars"
        companies[t] = {
            "ticker": t, "name": rec.get("name"), "cohort": c,
            "score": round(r["score_raw"]) if r["score_raw"] is not None else None,
            "score_raw": _round(r["score_raw"], 2), "rank": r["rank"],
            "ranked_of": r["ranked_of"], "rank_range": r["rank_range"],
            "range_text": r["range_text"],
            "pillars_scored": r["k"], "pillars_of": r["K"], "pillars_needed": r["need"],
            "reason": reason,
            "reason_text": (reason_text(reason, k=r["k"], K=r["K"], m=r["need"])
                            if reason else None),
            "value": round(value_raw) if value_raw is not None else None,
            "momentum": round(mom_raw) if mom_raw is not None else None,
            "sentence": _sentence(t, r, noun),
            "pillars": pillars_out,
            "positives": positives,
            "negatives": negatives,
            "facts": facts,
            "exclusivity_losses": losses,
            "chart": chart,
        }

    cohorts_out = {}
    for c in COHORT_ORDER:
        n = len(members[c])
        biz = [p for p, _ms in cspec[c] if p in BUSINESS]
        need = math.ceil(COVERAGE * len(biz)) if biz else 0
        not_ranked = []
        for t in members[c]:
            if res[t]["score_raw"] is None:
                text = f"{res[t]['k']} of {res[t]['K']} pillars, a score needs {res[t]['need']}"
                not_ranked.append({"ticker": t, "reason": text, "code": "too_few_pillars"})
        not_on_chart = [{"ticker": t, "reason": "no value measure on file"}
                        for t in ranked_list[c] if res[t]["pillar_raw"].get("value") is None]
        cohorts_out[c] = {
            "label": COHORTS[c]["label"], "noun": COHORTS[c]["noun"], "n": n,
            "business_pillars": len(biz), "pillars_needed": need,
            "pillars": [{"id": p, "metrics": list(ms)} for p, ms in cspec[c]],
            "not_scored": not_scored[c],
            "ranked": list(ranked_list[c]),
            "not_ranked": not_ranked,
            "not_on_chart": not_on_chart,
            "medians": medians[c],
            "metric_medians": {m: _round(v) for m, v in metric_medians[c].items()},
            "metric_median_text": {m: fmt(m, v) for m, v in metric_medians[c].items()},
            "context_text": f"Scored against {n} {COHORTS[c]['noun']}",
            "method_text": [line.format(label=COHORTS[c]["label"], n=n, m=need, K=len(biz))
                            for line in METHOD_LINES],
        }
    return {
        "today": today.isoformat(),
        "method": {
            "rules": {"coverage": round(COVERAGE, 4), "min_distinct": MIN_DISTINCT,
                      "positive_at": POSITIVE_AT, "negative_at": NEGATIVE_AT,
                      "revenue_floor_usd_m": REVENUE_FLOOR_USD_M,
                      "product_coverage": list(PRODUCT_COVERAGE),
                      "loe_dated_floor": LOE_DATED_FLOOR,
                      "deal_window_days": DEAL_WINDOW_DAYS, "deal_list_max": DEAL_LIST_MAX,
                      "range": {"seed": seed, "draws": draws, "level": LEVEL}},
            "pillars": PILLARS,
            "metrics": {m: {"label": o["label"], "better": o["better"], "unit": o["unit"]}
                        for m, o in METRICS.items()},
            "reasons": REASONS,
            "text": {"how_to_read": HOW_TO_READ, "method": list(METHOD_LINES)},
        },
        "cohorts": cohorts_out,
        "companies": companies,
    }


def _rates(payload: dict, db_path) -> dict:
    """The payload's rates over the book's latest set, so every conversion here uses the
    same ECB day as the records."""
    rates = {k: v for k, v in fx.latest_usd_rates(db_path).items() if k != "as_of" and v}
    rates.update((_g(payload, "fx.usd_per_unit") or {}))
    rates["USD"] = 1.0
    return rates


def build(payload: dict, db_path=None, today=None) -> dict:
    """The scorecard for every company in a built ``/comps/valuation`` payload. Reads tables
    the book already has, then scores. Never raises: a failure returns
    ``{"schema", "error", "companies": {}}`` so the Comps view still opens."""
    today = _date(today) or dt.date.today()
    started = time.perf_counter()
    stamp = {"schema": SCHEMA,
             "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "today": today.isoformat()}
    try:
        records = [r for r in (payload or {}).get("companies") or [] if isinstance(r, dict)]
        conn = db.get_connection(db_path)
        try:
            inputs = book_inputs(conn, records, _rates(payload or {}, db_path), today)
        finally:
            conn.close()
        out = score(records, inputs, today)
        out.update(stamp)
        out["error"] = None
    except Exception as exc:               # the Comps view must still open
        out = dict(stamp, error=f"{type(exc).__name__}: {exc}", method={}, cohorts={},
                   companies={})
    out["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    return {k: out[k] for k in ("schema", "generated_at", "today", "error", "elapsed_ms",
                                "method", "cohorts", "companies")}


def unknown_amber_flags(records: list[dict]) -> list[str]:
    """Amber flag codes in ``records`` that sit in neither table of 2.8 (nulled or shown),
    sorted. A new code the valuation builder starts to emit must be placed in one of them
    before it can be scored past."""
    known = set(FLAG_NULLS) | FLAG_SHOWN
    return sorted({f.get("code") for r in records for f in r.get("flags") or []
                   if f.get("severity") == "amber" and f.get("code") not in known})
