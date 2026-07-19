"""FDA approvals from openFDA drugsfda.

Queries drugsfda by both the sponsor name and the openFDA manufacturer name, and unions
the two. Neither field alone is enough. The manufacturer name is the legal entity that
holds the application, which for an acquired product is the company that was bought:
Bristol Myers Squibb holds Opdivo as E.R. Squibb & Sons, Revlimid as Celgene, Camzyos as
Myokardia, so a manufacturer query for Bristol found nothing. The sponsor name catches
those but misses the drugs an acquirer never re-registered, so both run and the results
are merged on application number.

Covers NDAs and BLAs, so approvals link to the same marketed assets the Orange and
Purple Book create, by application number.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import db
from assets_util import normalize_appl, upsert_asset
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "approvals"
OPENFDA_SOURCE = "openfda"
TTL_SECONDS = 24 * 60 * 60

DRUGSFDA_URL = "https://api.fda.gov/drug/drugsfda.json"
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 30
_LIMIT = 100

# ticker -> openFDA manufacturer-name phrases (matched as phrases against the
# tokenized field). Distinctive short phrases match more product records.
MANUFACTURER_MAP = {
    "LLY": ["Eli Lilly and Company"],
    "NVO": ["Novo Nordisk"],
    "MRK": ["Merck Sharp & Dohme"],
    "PFE": ["Pfizer"],
    "ABBV": ["AbbVie"],
    "JNJ": ["Janssen"],
    "AZN": ["AstraZeneca"],
    "GSK": ["GlaxoSmithKline"],
    "NVS": ["Novartis"],
    "ROG": ["Genentech", "Hoffmann-La Roche"],
    "SNY": ["sanofi-aventis", "Genzyme"],
    "BMY": ["Bristol-Myers Squibb"],
    "AMGN": ["Amgen"],
    "GILD": ["Gilead Sciences"],
    "VRTX": ["Vertex Pharmaceuticals"],
    "REGN": ["Regeneron Pharmaceuticals"],
    "BIIB": ["Biogen"],
    "BAYN": ["Bayer"],
}

# ticker -> sponsor_name terms. A term search, not a phrase: a quoted phrase 404s here,
# and the terms match only the exact sponsor anyway (a Merck query returns none of
# Merck KGaA). The sponsor is the parent, so this is where an acquired product surfaces.
SPONSOR_MAP = {
    "LLY": "ELI LILLY", "NVO": "NOVO NORDISK", "MRK": "MERCK SHARP DOHME",
    "PFE": "PFIZER", "ABBV": "ABBVIE", "JNJ": "JANSSEN", "AZN": "ASTRAZENECA",
    "GSK": "GLAXOSMITHKLINE", "NVS": "NOVARTIS", "ROG": "GENENTECH", "SNY": "SANOFI",
    "BMY": "BRISTOL MYERS SQUIBB", "AMGN": "AMGEN", "GILD": "GILEAD",
    "VRTX": "VERTEX", "REGN": "REGENERON", "BIIB": "BIOGEN", "BAYN": "BAYER",
}


def _approval_date(submissions) -> str | None:
    """Earliest original approval date (YYYYMMDD -> ISO) from the submissions list."""
    dates = [
        s.get("submission_status_date")
        for s in submissions or []
        if s.get("submission_type") == "ORIG" and s.get("submission_status") == "AP"
        and s.get("submission_status_date")
    ]
    if not dates:
        return None
    raw = min(dates)
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}" if len(raw) == 8 else None


def _modality(application_number: str) -> str:
    return "biologic" if application_number.upper().startswith("BLA") else "small molecule"


def parse_drugsfda(payload: dict, ticker: str) -> list[dict]:
    """Turn a drugsfda payload into approval rows. Pure."""
    rows = []
    for result in payload.get("results", []):
        appl = (result.get("application_number") or "").upper()
        match = re.match(r"([A-Za-z]+)(\d+)", appl)
        if not match:
            continue
        internal_code = normalize_appl(match.group(1), match.group(2))
        approval_date = _approval_date(result.get("submissions"))
        if approval_date is None:
            continue
        products = result.get("products") or [{}]
        brand = products[0].get("brand_name")
        rows.append(
            {
                "ticker": ticker,
                "internal_code": internal_code,
                "application_number": appl,
                "brand": brand.title() if brand else None,
                "generic": None,
                "modality": _modality(appl),
                "approval_date": approval_date,
                "marketing_status": products[0].get("marketing_status"),
            }
        )
    return rows


class ApprovalsOpenFdaFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()

    @property
    def entity_key(self) -> str:
        return self.ticker

    def _company_id(self, conn) -> int | None:
        row = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (self.ticker,)
        ).fetchone()
        return row[0] if row else None

    def _run(self, query: str) -> list[dict]:
        params = {"search": query, "limit": _LIMIT}
        api_key = (os.getenv("OPENFDA_API_KEY") or "").strip()
        if api_key:
            params["api_key"] = api_key
        url = f"{DRUGSFDA_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8")).get("results", [])
        except urllib.error.HTTPError as exc:
            if exc.code == 404:  # openFDA returns 404 for no matches
                return []
            raise

    def fetch(self) -> dict:
        names = MANUFACTURER_MAP.get(self.ticker)
        sponsor = SPONSOR_MAP.get(self.ticker)
        if not names and not sponsor:
            raise ValueError(f"no openFDA mapping for {self.ticker}")

        results: list[dict] = []
        if names:
            phrase = " ".join(f'"{n}"' for n in names)
            results += self._run(f"openfda.manufacturer_name:({phrase})")
        if sponsor:
            results += self._run(f"sponsor_name:({sponsor})")

        # An application can come back from both queries. The application number is its
        # identity, so a later parse keying on it dedupes, but merging here keeps the
        # count honest and the payload small.
        seen, merged = set(), []
        for item in results:
            number = item.get("application_number")
            if number and number in seen:
                continue
            seen.add(number)
            merged.append(item)
        return {"results": merged}

    def normalise(self, raw) -> list[dict]:
        return parse_drugsfda(raw, self.ticker)

    # --- snapshots -------------------------------------------------------
    def _write_snapshot(self, conn, payload):
        conn.execute(
            """
            INSERT INTO snapshots (source, entity_type, entity_key, payload, refresh_run_id)
            VALUES (?, 'company', ?, ?, ?)
            """,
            (self.source, self.ticker, json.dumps(payload), self.refresh_run_id),
        )

    def snapshot(self, rows: list[dict]) -> None:
        latest = max((r["approval_date"] for r in rows), default=None)
        conn = db.get_connection(self.db_path)
        try:
            self._write_snapshot(
                conn,
                {"ticker": self.ticker, "approvals": len(rows),
                 "latest_approval": latest, "source": OPENFDA_SOURCE, "fetch_kind": "live"},
            )
            conn.commit()
        finally:
            conn.close()

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            company_id = self._company_id(conn)
            if company_id is None:
                return
            n = conn.execute(
                """
                SELECT COUNT(*) FROM approvals ap JOIN assets a ON ap.asset_id = a.id
                 WHERE a.owner_company_id = ? AND ap.source = ?
                """,
                (company_id, OPENFDA_SOURCE),
            ).fetchone()[0]
            if not n:
                return
            self._write_snapshot(conn, {"ticker": self.ticker, "approvals": n,
                                        "source": OPENFDA_SOURCE, "fetch_kind": "cache"})
            conn.commit()
        finally:
            conn.close()

    # --- current-state table ---------------------------------------------
    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        try:
            company_id = self._company_id(conn)
            if company_id is None:
                return RefreshResult(self.source, 0, [f"unknown ticker {self.ticker}"], False, 0)
            for row in rows:
                asset_id = upsert_asset(
                    conn, company_id, row["internal_code"], row["brand"],
                    row["generic"], row["modality"],
                )
                conn.execute(
                    "DELETE FROM approvals WHERE asset_id = ? AND source = ?",
                    (asset_id, OPENFDA_SOURCE),
                )
                conn.execute(
                    """
                    INSERT INTO approvals
                        (asset_id, region, agency, approval_date, application_number, source)
                    VALUES (?, 'US', 'FDA', ?, ?, ?)
                    """,
                    (asset_id, row["approval_date"], row["application_number"], OPENFDA_SOURCE),
                )
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(rows), [], False, 0)
