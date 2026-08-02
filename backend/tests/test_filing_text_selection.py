"""Which filings get read, and why recency alone is the wrong rule for a current report.

Abeona is the case. Its earnings release for the June 2025 quarter is the eleventh most
recent 8-K it filed, so a window of the most recent six never reached it, and the twelve
thousand characters stating its cash, its burn and the launch of its first approved
product went unread while ten director changes and shareholder votes were fetched.
"""

import db
import edgar_items
from fetchers.filing_text_edgar import (PER_FORM, RESULTS_RESERVED,
                                        FilingTextEdgarFetcher)


def test_reports_results_reads_the_stored_title():
    assert edgar_items.reports_results("Results of operations")
    # A filing carries several items and the title lists them all.
    assert edgar_items.reports_results(
        "Acquisition or disposition completed, Results of operations, Other events")
    assert not edgar_items.reports_results("Director or officer change")
    assert not edgar_items.reports_results("Shareholder vote")
    assert not edgar_items.reports_results(None)


def _seed(tmp_path, filings):
    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'ABEO', 'Abeona')")
    for i, (date, title) in enumerate(filings):
        conn.execute(
            "INSERT INTO filings (company_id, form_type, filed_date, accession, title, url)"
            " VALUES (1, '8-K', ?, ?, ?, ?)",
            (date, f"acc-{i}", title, f"https://sec.gov/{i}/form8-k.htm"))
    conn.commit()
    return path, conn


# Abeona's real 8-K history, newest first. Four earnings releases, all of them below the
# six most recent.
ABEONA = [
    ("2026-06-12", "Director or officer change"),
    ("2026-06-12", "Shareholder vote"),
    ("2026-06-10", "Regulation FD disclosure, Financial statements and exhibits"),
    ("2026-06-04", "Other events"),
    ("2026-05-13", "Results of operations"),
    ("2026-04-07", "Director or officer change"),
    ("2026-03-20", "Charter or bylaws amended, Financial statements and exhibits"),
    ("2026-03-17", "Results of operations"),
    ("2026-03-09", "Other events"),
    ("2025-11-12", "Results of operations"),
    ("2025-08-14", "Results of operations"),
    ("2025-07-18", "Material agreement signed, Direct financial obligation created"),
]


def test_every_reserved_slot_goes_to_an_earnings_release(tmp_path):
    path, conn = _seed(tmp_path, ABEONA)
    chosen = FilingTextEdgarFetcher("ABEO")._choose(conn, 1, "8-K")
    conn.close()
    results = [r for r in chosen if edgar_items.reports_results(r["title"])]
    assert len(results) == 4          # every one Abeona has filed, not just the newest
    assert len(chosen) == PER_FORM["8-K"]


def test_the_document_that_started_this_is_chosen(tmp_path):
    """2025-08-14, the eleventh most recent, stating 225.9m of cash and the quarter."""
    path, conn = _seed(tmp_path, ABEONA)
    chosen = FilingTextEdgarFetcher("ABEO")._choose(conn, 1, "8-K")
    conn.close()
    assert any(r["filed_date"] == "2025-08-14" for r in chosen)


def test_the_rest_of_the_budget_still_goes_to_the_newest(tmp_path):
    """Reserving slots for results must not stop the newest filings being read: a
    director change filed yesterday is how a leadership change is detected."""
    path, conn = _seed(tmp_path, ABEONA)
    chosen = FilingTextEdgarFetcher("ABEO")._choose(conn, 1, "8-K")
    conn.close()
    assert chosen[0]["filed_date"] == "2026-06-12"
    others = [r for r in chosen if not edgar_items.reports_results(r["title"])]
    assert [r["filed_date"] for r in others] == ["2026-06-12", "2026-06-12",
                                                 "2026-06-10", "2026-06-04"]


def test_a_company_that_files_only_results_is_not_padded(tmp_path):
    path, conn = _seed(tmp_path, [("2026-05-13", "Results of operations"),
                                  ("2026-03-17", "Results of operations")])
    chosen = FilingTextEdgarFetcher("ABEO")._choose(conn, 1, "8-K")
    conn.close()
    assert len(chosen) == 2


def test_a_company_that_files_no_results_falls_back_to_recency(tmp_path):
    path, conn = _seed(tmp_path, [("2026-05-13", "Other events"),
                                  ("2026-03-17", "Shareholder vote"),
                                  ("2026-01-02", "Director or officer change")])
    chosen = FilingTextEdgarFetcher("ABEO")._choose(conn, 1, "8-K")
    conn.close()
    assert [r["filed_date"] for r in chosen] == ["2026-05-13", "2026-03-17", "2026-01-02"]


def test_an_annual_report_is_still_chosen_by_recency(tmp_path):
    """The rule is for current reports only. There is one 10-K a year and the newest is
    always the one to read."""
    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'ABEO', 'Abeona')")
    for i, date in enumerate(["2026-03-17", "2025-03-20", "2024-03-15"]):
        conn.execute(
            "INSERT INTO filings (company_id, form_type, filed_date, accession, title, url)"
            " VALUES (1, '10-K', ?, ?, 'Annual report', ?)",
            (date, f"k-{i}", f"https://sec.gov/{i}/10k.htm"))
    conn.commit()
    chosen = FilingTextEdgarFetcher("ABEO")._choose(conn, 1, "10-K")
    conn.close()
    assert [r["filed_date"] for r in chosen] == ["2026-03-17", "2025-03-20"]


def test_the_reserve_fits_inside_the_budget():
    assert RESULTS_RESERVED <= PER_FORM["8-K"]
    assert RESULTS_RESERVED <= PER_FORM["6-K"]
