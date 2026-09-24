"""Reported financials from SEC EDGAR XBRL company-facts.

Pulls the three statements (see ``statements.LINES``) at every period the filer tags:
full years, discrete quarters, cumulative year-to-date spans, and balance sheet
instants. Handles both us-gaap (US filers) and ifrs-full (foreign 20-F filers), and the
fact that companies drift between XBRL concepts over time: each line has a priority
list of candidate concepts, and we pick the one whose series reaches the latest period
so a trend is computed from a single consistent concept.

Only reported facts are written here. Subtotals a filer does not tag (gross profit for
Lilly, free cash flow for everyone) are computed in the API layer and flagged there, so
nothing in this table is anything other than a number the company published.

Values are stored in the unit the filer tagged, which is the reporting currency for
money lines and USD/shares for EPS. Nothing is converted or estimated; a missing input
is stored null.
"""

from __future__ import annotations

import json
import os
import urllib.request

import db
from fetchers.base import BaseFetcher, RefreshResult

# The parser is shared with the ESEF fetcher, so it lives in ``companyfacts`` rather than
# in either fetcher. Re-exported so the callers that read it from here keep one import.
from companyfacts import (  # noqa: F401
    CASH_CANDIDATES,
    DEBT_COMBINED_CANDIDATES,
    DEBT_CURRENT_CANDIDATES,
    MAX_FISCAL_YEARS,
    MAX_PERIODS,
    METRIC_CANDIDATES,
    _agrees,
    _continues,
    _latest,
    _latest_year,
    backfill_rd_less_iprd,
    financial_rows,
    headline,
    instant_series,
    latest_shares,
    parse_companyfacts,
    parse_statements,
    pick_annual_series,
    pick_kind_series,
    rd_less_expensed_iprd,
    select_instant,
    select_total_debt,
    total_debt_series,
)

SOURCE = "financials"
EDGAR_SOURCE = "edgar_companyfacts"
TTL_SECONDS = 24 * 60 * 60

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_TIMEOUT_S = 30
_ANNUAL_FORMS = ("10-K", "20-F")


# --- fetcher -------------------------------------------------------------
class FinancialsEdgarFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()
        self._parsed: dict = {}
        self._statements: dict = {}

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
        self._statements = parse_statements(raw)
        self._parsed = headline(self._statements)
        return financial_rows(self._statements)

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
