"""Reads over the stored filing sections.

For one company, the most recent filing of each form has its risk factors and MD&A
diffed against the previous filing of the same form. The counts drive the What Changed
feed; this returns the passages too, so the view can show the risk factors that were
actually added rather than only that some were.
"""

from __future__ import annotations

import db
import filingtext

FORMS = ("10-K", "10-Q")


def company_filing_diff(db_path, ticker: str) -> list[dict] | None:
    conn = db.get_connection(db_path)
    try:
        company = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (ticker.upper(),)).fetchone()
        if company is None:
            return None
        out = []
        for form in FORMS:
            for section in filingtext.SECTIONS:
                rows = conn.execute(
                    "SELECT accession, filed_date, text FROM filing_sections"
                    " WHERE company_id = ? AND form_type = ? AND section = ?"
                    " ORDER BY filed_date DESC, accession DESC LIMIT 2",
                    (company["id"], form, section)).fetchall()
                if not rows:
                    continue
                newest = rows[0]
                entry = {"form": form, "section": section,
                         "filed_date": newest["filed_date"],
                         "chars": len(newest["text"]), "prior_date": None,
                         "added": None, "removed": None, "ratio": None,
                         "added_passages": []}
                if len(rows) > 1:
                    prior = rows[1]
                    diff = filingtext.diff_sections(prior["text"], newest["text"])
                    entry.update(prior_date=prior["filed_date"], added=diff["added"],
                                 removed=diff["removed"], ratio=diff["ratio"],
                                 added_passages=diff["added_passages"])
                out.append(entry)
        return out
    finally:
        conn.close()
