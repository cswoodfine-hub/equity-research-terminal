"""Seed the companies table and resolve SEC CIKs.

Loads ``data/companies_seed.csv`` into ``companies``, then resolves each SEC
filer's 10-digit CIK from EDGAR's official ticker map and writes it back. Rows
flagged ``is_sec_filer = 0`` (Roche, Bayer) are skipped and left with a null CIK.
Any ticker that does not resolve is logged, never guessed.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import time
import urllib.request
from pathlib import Path

import env  # noqa: F401  loads the .env from the repo root

import db

logger = logging.getLogger(__name__)

DATA_DIR = db.BACKEND_DIR.parent / "data"
SEED_CSV = DATA_DIR / "companies_seed.csv"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# EDGAR asks callers to stay under 10 requests/second. One request is made here,
# but the delay keeps the helper honest if it is ever called in a loop.
_MIN_REQUEST_INTERVAL_S = 0.15

# Columns copied verbatim from the seed CSV. cik is resolved separately and is
# deliberately excluded so a re-run of load_companies never clears a resolved CIK.
_TEXT_COLUMNS = (
    "ticker",
    "name",
    "primary_exchange",
    "country",
    "reporting_currency",
    "us_adr_ticker",
    "ir_rss_url",
    # What each source calls this company. Kept here rather than in five dictionaries
    # spread across four fetchers, so adding a company is adding a row.
    "ctgov_sponsor",
    "openfda_manufacturer",
    "openfda_sponsor",
    "orange_book_applicant",
    "purple_book_applicant",
)
_INT_COLUMNS = ("is_foreign_private_issuer", "is_sec_filer")


def load_companies(db_path: str | Path | None = None) -> int:
    """Upsert every row of the seed CSV into ``companies``. Returns the row count."""
    with open(SEED_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    conn = db.get_connection(db_path)
    try:
        for row in rows:
            values = {c: (row.get(c) or "").strip() or None for c in _TEXT_COLUMNS}
            for c in _INT_COLUMNS:
                raw = (row.get(c) or "").strip()
                values[c] = int(raw) if raw else 0
            conn.execute(
                """
                INSERT INTO companies
                    (ticker, name, primary_exchange, country, reporting_currency,
                     us_adr_ticker, is_foreign_private_issuer, is_sec_filer, ir_rss_url,
                     ctgov_sponsor, openfda_manufacturer, openfda_sponsor,
                     orange_book_applicant, purple_book_applicant)
                VALUES
                    (:ticker, :name, :primary_exchange, :country, :reporting_currency,
                     :us_adr_ticker, :is_foreign_private_issuer, :is_sec_filer,
                     :ir_rss_url, :ctgov_sponsor, :openfda_manufacturer,
                     :openfda_sponsor, :orange_book_applicant, :purple_book_applicant)
                ON CONFLICT(ticker) DO UPDATE SET
                    name=excluded.name,
                    primary_exchange=excluded.primary_exchange,
                    country=excluded.country,
                    reporting_currency=excluded.reporting_currency,
                    us_adr_ticker=excluded.us_adr_ticker,
                    is_foreign_private_issuer=excluded.is_foreign_private_issuer,
                    is_sec_filer=excluded.is_sec_filer,
                    ir_rss_url=excluded.ir_rss_url,
                    -- COALESCE so a blank cell never erases a name that works. A
                    -- clinical-stage company has no Orange Book applicant and its
                    -- column is empty, which is not the same as wrong.
                    ctgov_sponsor=COALESCE(excluded.ctgov_sponsor, companies.ctgov_sponsor),
                    openfda_manufacturer=COALESCE(excluded.openfda_manufacturer,
                                                  companies.openfda_manufacturer),
                    openfda_sponsor=COALESCE(excluded.openfda_sponsor,
                                             companies.openfda_sponsor),
                    orange_book_applicant=COALESCE(excluded.orange_book_applicant,
                                                   companies.orange_book_applicant),
                    purple_book_applicant=COALESCE(excluded.purple_book_applicant,
                                                   companies.purple_book_applicant),
                    updated_at=datetime('now')
                """,
                values,
            )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def fetch_company_tickers(user_agent: str | None = None) -> dict:
    """Download EDGAR's ticker->CIK map. Requires a real SEC_USER_AGENT header."""
    ua = (user_agent or os.getenv("SEC_USER_AGENT") or "").strip()
    if not ua:
        raise RuntimeError(
            "SEC_USER_AGENT is not set. EDGAR blocks requests without a real "
            "User-Agent. Set it to 'Your Name your@email' (see .env.example)."
        )
    time.sleep(_MIN_REQUEST_INTERVAL_S)
    request = urllib.request.Request(SEC_TICKERS_URL, headers={"User-Agent": ua})
    with urllib.request.urlopen(request, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_ticker_map(raw: dict) -> dict[str, str]:
    """Normalise EDGAR's payload into {TICKER: '0000000000'} (10-digit CIK).

    Pure function with no network access; this is the seam the tests drive.
    """
    ticker_map: dict[str, str] = {}
    for entry in raw.values():
        ticker = str(entry["ticker"]).upper()
        ticker_map[ticker] = f"{int(entry['cik_str']):010d}"
    return ticker_map


def resolve_ciks(
    companies: list[dict], ticker_map: dict[str, str]
) -> tuple[dict[str, str | None], list[str]]:
    """Resolve a CIK per company.

    Returns ``(resolved, unresolved)`` where ``resolved`` maps ticker -> CIK (or
    None for non-filers and misses) and ``unresolved`` lists SEC filers whose
    lookup symbol was not found in the EDGAR map.
    """
    resolved: dict[str, str | None] = {}
    unresolved: list[str] = []
    for company in companies:
        ticker = company["ticker"]
        if not int(company.get("is_sec_filer") or 0):
            resolved[ticker] = None  # Roche, Bayer: no SEC registration
            continue
        lookup = (company.get("us_adr_ticker") or "").strip() or ticker
        cik = ticker_map.get(lookup.upper())
        if cik is None:
            resolved[ticker] = None
            unresolved.append(ticker)
            logger.warning(
                "No CIK found for %s (lookup symbol %s); leaving null", ticker, lookup
            )
        else:
            resolved[ticker] = cik
    return resolved, unresolved


def run(db_path: str | Path | None = None) -> dict:
    """Full seed: init DB, load CSV, resolve CIKs, write them back, print a summary."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db.init(db_path)
    loaded = load_companies(db_path)

    raw = fetch_company_tickers()
    ticker_map = build_ticker_map(raw)

    conn = db.get_connection(db_path)
    try:
        companies = [
            dict(r)
            for r in conn.execute(
                "SELECT ticker, us_adr_ticker, is_sec_filer FROM companies"
            )
        ]
        resolved, unresolved = resolve_ciks(companies, ticker_map)
        for ticker, cik in resolved.items():
            conn.execute(
                "UPDATE companies SET cik=?, updated_at=datetime('now') WHERE ticker=?",
                (cik, ticker),
            )
        conn.commit()
        non_filers = [c["ticker"] for c in companies if not int(c["is_sec_filer"] or 0)]
    finally:
        conn.close()

    filled = sum(1 for c in resolved.values() if c is not None)
    print(f"Loaded {loaded} companies from {SEED_CSV.name}")
    print(f"Resolved CIKs for {filled} SEC filers")
    print(f"Skipped {len(non_filers)} non-filers (cik left null): {', '.join(non_filers)}")
    if unresolved:
        print(f"Unresolved tickers (cik left null): {', '.join(unresolved)}")
    else:
        print("All SEC filers resolved")

    return {
        "loaded": loaded,
        "resolved": filled,
        "non_filers": non_filers,
        "unresolved": unresolved,
    }


if __name__ == "__main__":
    run()
