"""Migration 079: rows labelled with the year of their period end, relabelled once.

A 52/53-week year that ends in the first week of January belongs to the year before.
The parser now says so; this checks the rows it wrote before are put right, and that a
year holding two year ends is left for the refresh rather than guessed at.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import db

MIGRATION = Path(db.__file__).resolve().parent / "migrations" / \
    "079_fiscal_year_of_52_53_week_years.sql"


def _book(tmp_path) -> sqlite3.Connection:
    path = tmp_path / "book.db"
    db.init(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    for cid, ticker in ((1, "EXEL"), (2, "JNJ"), (3, "VRTX")):
        conn.execute("INSERT INTO companies (id, ticker, name) VALUES (?, ?, ?)",
                     (cid, ticker, ticker))
    conn.executemany("INSERT INTO assets (id, owner_company_id, brand_name) VALUES (?, ?, ?)",
                     [(10, 1, "Cabometyx"), (11, 1, "Cometriq"), (20, 2, "Darzalex")])
    # Totals as the old parser labelled them: by the year of the period end.
    totals = [(1, "2023-12-29", 2023, 1830.0), (1, "2025-01-03", 2025, 2169.0),
              (1, "2026-01-02", 2026, 2320.0),
              (2, "2023-01-01", 2023, 79990.0), (2, "2023-12-31", 2023, 85159.0)]
    conn.executemany(
        "INSERT INTO financials (company_id, period_end, period_type, metric, value,"
        " fiscal_year) VALUES (?, ?, 'FY', 'Revenues', ?, ?)",
        [(c, end, value, year) for c, end, year, value in totals])
    conn.execute("INSERT INTO financials (company_id, period_end, period_type, metric,"
                 " value, fiscal_year) VALUES (1, '2026-01-02', 'instant', 'Assets', 1, 2026)")
    # A December filer's opening balance on adopting a standard: the same moment as the
    # close the day before.
    conn.execute("INSERT INTO financials (company_id, period_end, period_type, metric,"
                 " value, fiscal_year) VALUES (3, '2018-01-01', 'instant', 'Assets', 1, 2018)")
    rows = [(10, 2026, "mdna_10k", 2113.4, 0), (11, 2026, "mdna_10k", 9.4, 0),
            (11, 2025, "filing_table", 9.4, 1),    # its right year, entered by hand
            (10, 2024, "sec_fsds", 1798.2, 0),     # the data sets round to the month
            (20, 2023, "mdna_10k", 9000.0, 0)]     # JNJ's 2023 holds two year ends
    conn.executemany("INSERT INTO asset_revenue (asset_id, fiscal_year, period, source,"
                     " value, is_curated) VALUES (?, ?, 'FY', ?, ?, ?)", rows)
    conn.commit()
    return conn


def test_the_old_labels_are_moved_to_the_year_each_period_belongs_to(tmp_path):
    conn = _book(tmp_path)
    conn.executescript(MIGRATION.read_text())
    years = {r["period_end"]: r["fiscal_year"] for r in conn.execute(
        "SELECT period_end, fiscal_year FROM financials WHERE company_id = 1"
        "  AND metric = 'Revenues'")}
    assert years == {"2023-12-29": 2023, "2025-01-03": 2024, "2026-01-02": 2025}
    jnj = {r["period_end"]: r["fiscal_year"] for r in conn.execute(
        "SELECT period_end, fiscal_year FROM financials WHERE company_id = 2")}
    assert jnj == {"2023-01-01": 2022, "2023-12-31": 2023}
    assert conn.execute("SELECT fiscal_year FROM financials WHERE company_id = 1"
                        "  AND period_type = 'instant'").fetchone()[0] == 2025
    assert conn.execute("SELECT fiscal_year FROM financials WHERE company_id = 3"
                        ).fetchone()[0] == 2017

    product = {(r["asset_id"], r["source"]): r["fiscal_year"] for r in conn.execute(
        "SELECT asset_id, fiscal_year, source FROM asset_revenue")}
    assert product[(10, "mdna_10k")] == 2025           # Cabometyx's fiscal 2025
    assert product[(10, "sec_fsds")] == 2024           # untouched: already right
    assert product[(20, "mdna_10k")] == 2023           # ambiguous: left for the refresh
    # Cometriq's mislabelled 2026 was its fiscal 2025, already entered by hand under
    # 2025, which outranks the filing: the duplicate goes and the hand entry stays.
    assert [tuple(r) for r in conn.execute(
        "SELECT fiscal_year, source FROM asset_revenue WHERE asset_id = 11")] == \
        [(2025, "filing_table")]
    assert conn.execute("SELECT COUNT(*) FROM asset_revenue WHERE fiscal_year < 0"
                        ).fetchone()[0] == 0


def test_run_twice_it_moves_nothing_further(tmp_path):
    """db.init records a migration once, but a second run must not shift a year again."""
    conn = _book(tmp_path)
    conn.executescript(MIGRATION.read_text())
    before = conn.execute("SELECT * FROM financials ORDER BY id").fetchall()
    product = conn.execute("SELECT * FROM asset_revenue ORDER BY id").fetchall()
    conn.executescript(MIGRATION.read_text())
    assert [tuple(r) for r in conn.execute("SELECT * FROM financials ORDER BY id")] == \
        [tuple(r) for r in before]
    assert [tuple(r) for r in conn.execute("SELECT * FROM asset_revenue ORDER BY id")] == \
        [tuple(r) for r in product]


def test_a_run_cut_off_partway_leaves_nothing_moved_to_be_moved_twice(tmp_path):
    """Its statements read the totals' old labels and then correct them. Committed one by
    one, a run stopped before the last statement left Cabometyx at 2025 with the totals
    still labelled the old way, and the next start moved it again onto the data sets'
    2024 row and deleted it. As one transaction a failed run moves nothing."""
    conn = _book(tmp_path)
    conn.execute("""CREATE TRIGGER cut_off BEFORE UPDATE OF fiscal_year ON financials
                    BEGIN SELECT RAISE(ABORT, 'cut off'); END""")
    conn.commit()
    try:
        conn.executescript(MIGRATION.read_text())
    except sqlite3.DatabaseError:
        conn.rollback()                    # what closing the connection would do
    assert conn.execute("SELECT fiscal_year FROM asset_revenue WHERE asset_id = 10"
                        "  AND source = 'mdna_10k'").fetchone()[0] == 2026
    conn.execute("DROP TRIGGER cut_off")
    conn.commit()
    conn.executescript(MIGRATION.read_text())
    assert [tuple(r) for r in conn.execute(
        "SELECT fiscal_year, source FROM asset_revenue WHERE asset_id = 10"
        " ORDER BY fiscal_year")] == [(2024, "sec_fsds"), (2025, "mdna_10k")]
