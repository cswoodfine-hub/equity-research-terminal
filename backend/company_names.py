"""What each source calls a company, read from the company rather than a dictionary.

Five per-ticker maps lived across four fetcher modules, so adding a company meant
editing five Python files. The names belong to the company, so they are columns on it
now, loaded from the seed. Each fetcher asks here.

The hardcoded map stays as the fallback, which is what lets the original eighteen keep
working with no change to their rows and makes this a widening rather than a migration.
A company with nothing in the column and nothing in the map has no name at that source,
which is the ordinary case for a clinical-stage company with no approved product: it is
returned as None and the fetcher skips rather than inventing a query.
"""

from __future__ import annotations

import db

COLUMNS = ("ctgov_sponsor", "openfda_manufacturer", "openfda_sponsor",
           "orange_book_applicant", "purple_book_applicant")


def source_name(ticker: str, column: str, fallback=None, db_path=None):
    """The name this source knows the ticker by, or the fallback, or None.

    A cell holding "MERCK SHARP|MSD|MERCK" is several names for one company, which is
    how the Orange Book lists a filer that has changed its applicant string over the
    years; it comes back as a list so the caller can search each.
    """
    if column not in COLUMNS:
        raise ValueError(f"{column} is not a source name column")
    conn = db.get_connection(db_path)
    try:
        row = conn.execute(
            f"SELECT {column} FROM companies WHERE ticker = ?",
            (ticker.upper(),)).fetchone()
    finally:
        conn.close()
    value = (row[0] or "").strip() if row and row[0] else ""
    if not value:
        return fallback
    parts = [p.strip() for p in value.split("|") if p.strip()]
    return parts if len(parts) > 1 else parts[0]
