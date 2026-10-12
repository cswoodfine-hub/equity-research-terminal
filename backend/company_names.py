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

import re

import db

COLUMNS = ("ctgov_sponsor", "openfda_manufacturer", "openfda_sponsor",
           "orange_book_applicant", "purple_book_applicant")

# A legal suffix the press leaves off. "Novartis AG" in quotes found 88 headlines, the
# newest five weeks old, and not one of the Abogen licence's dozen (2026-10-07): a headline
# says Novartis.
LEGAL_SUFFIX = re.compile(
    r"[,\s]+(?:Inc\.?|Incorporated|Corp\.?|Corporation|Co\.?|Company|PLC|plc|AG|A/S|"
    r"S\.?A\.?|SE|N\.?V\.?|Ltd\.?|Limited|Holdings?|and|&)$")
# Where the press name is not the legal name less its suffix: "Lilly" and "Gilead" lead a
# headline, and Bristol Myers Squibb dropped its hyphen in 2020. The news deal search and
# the acquired-sponsor check both read a headline by these names, so they live here.
PRESS_NAMES = {
    "LLY": ("Eli Lilly", "Lilly"), "GILD": ("Gilead",), "REGN": ("Regeneron",),
    "BMY": ("Bristol Myers Squibb", "Bristol-Myers Squibb"), "MRK": ("Merck",),
    "JNJ": ("Johnson & Johnson", "J&J"), "ROG": ("Roche",),
}


def bare(name: str) -> str:
    """A name less its legal suffixes: "Eli Lilly and Company" is "Eli Lilly"."""
    name = (name or "").strip()
    while True:
        short = LEGAL_SUFFIX.sub("", name.rstrip(" .,")).strip()
        if short == name or not short:
            return name
        name = short


def press_names(ticker: str, company_name: str) -> tuple:
    """The names a headline calls the company by, most formal first."""
    if ticker in PRESS_NAMES:
        return PRESS_NAMES[ticker]
    return (bare(company_name),)


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
