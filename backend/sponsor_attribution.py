"""Which company a study belongs to, by the registry's own lead sponsor.

The completed-studies fetch asks the registry for a company's studies by lead sponsor,
and until this module it believed the answer for the company's own name. Only studies
found through an acquired company's name were checked against the lead sponsor the
registry states. The query is looser than its name says, so partners' studies came back
as the company's own: Lilly held Pfizer's tanezumab studies and AstraZeneca's exenatide
studies, and Pfizer held Orexigen's naltrexone/bupropion studies, a company it never
owned. Every such row then bound to one of the wrong company's products.

The rule is one test for every study: the lead sponsor has to name the company, by its
registry name or its legal name, or one of the companies it acquired. The registry's
answer to whose study it is decides it, never the query that happened to return it.

    python -m sponsor_attribution           # the studies on file that fail the rule
"""

from __future__ import annotations

import argparse
import sys

import acquired_sponsors
import company_names
import ctgov
import db


def own_names(ticker: str, db_path=None) -> list:
    """Every name the company itself is known by in the registry: the lead-sponsor term
    it is searched under, and its legal name, which a subsidiary names as its parent."""
    ticker = ticker.upper()
    source = company_names.source_name(
        ticker, "ctgov_sponsor", ctgov.SPONSOR_LEAD.get(ticker), db_path)
    names = list(source) if isinstance(source, list) else [source]
    conn = db.get_connection(db_path)
    try:
        row = conn.execute("SELECT name FROM companies WHERE ticker = ?",
                           (ticker,)).fetchone()
    finally:
        conn.close()
    if row is not None:
        names.append(row["name"])
    return list(dict.fromkeys(n for n in names if n))


def names_for(ticker: str, db_path=None, today=None) -> list:
    """The company's own names and the names of the companies it recently acquired."""
    return own_names(ticker, db_path) + acquired_sponsors.for_company(
        db_path, ticker, today=today)


def misfiled(db_path=None, table: str = "completed_trials", today=None) -> list[dict]:
    """Studies on file whose stated lead sponsor names neither the company they are
    filed under nor any company it acquired. A study with no lead sponsor on file cannot
    be tested and is not reported."""
    if table not in ("completed_trials", "trials"):
        raise ValueError(f"{table} holds no sponsored studies")
    conn = db.get_connection(db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT t.nct_id, c.ticker, t.lead_sponsor, a.brand_name AS asset
              FROM {table} t
              JOIN companies c ON c.id = t.sponsor_company_id
              LEFT JOIN assets a ON a.id = t.asset_id
             WHERE t.lead_sponsor IS NOT NULL
             ORDER BY c.ticker, t.lead_sponsor, t.nct_id
            """).fetchall()
    finally:
        conn.close()
    names: dict = {}
    out = []
    for row in rows:
        if row["ticker"] not in names:
            names[row["ticker"]] = names_for(row["ticker"], db_path, today)
        if not ctgov.lead_names(row["lead_sponsor"], names[row["ticker"]]):
            out.append(dict(row))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", help="database path (default: the configured one)")
    parser.add_argument("--table", default="completed_trials",
                        choices=("completed_trials", "trials"))
    args = parser.parse_args(argv)
    rows = misfiled(args.db, args.table)
    for row in rows:
        print(f"{row['ticker']:<6} {row['nct_id']}  lead: {row['lead_sponsor']}"
              f"  asset: {row['asset'] or '-'}")
    print(f"{len(rows)} studies in {args.table} are led by a company that is not the "
          "one they are filed under", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
