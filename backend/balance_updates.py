"""A balance sheet the filer has published that EDGAR's structured data does not carry.

Every stock line the valuation reads comes from the companyfacts API, which is the right
default: it is the filer's own tagged data and it needs no reading. It lags, though, and
the lag is worst exactly where it matters most. Biogen filed its second-quarter 10-Q on
29 July 2026 carrying the Apellis acquisition, $5.3bn of cash paid and $2.0bn of new term
debt, and seven weeks later companyfacts still ended at the March quarter. The model
netted $1,540mm of debt against a price that already knew about $6,805mm.

So a balance sheet line an analyst has read off a filing can be carried here, with its
caption, its accession and a verbatim quote, until the structured data catches up. The
rows are insert-only against the same unique key the fetcher writes on, so companyfacts
always wins: the day EDGAR tags the period, the fetcher's value replaces this one and the
row here stops doing anything. Nothing is derived and nothing is summed; each row is a
line as printed, because a net figure cannot be checked against the filing.
"""

from __future__ import annotations

import csv
import pathlib

DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "balance_sheet_updates.csv"
SOURCE = "filing"


def rows(path=None) -> list[dict]:
    """The curated rows, each {ticker, period_end, metric, value, unit, accession,
    caption, quote}. Value is in units, converted from the file's millions."""
    source = pathlib.Path(path) if path else DATA
    if not source.exists():
        return []
    out = []
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(line for line in handle
                                  if not line.lstrip().startswith("#")):
            ticker = (row.get("ticker") or "").strip().upper()
            metric = (row.get("metric") or "").strip()
            period_end = (row.get("period_end") or "").strip()
            value = (row.get("value_musd") or "").strip()
            if not (ticker and metric and period_end and value):
                continue
            out.append({"ticker": ticker, "period_end": period_end, "metric": metric,
                        "value": float(value) * 1e6,
                        "unit": (row.get("unit") or "USD").strip() or "USD",
                        "accession": (row.get("accession") or "").strip(),
                        "caption": (row.get("caption") or "").strip(),
                        "quote": (row.get("quote") or "").strip()})
    return out


def load(conn, path=None) -> dict:
    """Write the curated rows into ``financials`` as balance sheet instants. Insert-only:
    a period the filer's structured data already carries is left alone, so this never
    overwrites companyfacts. Returns {written, skipped}."""
    written = skipped = 0
    for row in rows(path):
        company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                               (row["ticker"],)).fetchone()
        if company is None:
            skipped += 1
            continue
        cursor = conn.execute(
            """INSERT INTO financials (company_id, period_end, period_type, metric, value,
                                       unit, fiscal_year, fiscal_period, source, accession)
               VALUES (?, ?, 'instant', ?, ?, ?, ?, NULL, ?, ?)
               ON CONFLICT(company_id, metric, period_end, period_type) DO NOTHING""",
            (company["id"], row["period_end"], row["metric"], row["value"], row["unit"],
             int(row["period_end"][:4]), SOURCE, row["accession"]))
        written += cursor.rowcount
        skipped += 1 - cursor.rowcount
    conn.commit()
    return {"written": written, "skipped": skipped}
