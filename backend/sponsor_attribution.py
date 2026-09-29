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
"""

from __future__ import annotations

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

