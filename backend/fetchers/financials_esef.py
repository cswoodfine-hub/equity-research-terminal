"""Reported financials for a filer the SEC never sees, from its ESEF annual reports.

Bayer is not an SEC registrant, so EDGAR's company facts hold nothing for it, and with no
financials it could carry no valuation at all. It does file XBRL, just not with the SEC:
every EU-listed company has filed its annual financial report in the European Single
Electronic Format since fiscal 2020, an XHTML document with inline XBRL tags. The
consolidated statements are tagged in the ``ifrs-full`` taxonomy, the same one Novo,
GSK and Sanofi use in their 20-F, so the candidate concepts ``statements.LINES`` already
names for them name Bayer's lines too.

The equivalent of EDGAR's company-facts file is filings.xbrl.org, XBRL International's
index of ESEF filings. It carries each report as submitted and as xBRL-JSON, the OIM
rendering of the same facts, produced by Arelle. The index is keyed by LEI, which is why
a company here needs one where an SEC filer needs a CIK.

This fetcher turns each xBRL-JSON report into the company-facts shape and hands it to
the parser EDGAR data goes through, so a Bayer line and a Novo line are resolved by the
same code. What is different, and what the conversion has to get right:

- A period is a pair of datetimes on XBRL's end-of-day convention. The year to
  31 December 2024 is ``2024-01-01T00:00:00/2025-01-01T00:00:00``, so the end is the
  day before the stamp. Read naively every year would run to 1 January and be one day
  long in the wrong place.
- A fact carrying any dimension beyond concept, entity, period and unit is a member of a
  breakdown (a segment, a component of equity), not the total, and is left out. EDGAR's
  company facts carry only undimensioned facts, so this is the same set.
- One report states two years: its own and the comparative. A later report restating
  the comparative is the one that stands, so each fact is dated by the period end of the
  report it came from, which the parser reads as the filing order.
- ESEF covers annual reports only. There are no quarters, and history starts with the
  fiscal 2020 report and its 2019 comparative.

Values are stored as tagged: reporting currency, as reported, nothing converted. A line
Bayer does not tag in ``ifrs-full`` (an extension concept of its own) is absent, never
estimated.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import urllib.parse
import urllib.request

import companyfacts
import db
from fetchers.base import BaseFetcher, RefreshResult

# The same snapshot series EDGAR writes, so a company's financial history is one series
# whichever route filled it. The rows say which route in their ``source`` column.
SOURCE = "financials"
ESEF_SOURCE = "esef_xbrl"
TTL_SECONDS = 24 * 60 * 60

INDEX_URL = "https://filings.xbrl.org/api/filings"
BASE_URL = "https://filings.xbrl.org/"
# The form every converted fact is stamped with; ``statements.FORMS`` admits it.
FORM = "ESEF"
_TIMEOUT_S = 60
_PAGE_SIZE = 100
_MAX_PAGES = 5
# Seven reports reach back to the fiscal 2019 comparative, which is as far as ESEF goes.
# One more is headroom for a year the index carries twice under different period ends.
MAX_REPORTS = 8
_HEADERS = {"User-Agent": "equity-research-terminal (ESEF financials)",
            "Accept": "application/vnd.api+json, application/json"}

# ifrs-full is versioned by date in its namespace, one version per annual taxonomy.
_IFRS_NAMESPACE = re.compile(r"^https?://xbrl\.ifrs\.org/taxonomy/\d{4}-\d{2}-\d{2}/ifrs-full$")
# The aspects every fact has. Anything else is a dimension, so the fact is a breakdown.
_CORE_ASPECTS = {"concept", "entity", "period", "unit", "language"}
_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:T(\d{2}):(\d{2}):(\d{2}))?")


class NotIndexed(LookupError):
    """The index answered and has no ESEF report for the LEI."""


# --- pure conversion -----------------------------------------------------
def _day(stamp: str, *, closing: bool) -> str | None:
    """An xBRL-JSON period stamp as an ISO date, on the convention the parser expects.

    A closing stamp at midnight is the end of the day before: XBRL writes the year to
    31 December as ending ``T00:00:00`` on 1 January. An opening stamp at midnight is
    the start of its own day. A bare date is the day itself either way.
    """
    match = _STAMP.match(stamp or "")
    if not match:
        return None
    try:
        day = dt.date.fromisoformat(match.group(1))
    except ValueError:
        return None
    if closing and match.group(2) is not None and match.group(2, 3, 4) == ("00", "00", "00"):
        day -= dt.timedelta(days=1)
    return day.isoformat()


def _unit(aspect: str | None) -> str | None:
    """``iso4217:EUR`` as ``EUR``, ``iso4217:EUR/xbrli:shares`` as ``EUR/shares``: the
    spelling EDGAR's company facts use, so a line reads one unit whichever route it came
    by. None for a fact with no unit, which is never a line the parser takes."""
    if not aspect:
        return None
    return "/".join(part.rpartition(":")[2] for part in aspect.split("/"))


def _number(value):
    """A fact's value as a number, or None when it is nil, text or not finite."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def _precision(fact: dict) -> float:
    """The fact's decimals. Arelle omits the attribute when the value is exact."""
    decimals = fact.get("decimals")
    if isinstance(decimals, (int, float)) and not isinstance(decimals, bool):
        return float(decimals)
    return math.inf


def report_facts(report: dict, lei: str, filed: str, accession: str) -> tuple[dict, list[str]]:
    """One xBRL-JSON report as company facts, ``{"ifrs-full": {concept: {"units": ...}}}``.

    Only undimensioned ``ifrs-full`` facts about the LEI's own entity are taken. The same
    fact tagged in two places in a report (a total in the statement and again in a note)
    is kept once. Where two such copies disagree, the more precise one stands, and where
    they are equally precise and still disagree neither does, since picking one would be
    choosing a number the report does not settle. Returns the facts and a note per fact
    refused that way.
    """
    namespaces = (report.get("documentInfo") or {}).get("namespaces") or {}
    ifrs = {prefix for prefix, uri in namespaces.items()
            if isinstance(uri, str) and _IFRS_NAMESPACE.match(uri)}
    chosen: dict[tuple, tuple[float, dict]] = {}
    contested: set[tuple] = set()
    for fact in (report.get("facts") or {}).values():
        aspects = fact.get("dimensions") or {}
        if set(aspects) - _CORE_ASPECTS:
            continue                          # a member of a breakdown, not the total
        prefix, _, concept = (aspects.get("concept") or "").partition(":")
        if prefix not in ifrs or not concept:
            continue                          # an extension concept, or not a line
        if (aspects.get("entity") or "").rpartition(":")[2] != lei:
            continue
        value = _number(fact.get("value"))
        unit = _unit(aspects.get("unit"))
        if value is None or unit is None:
            continue
        opening, _, closing = (aspects.get("period") or "").rpartition("/")
        end = _day(closing, closing=True)
        start = _day(opening, closing=False) if opening else None
        if end is None or (opening and start is None):
            continue
        entry = {"end": end, "val": value, "form": FORM, "filed": filed, "accn": accession}
        if start:
            entry["start"] = start
        key = (concept, unit, start, end)
        precision = _precision(fact)
        held = chosen.get(key)
        if held is None or precision > held[0]:
            chosen[key] = (precision, entry)
            contested.discard(key)
        elif precision == held[0] and held[1]["val"] != value:
            contested.add(key)

    facts: dict = {}
    notes = []
    for key, (_, entry) in chosen.items():
        concept, unit, start, end = key
        if key in contested:
            notes.append(f"{concept} {start or ''}..{end}: report {accession} tags two "
                         "different values at the same precision; neither taken")
            continue
        units = facts.setdefault(concept, {"units": {}})["units"]
        units.setdefault(unit, []).append(entry)
    return {"ifrs-full": facts} if facts else {}, notes


def merge_facts(parts: list[dict]) -> dict:
    """Several reports' company facts as one. Every entry is kept; the parser dedupes a
    period by its ``filed`` date, which is how the later report's restatement wins."""
    merged: dict = {}
    for part in parts:
        for taxonomy, concepts in part.items():
            for concept, body in concepts.items():
                units = merged.setdefault(taxonomy, {}).setdefault(
                    concept, {"units": {}})["units"]
                for unit, entries in body["units"].items():
                    units.setdefault(unit, []).extend(entries)
    return merged


# --- the index -------------------------------------------------------------
def index_url(lei: str) -> str:
    """The filings.xbrl.org query for every report one LEI has filed."""
    return INDEX_URL + "?" + urllib.parse.urlencode({
        "filter[entity.identifier]": lei, "include": "entity",
        "page[size]": _PAGE_SIZE})


def select_reports(pages: list[dict], lei: str) -> list[dict]:
    """The reports worth reading from index pages, newest first.

    A report the index files under a different entity is dropped, however it got into
    the result. A period the index carries twice (a report in two languages, or a
    refiling) is read once, from the copy processed last. Only the latest MAX_REPORTS
    periods are kept: older ones are the comparatives of the next report anyway.
    """
    entities = {}
    for page in pages:
        for item in page.get("included") or []:
            if item.get("type") == "entity":
                entities[item.get("id")] = item.get("attributes") or {}
    by_period: dict[str, dict] = {}
    for page in pages:
        for item in page.get("data") or []:
            attrs = item.get("attributes") or {}
            entity_id = (((item.get("relationships") or {}).get("entity") or {})
                         .get("data") or {}).get("id")
            entity = entities.get(entity_id)
            if entity is not None and entity.get("identifier") != lei:
                continue
            period_end, json_url = attrs.get("period_end"), attrs.get("json_url")
            if not period_end or not json_url:
                continue                     # not yet converted, so nothing to read
            report = {"period_end": period_end,
                      "json_url": urllib.parse.urljoin(BASE_URL, json_url),
                      "fxo_id": attrs.get("fxo_id") or item.get("id"),
                      "processed": attrs.get("processed") or attrs.get("date_added") or "",
                      "entity_name": (entity or {}).get("name")}
            held = by_period.get(period_end)
            if held is None or report["processed"] > held["processed"]:
                by_period[period_end] = report
    return sorted(by_period.values(), key=lambda r: r["period_end"],
                  reverse=True)[:MAX_REPORTS]


def parse_reports(reports: list[dict], lei: str) -> tuple[dict, list[str]]:
    """``[{period_end, fxo_id, report}]`` as parsed statements, plus notes."""
    parts, notes = [], []
    for item in reports:
        facts, refused = report_facts(item["report"], lei, filed=item["period_end"],
                                      accession=str(item.get("fxo_id") or ""))
        notes.extend(refused)
        if facts:
            parts.append(facts)
    return companyfacts.parse_statements({"facts": merge_facts(parts)}), notes


# --- fetcher -------------------------------------------------------------
def _get_json(url: str):
    request = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


class FinancialsEsefFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()
        self._statements: dict = {}
        self._parsed: dict = {}
        self._notes: list[str] = []
        self._reports: list[dict] = []

    @property
    def entity_key(self) -> str:
        return self.ticker

    def _company(self, conn):
        return conn.execute(
            "SELECT id, lei FROM companies WHERE ticker = ?", (self.ticker,)).fetchone()

    def fetch(self) -> dict:
        conn = db.get_connection(self.db_path)
        try:
            company = self._company(conn)
        finally:
            conn.close()
        if company is None:
            raise ValueError(f"unknown ticker {self.ticker}")
        lei = (company["lei"] or "").strip()
        if not lei:
            raise ValueError(f"no LEI for {self.ticker}")
        pages, url = [], index_url(lei)
        while url and len(pages) < _MAX_PAGES:
            page = _get_json(url)
            pages.append(page)
            following = (page.get("links") or {}).get("next")
            url = urllib.parse.urljoin(BASE_URL, following) if following else None
        reports = select_reports(pages, lei)
        if not reports:
            raise NotIndexed(f"filings.xbrl.org indexes no converted ESEF report for "
                             f"{self.ticker} (LEI {lei})")
        for report in reports:
            report["report"] = _get_json(report["json_url"])
        return {"lei": lei, "reports": reports}

    def normalise(self, raw) -> list[dict]:
        self._statements, self._notes = parse_reports(raw["reports"], raw["lei"])
        self._parsed = companyfacts.headline(self._statements)
        self._reports = [{k: r.get(k) for k in ("period_end", "fxo_id", "json_url",
                                                 "entity_name")}
                         for r in raw["reports"]]
        return companyfacts.financial_rows(self._statements)

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
            self._write_snapshot(conn, {
                "ticker": self.ticker,
                "fiscal_year": companyfacts._latest_year(annual.get("Revenues")),
                "currency": self._parsed["currency"],
                "revenue": companyfacts._latest(annual.get("Revenues") or {}),
                "net_income": companyfacts._latest(annual.get("NetIncomeLoss") or {}),
                "rd_expense": companyfacts._latest(
                    annual.get("ResearchAndDevelopmentExpense") or {}),
                "shares": None,       # ESEF has no cover-page share count
                "cash": self._parsed["cash"],
                "total_debt": self._parsed["total_debt"],
                "reports": self._reports,
                "source": ESEF_SOURCE,
                "fetch_kind": "live",
            })
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
            self._write_snapshot(conn, {
                "ticker": self.ticker,
                "fiscal_year": rows[0]["fiscal_year"],
                "currency": rows[0]["unit"],
                "revenue": by_metric.get("Revenues"),
                "net_income": by_metric.get("NetIncomeLoss"),
                "rd_expense": by_metric.get("ResearchAndDevelopmentExpense"),
                "source": ESEF_SOURCE,
                "fetch_kind": "cache",
            })
            conn.commit()
        finally:
            conn.close()

    # --- current-state table ---------------------------------------------
    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        try:
            company = self._company(conn)
            if company is None:
                return RefreshResult(self.source, 0, [f"unknown ticker {self.ticker}"],
                                     False, 0)
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO financials
                        (company_id, period_end, period_type, metric, value, unit,
                         fiscal_year, fiscal_period, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(company_id, metric, period_end, period_type) DO UPDATE SET
                        value=excluded.value, unit=excluded.unit,
                        fiscal_year=excluded.fiscal_year,
                        fiscal_period=excluded.fiscal_period, source=excluded.source
                    """,
                    (company["id"], row["period_end"], row["period_type"], row["metric"],
                     row["value"], row["unit"], row["fiscal_year"], row["fiscal_period"],
                     ESEF_SOURCE),
                )
            conn.commit()
        finally:
            conn.close()
        notes = list(self._notes)
        if rows and "Revenues" not in self._statements.get("lines", {}):
            notes.append(f"{self.ticker}: ESEF reports parsed but no ifrs-full revenue "
                         "concept resolved; the filer may tag it as an extension")
        return RefreshResult(self.source, len(rows), [], False, 0, notes=notes)
