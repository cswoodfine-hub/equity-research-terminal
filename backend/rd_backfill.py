"""R&D spend from before XBRL, loaded from the filings it was read out of.

The launch productivity rate divides fresh revenue by the R&D that bought it. For the
denominator to sit where the spend actually happened it has to reach a development lag
back from the launches, and companyfacts could not take it there: it carries only tagged
facts, and tagging began with the 2009 mandate for US filers and years later for foreign
private issuers. The history stopped at 2007 for the Americans and at 2015 or 2016 for
AstraZeneca, Novartis, Novo, GSK and Sanofi.

The filings themselves go back decades and are free, so the missing years were read out of
them and curated into ``data/rd_history_pre_xbrl.csv``, one row per filer-year carrying
the accession and the line it was read from.

Insert-only, and that is the whole safety argument. A year the filer has tagged is never
overwritten by a year an analyst transcribed: the row is written only where nothing is on
file for that company, metric and period, so the curated figure fills a hole and can never
contradict a filed one. Re-running it is a no-op.
"""

from __future__ import annotations

import csv
import pathlib

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
CURATED = DATA_DIR / "rd_history_pre_xbrl.csv"
METRIC = "ResearchAndDevelopmentExpense"
SOURCE = "pre_xbrl_filing"
# A fiscal year end for a filer that does not close on 31 December. The period end is part
# of the table's unique key, so it has to match the shape the fetcher writes or the same
# year would be stored twice.
YEAR_END = {"JNJ": "-12-28"}


def rows(path=None) -> list[dict]:
    """[{ticker, fiscal_year, value, unit, source, quote}] from the curated file. Pure."""
    source = pathlib.Path(path) if path else CURATED
    if not source.exists():
        return []
    with source.open(newline="", encoding="utf-8") as handle:
        lines = [line for line in handle if not line.lstrip().startswith("#")]
    out = []
    for row in csv.DictReader(lines):
        ticker = (row.get("ticker") or "").strip().upper()
        try:
            year = int((row.get("fiscal_year") or "").strip())
            value = float((row.get("value_musd") or "").strip())
        except ValueError:
            continue
        if not ticker or value <= 0:
            continue
        out.append({"ticker": ticker, "fiscal_year": year, "value": value * 1e6,
                    "unit": (row.get("unit") or "USD").strip().upper(),
                    "source": (row.get("accession_or_url") or "").strip(),
                    "quote": (row.get("quote") or "").strip()})
    return out


def period_end(ticker: str, year: int) -> str:
    return f"{year}{YEAR_END.get(ticker.upper(), '-12-31')}"


def load(conn, path=None) -> dict:
    """Write the curated years into ``financials`` where nothing is on file for them."""
    companies = {r["ticker"].upper(): r["id"] for r in
                 conn.execute("SELECT id, ticker FROM companies WHERE ticker IS NOT NULL")}
    written = skipped = unknown = 0
    for row in rows(path):
        company_id = companies.get(row["ticker"])
        if company_id is None:
            unknown += 1
            continue
        end = period_end(row["ticker"], row["fiscal_year"])
        # A filed year is recognised by WHEN IT ENDS, not by its label. Johnson & Johnson's
        # 53-week fiscal 2009 ended on 3 January 2010 and companyfacts labels it 2010, so a
        # check on the label found no 2009 and wrote a second copy of a year that was
        # already there, and the productivity window summed it twice. Any filed FY row
        # ending within ten days of the curated one is the same year.
        held = conn.execute(
            """SELECT 1 FROM financials WHERE company_id = ? AND metric = ?
                AND period_type = 'FY' AND value IS NOT NULL
                AND (fiscal_year = ?
                     OR ABS(julianday(period_end) - julianday(?)) <= 10)""",
            (company_id, METRIC, row["fiscal_year"], end)).fetchone()
        if held:
            skipped += 1                      # the filer tagged it; the filing wins
            continue
        conn.execute(
            """INSERT INTO financials (company_id, period_end, period_type, metric, value,
                 unit, fiscal_year, fiscal_period, source, accession)
               VALUES (?, ?, 'FY', ?, ?, ?, ?, 'FY', ?, ?)
               ON CONFLICT(company_id, metric, period_end, period_type) DO NOTHING""",
            (company_id, end, METRIC, row["value"], row["unit"], row["fiscal_year"],
             SOURCE, row["source"][:200]))
        written += 1
    conn.commit()
    return {"written": written, "already_filed": skipped, "unknown_ticker": unknown}
