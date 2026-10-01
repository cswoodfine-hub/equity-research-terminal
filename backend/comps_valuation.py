"""The Comps tab's valuation view: one record per company, all seventy, in one read.

``GET /comps/valuation`` returns what the view needs to compare a company with any peer set
the analyst picks, without a round trip per click. The records carry components, never
multiples: the view divides price by earnings itself, so its currency, period and
earnings-basis toggles cannot disagree with anything computed here. Growth rates are the
exception, because they are currency-internal and need rows the view does not receive.

Every value is a filed figure, a street figure, a model figure read from the response cache,
or arithmetic on those. Nothing is estimated. A value that cannot be had is null, and the
record's ``na`` map says why, so the view shows the reason rather than a blank or a zero.

Several shared builders put wrong numbers on screen for this purpose, and this module does
not reuse them where they are wrong. The fixes live here, in the builder, so every other
caller keeps the behaviour it was written against:

- Enterprise value uses ``cashflow``'s dated net debt (debt read on the cash line's balance
  sheet date), never ``comps``' newest debt row of any date, which carried Incyte's 2018
  mis-tag of $19bn into this year's EV.
- Market cap has two routes, the cover-page count and the weighted diluted count, so AZN,
  NVO, ROG, BAYN, BNTX and the pre-revenue names get one. ``comps._market_cap`` is null for
  twelve of them.
- Net debt over EBITDA is never sent. The view divides, and treats a negative EBITDA as
  not meaningful, where ``cashflow`` reads CRISPR's net cash over its losses as 2.8x.
- Operating income derived from revenue less costs is marked, since it can leave out
  separately presented charges.
- Money is converted at the unit on each filed row, never at the company's stated
  currency: BioNTech's record says USD and every one of its rows is in euro.
- The twelve-month EPS blend weights by the company's own fiscal year end, where
  ``fair_value._ntm_eps`` assumes December.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import statistics

import beta as beta_module
import cashflow
import comps
import db
import engines
import financials_view
import forecast_view
import fx
import notecontext
import other_claims
import pipeline
import response_cache
import runway
import screen

SCHEMA = 1

# The sources this view reads. A failure of one of them in the latest refresh run is
# shown against the figures it feeds; a failure of any other source is listed only.
VIEW_SOURCES = ("prices", "consensus_nasdaq", "financials", "fx")

# A cover-page share count older than this, against the price date, is not a current count.
COVER_COUNT_MAX_AGE_DAYS = 400
# Two share counts further apart than this factor are not two measurements of one thing:
# one of them is in the wrong scale (IOVA files its weighted diluted count in thousands).
SHARE_SCALE_LIMIT = 5
# Tickers whose cover-page count is known not to be the count EPS is struck on. Each entry
# is added only with a cited reason, which the view shows.
COVER_COUNT_EXCEPTIONS = {
    "LLY": ("The cover count includes about 50m shares held by the employee benefit "
            "trust, which are not outstanding for EPS."),
}

DISAGREEMENT_FLAG = 0.10          # market cap routes further apart than this are flagged
STALE_CONSENSUS_DAYS = 3
STALE_BALANCE_SHEET_DAYS = 200
STALE_FISCAL_YEAR_DAYS = 456      # fifteen months
THIN_ESTIMATES = 3                # fewer estimates than this for a period is thin
WIDE_RANGE = 0.5                  # FY1 EPS range over the mean above this is wide
VOL_MIN_RETURNS = 200             # a year of volatility needs this many daily returns
MAJOR_PRODUCT_USD = 1e9
SPARK_DAYS, SPARK_POINTS = 90, 60
DETAIL_SPARK_DAYS, DETAIL_SPARK_POINTS = 365, 52
SPARK_DECIMALS = 4
PRICE_WINDOW_DAYS = 800           # how far back the one bulk price read reaches

LINEAGE_SOURCES = ("prices", "financials", "financials_ir", "filings", "trials",
                   "consensus_nasdaq", "approvals", "labels", "press_ir")

EUROPE = frozenset({"GB", "CH", "DE", "DK", "FR", "NL", "BE", "IE", "SE", "NO", "ES", "IT",
                    "AT", "FI"})
ABSENT_SUBSECTORS = ["Medtech", "Healthcare services"]
ANNUAL_FORMS = ("10-K", "20-F", "40-F")
_FILER_KIND = {"10-K": "10-K filer", "20-F": "20-F filer", "40-F": "40-F filer"}

# Money lines read from ``financials``. Share counts and EPS are not money and are never
# converted at an exchange rate.
_MONEY_METRICS = (
    "Revenues", "GrossProfit", "CostOfRevenue", "OperatingIncomeLoss",
    "DepreciationAndAmortisation", "Depreciation", "AmortisationOfIntangibles",
    "AcquiredIprd", "NetIncomeLoss", "NetIncomeAttributableToParent", "CashFlowOperating",
    "CapitalExpenditure", "ResearchAndDevelopmentExpense", "ResearchLessExpensedIprd",
    "SellingGeneralAndAdministrative", "IncomeTaxExpense", "IncomeBeforeTax",
    "StockholdersEquity", "CashAndEquivalents",
)
_OTHER_METRICS = ("EarningsPerShareDiluted", "SharesOutstanding", "WeightedAverageDilutedShares")
# The lines whose latest full year sets a company's latest fiscal year.
_ANCHOR_METRICS = ("Revenues", "NetIncomeLoss", "CashFlowOperating")
# The lines an interim row is read for, to build a trailing twelve months.
_LTM_METRICS = ("Revenues", "NetIncomeLoss")

_RATINGS = re.compile(r"(\d+)\s+buy,\s*(\d+)\s+hold,\s*(\d+)\s+sell", re.I)
_ESTIMATES = re.compile(r"(\d+)\s+estimates?", re.I)
_SCOPE = re.compile(r"Scope:\s*([^.]*)", re.I)
_NOT_TOTAL = re.compile(r"not total revenues?", re.I)
_TOTAL = re.compile(r"\btotal revenues?\b|\btop line\b", re.I)
_PRODUCT = re.compile(r"\bproduct (revenue|sales)", re.I)
_CURRENCY_CODE = re.compile(r"^[A-Z]{3}$")

# Sections of a record whose every null carries a reason in ``na``.
NA_SECTIONS = ("market", "ev", "periods", "growth", "street", "risk", "healthcare", "model")


# --- small helpers ---------------------------------------------------------------------
def _finite(value):
    """A JSON-safe number: NaN and infinities become None, numpy scalars plain floats."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clean(obj):
    """Strict JSON: every float through ``_finite``, keys as strings, tuples as lists."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, (int, float)):
        return _finite(obj)
    if hasattr(obj, "item"):                      # a numpy scalar
        return _finite(obj.item())
    return str(obj)


def _date(value) -> dt.date | None:
    if not value:
        return None
    text = str(value)
    if re.match(r"^\d{8}$", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _iso_date(value) -> str | None:
    day = _date(value)
    return day.isoformat() if day else None


def _catalyst_date(value) -> str | None:
    """A catalyst's date as ISO: the day where the source gives one, else "YYYY-MM" for a
    month-precision date, never a day the source did not state."""
    text = str(value or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})", text)
    if m:
        return text if 1 <= int(m.group(2)) <= 12 else None
    return _iso_date(value)


def _iso_ts(value) -> str | None:
    """A stored ``datetime('now')`` stamp as ISO 8601 UTC with a Z."""
    if not value:
        return None
    text = str(value).strip().replace(" ", "T")
    if text.endswith("Z"):
        return text
    if re.search(r"[+-]\d{2}:?\d{2}$", text):
        return text
    if len(text) == 10:
        text += "T00:00:00"
    return text + "Z"


def _weekdays_between(first: dt.date | None, last: dt.date | None) -> int | None:
    """Weekdays strictly between two dates. Holidays are not modelled."""
    if first is None or last is None:
        return None
    count, day = 0, first + dt.timedelta(days=1)
    while day < last:
        if day.weekday() < 5:
            count += 1
        day += dt.timedelta(days=1)
    return count


def _snap(period_end: str) -> tuple[int, int]:
    """(month, year) the period ends nearest: J&J's 3 January 2021 year is 2020."""
    return financials_view._nearest_month_end(dt.date.fromisoformat(period_end[:10]))


def _month_end(year: int, month: int) -> dt.date:
    first_next = dt.date(year + (month == 12), month % 12 + 1, 1)
    return first_next - dt.timedelta(days=1)


def _div(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _short_date(day: dt.date | None) -> str | None:
    return f"{day.day} {day.strftime('%b')} {day.year}" if day else None


# --- the amount type: a value and the unit it was filed in -----------------------------
def _amt(row):
    return (row["value"], row["unit"]) if row and row["value"] is not None else None


def _to_usd(value, unit, rates):
    """Raw units of ``unit`` to raw US dollars, or None when no rate is stored."""
    if value is None or not unit:
        return None
    rate = rates.get(unit)
    return value * rate if rate is not None else None


def _combine(parts, rates):
    """Sum of signed amounts. One unit: summed in it. Mixed: converted to USD first."""
    if any(p is None or p[0] is None for p in parts):
        return None
    units = {p[1] for p in parts}
    if len(units) == 1:
        return (sum(p[0] for p in parts), parts[0][1])
    usd = [_to_usd(p[0], p[1], rates) for p in parts]
    if any(v is None for v in usd):
        return None
    return (sum(usd), "USD")


def _usd_m(amount, rates):
    if amount is None:
        return None
    usd = _to_usd(amount[0], amount[1], rates)
    return usd / 1e6 if usd is not None else None


def _growth(latest, base, rates):
    """latest / base − 1 on amounts, in the filing unit when both share it. None when the
    base is not positive or an end is missing."""
    if latest is None or base is None:
        return None
    if latest[1] == base[1]:
        a, b = latest[0], base[0]
    else:
        a, b = _to_usd(latest[0], latest[1], rates), _to_usd(base[0], base[1], rates)
    if a is None or b is None or b <= 0:
        return None
    return a / b - 1.0


class _Rec:
    """The two maps every record accumulates while it is built."""

    def __init__(self):
        self.na: dict = {}
        self.flags: list = []

    def reason(self, path: str, code: str) -> None:
        self.na.setdefault(path, code)

    def flag(self, code: str, field, severity: str, **params) -> None:
        self.flags.append({"code": code, "field": field, "severity": severity,
                           "params": params})


# --- the universe-wide reads, one pass each ----------------------------------------------
class _Universe:
    def __init__(self, conn, db_path, today: dt.date):
        self.conn, self.db_path, self.today = conn, db_path, today
        self.errors: list = []
        self.companies = [dict(r) for r in conn.execute(
            """SELECT id, ticker, name, primary_exchange, country, reporting_currency,
                      us_adr_ticker, is_sec_filer, is_foreign_private_issuer
                 FROM companies ORDER BY ticker""")]
        self.tickers = {c["ticker"] for c in self.companies}
        raw_rates = fx.latest_usd_rates(db_path)
        self.fx_as_of = raw_rates.get("as_of")
        self.rates = {k: v for k, v in raw_rates.items() if k != "as_of" and v}
        self.rates["USD"] = 1.0

        self.homes = self._guard("engines", lambda: engines.home(db_path), {})
        self.lead = self._guard("lead_stage", lambda: engines._lead_stage(
            conn, [c["ticker"] for c in self.companies]), {})
        self.screen = self._guard("screen", lambda: {
            r["ticker"]: r for r in screen.build_screen(db_path)}, {})
        trend = self._guard("comps_trend", lambda: comps.comps_trend(db_path),
                            {"labels": [], "companies": []})
        self.trend_labels = trend.get("labels") or []
        self.trend = {r["ticker"]: r for r in trend.get("companies") or []}
        self.pipeline = self._guard("pipeline", lambda: {
            r["ticker"]: r for r in pipeline.build_pipeline(db_path)}, {})

        self.adr = {r["ticker"]: r["ordinary_per_adr"] for r in conn.execute(
            "SELECT ticker, ordinary_per_adr FROM adr_ratios") if r["ordinary_per_adr"]}
        self.themes: dict = {}
        for r in conn.execute("SELECT company_id, theme FROM company_themes"):
            self.themes.setdefault(r["company_id"], []).append(r["theme"])
        self._financials()
        self._prices()
        self._snapshots()
        self._consensus()
        self._filings()
        self._catalysts()
        self._products()
        self._trials()
        self._insights()
        self._run()
        self.modelled = {r["ticker"] for r in conn.execute(
            """SELECT DISTINCT c.ticker FROM companies c
                 JOIN assets a ON a.owner_company_id = c.id
                 JOIN assumptions s ON s.asset_id = a.id""")}

    def _guard(self, stage, fn, default):
        try:
            return fn()
        except Exception as exc:          # a global read failing leaves its fields null
            self.errors.append({"ticker": None, "stage": stage,
                                "message": f"{type(exc).__name__}: {exc}"})
            return default

    def _financials(self):
        """Every row the records read, keyed company → metric → kind."""
        metrics = _MONEY_METRICS + _OTHER_METRICS
        marks = ",".join("?" * len(metrics))
        self.fin: dict = {}
        for r in self.conn.execute(
                f"""SELECT company_id, metric, period_type, period_end, value, unit,
                           fiscal_year, fiscal_period, source
                      FROM financials
                     WHERE value IS NOT NULL AND period_end IS NOT NULL
                       AND metric IN ({marks})
                     ORDER BY period_end""", metrics):
            by_kind = self.fin.setdefault(r["company_id"], {}).setdefault(
                r["metric"], {"FY": {}, "interim": [], "instant": []})
            row = {"end": r["period_end"][:10], "value": r["value"], "unit": r["unit"],
                   "type": r["period_type"], "fp": r["fiscal_period"] or "",
                   "source": r["source"]}
            if r["period_type"] == "FY":
                _, year = _snap(row["end"])
                held = by_kind["FY"].get(year)
                if held is None or row["end"] >= held["end"]:
                    by_kind["FY"][year] = row
            elif r["period_type"] == "instant":
                by_kind["instant"].append(row)
            elif r["period_type"] in ("Q", "YTD"):
                by_kind["interim"].append(row)

    def _prices(self):
        start = (self.today - dt.timedelta(days=PRICE_WINDOW_DAYS)).isoformat()
        self.prices: dict = {}
        for r in self.conn.execute(
                """SELECT company_id, substr(as_of, 1, 10) AS day, close, high, low
                     FROM prices
                    WHERE interval = '1d' AND close IS NOT NULL
                      AND substr(as_of, 1, 10) >= ? AND substr(as_of, 1, 10) <= ?
                    ORDER BY company_id, as_of""", (start, self.today.isoformat())):
            self.prices.setdefault(r["company_id"], []).append(
                (r["day"], r["close"], r["high"], r["low"]))
        newest = [rows[-1][0] for rows in self.prices.values() if rows]
        self.newest_price = max(newest) if newest else None

    def _snapshots(self):
        """Lineage per (ticker, source): the newest live and newest error capture, one
        GROUP BY. Then the price currency and the filed taxonomy, one pass each."""
        marks = ",".join("?" * len(LINEAGE_SOURCES))
        self.lineage: dict = {}
        for r in self.conn.execute(
                f"""SELECT entity_key, source, json_extract(payload, '$.fetch_kind') AS kind,
                           MAX(captured_at) AS at
                      FROM snapshots
                     WHERE entity_type = 'company' AND source IN ({marks})
                     GROUP BY entity_key, source, kind""", LINEAGE_SOURCES):
            if r["kind"] in ("live", "error"):
                self.lineage.setdefault(r["entity_key"], {}).setdefault(
                    r["source"], {})[r["kind"]] = _iso_ts(r["at"])
        self.price_currency = {r["entity_key"]: r["cur"] for r in self.conn.execute(
            """SELECT entity_key, json_extract(payload, '$.currency') AS cur,
                      MAX(captured_at) AS at
                 FROM snapshots
                WHERE source = 'prices' AND entity_type = 'company'
                  AND json_extract(payload, '$.currency') IS NOT NULL
                GROUP BY entity_key""")}
        self.taxonomy = {r["entity_key"]: r["tax"] for r in self.conn.execute(
            """SELECT entity_key, json_extract(payload, '$.taxonomy') AS tax,
                      MAX(captured_at) AS at
                 FROM snapshots
                WHERE source = 'financials' AND entity_type = 'company'
                  AND json_extract(payload, '$.taxonomy') IS NOT NULL
                GROUP BY entity_key""")}

    def _consensus(self):
        self.consensus: dict = {}
        first = None
        for r in self.conn.execute(
                """SELECT company_id, metric, period, value, low, high, currency, source,
                          as_of, note, fx_basis
                     FROM consensus_estimates ORDER BY as_of, id"""):
            row = dict(r)
            self.consensus.setdefault(r["company_id"], {}).setdefault(
                (r["metric"], r["period"], r["source"] or ""), []).append(row)
            if r["source"] == "nasdaq" and (first is None or r["as_of"] < first):
                first = r["as_of"]
        self.consensus_history_starts = _iso_date(first)

    def _filings(self):
        self.annual_form: dict = {}
        self.filings: dict = {}
        for r in self.conn.execute(
                """SELECT company_id, form_type, filed_date, title, url FROM filings
                    ORDER BY filed_date DESC, id DESC"""):
            cid = r["company_id"]
            if r["form_type"] in ANNUAL_FORMS and cid not in self.annual_form:
                self.annual_form[cid] = r["form_type"]
            listed = self.filings.setdefault(cid, [])
            if len(listed) < 5:
                listed.append({"form": r["form_type"], "filed_date": _iso_date(r["filed_date"]),
                               "title": r["title"], "url": r["url"]})

    def _catalysts(self):
        """The next five pending catalysts a company. The registry gives about a quarter of
        readouts as a month and no day ("2026-11"); those keep their month as "YYYY-MM",
        which the panel prints "Nov 2026", where a day parse would leave a dash. A month
        still running is ahead, not past."""
        self.catalysts: dict = {}
        for r in self.conn.execute(
                """SELECT company_id, catalyst_type, expected_date, date_confidence, title,
                          is_curated, source_url FROM catalysts
                    WHERE status = 'pending' AND expected_date IS NOT NULL
                      AND (substr(expected_date, 1, 10) >= ?
                           OR (length(expected_date) = 7 AND expected_date >= ?))
                    ORDER BY expected_date, id""",
                (self.today.isoformat(), self.today.isoformat()[:7])):
            listed = self.catalysts.setdefault(r["company_id"], [])
            if len(listed) < 5:
                listed.append({"type": r["catalyst_type"],
                               "expected_date": _catalyst_date(r["expected_date"]),
                               "date_confidence": r["date_confidence"], "title": r["title"],
                               "is_curated": bool(r["is_curated"]),
                               "source_url": r["source_url"]})

    def _products(self):
        """{company: {fiscal_year: [(name, value, unit)]}} of full-year product revenue."""
        self.products: dict = {}
        for r in self.conn.execute(
                """SELECT a.owner_company_id AS cid,
                          COALESCE(a.brand_name, a.generic_name, a.internal_code) AS name,
                          ar.fiscal_year, ar.value, ar.unit
                     FROM asset_revenue ar JOIN assets a ON a.id = ar.asset_id
                    WHERE ar.period = 'FY' AND ar.value IS NOT NULL"""):
            self.products.setdefault(r["cid"], {}).setdefault(r["fiscal_year"], []).append(
                (r["name"], r["value"], r["unit"]))

    def _trials(self):
        """Lead-sponsored trials mapped to an asset, counted per asset."""
        self.trials: dict = {}
        # The trials table holds active studies only (completed ones live elsewhere), so
        # every row counts; the asset must be the sponsor's own.
        for r in self.conn.execute(
                """SELECT t.sponsor_company_id AS cid, t.asset_id, COUNT(*) AS n
                     FROM trials t JOIN assets a ON a.id = t.asset_id
                    WHERE t.sponsor_company_id IS NOT NULL
                      AND a.owner_company_id = t.sponsor_company_id
                    GROUP BY t.sponsor_company_id, t.asset_id"""):
            self.trials.setdefault(r["cid"], []).append(r["n"])

    def _insights(self):
        self.insights: dict = {}
        for r in self.conn.execute(
                """SELECT company_id, generated_at, model, body FROM insights
                    WHERE company_id IS NOT NULL ORDER BY generated_at, id"""):
            self.insights[r["company_id"]] = {
                "generated_at": _iso_ts(r["generated_at"]), "model": r["model"],
                "excerpt": (r["body"] or "")[:400]}

    def _run(self):
        row = self.conn.execute(
            """SELECT id, started_at, finished_at, status, detail FROM refresh_runs
                ORDER BY id DESC LIMIT 1""").fetchone()
        self.run = None
        self.failed_sources: list = []
        if row is None:
            return
        other = set()
        try:
            detail = json.loads(row["detail"]) if row["detail"] else {}
        except (TypeError, ValueError):
            detail = {}
        for source in (detail.get("sources") or []) if isinstance(detail, dict) else []:
            name = source.get("source")
            for error in source.get("errors") or []:
                if name not in VIEW_SOURCES:
                    other.add(name)
                    continue
                ticker, message = None, str(error)
                head, sep, rest = message.partition(":")
                if sep and head.strip().upper() in self.tickers:
                    ticker, message = head.strip().upper(), rest.strip()
                    prefix = f"{name}:"
                    if message.startswith(prefix):
                        message = message[len(prefix):].strip()
                self.failed_sources.append({"source": name, "ticker": ticker,
                                            "message": message})
        self.run = {"id": row["id"], "started_at": _iso_ts(row["started_at"]),
                    "finished_at": _iso_ts(row["finished_at"]), "status": row["status"],
                    "failed_sources": self.failed_sources,
                    "other_failures": sorted(n for n in other if n)}

    # Units every money row in the universe is filed in, for the fx block.
    def row_units(self) -> set:
        units = set()
        for metrics in self.fin.values():
            for metric, by_kind in metrics.items():
                if metric not in _MONEY_METRICS:
                    continue
                for row in list(by_kind["FY"].values()) + by_kind["instant"]:
                    if row["unit"] and _CURRENCY_CODE.match(row["unit"]):
                        units.add(row["unit"])
        return units


# --- the per-company record ------------------------------------------------------------
def _fy(fin, metric, year):
    return ((fin.get(metric) or {}).get("FY") or {}).get(year)


def _latest_instant(fin, metric):
    rows = (fin.get(metric) or {}).get("instant") or []
    return rows[-1] if rows else None


def _fy0(fin):
    """(year, period_end) of the latest full fiscal year over revenue, net income and
    operating cash flow, or None. A company whose revenue stopped (SLDB after 2022) is
    read at its latest filed year with revenue not filed, not at its last revenue year."""
    years = [y for m in _ANCHOR_METRICS for y in ((fin.get(m) or {}).get("FY") or {})]
    if not years:
        return None
    year = max(years)
    for metric in _ANCHOR_METRICS:
        row = _fy(fin, metric, year)
        if row:
            return year, row["end"]
    return None


def _operating(fin, year, rates):
    """(amount, basis) of operating income: filed, else revenue less cost of sales, R&D and
    SG&A when all four are filed (marked derived), else (None, None)."""
    row = _fy(fin, "OperatingIncomeLoss", year)
    if row:
        return _amt(row), "reported"
    parts = [_amt(_fy(fin, m, year)) for m in (
        "Revenues", "CostOfRevenue", "ResearchAndDevelopmentExpense",
        "SellingGeneralAndAdministrative")]
    if any(p is None for p in parts):
        return None, None
    revenue, *costs = parts
    return _combine([revenue] + [(-abs(v), u) for v, u in costs], rates), "derived"


def _dna(fin, year, rates):
    row = _fy(fin, "DepreciationAndAmortisation", year)
    if row:
        return (abs(row["value"]), row["unit"])
    dep, amort = _fy(fin, "Depreciation", year), _fy(fin, "AmortisationOfIntangibles", year)
    if dep and amort:
        return _combine([(abs(dep["value"]), dep["unit"]),
                         (abs(amort["value"]), amort["unit"])], rates)
    return None


def _ebitda(operating, dna, rates):
    if operating is None or dna is None:
        return None
    return _combine([operating, dna], rates)


def _abs_amt(row):
    return (abs(row["value"]), row["unit"]) if row and row["value"] is not None else None


def _ltm(fin, metric, fy0_year, fy0_end):
    """Trailing twelve months: the full year, plus the current cumulative year to date,
    less the same span a year earlier. The cumulative row is the one whose months match
    the months elapsed, never the discrete quarter on the same date."""
    by_kind = fin.get(metric) or {}
    full = (by_kind.get("FY") or {}).get(fy0_year)
    later = [r for r in by_kind.get("interim") or [] if r["end"] > fy0_end]
    if not full or not later:
        return None
    last_end = max(r["end"] for r in later)
    months = round((dt.date.fromisoformat(last_end)
                    - dt.date.fromisoformat(fy0_end)).days / 30.44)
    if months not in (3, 6, 9):
        return None
    tag = f"{months}M"
    current = next((r for r in later if r["end"] == last_end and r["fp"] == tag), None)
    if current is None:
        return None
    target = dt.date.fromisoformat(last_end) - dt.timedelta(days=365)
    prior = next((r for r in by_kind.get("interim") or []
                  if r["fp"] == tag and abs((dt.date.fromisoformat(r["end"]) - target).days) <= 20),
                 None)
    if prior is None or not (full["unit"] == current["unit"] == prior["unit"]):
        return None
    return {"value": full["value"] + current["value"] - prior["value"], "unit": full["unit"],
            "end": last_end}


def _spark(conn, company_id: int, today: dt.date, days: int = 90,
           max_points: int = 60) -> list:
    """Daily closes after ``today − days`` up to ``today``, downsampled evenly so the first
    and the last close are always kept and the line ends on the latest price."""
    start = (today - dt.timedelta(days=days)).isoformat()
    closes = [r["close"] for r in conn.execute(
        """SELECT close FROM prices
            WHERE company_id = ? AND interval = '1d' AND close IS NOT NULL
              AND substr(as_of, 1, 10) > ? AND substr(as_of, 1, 10) <= ?
            ORDER BY as_of""", (company_id, start, today.isoformat()))]
    # Four decimals: a sparkline is drawn, not read, and the stored closes carry the
    # float32 noise of the quote feed (166.14999389648438), which is most of their bytes.
    closes = [round(c, SPARK_DECIMALS) for c in closes]
    n = len(closes)
    if n <= max_points or max_points < 2:
        return closes
    return [closes[int(math.floor(i * (n - 1) / (max_points - 1) + 0.5))]
            for i in range(max_points)]


def _diluted_basis(conn, company_id: int):
    """Which count ``forecast_view._diluted_shares`` used, in words: (shares_basis, the
    phrase the market cap basis text uses, route). The route is ``weighted``, ``cover``
    (the helper fell back to the cover-page count, so it is not a second measurement) or
    ``implied`` (net income over diluted EPS)."""
    for metric in ("WeightedAverageDilutedShares", "SharesOutstanding"):
        row = conn.execute(
            """SELECT value, period_type, period_end FROM financials
                WHERE company_id = ? AND metric = ? AND period_type IN ('FY', 'instant')
                ORDER BY fiscal_year DESC, period_end DESC LIMIT 1""",
            (company_id, metric)).fetchone()
        if row and row["value"]:
            if metric == "SharesOutstanding":
                return (f"shares outstanding at {row['period_end'][:10]}",
                        f"shares outstanding at {row['period_end'][:10]}, per US-listed share",
                        "cover")
            if row["period_type"] == "FY":
                year = _snap(row["period_end"])[1]
                return (f"FY{year} weighted average diluted",
                        f"FY{year} weighted diluted shares, per US-listed share", "weighted")
            return (f"weighted average diluted at {row['period_end'][:10]}",
                    "weighted diluted shares, per US-listed share", "weighted")
    row = conn.execute(
        """SELECT period_end FROM financials WHERE company_id = ?
            AND metric = 'NetIncomeLoss' AND period_type = 'FY'
            ORDER BY fiscal_year DESC LIMIT 1""", (company_id,)).fetchone()
    year = _snap(row["period_end"])[1] if row else None
    label = f"FY{year} " if year else ""
    return (f"{label}weighted average diluted, implied by net income over diluted EPS",
            f"{label}weighted diluted shares implied by net income over diluted EPS, "
            "per US-listed share", "implied")


def _vol_1y(rows, price_as_of: str) -> float | None:
    start = (dt.date.fromisoformat(price_as_of) - dt.timedelta(days=365)).isoformat()
    closes = [r[1] for r in rows if start < r[0] <= price_as_of and r[1] and r[1] > 0]
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    if len(returns) <= VOL_MIN_RETURNS:
        return None
    return statistics.stdev(returns) * math.sqrt(252)


def _scope(metric: str, note: str | None) -> str:
    """Whether a revenue guide covers total revenue or product sales only."""
    if metric == "ProductSales":
        return "product"
    text = note or ""
    clause = _SCOPE.search(text)
    text = clause.group(1) if clause else text
    if _NOT_TOTAL.search(text):
        return "product"
    if _TOTAL.search(text):
        return "total"
    if _PRODUCT.search(text):
        return "product"
    return "total"


def _estimate_n(note) -> int | None:
    match = _ESTIMATES.search(note or "")
    return int(match.group(1)) if match else None


def _record(u: _Universe, co: dict, stage: dict) -> tuple:
    """(record, whether a modelled company's cached model reads were missing)."""
    conn, rates, today = u.conn, u.rates, u.today
    t, cid = co["ticker"], co["id"]
    rec = _Rec()
    fin = u.fin.get(cid, {})
    reporting = co["reporting_currency"] or "USD"

    # --- identity -------------------------------------------------------------------
    stage["name"] = "identity"
    annual_form = u.annual_form.get(cid)
    country = co["country"]
    if not country:
        region = None
        rec.reason("region", "domicile_unknown")
    elif country == "US":
        # A 20-F filer is by definition not a US company, so a stored US is known wrong.
        region = None if annual_form in ("20-F", "40-F") else "US"
        if region is None:
            rec.reason("region", "domicile_unknown")
    else:
        region = "Europe" if country in EUROPE else "Other"
    exchange = co["primary_exchange"]
    if exchange and exchange.upper() == "NASDAQ":
        exchange = "Nasdaq"
    listing = {
        "home_exchange": exchange,
        "us_line": co["us_adr_ticker"] or None,
        "adr_ratio": u.adr.get(t),
        "otc": bool((co["primary_exchange"] or "").upper() == "OTC"
                    or (co["us_adr_ticker"] and not co["is_sec_filer"])),
    }
    taxonomy = u.taxonomy.get(t)
    if taxonomy in ("us-gaap", "ifrs-full"):
        standard = "US GAAP" if taxonomy == "us-gaap" else "IFRS"
        standard_source = "filed facts"
    elif not co["is_sec_filer"] or co["is_foreign_private_issuer"]:
        standard, standard_source = "IFRS", "company record"
    elif annual_form == "10-K":
        standard, standard_source = "US GAAP", "form"
    else:
        standard, standard_source = None, None
        rec.reason("filer.standard", "standard_not_recorded")
    kind = "not an SEC filer" if not co["is_sec_filer"] else _FILER_KIND.get(annual_form)
    filer = {"kind": kind, "annual_form": annual_form, "standard": standard,
             "standard_source": standard_source, "is_sec_filer": bool(co["is_sec_filer"]),
             "is_fpi_flag": bool(co["is_foreign_private_issuer"])}

    fy0 = _fy0(fin)
    fy0_year, fy0_end = fy0 if fy0 else (None, None)
    anchor = (_fy(fin, "Revenues", fy0_year) or _fy(fin, "CashFlowOperating", fy0_year)
              if fy0 else None)
    row_currency = anchor["unit"] if anchor else None
    fye_month = _snap(fy0_end)[0] if fy0_end else None
    areas_all = notecontext._pipeline_areas(conn, cid)
    areas = dict(sorted(((a, n) for a, n in areas_all.items() if a != "Healthy volunteers"),
                        key=lambda kv: (-kv[1], kv[0]))[:5])

    # --- market -----------------------------------------------------------------------
    stage["name"] = "market"
    px = u.prices.get(cid, [])
    price = px[-1][1] if px else None
    price_as_of = px[-1][0] if px else None
    prev_close = px[-2][1] if len(px) > 1 else None
    market: dict = {"price": price, "price_currency": u.price_currency.get(t),
                    "price_as_of": price_as_of, "prev_close": prev_close,
                    "change_1d": (price / prev_close - 1.0) if price and prev_close else None,
                    "quote_fetched_at": (u.lineage.get(t, {}).get("prices") or {}).get("live"),
                    "ttm_change": (u.screen.get(t) or {}).get("ttm_price_change")}
    if price is None:
        for key in ("price", "price_as_of", "prev_close", "change_1d", "range_52w"):
            rec.reason(f"market.{key}", "no_prices")
    elif prev_close is None:
        rec.reason("market.prev_close", "insufficient_history")
        rec.reason("market.change_1d", "insufficient_history")
    if market["price_currency"] is None:
        rec.reason("market.price_currency", "no_prices" if price is None else "no_free_data")
    if market["quote_fetched_at"] is None:
        rec.reason("market.quote_fetched_at", "no_prices" if price is None else "no_free_data")
    if market["ttm_change"] is None:
        rec.reason("market.ttm_change", "no_prices" if price is None else "insufficient_history")
    if price is not None:
        start = (dt.date.fromisoformat(price_as_of) - dt.timedelta(days=365)).isoformat()
        window = [r for r in px if start < r[0] <= price_as_of]
        lows = [r[3] if r[3] is not None else r[1] for r in window]
        highs = [r[2] if r[2] is not None else r[1] for r in window]
        market["range_52w"] = {"low": min(lows), "high": max(highs)} if window else None
    else:
        market["range_52w"] = None
    market["spark_90d"] = _spark(conn, cid, today, SPARK_DAYS, SPARK_POINTS)

    ratio = u.adr.get(t)
    cover = _latest_instant(fin, "SharesOutstanding")
    shares_cover_m = cover["value"] / (ratio or 1.0) / 1e6 if cover and cover["value"] else None
    shares_cover_as_of = cover["end"] if shares_cover_m else None
    divisor = forecast_view._diluted_shares(conn, cid)
    shares_diluted_m = (divisor * rates[reporting] / 1e6
                        if divisor and reporting in rates else None)
    shares_basis, diluted_phrase, diluted_route = (_diluted_basis(conn, cid)
                                                   if shares_diluted_m else (None, None, None))
    market.update({"shares_cover_m": shares_cover_m, "shares_cover_as_of": shares_cover_as_of,
                   "shares_diluted_m": shares_diluted_m, "shares_basis": shares_basis})
    if shares_cover_m is None:
        rec.reason("market.shares_cover_m", "no_shares")
        rec.reason("market.shares_cover_as_of", "no_shares")
    if shares_diluted_m is None:
        code = "no_rate" if divisor and reporting not in rates else "no_shares"
        rec.reason("market.shares_diluted_m", code)
        rec.reason("market.shares_basis", code)

    exception = COVER_COUNT_EXCEPTIONS.get(t)
    cover_age = None
    if shares_cover_as_of and price_as_of:
        cover_age = abs((dt.date.fromisoformat(price_as_of)
                         - dt.date.fromisoformat(shares_cover_as_of)).days)
    cover_current = (shares_cover_m is not None and cover_age is not None
                     and cover_age <= COVER_COUNT_MAX_AGE_DAYS)
    mcap = basis = basis_text = None
    alt_shares = alt_basis = disagreement_reason = None
    if price is None:
        for key in ("market_cap_usd_m", "market_cap_basis", "market_cap_basis_text",
                    "market_cap_shares_m"):
            rec.reason(f"market.{key}", "no_prices")
    elif cover_current and not exception:
        mcap = price * shares_cover_m
        basis = "shares_outstanding"
        basis_text = f"Shares outstanding at the {shares_cover_as_of} cover date"
        # A diluted count the helper took from the cover page is the same count, not a
        # second measurement, so there is no alternative to compare with.
        alt_shares = shares_diluted_m if diluted_route != "cover" else None
        alt_basis = "diluted_weighted"
        disagreement_reason = "it is the more recent count"
    elif shares_diluted_m:
        mcap = price * shares_diluted_m
        basis = "diluted_weighted"
        basis_text = diluted_phrase[0].upper() + diluted_phrase[1:]
        alt_shares = shares_cover_m if diluted_route != "cover" else None
        alt_basis = "shares_outstanding"
        if shares_cover_m is None:
            rec.flag("market_cap_diluted_route", "market.market_cap_usd_m", "info")
        elif exception:
            basis_text += f". {exception}"
            disagreement_reason = exception
            rec.flag("cover_count_exception", "market.market_cap_usd_m", "info",
                     reason=exception)
        else:
            basis_text += f"; the cover count is from {shares_cover_as_of}"
            disagreement_reason = f"the cover count is from {shares_cover_as_of}"
            rec.flag("stale_shares", "market.market_cap_usd_m", "amber",
                     as_of=shares_cover_as_of, days=cover_age)
    else:
        for key in ("market_cap_usd_m", "market_cap_basis", "market_cap_basis_text",
                    "market_cap_shares_m"):
            rec.reason(f"market.{key}", "no_shares")
    alt = disagreement = None
    if mcap is not None and alt_shares:
        primary_shares = mcap / price
        scale = max(primary_shares, alt_shares) / min(primary_shares, alt_shares)
        if scale <= SHARE_SCALE_LIMIT:
            alt = price * alt_shares
            disagreement = abs(mcap / alt - 1.0)
        else:
            rec.reason("market.market_cap_alt_usd_m", "share_count_scale")
            rec.reason("market.market_cap_disagreement", "share_count_scale")
    elif mcap is not None:
        rec.reason("market.market_cap_alt_usd_m", "no_shares")
        rec.reason("market.market_cap_disagreement", "no_shares")
    else:
        code = "no_prices" if price is None else "no_shares"
        rec.reason("market.market_cap_alt_usd_m", code)
        rec.reason("market.market_cap_disagreement", code)
    if disagreement is not None and disagreement > DISAGREEMENT_FLAG:
        rec.flag("market_cap_disagreement", "market.market_cap_usd_m", "amber",
                 primary=mcap, alt=alt, pct=disagreement, primary_basis=basis,
                 alt_basis=alt_basis, reason=disagreement_reason)
    b, b_basis = beta_module.compute(conn, t)
    market.update({"market_cap_usd_m": mcap, "market_cap_basis": basis,
                   "market_cap_basis_text": basis_text,
                   "market_cap_shares_m": (mcap / price) if mcap is not None else None,
                   "market_cap_alt_usd_m": alt, "market_cap_disagreement": disagreement,
                   "beta": b, "beta_basis": b_basis,
                   "vol_1y": _vol_1y(px, price_as_of) if price_as_of else None})
    if b is None:
        rec.reason("market.beta", "insufficient_history")
        rec.reason("market.beta_basis", "insufficient_history")
    if market["vol_1y"] is None:
        rec.reason("market.vol_1y", "no_prices" if price is None else "insufficient_history")

    # --- enterprise value ---------------------------------------------------------------
    stage["name"] = "ev"
    cf = cashflow.build_cashflow(u.db_path, t) or {}
    inputs = cf.get("inputs") or {}
    # cashflow's currency is the revenue or cash flow row's unit, and an empty dict when
    # neither is filed, which is no currency.
    cf_currency = cf.get("currency") if isinstance(cf.get("currency"), str) else None
    # Debt and cash are shown in the unit cashflow netted them in, else the cash row's own.
    cash_row = _latest_instant(fin, "CashAndEquivalents")
    cf_currency = cf_currency or (cash_row["unit"] if cash_row else None)
    net_debt_usd = cf.get("net_debt_usd")
    ev: dict = {
        "net_debt_usd_m": net_debt_usd / 1e6 if net_debt_usd is not None else None,
        "total_debt_usd_m": _usd_m((inputs.get("total_debt"), cf_currency), rates)
        if inputs.get("total_debt") is not None and cf_currency else None,
        "cash_usd_m": _usd_m((inputs.get("cash"), cf_currency), rates)
        if inputs.get("cash") is not None and cf_currency else None,
        "cash_lines": inputs.get("cash_lines") or [],
        "balance_sheet_as_of": _iso_date(inputs.get("balance_sheet_as_of")),
        "debt_as_of": _iso_date(inputs.get("debt_as_of")),
        "debt_basis": inputs.get("debt_basis"),
    }
    no_cash = inputs.get("cash") is None
    no_debt = inputs.get("total_debt") is None
    unconverted = cf_currency is not None and cf_currency not in rates
    if ev["cash_usd_m"] is None:
        rec.reason("ev.cash_usd_m", "no_rate" if unconverted and not no_cash else "not_filed")
    if ev["total_debt_usd_m"] is None:
        rec.reason("ev.total_debt_usd_m",
                   "no_rate" if unconverted and not no_debt else "no_debt_line")
    if ev["net_debt_usd_m"] is None:
        nd_code = ("not_filed" if no_cash else "no_debt_line" if no_debt
                   else "no_rate" if unconverted else "no_free_data")
        rec.reason("ev.net_debt_usd_m", nd_code)
    for key, code in (("balance_sheet_as_of", "not_filed"), ("debt_as_of", "no_debt_line"),
                      ("debt_basis", "not_filed" if no_cash else "no_debt_line")):
        if ev[key] is None:
            rec.reason(f"ev.{key}", code)
    if mcap is not None and ev["net_debt_usd_m"] is not None:
        ev["ev_usd_m"] = mcap + ev["net_debt_usd_m"]
    else:
        # Debt is never assumed to be nil: no dated debt line, no enterprise value.
        ev["ev_usd_m"] = None
        rec.reason("ev.ev_usd_m",
                   rec.na.get("market.market_cap_usd_m", "no_shares") if mcap is None
                   else rec.na.get("ev.net_debt_usd_m", "no_debt_line"))
    claims = other_claims.for_company(conn, t)
    lines = []
    for line in claims.get("lines") or []:
        unit = line.get("unit") or reporting
        value = line["value"] * line["sign"] if line.get("value") is not None else None
        lines.append({"label": line.get("label") or line.get("item"),
                      "value_usd_m": (value * rates[unit]
                                      if value is not None and unit in rates else None),
                      "as_of": _iso_date(line.get("as_of")), "basis": line.get("basis")})
    ev["other_claims_lines"] = lines
    if not lines:
        ev["other_claims_usd_m"] = None
        rec.reason("ev.other_claims_usd_m", "none_on_file")
    elif any(line["value_usd_m"] is None for line in lines):
        ev["other_claims_usd_m"] = None
        rec.reason("ev.other_claims_usd_m", "no_rate")
        rec.reason("ev.other_claims_lines", "no_rate")
    else:
        ev["other_claims_usd_m"] = sum(line["value_usd_m"] for line in lines)
    if any(line["as_of"] is None or line["basis"] is None for line in lines):
        rec.reason("ev.other_claims_lines", "no_free_data")

    # --- periods ------------------------------------------------------------------------
    stage["name"] = "periods"
    periods: dict = {}
    fy0_amounts: dict = {}
    fym1_amounts: dict = {}

    def money(path, row, missing="not_filed"):
        if row is None or row["value"] is None:
            rec.reason(path, missing)
            return None
        value = _usd_m(_amt(row), rates)
        if value is None:
            rec.reason(path, "no_rate")
        return value

    def amount_usd(path, amount, missing="not_filed"):
        if amount is None:
            rec.reason(path, missing)
            return None
        value = _usd_m(amount, rates)
        if value is None:
            rec.reason(path, "no_rate")
        return value

    if fy0 is None:
        for key in ("FY0", "FYm1", "FYm3", "LTM"):
            periods[key] = None
            rec.reason(f"periods.{key}", "not_filed")
    else:
        p = "periods.FY0"
        revenue = _amt(_fy(fin, "Revenues", fy0_year))
        gross_row = _fy(fin, "GrossProfit", fy0_year)
        cogs = _fy(fin, "CostOfRevenue", fy0_year)
        if gross_row:
            gross, gross_basis = _amt(gross_row), "GrossProfit"
        elif revenue and cogs:
            gross = _combine([revenue, (-abs(cogs["value"]), cogs["unit"])], rates)
            gross_basis = "Revenues less CostOfRevenue"
        else:
            gross, gross_basis = None, None
            rec.reason(f"{p}.gross_basis", "not_filed")
        operating, op_basis = _operating(fin, fy0_year, rates)
        if op_basis is None:
            rec.reason(f"{p}.operating_income_basis", "not_filed")
        dna = _dna(fin, fy0_year, rates)
        ebitda = _ebitda(operating, dna, rates)
        attributable = _fy(fin, "NetIncomeAttributableToParent", fy0_year)
        net_row = attributable or _fy(fin, "NetIncomeLoss", fy0_year)
        cfo, capex = _fy(fin, "CashFlowOperating", fy0_year), _fy(fin, "CapitalExpenditure",
                                                                   fy0_year)
        fcf = (_combine([_amt(cfo), (-abs(capex["value"]), capex["unit"])], rates)
               if cfo and capex else None)
        tax, pretax = _fy(fin, "IncomeTaxExpense", fy0_year), _fy(fin, "IncomeBeforeTax",
                                                                  fy0_year)
        tax_rate = None
        if tax and pretax and pretax["value"] > 0 and tax["unit"] == pretax["unit"]:
            tax_rate = min(0.5, max(0.0, tax["value"] / pretax["value"]))
        else:
            rec.reason(f"{p}.tax_rate", "no_tax_rate")
        equity = _latest_instant(fin, "StockholdersEquity")
        eps = _fy(fin, "EarningsPerShareDiluted", fy0_year)
        amort = _fy(fin, "AmortisationOfIntangibles", fy0_year)
        iprd = _fy(fin, "AcquiredIprd", fy0_year)
        fy0_amounts = {"revenue": revenue, "ebitda": ebitda, "iprd": _abs_amt(iprd),
                       "eps": eps["value"] if eps else None,
                       "op_basis": op_basis}
        periods["FY0"] = {
            "label": f"FY{fy0_year}", "period_end": fy0_end, "unit": row_currency,
            "revenue_usd_m": amount_usd(f"{p}.revenue_usd_m", revenue),
            "gross_profit_usd_m": amount_usd(f"{p}.gross_profit_usd_m", gross),
            "gross_basis": gross_basis,
            "operating_income_usd_m": amount_usd(f"{p}.operating_income_usd_m", operating),
            "operating_income_basis": op_basis,
            "da_usd_m": amount_usd(f"{p}.da_usd_m", dna),
            "ebitda_usd_m": amount_usd(f"{p}.ebitda_usd_m", ebitda),
            "amortisation_usd_m": amount_usd(f"{p}.amortisation_usd_m", _abs_amt(amort),
                                             "not_tagged"),
            "acquired_iprd_usd_m": amount_usd(f"{p}.acquired_iprd_usd_m", _abs_amt(iprd),
                                              "not_tagged"),
            "net_income_usd_m": money(f"{p}.net_income_usd_m", net_row),
            "net_income_basis": ("attributable to shareholders" if attributable
                                 else "as filed" if net_row else None),
            "fcf_usd_m": amount_usd(f"{p}.fcf_usd_m", fcf),
            "rd_usd_m": money(f"{p}.rd_usd_m", _fy(fin, "ResearchAndDevelopmentExpense",
                                                   fy0_year)),
            "rd_ex_iprd_usd_m": money(f"{p}.rd_ex_iprd_usd_m",
                                      _fy(fin, "ResearchLessExpensedIprd", fy0_year)),
            "tax_rate": tax_rate,
            "equity_usd_m": money(f"{p}.equity_usd_m", equity),
            "equity_as_of": equity["end"] if equity else None,
            "equity_basis": "as filed" if equity else None,
            "eps_diluted_rc": eps["value"] if eps else None,
        }
        fy = periods["FY0"]
        if fy["net_income_basis"] is None:
            rec.reason(f"{p}.net_income_basis", "not_filed")
        if equity is None:
            rec.reason(f"{p}.equity_as_of", "not_filed")
            rec.reason(f"{p}.equity_basis", "not_filed")
        if eps is None:
            rec.reason(f"{p}.eps_diluted_rc", "not_filed")
        if row_currency is None:
            rec.reason(f"{p}.unit", "not_filed")
        if standard == "IFRS" and not attributable and net_row is not None:
            rec.flag("includes_minorities", f"{p}.net_income_usd_m", "amber",
                     line="net income")
        if standard == "IFRS" and equity is not None:
            rec.flag("includes_minorities", f"{p}.equity_usd_m", "amber", line="equity")
        if op_basis == "derived":
            rec.flag("derived_operating_income", f"{p}.operating_income_usd_m", "amber")

        # The prior year, read the same way so growth compares like with like.
        y1 = fy0_year - 1
        if not any(_fy(fin, m, y1) for m in _ANCHOR_METRICS):
            periods["FYm1"] = None
            rec.reason("periods.FYm1", "one_year_only")
        else:
            p = "periods.FYm1"
            anchor1 = next(_fy(fin, m, y1) for m in _ANCHOR_METRICS if _fy(fin, m, y1))
            revenue1 = _amt(_fy(fin, "Revenues", y1))
            operating1, op_basis1 = _operating(fin, y1, rates)
            dna1 = _dna(fin, y1, rates)
            ebitda1 = _ebitda(operating1, dna1, rates)
            attributable1 = _fy(fin, "NetIncomeAttributableToParent", y1)
            eps1 = _fy(fin, "EarningsPerShareDiluted", y1)
            iprd1 = _fy(fin, "AcquiredIprd", y1)
            fym1_amounts = {"revenue": revenue1, "ebitda": ebitda1, "iprd": _abs_amt(iprd1),
                            "eps": eps1["value"] if eps1 else None, "op_basis": op_basis1}
            periods["FYm1"] = {
                "label": f"FY{y1}", "period_end": anchor1["end"],
                "revenue_usd_m": amount_usd(f"{p}.revenue_usd_m", revenue1),
                "operating_income_usd_m": amount_usd(f"{p}.operating_income_usd_m",
                                                     operating1),
                "da_usd_m": amount_usd(f"{p}.da_usd_m", dna1),
                "ebitda_usd_m": amount_usd(f"{p}.ebitda_usd_m", ebitda1),
                "amortisation_usd_m": amount_usd(
                    f"{p}.amortisation_usd_m",
                    _abs_amt(_fy(fin, "AmortisationOfIntangibles", y1)), "not_tagged"),
                "acquired_iprd_usd_m": amount_usd(f"{p}.acquired_iprd_usd_m",
                                                  _abs_amt(iprd1), "not_tagged"),
                "net_income_usd_m": money(f"{p}.net_income_usd_m",
                                          attributable1 or _fy(fin, "NetIncomeLoss", y1)),
                "eps_diluted_rc": eps1["value"] if eps1 else None,
            }
            if eps1 is None:
                rec.reason(f"{p}.eps_diluted_rc", "not_filed")
        y3 = fy0_year - 3
        revenue3 = _fy(fin, "Revenues", y3)
        if revenue3 is None:
            periods["FYm3"] = None
            rec.reason("periods.FYm3", "insufficient_history")
        else:
            periods["FYm3"] = {"label": f"FY{y3}",
                               "revenue_usd_m": money("periods.FYm3.revenue_usd_m", revenue3)}
        fy0_amounts["revenue3"] = _amt(revenue3)

        ltm_rev = _ltm(fin, "Revenues", fy0_year, fy0_end)
        ltm_ni = _ltm(fin, "NetIncomeLoss", fy0_year, fy0_end)
        if ltm_rev is None and ltm_ni is None:
            periods["LTM"] = None
            rec.reason("periods.LTM", "no_ltm_20f" if kind in ("20-F filer", "40-F filer",
                                                               "not an SEC filer")
                       else "no_ltm")
        else:
            end = (ltm_rev or ltm_ni)["end"]
            month, year = _snap(end)
            periods["LTM"] = {
                "label": f"LTM {dt.date(year, month, 1).strftime('%b')}-{year % 100:02d}",
                "period_end": end,
                "revenue_usd_m": amount_usd("periods.LTM.revenue_usd_m",
                                            (ltm_rev["value"], ltm_rev["unit"])
                                            if ltm_rev else None, "no_ltm"),
                "net_income_usd_m": amount_usd("periods.LTM.net_income_usd_m",
                                               (ltm_ni["value"], ltm_ni["unit"])
                                               if ltm_ni else None, "no_ltm"),
            }

    # Forward periods: the street's EPS, on the company's own fiscal calendar.
    stage["name"] = "consensus"
    cons = u.consensus.get(cid, {})
    nasdaq_eps = {k[1]: rows for k, rows in cons.items() if k[0] == "EPS" and k[2] == "nasdaq"}
    otc = listing["otc"]
    no_cons_code = "no_consensus_otc" if otc else "no_consensus"
    if not nasdaq_eps:
        rec.flag("no_consensus", "periods.FY1", "amber", otc=otc)
    anchor_day = dt.date.fromisoformat(price_as_of) if price_as_of else today
    month = fye_month or 12
    fy1_year = anchor_day.year if _month_end(anchor_day.year, month) >= anchor_day \
        else anchor_day.year + 1
    fy1_end = _month_end(fy1_year, month)
    forward: dict = {}
    for offset, key in enumerate(("FY1", "FY2", "FY3")):
        label = f"FY{fy1_year + offset}"
        rows = nasdaq_eps.get(label)
        if not rows:
            forward[key] = None
            continue
        last = rows[-1]
        n = _estimate_n(last["note"])
        forward[key] = {"label": label, "eps": last["value"], "eps_low": last["low"],
                        "eps_high": last["high"], "eps_n": n, "as_of": _iso_date(last["as_of"])}
        for field in ("eps", "eps_low", "eps_high", "eps_n"):
            if forward[key][field] is None:
                rec.reason(f"periods.{key}.{field}", "no_free_data")
        if n is not None and n < THIN_ESTIMATES:
            rec.flag("thin_estimates", f"periods.{key}", "amber", period=label, n=n)

    guidance = _guidance(cons, f"FY{fy1_year}", rates, row_currency)
    if forward["FY1"] is None and guidance is not None:
        forward["FY1"] = {"label": f"FY{fy1_year}", "eps": None, "eps_low": None,
                          "eps_high": None, "eps_n": None, "as_of": None}
        rec.reason("periods.FY1.eps", no_cons_code)
        rec.reason("periods.FY1.eps_low", no_cons_code)
        rec.reason("periods.FY1.eps_high", no_cons_code)
        rec.reason("periods.FY1.eps_n", no_cons_code)
        rec.reason("periods.FY1.as_of", no_cons_code)
    if forward["FY1"] is not None:
        forward["FY1"]["guidance"] = guidance["block"] if guidance else None
        if guidance is None:
            rec.reason("periods.FY1.guidance", "no_guidance")
        elif guidance["numbers_reason"]:
            rec.reason("periods.FY1.guidance", guidance["numbers_reason"])
        else:
            # A level guide states no growth and a growth guide no level: each missing
            # form is guidance that was not given.
            for field in ("value_usd_m", "low_usd_m", "high_usd_m", "growth", "growth_low",
                          "growth_high"):
                if guidance["block"][field] is None:
                    rec.reason(f"periods.FY1.guidance.{field}", "no_guidance")
            if guidance["block"]["fx_basis"] is None:
                rec.reason("periods.FY1.guidance.fx_basis", "no_free_data")
    for key in ("FY1", "FY2", "FY3"):
        periods[key] = forward[key]
        if forward[key] is None:
            rec.reason(f"periods.{key}", no_cons_code)

    fy1, fy2 = forward["FY1"], forward["FY2"]
    fy1_eps = fy1["eps"] if fy1 else None
    fy2_eps = fy2["eps"] if fy2 else None
    if fy1_eps is None:
        periods["NTM"] = None
        rec.reason("periods.NTM", no_cons_code)
    elif fy2_eps is None:
        periods["NTM"] = None
        rec.reason("periods.NTM", "no_fy2_consensus")
    else:
        weight = min(1.0, max(0.0, (fy1_end - anchor_day).days / 365.0))
        sign_change = (fy1_eps <= 0 < fy2_eps) or (fy2_eps <= 0 < fy1_eps)
        periods["NTM"] = {
            "eps": weight * fy1_eps + (1.0 - weight) * fy2_eps, "weight_fy1": weight,
            "sign_change": sign_change,
            "basis_text": (f"{fy1['label']} and {fy2['label']} consensus EPS weighted by the "
                           f"days of each in the twelve months from {anchor_day.isoformat()}"),
        }
        if sign_change:
            rec.flag("eps_sign_change", "periods.NTM", "amber", fy1=fy1_eps, fy2=fy2_eps)

    # --- growth -------------------------------------------------------------------------
    stage["name"] = "growth"
    growth: dict = {}
    fy3 = forward["FY3"]
    fy3_eps = fy3["eps"] if fy3 else None

    def set_growth(key, value, reason):
        growth[key] = value
        if value is None:
            rec.reason(f"growth.{key}", reason)

    def base_reason(latest, base):
        if fy0 is None or latest is None:
            return "not_filed"
        if base is None:
            return "one_year_only" if not periods.get("FYm1") else "not_filed"
        return "non_positive_base"

    rev0, rev1 = fy0_amounts.get("revenue"), fym1_amounts.get("revenue")
    set_growth("revenue_fy", _growth(rev0, rev1, rates), base_reason(rev0, rev1))
    rev3 = fy0_amounts.get("revenue3")
    cagr = None
    if rev0 is not None and rev3 is not None:
        ratio3 = _growth(rev0, rev3, rates)
        if ratio3 is not None and ratio3 + 1.0 >= 0:
            cagr = (ratio3 + 1.0) ** (1.0 / 3.0) - 1.0
    set_growth("revenue_cagr3", cagr,
               "not_filed" if rev0 is None else "insufficient_history" if rev3 is None
               else "non_positive_base")
    e0, e1 = fy0_amounts.get("ebitda"), fym1_amounts.get("ebitda")
    set_growth("ebitda_fy", _growth(e0, e1, rates), base_reason(e0, e1))
    if (fy0_amounts.get("op_basis") == "derived" or fym1_amounts.get("op_basis") == "derived"
            or (fy0_amounts.get("iprd") is None and fym1_amounts.get("iprd") is None)):
        # Derived operating income never subtracted the separately presented IPR&D, so
        # adding it back would count it twice (LLY's $3,008m).
        set_growth("ebitda_fy_adjusted", growth["ebitda_fy"], rec.na.get("growth.ebitda_fy"))
    else:
        adj0 = _combine([e0, fy0_amounts["iprd"]], rates) if (
            e0 is not None and fy0_amounts.get("iprd") is not None) else e0
        adj1 = _combine([e1, fym1_amounts["iprd"]], rates) if (
            e1 is not None and fym1_amounts.get("iprd") is not None) else e1
        set_growth("ebitda_fy_adjusted", _growth(adj0, adj1, rates), base_reason(adj0, adj1))
    eps0, eps1 = fy0_amounts.get("eps"), fym1_amounts.get("eps")
    eps_growth = (eps0 / eps1 - 1.0) if eps0 is not None and eps1 and eps1 > 0 else None
    if eps0 is None:
        eps_reason = "not_filed"
    elif eps1 is None:
        eps_reason = "not_filed" if periods.get("FYm1") else "one_year_only"
    else:
        eps_reason = "non_positive_base"
    set_growth("eps_fy_gaap", eps_growth, eps_reason)
    set_growth("eps_street_fy2",
               (fy2_eps / fy1_eps - 1.0) if fy1_eps and fy1_eps > 0 and fy2_eps is not None
               else None,
               no_cons_code if fy1_eps is None else
               "no_fy2_consensus" if fy2_eps is None else "non_positive_base")
    set_growth("eps_street_cagr",
               (fy3_eps / fy1_eps) ** 0.5 - 1.0
               if fy1_eps and fy1_eps > 0 and fy3_eps and fy3_eps > 0 else None,
               no_cons_code if fy1_eps is None or fy3_eps is None else "non_positive_base")
    guided = None
    if guidance is None:
        guided_reason = "no_guidance"
    elif guidance["numbers_reason"]:
        guided_reason = guidance["numbers_reason"]
    elif guidance["block"]["metric_scope"] == "product":
        guided_reason = "guidance_product_scope"
    elif guidance["block"]["fx_basis"] == "cer":
        guided_reason = "guidance_cer"
    else:
        block = guidance["block"]
        base = periods["FY0"]["revenue_usd_m"] if periods.get("FY0") else None
        if block["value_usd_m"] is not None:
            guided = (block["value_usd_m"] / base - 1.0) if base and base > 0 else None
            guided_reason = "not_filed" if base is None else "non_positive_base"
        else:
            guided = block["growth"]
            guided_reason = "no_free_data"
        if guided is not None and block["fx_basis"] is None:
            rec.flag("guidance_fx_unstated", "growth.revenue_guided_fy1", "amber")
    set_growth("revenue_guided_fy1", guided, guided_reason)

    def usd_or_none(amount):
        return _usd_m(amount, rates) if amount is not None else None

    growth["bases"] = {
        "revenue_fy": [usd_or_none(rev0), usd_or_none(rev1)],
        "revenue_cagr3": [usd_or_none(rev0), usd_or_none(rev3)],
        "ebitda_fy": [usd_or_none(e0), usd_or_none(e1)],
        "eps_fy_gaap": [eps0, eps1],
        "eps_street_fy2": [fy1_eps, fy2_eps],
        "eps_street_cagr": [fy1_eps, fy3_eps],
    }
    for key, pair in growth["bases"].items():
        if any(v is None for v in pair):
            rec.reason(f"growth.bases.{key}", rec.na.get(f"growth.{key}") or "not_filed")

    # --- street -------------------------------------------------------------------------
    stage["name"] = "street"
    target_rows = cons.get(("PriceTarget", "12M", "nasdaq")) or []
    street: dict = {"price_target": None,
                    "consensus_checked_at": (u.lineage.get(t, {}).get("consensus_nasdaq")
                                             or {}).get("live")}
    if target_rows:
        last = target_rows[-1]
        ratings = _RATINGS.search(last["note"] or "")
        street["price_target"] = {
            "value": last["value"], "low": last["low"], "high": last["high"],
            "as_of": _iso_date(last["as_of"]),
            "ratings": ({"buy": int(ratings.group(1)), "hold": int(ratings.group(2)),
                         "sell": int(ratings.group(3))} if ratings else None)}
        for field in ("value", "low", "high", "ratings"):
            if street["price_target"][field] is None:
                rec.reason(f"street.price_target.{field}", "no_free_data")
    else:
        rec.reason("street.price_target", no_cons_code)
    if street["consensus_checked_at"] is None:
        rec.reason("street.consensus_checked_at", no_cons_code)
    firsts = {}
    for key in ("FY1", "FY2"):
        f = forward[key]
        rows = nasdaq_eps.get(f["label"]) if f else None
        firsts[key] = ({"value": rows[0]["value"], "as_of": _iso_date(rows[0]["as_of"])}
                       if rows else None)
        if firsts[key] is None:
            rec.reason(f"street.eps_first.{key}", no_cons_code)
    street["eps_first"] = firsts

    # --- risk ---------------------------------------------------------------------------
    stage["name"] = "risk"
    run_row = runway._row(conn, {"id": cid, "ticker": t, "name": co["name"]}, today)
    months = run_row.get("runway_months")
    risk: dict = {"runway_months": months, "runway_basis": run_row.get("burn_basis"),
                  "burn_flattered": bool(run_row.get("burn_flattered")),
                  "cash_out": run_row.get("cash_out")}
    if months is None:
        burn = run_row.get("burn_annual")
        code = ("no_cash" if not run_row.get("available") else
                "no_cash_flow" if burn is None else
                "not_burning" if burn >= 0 else "no_free_data")
        rec.reason("risk.runway_months", code)
        rec.reason("risk.cash_out", code)
    if risk["runway_basis"] is None:
        rec.reason("risk.runway_basis", "no_cash_flow")
    if risk["burn_flattered"]:
        rec.flag("burn_flattered", "risk.runway_months", "amber")
    dispersion = None
    if fy1 and fy1["eps_high"] is not None and fy1["eps_low"] is not None and fy1_eps:
        dispersion = (fy1["eps_high"] - fy1["eps_low"]) / abs(fy1_eps)
    risk["est_dispersion"] = dispersion
    if dispersion is None:
        rec.reason("risk.est_dispersion", no_cons_code if not fy1 or fy1_eps is None
                   else "no_free_data")
    target = street["price_target"]
    risk["pt_dispersion"] = (_div(target["high"] - target["low"], target["value"])
                             if target and target["high"] is not None
                             and target["low"] is not None else None)
    if risk["pt_dispersion"] is None:
        rec.reason("risk.pt_dispersion", no_cons_code if not target else "no_free_data")
    if (dispersion is not None and dispersion > WIDE_RANGE and fy1["eps_n"] is not None
            and fy1["eps_n"] >= THIN_ESTIMATES):
        rec.flag("estimate_range_wide", "periods.FY1", "amber", low=fy1["eps_low"],
                 high=fy1["eps_high"], mean=fy1_eps, n=fy1["eps_n"])

    # --- healthcare ---------------------------------------------------------------------
    stage["name"] = "healthcare"
    screen_row = u.screen.get(t) or {}
    by_year = u.products.get(cid) or {}
    product_year = max(by_year) if by_year else None
    product_rows = []
    for name, value, unit in by_year.get(product_year, []) if product_year else []:
        usd = _to_usd(value, unit or reporting, rates)
        if usd is not None:
            product_rows.append((name, usd))
    product_rows.sort(key=lambda r: -r[1])
    tagged = sum(v for _, v in product_rows) if product_rows else None
    trial_counts = u.trials.get(cid) or []
    active = sum(trial_counts)
    late = screen_row.get("late_trials")
    per_trial = screen_row.get("revenue_per_late_trial")
    healthcare = {
        "lead_phase": u.lead.get(t),
        "major_products": (sum(1 for _, v in product_rows if v >= MAJOR_PRODUCT_USD)
                           if product_rows else None),
        "top_product_share": (product_rows[0][1] / tagged
                              if product_rows and tagged and tagged > 0 else None),
        "trial_concentration": (max(trial_counts) / active if active else None),
        "active_mapped_trials": active,
        "late_trials": late,
        "catalysts_12m": screen_row.get("catalysts_12m"),
        "loe_share_5y": screen_row.get("loe_share_5y"),
        "loe_unpriced_5y": screen_row.get("loe_unpriced_5y"),
        "revenue_per_late_trial_usd_m": per_trial / 1e6 if per_trial is not None else None,
    }
    if healthcare["lead_phase"] is None:
        rec.reason("healthcare.lead_phase", "no_trials")
    for key in ("major_products", "top_product_share", "loe_share_5y", "loe_unpriced_5y"):
        if healthcare[key] is None:
            rec.reason(f"healthcare.{key}", "no_product_revenue")
    if healthcare["trial_concentration"] is None:
        rec.reason("healthcare.trial_concentration", "no_trials")
    for key in ("late_trials", "catalysts_12m"):
        if healthcare[key] is None:
            rec.reason(f"healthcare.{key}", "no_free_data")
    if healthcare["revenue_per_late_trial_usd_m"] is None:
        rec.reason("healthcare.revenue_per_late_trial_usd_m",
                   "no_trials" if not late else "not_filed")

    # --- model --------------------------------------------------------------------------
    stage["name"] = "model"
    model, model_missing = _model(t, u, rec, reporting, rates)

    # --- flags on freshness, currency and filer -------------------------------------------
    stage["name"] = "flags"
    price_day = _date(price_as_of)
    if price_day is not None:
        gap = _weekdays_between(price_day, today)
        if gap and gap >= 1:
            rec.flag("stale_price", "market.price", "amber", as_of=price_as_of,
                     trading_days=gap)
    checked = _date(street["consensus_checked_at"])
    if checked is not None and (today - checked).days > STALE_CONSENSUS_DAYS:
        rec.flag("stale_consensus", "street.consensus_checked_at", "amber",
                 checked_at=street["consensus_checked_at"], days=(today - checked).days)
    balance_day = _date(ev["balance_sheet_as_of"])
    if balance_day is not None and (today - balance_day).days > STALE_BALANCE_SHEET_DAYS:
        rec.flag("stale_balance_sheet", "ev", "amber", as_of=ev["balance_sheet_as_of"],
                 days=(today - balance_day).days)
    fy0_day = _date(fy0_end)
    if fy0_day is not None and (today - fy0_day).days > STALE_FISCAL_YEAR_DAYS:
        rec.flag("stale_fiscal_year", "periods.FY0", "amber", label=f"FY{fy0_year}",
                 period_end=fy0_end)
    field_of = {"prices": "market.price", "consensus_nasdaq": "periods.FY1",
                "financials": "periods.FY0", "fx": "row_currency"}
    for failure in u.failed_sources:
        if failure["ticker"] in (None, t):
            rec.flag("source_failed", field_of.get(failure["source"]), "amber",
                     source=failure["source"], run_id=(u.run or {}).get("id"),
                     message=failure["message"])
    if row_currency and row_currency != "USD":
        rec.flag("fx_converted", "row_currency", "info", **{
            "from": row_currency, "rate": rates.get(row_currency), "as_of": u.fx_as_of})
    units = _recent_units(fin, fy0_year)
    if units and any(unit != reporting for unit in units):
        rec.flag("currency_mismatch", "reporting_currency", "amber",
                 company_currency=reporting, row_units=sorted(units))
    if fye_month is not None and fye_month != 12:
        rec.flag("fiscal_year_end", "fiscal_year_end_month", "amber", month=fye_month)
    if standard == "IFRS":
        rec.flag("ifrs_filer", "filer", "info")
    if not co["is_sec_filer"]:
        rec.flag("non_sec_filer", "filer", "info", source="financials_ir")

    # --- lineage, history, extras, detail -------------------------------------------------
    stage["name"] = "detail"
    fin_row = anchor or (_fy(fin, "NetIncomeLoss", fy0_year) if fy0 else None)
    lineage = {"price_as_of": price_as_of, "quote_fetched_at": market["quote_fetched_at"],
               "consensus_checked_at": street["consensus_checked_at"],
               "balance_sheet_as_of": ev["balance_sheet_as_of"], "fy_period_end": fy0_end,
               "financials_source": fin_row["source"] if fin_row else None,
               "fx_as_of": u.fx_as_of}
    trend = u.trend.get(t)
    blank = [None] * len(u.trend_labels)
    history = {"labels": list(u.trend_labels),
               "revenue_growth": list(trend["revenue_growth"]) if trend else blank,
               "net_margin": list(trend["net_margin"]) if trend else list(blank)}
    extras = {"net_margin": screen_row.get("net_margin"), "rd_pct": screen_row.get("rd_pct")}
    detail = _detail(u, co, fin, forward, target_rows, nasdaq_eps, product_year,
                     product_rows, tagged, fy0_year, rates)

    record = {
        "ticker": t, "name": co["name"], "engine": u.homes.get(t),
        "stage": runway.stage(conn, cid), "country": country, "region": region,
        "listing": listing, "filer": filer, "reporting_currency": co["reporting_currency"],
        "row_currency": row_currency, "fiscal_year_end_month": fye_month,
        "themes": sorted(u.themes.get(cid, [])), "areas": areas,
        "market": market, "ev": ev, "periods": periods, "growth": growth, "street": street,
        "risk": risk, "healthcare": healthcare, "model": model,
        "flags": rec.flags, "na": rec.na, "lineage": lineage, "history": history,
        "screen_extras": extras, "detail": detail, "error": None,
    }
    _fill_reasons(record)
    return record, model_missing


def _recent_units(fin, fy0_year) -> set:
    """Units of the money rows the record reads: the last four fiscal years and the
    balance sheets since."""
    if fy0_year is None:
        return set()
    floor = f"{fy0_year - 4}-06-30"
    units = set()
    for metric, by_kind in fin.items():
        if metric not in _MONEY_METRICS:
            continue
        for row in list(by_kind["FY"].values()) + by_kind["instant"]:
            if row["end"] > floor and row["unit"] and _CURRENCY_CODE.match(row["unit"]):
                units.add(row["unit"])
    return units


def _guidance(cons: dict, label: str, rates: dict, row_currency) -> dict | None:
    """FY1 revenue guidance: {block, numbers_reason} or None when there is none."""
    newest = {}
    for metric in ("Revenue", "ProductSales", "RevenueGrowth"):
        rows = cons.get((metric, label, "guidance"))
        if rows:
            newest[metric] = rows[-1]
    if not newest:
        return None
    level = newest.get("Revenue") or newest.get("ProductSales")
    growth_row = newest.get("RevenueGrowth")
    # The row that decides scope, basis and text: the level guide where there is one.
    lead = level or growth_row
    lead_metric = next(m for m in ("Revenue", "ProductSales", "RevenueGrowth")
                       if newest.get(m) is lead)

    def usd_m(value, currency):
        if value is None:
            return None
        unit = currency or row_currency or "USD"
        return value * rates[unit] / 1e6 if unit in rates else None

    block = {"value_usd_m": None, "low_usd_m": None, "high_usd_m": None, "growth": None,
             "growth_low": None, "growth_high": None,
             "metric_scope": _scope(lead_metric, lead["note"]), "fx_basis": lead["fx_basis"],
             "text": lead["note"], "as_of": _iso_date(lead["as_of"])}
    if level is not None:
        block["value_usd_m"] = usd_m(level["value"], level["currency"])
        block["low_usd_m"] = usd_m(level["low"], level["currency"])
        block["high_usd_m"] = usd_m(level["high"], level["currency"])
    if growth_row is not None:
        for field, key in (("growth", "value"), ("growth_low", "low"), ("growth_high", "high")):
            if growth_row[key] is not None:
                block[field] = growth_row[key] / 100.0
    numbers = [block[k] for k in ("value_usd_m", "low_usd_m", "high_usd_m", "growth",
                                  "growth_low", "growth_high")]
    reason = None
    if all(v is None for v in numbers):
        # A growth guide in words ("mid-single digit") has a sentence and no number. A
        # level row with no number is a company that gives no revenue guide at all.
        reason = "guidance_in_words" if lead_metric == "RevenueGrowth" else "no_guidance"
    return {"block": block, "numbers_reason": reason}


def _model(ticker: str, u: _Universe, rec: _Rec, reporting: str, rates: dict):
    """The model block, read from the response cache only. Returns (block, missing)."""
    fields = ("fair_value_per_share", "rating", "range_today", "forward_12m", "upside_12m",
              "pipeline_rnpv_usd_m", "pipeline_per_share", "pipeline_per_share_unrisked",
              "pipeline_assets", "price_date")
    block = {"state": "not_modelled", **{f: None for f in fields}}
    if ticker not in u.modelled:
        for f in fields:
            rec.reason(f"model.{f}", "not_modelled")
        return block, False
    fair = response_cache.cached_json(f"/companies/{ticker}/fair-value")
    verdict = response_cache.cached_json(f"/companies/{ticker}/forecast-verdict")
    if fair is None or verdict is None:
        block["state"] = "not_computed"
        for f in fields:
            rec.reason(f"model.{f}", "model_not_computed")
        return block, True
    if not fair.get("ok"):
        block["state"] = "failed"
    else:
        block["state"] = "modelled"
        rating = fair.get("rating") if isinstance(fair.get("rating"), dict) else {}
        low, high = rating.get("low_today"), rating.get("high_today")
        block.update({
            "fair_value_per_share": fair.get("equity_per_share"),
            "rating": rating.get("rating") if rating.get("ok", True) else None,
            "range_today": [low, high] if low is not None and high is not None else None,
            "forward_12m": rating.get("forward_12m"), "upside_12m": rating.get("upside_12m"),
            "price_date": _iso_date(fair.get("price_date")),
        })
    sotp = verdict.get("sotp") if verdict.get("ok") else None
    pipe = (sotp or {}).get("pipeline") if isinstance(sotp, dict) else None
    if isinstance(pipe, dict):
        rnpv = pipe.get("rnpv")
        block.update({
            "pipeline_rnpv_usd_m": (rnpv * rates[reporting]
                                    if rnpv is not None and reporting in rates else None),
            "pipeline_per_share": pipe.get("per_share"),
            "pipeline_per_share_unrisked": pipe.get("per_share_unrisked"),
            "pipeline_assets": pipe.get("n"),
        })
    code = "model_failed" if block["state"] == "failed" else "no_free_data"
    for f in fields:
        if block[f] is None:
            rec.reason(f"model.{f}", "model_failed" if block["state"] == "failed"
                       or not verdict.get("ok") else code)
    return block, False


def _detail(u, co, fin, forward, target_rows, nasdaq_eps, product_year, product_rows,
            tagged, fy0_year, rates) -> dict:
    """The side panel record (spec 2.7): small, and nothing that costs seconds."""
    conn, today, t, cid = u.conn, u.today, co["ticker"], co["id"]
    closes = _spark(conn, cid, today, DETAIL_SPARK_DAYS, DETAIL_SPARK_POINTS)
    relative = comps.relative_performance(None, t, conn=conn)
    fy_rows = []
    years = sorted((fin.get("Revenues") or {}).get("FY") or {})[-5:]
    unit = None
    for year in years:
        revenue = _fy(fin, "Revenues", year)
        income = _fy(fin, "NetIncomeLoss", year)
        eps = _fy(fin, "EarningsPerShareDiluted", year)
        unit = revenue["unit"]
        fy_rows.append({"fy": year, "revenue_usd_m": _usd_m(_amt(revenue), rates),
                        "net_income_usd_m": _usd_m(_amt(income), rates),
                        "eps_rc": eps["value"] if eps else None})
    quarters = _quarters(u, t, rates)
    results = None
    if quarters:
        latest = quarters[-1]
        target = dt.date.fromisoformat(latest["period_end"]) - dt.timedelta(days=365)
        year_ago = next((q for q in quarters if abs(
            (dt.date.fromisoformat(q["period_end"]) - target).days) <= 20), None)
        results = {"period_end": latest["period_end"], "revenue_usd_m": latest["revenue_usd_m"],
                   "yoy": (_div(latest["revenue_usd_m"], year_ago["revenue_usd_m"]) - 1.0
                           if year_ago and latest["revenue_usd_m"] is not None
                           and year_ago["revenue_usd_m"] else None),
                   "eps_rc": latest["eps_rc"]}
    revisions = []
    for key in ("FY1", "FY2"):
        f = forward[key]
        rows = nasdaq_eps.get(f["label"]) if f else None
        if rows:
            revisions.append({"metric": "EPS", "period": f["label"], "value": rows[-1]["value"],
                              "first_value": rows[0]["value"],
                              "first_as_of": _iso_date(rows[0]["as_of"]),
                              "as_of": _iso_date(rows[-1]["as_of"]),
                              "revisions": len(rows) - 1, "n": _estimate_n(rows[-1]["note"]),
                              "low": rows[-1]["low"], "high": rows[-1]["high"]})
    if target_rows:
        revisions.append({"metric": "PriceTarget", "period": "12M",
                          "value": target_rows[-1]["value"],
                          "first_value": target_rows[0]["value"],
                          "first_as_of": _iso_date(target_rows[0]["as_of"]),
                          "as_of": _iso_date(target_rows[-1]["as_of"]),
                          "revisions": len(target_rows) - 1, "n": None,
                          "low": target_rows[-1]["low"], "high": target_rows[-1]["high"]})
    pipe = u.pipeline.get(t) or {}
    revenue_same_year = _fy(fin, "Revenues", product_year) if product_year else None
    revenue_usd = (_to_usd(revenue_same_year["value"], revenue_same_year["unit"], rates)
                   if revenue_same_year else None)
    unattributed = (revenue_usd - tagged if revenue_usd is not None and tagged is not None
                    and revenue_usd >= tagged else None)
    products = {"fiscal_year": product_year,
                "rows": [{"name": name, "value_usd_m": value / 1e6,
                          "share": value / tagged if tagged else None}
                         for name, value in product_rows[:6]],
                "unattributed_usd_m": unattributed / 1e6 if unattributed is not None else None}
    financial_sources = sorted({row["source"] for metric in ("Revenues", "NetIncomeLoss")
                                for row in ((fin.get(metric) or {}).get("FY") or {}).values()
                                if row["source"]})
    ends = []
    for metric in ("Revenues", "NetIncomeLoss"):
        by_kind = fin.get(metric) or {}
        ends += [row["end"] for row in (by_kind.get("FY") or {}).values()]
        ends += [row["end"] for row in by_kind.get("interim") or []]
    return {
        "spark": {"closes": closes,
                  "change": (closes[-1] / closes[0] - 1.0) if len(closes) > 1 and closes[0]
                  else None},
        "relative": {span: ({"company_pct": v["company_pct"], "relative_pct": v["relative_pct"],
                             "covers_window": v["covers_window"]} if v else None)
                     for span, v in relative.items()},
        "earnings": {"unit": unit, "fy": fy_rows, "quarters": quarters[-8:]},
        "results": results,
        "revisions": revisions,
        "catalysts": u.catalysts.get(cid, []),
        "pipeline": {"compounds": pipe.get("compounds"), "unattributed": pipe.get("unattributed")},
        "products": products,
        "filings": u.filings.get(cid, []),
        "notes": {"system": u.insights.get(cid)},
        "lineage": {
            "sources": u.lineage.get(t, {}),
            "financials": {"latest_period_end": max(ends) if ends else None,
                           "sources": financial_sources},
            "fx_as_of": u.fx_as_of,
            "refresh_run": ({"id": u.run["id"], "finished_at": u.run["finished_at"],
                             "status": u.run["status"]} if u.run else None),
        },
    }


def _quarters(u, ticker, rates) -> list:
    """Up to eight discrete quarters, oldest first, with Q4 derived as FY less 9M and
    marked so."""
    statement = financials_view.build_statements(u.db_path, ticker, basis="quarterly",
                                                 limit=8)
    income = ((statement or {}).get("statements") or {}).get("income") or {}
    periods = income.get("periods") or []
    lines = {line["key"]: line for line in income.get("lines") or []}
    revenue, eps = lines.get("Revenues"), lines.get("EarningsPerShareDiluted")
    out = []
    for i, period in enumerate(periods):
        if period["period_type"] != "Q":
            continue
        cell = revenue["cells"][i] if revenue else {"value": None, "derived": False}
        out.append({"label": (period["label"] or "").replace(" ", "-"),
                    "period_end": period["period_end"],
                    "revenue_usd_m": (_usd_m((cell["value"], revenue["unit"]), rates)
                                      if revenue and cell["value"] is not None else None),
                    "eps_rc": eps["cells"][i]["value"] if eps else None,
                    "derived": bool(cell["derived"])})
    return sorted(out, key=lambda q: q["period_end"])


def _fill_reasons(record: dict) -> None:
    """Every null in the checked sections carries a reason: where the builder named none,
    the reason of a covering path, else ``no_free_data``. A list's items share its path."""
    na = record["na"]

    def covered(path):
        parts = path.split(".")
        return any(".".join(parts[:i]) in na for i in range(1, len(parts) + 1))

    def walk(value, path):
        if value is None:
            if not covered(path):
                na[path] = "no_free_data"
            return
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for child in value:
                walk(child, path)

    for section in NA_SECTIONS:
        walk(record.get(section), section)
    for path in ("filer.standard", "region"):
        head, _, tail = path.partition(".")
        value = record.get(head) if not tail else (record.get(head) or {}).get(tail)
        if value is None and not covered(path):
            na[path] = "no_free_data"


def _failed_record(u: _Universe, co: dict, message: str) -> dict:
    """A company whose builder raised: every value null, the error named."""
    reasons = {section: "calc_failed" for section in NA_SECTIONS}
    reasons.update({"filer.standard": "calc_failed", "region": "calc_failed"})
    return {
        "ticker": co["ticker"], "name": co["name"], "engine": u.homes.get(co["ticker"]),
        "stage": None, "country": co["country"], "region": None,
        "listing": {"home_exchange": None, "us_line": None, "adr_ratio": None, "otc": False},
        "filer": {"kind": None, "annual_form": None, "standard": None,
                  "standard_source": None, "is_sec_filer": bool(co["is_sec_filer"]),
                  "is_fpi_flag": bool(co["is_foreign_private_issuer"])},
        "reporting_currency": co["reporting_currency"], "row_currency": None,
        "fiscal_year_end_month": None, "themes": [], "areas": {},
        "market": None, "ev": None, "periods": None, "growth": None, "street": None,
        "risk": None, "healthcare": None, "model": None,
        "flags": [{"code": "calc_failed", "field": None, "severity": "red",
                   "params": {"message": message}}],
        "na": reasons, "lineage": None, "history": None, "screen_extras": None,
        "detail": None, "error": message,
    }


# --- the payload -----------------------------------------------------------------------
def build(db_path=None, today=None) -> dict:
    """Every company's valuation record, with the universe's dates, rates and run status.

    ``today`` defaults to the calendar date; tests pass a fixed one. One connection, one
    pass per universe-wide read, then one record per company, each wrapped so a company
    whose builder raises is returned with its error rather than failing the response.
    """
    today = today or dt.date.today()
    generated_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = db.get_connection(db_path)
    try:
        u = _Universe(conn, db_path, today)
        companies, errors, missing = [], list(u.errors), False
        for co in u.companies:
            stage = {"name": "start"}
            try:
                record, model_missing = _record(u, co, stage)
                missing = missing or model_missing
            except Exception as exc:          # one company's failure is its own
                message = f"{type(exc).__name__}: {exc}"
                record = _failed_record(u, co, message)
                errors.append({"ticker": co["ticker"], "stage": stage["name"],
                               "message": message})
            companies.append(record)
        units = u.row_units()
        fx_day = _date(u.fx_as_of)
        fx_label = _short_date(fx_day) or "an unrecorded date"
        engine_counts = {e: 0 for e in engines.ENGINES}
        for record in companies:
            if record.get("engine") in engine_counts:
                engine_counts[record["engine"]] += 1
        payload = {
            "schema": SCHEMA,
            "generated_at": generated_at,
            "complete": not missing,
            "incomplete_reason": "model_not_computed" if missing else None,
            "as_of": {
                "price_date": u.newest_price,
                "price_trading_days_old": _weekdays_between(_date(u.newest_price), today),
                "fx_date": u.fx_as_of,
                "consensus_history_starts": u.consensus_history_starts,
                "run": u.run,
            },
            "fx": {"as_of": u.fx_as_of, "source": "ECB reference rates",
                   "usd_per_unit": {cur: u.rates[cur] for cur in sorted(
                       (units | {"USD"}) & set(u.rates))}},
            "universe": {"n": len(companies), "engines": engine_counts,
                         "engine_labels": dict(engines.LABELS),
                         "absent_subsectors": list(ABSENT_SUBSECTORS)},
            "basis_text": {
                "standardised": (f"{{cur}} at the ECB reference rate of {fx_label}; per-share "
                                 "figures in USD per US-listed share; fiscal years as filed"),
                "as_reported": ("Each company's filing currency and standard, fiscal years as "
                                "filed. Market cap and enterprise value are the USD market "
                                f"figures translated at the ECB rate of {fx_label}; per-share "
                                "figures stay in USD"),
                "adjusted": ("Operating income and EBITDA excluding tagged amortisation of "
                             "intangibles and acquired IPR&D. Nothing is added back where "
                             "operating income is derived"),
                "street": "Nasdaq consensus, adjusted, per US-listed share, USD",
            },
            "companies": companies,
            "errors": errors,
        }
    finally:
        conn.close()
    return _clean(payload)
