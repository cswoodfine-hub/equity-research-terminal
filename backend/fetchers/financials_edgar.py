"""Reported financials from SEC EDGAR XBRL company-facts.

Pulls annual revenue, net income, and R&D (last few fiscal years) plus shares
outstanding, cash, and total debt for the balance-sheet inputs to EV. Handles both
us-gaap (US filers) and ifrs-full (foreign 20-F filers), and the fact that companies
drift between XBRL concepts over time: each metric has a priority list of candidate
concepts, and we pick the one whose annual series reaches the latest year so YoY is
computed from a single consistent concept.

Values are stored in the filer's reporting currency (the XBRL unit). Nothing is
converted or estimated; a missing input is stored null.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.request

import db
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "financials"
EDGAR_SOURCE = "edgar_companyfacts"
TTL_SECONDS = 24 * 60 * 60

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_TIMEOUT_S = 30
_ANNUAL_FORMS = ("10-K", "20-F")

# Priority-ordered candidate concepts per canonical metric. First candidate whose
# annual series reaches the latest available year wins (handles tag drift).
METRIC_CANDIDATES = {
    "Revenues": [
        ("us-gaap", "Revenues"),
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"),
        ("us-gaap", "SalesRevenueNet"),
        ("ifrs-full", "Revenue"),
        ("ifrs-full", "RevenueFromContractsWithCustomers"),
    ],
    "NetIncomeLoss": [
        ("us-gaap", "NetIncomeLoss"),
        ("ifrs-full", "ProfitLoss"),
    ],
    "ResearchAndDevelopmentExpense": [
        ("us-gaap", "ResearchAndDevelopmentExpense"),
        ("us-gaap", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"),
        ("ifrs-full", "ResearchAndDevelopmentExpense"),
    ],
}
CASH_CANDIDATES = [
    ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
    ("ifrs-full", "CashAndCashEquivalents"),
]
DEBT_COMBINED_CANDIDATES = [("us-gaap", "DebtLongtermAndShorttermCombinedAmount")]

MAX_FISCAL_YEARS = 3  # how many recent FYs of each annual metric to store


# --- pure parsing --------------------------------------------------------
def _concept(facts: dict, taxonomy: str, name: str) -> dict | None:
    return (facts.get(taxonomy) or {}).get(name)


def _annual_by_year(concept: dict) -> dict[int, dict]:
    """Full-year (10-K/20-F) duration values, deduped by fiscal year, latest filed."""
    by_year: dict[int, dict] = {}
    for unit, entries in (concept.get("units") or {}).items():
        for e in entries:
            start, end = e.get("start"), e.get("end")
            if not start or not end or e.get("form") not in _ANNUAL_FORMS:
                continue
            days = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days
            if not (340 <= days <= 380):
                continue
            year = int(end[:4])
            current = by_year.get(year)
            if current is None or e.get("filed", "") > current["filed"]:
                by_year[year] = {"val": e["val"], "unit": unit, "end": end,
                                 "filed": e.get("filed", "")}
    return by_year


def pick_annual_series(facts: dict, candidates):
    """Pick the highest-priority concept whose annual series reaches the latest year.

    Returns (unit, {year: {'val','end'}}); ({}, None) when no candidate has data.
    """
    per_candidate = []
    for taxonomy, name in candidates:
        concept = _concept(facts, taxonomy, name)
        if not concept:
            continue
        by_year = _annual_by_year(concept)
        if by_year:
            per_candidate.append(by_year)
    if not per_candidate:
        return None, {}
    max_year = max(y for by in per_candidate for y in by)
    chosen = next((by for by in per_candidate if max_year in by), per_candidate[0])
    unit = chosen[max(chosen)]["unit"]
    series = {y: {"val": chosen[y]["val"], "end": chosen[y]["end"]} for y in chosen}
    return unit, series


def _instant_at(concept: dict, fy_end: str) -> dict | None:
    best = None
    for unit, entries in (concept.get("units") or {}).items():
        for e in entries:
            if e.get("start") or e.get("form") not in _ANNUAL_FORMS or e.get("end") != fy_end:
                continue
            if best is None or e.get("filed", "") > best["filed"]:
                best = {"val": e["val"], "unit": unit, "filed": e.get("filed", "")}
    return best


def select_instant(facts: dict, candidates, fy_end: str):
    for taxonomy, name in candidates:
        concept = _concept(facts, taxonomy, name)
        if not concept:
            continue
        got = _instant_at(concept, fy_end)
        if got:
            return got["val"], got["unit"]
    return None, None


def select_total_debt(facts: dict, fy_end: str):
    """Prefer the single combined debt tag; else long-term (non-current + current)."""
    val, unit = select_instant(facts, DEBT_COMBINED_CANDIDATES, fy_end)
    if val is not None:
        return val, unit
    noncurrent, unit = select_instant(facts, [("us-gaap", "LongTermDebtNoncurrent")], fy_end)
    if noncurrent is None:
        return None, None  # avoid mixing stale years; leave EV null instead
    current, _ = select_instant(facts, [("us-gaap", "LongTermDebtCurrent")], fy_end)
    return noncurrent + (current or 0), unit


def latest_shares(facts: dict) -> dict | None:
    concept = _concept(facts, "dei", "EntityCommonStockSharesOutstanding")
    if not concept:
        return None
    best = None
    for entries in (concept.get("units") or {}).values():
        for e in entries:
            end = e.get("end")
            if not end:
                continue
            key = (end, e.get("filed", ""))
            if best is None or key > best[0]:
                best = (key, e["val"], end)
    return {"as_of": best[2], "val": int(best[1])} if best else None


def parse_companyfacts(payload: dict) -> dict:
    """Turn a company-facts payload into annual metrics plus balance-sheet inputs. Pure."""
    facts = payload.get("facts") or {}
    annual: dict[str, dict] = {}
    unit_by_metric: dict[str, str] = {}
    for metric, candidates in METRIC_CANDIDATES.items():
        unit, series = pick_annual_series(facts, candidates)
        annual[metric] = series
        if unit:
            unit_by_metric[metric] = unit

    currency = unit_by_metric.get("Revenues") or unit_by_metric.get("NetIncomeLoss")
    reference = annual.get("Revenues") or annual.get("NetIncomeLoss") or {}
    fy_end = reference[max(reference)]["end"] if reference else None

    cash = total_debt = None
    if fy_end:
        cash, _ = select_instant(facts, CASH_CANDIDATES, fy_end)
        total_debt, _ = select_total_debt(facts, fy_end)

    return {
        "entity_name": payload.get("entityName"),
        "currency": currency,
        "fy_end": fy_end,
        "annual": annual,          # {metric: {year: {'val','end'}}}
        "shares": latest_shares(facts),
        "cash": cash,
        "total_debt": total_debt,
    }


def _latest(series: dict):
    """Latest {'val'} from an annual series, or None."""
    if not series:
        return None
    return series[max(series)]["val"]


# --- fetcher -------------------------------------------------------------
class FinancialsEdgarFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()
        self._parsed: dict = {}

    @property
    def entity_key(self) -> str:
        return self.ticker

    def _company(self, conn):
        return conn.execute(
            "SELECT id, cik FROM companies WHERE ticker = ?", (self.ticker,)
        ).fetchone()

    def fetch(self) -> dict:
        conn = db.get_connection(self.db_path)
        try:
            company = self._company(conn)
        finally:
            conn.close()
        if company is None:
            raise ValueError(f"unknown ticker {self.ticker}")
        if not company["cik"]:
            raise ValueError(f"no CIK for {self.ticker}")
        user_agent = (os.getenv("SEC_USER_AGENT") or "").strip()
        if not user_agent:
            raise RuntimeError("SEC_USER_AGENT is not set; EDGAR blocks anonymous requests")
        url = COMPANYFACTS_URL.format(cik=company["cik"])
        request = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def normalise(self, raw) -> list[dict]:
        self._parsed = parse_companyfacts(raw)
        currency = self._parsed["currency"]
        rows: list[dict] = []
        for metric, series in self._parsed["annual"].items():
            for year in sorted(series)[-MAX_FISCAL_YEARS:]:
                rows.append(
                    {
                        "metric": metric,
                        "value": series[year]["val"],
                        "unit": currency,
                        "period_end": series[year]["end"],
                        "period_type": "FY",
                        "fiscal_year": year,
                        "fiscal_period": "FY",
                    }
                )
        shares = self._parsed["shares"]
        if shares:
            rows.append(
                {
                    "metric": "SharesOutstanding",
                    "value": shares["val"],
                    "unit": "shares",
                    "period_end": shares["as_of"],
                    "period_type": "instant",
                    "fiscal_year": int(shares["as_of"][:4]),
                    "fiscal_period": None,
                }
            )
        fy_end = self._parsed["fy_end"]
        for metric, value in (("CashAndEquivalents", self._parsed["cash"]),
                              ("TotalDebt", self._parsed["total_debt"])):
            if value is not None and fy_end:
                rows.append(
                    {
                        "metric": metric,
                        "value": value,
                        "unit": currency,
                        "period_end": fy_end,
                        "period_type": "instant",
                        "fiscal_year": int(fy_end[:4]),
                        "fiscal_period": None,
                    }
                )
        return rows

    # --- snapshots -------------------------------------------------------
    def _write_snapshot(self, conn, payload: dict) -> None:
        conn.execute(
            """
            INSERT INTO snapshots (source, entity_type, entity_key, payload, refresh_run_id)
            VALUES (?, 'company', ?, ?, ?)
            """,
            (self.source, self.ticker, json.dumps(payload), self.refresh_run_id),
        )

    def snapshot(self, rows: list[dict]) -> None:
        if not self._parsed:
            return
        annual = self._parsed["annual"]
        conn = db.get_connection(self.db_path)
        try:
            self._write_snapshot(
                conn,
                {
                    "ticker": self.ticker,
                    "fiscal_year": _latest_year(annual.get("Revenues")),
                    "currency": self._parsed["currency"],
                    "revenue": _latest(annual.get("Revenues") or {}),
                    "net_income": _latest(annual.get("NetIncomeLoss") or {}),
                    "rd_expense": _latest(annual.get("ResearchAndDevelopmentExpense") or {}),
                    "shares": (self._parsed["shares"] or {}).get("val"),
                    "cash": self._parsed["cash"],
                    "total_debt": self._parsed["total_debt"],
                    "source": EDGAR_SOURCE,
                    "fetch_kind": "live",
                },
            )
            conn.commit()
        finally:
            conn.close()

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            company = self._company(conn)
            if company is None:
                return
            rows = conn.execute(
                """
                SELECT metric, value, unit, fiscal_year FROM financials
                 WHERE company_id = ? AND period_type = 'FY'
                   AND fiscal_year = (SELECT MAX(fiscal_year) FROM financials
                                       WHERE company_id = ? AND period_type = 'FY')
                """,
                (company["id"], company["id"]),
            ).fetchall()
            if not rows:
                return
            by_metric = {r["metric"]: r["value"] for r in rows}
            self._write_snapshot(
                conn,
                {
                    "ticker": self.ticker,
                    "fiscal_year": rows[0]["fiscal_year"],
                    "currency": rows[0]["unit"],
                    "revenue": by_metric.get("Revenues"),
                    "net_income": by_metric.get("NetIncomeLoss"),
                    "rd_expense": by_metric.get("ResearchAndDevelopmentExpense"),
                    "source": EDGAR_SOURCE,
                    "fetch_kind": "cache",
                },
            )
            conn.commit()
        finally:
            conn.close()

    # --- current-state table ---------------------------------------------
    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        try:
            company = self._company(conn)
            if company is None:
                return RefreshResult(self.source, 0, [f"unknown ticker {self.ticker}"], False, 0)
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO financials
                        (company_id, period_end, period_type, metric, value, unit,
                         fiscal_year, fiscal_period, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(company_id, metric, period_end, period_type) DO UPDATE SET
                        value=excluded.value, unit=excluded.unit,
                        fiscal_year=excluded.fiscal_year, fiscal_period=excluded.fiscal_period,
                        source=excluded.source
                    """,
                    (
                        company["id"], row["period_end"], row["period_type"], row["metric"],
                        row["value"], row["unit"], row["fiscal_year"], row["fiscal_period"],
                        EDGAR_SOURCE,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(rows), [], False, 0)


def _latest_year(series):
    return max(series) if series else None
