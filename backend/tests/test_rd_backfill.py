"""R&D from before XBRL, and the rule that a filed year always wins."""

from __future__ import annotations

import db
import rd_backfill as RB


def _db(tmp_path):
    path = str(tmp_path / "rd.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1,'MRK','Merck'),"
                 " (2,'AZN','AstraZeneca')")
    conn.commit()
    return conn


def _file(tmp_path, body):
    path = tmp_path / "rd.csv"
    path.write_text("# a comment\nticker,fiscal_year,value_musd,unit,accession_or_url,quote\n"
                    + body)
    return path


def test_rows_read_millions_of_the_filers_own_currency(tmp_path):
    path = _file(tmp_path, "AZN,2006,3902,USD,acc 0000950103-09-000555,R&D 3902\n"
                           "GSK,2006,3457,GBP,acc 1,R&D 3457\n"
                           "BAD,2006,notanumber,USD,acc 2,\n")
    got = RB.rows(path)
    assert [(r["ticker"], r["value"], r["unit"]) for r in got] == \
        [("AZN", 3902e6, "USD"), ("GSK", 3457e6, "GBP")]


def test_a_year_the_filer_tagged_is_never_overwritten(tmp_path):
    """The whole safety argument: a curated figure fills a hole, it never contradicts."""
    conn = _db(tmp_path)
    conn.execute("""INSERT INTO financials (company_id, period_end, period_type, metric,
        value, unit, fiscal_year, fiscal_period, source)
        VALUES (1, '2007-12-31', 'FY', 'ResearchAndDevelopmentExpense', 4882800000.0,
                'USD', 2007, 'FY', 'edgar_companyfacts')""")
    conn.commit()
    path = _file(tmp_path, "MRK,2006,4782.9,USD,acc 0000950123-09-003688,R&D 4782.9\n"
                           "MRK,2007,9999,USD,acc wrong,should never land\n")
    got = RB.load(conn, path)
    assert got == {"written": 1, "already_filed": 1, "unknown_ticker": 0}
    held = dict(conn.execute("""SELECT fiscal_year, value FROM financials
        WHERE company_id=1 AND metric='ResearchAndDevelopmentExpense'""").fetchall())
    assert held[2007] == 4882800000.0          # the filed figure stands
    assert held[2006] == 4782900000.0          # the hole is filled
    conn.close()


def test_running_it_twice_changes_nothing(tmp_path):
    conn = _db(tmp_path)
    path = _file(tmp_path, "AZN,2006,3902,USD,acc 0000950103-09-000555,R&D 3902\n")
    first = RB.load(conn, path)
    second = RB.load(conn, path)
    assert first["written"] == 1 and second["written"] == 0
    assert conn.execute("SELECT COUNT(*) FROM financials").fetchone()[0] == 1
    conn.close()


def test_a_ticker_the_book_does_not_hold_is_counted_not_crashed(tmp_path):
    conn = _db(tmp_path)
    path = _file(tmp_path, "ZZZZ,2006,100,USD,acc 1,\n")
    assert RB.load(conn, path)["unknown_ticker"] == 1
    conn.close()


def test_a_filer_whose_year_does_not_end_in_december(tmp_path):
    """The period end is part of the table's unique key, so it must match the shape the
    fetcher writes or the same year lands twice."""
    assert RB.period_end("JNJ", 2006) == "2006-12-28"
    assert RB.period_end("MRK", 2006) == "2006-12-31"


def test_the_committed_file_carries_a_source_on_every_row():
    got = RB.rows()
    assert got, "the curated pre-XBRL file read nothing"
    for row in got:
        assert row["source"], f"{row['ticker']} {row['fiscal_year']} has no source"
        assert 1e7 < row["value"] < 2e10, (row["ticker"], row["fiscal_year"], row["value"])
    # Schering-Plough's figures must never appear under Merck: its FY2006 R&D was 2,188mm.
    merck = {r["fiscal_year"]: r["value"] for r in got if r["ticker"] == "MRK"}
    assert merck.get(2006) == 4782.9e6, "MRK 2006 must be old Merck & Co, not Schering-Plough"


def test_a_year_filed_under_a_53_week_label_is_recognised_by_when_it_ends(tmp_path):
    """Johnson & Johnson's fiscal 2009 ended on 3 January 2010 and companyfacts labels it
    2010. A check on the label saw a hole and wrote a second copy, which the productivity
    window then summed twice. The filed year is recognised by its period end."""
    conn = _db(tmp_path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (3, 'JNJ', 'J&J')")
    conn.execute("""INSERT INTO financials (company_id, period_end, period_type, metric,
        value, unit, fiscal_year, fiscal_period, source)
        VALUES (3, '2010-01-03', 'FY', 'ResearchAndDevelopmentExpense', 6986000000.0,
                'USD', 2010, 'FY', 'edgar_companyfacts')""")
    conn.commit()
    path = _file(tmp_path, "JNJ,2009,6986,USD,acc 0000950123-10-019392,Research expense 6986\n")
    got = RB.load(conn, path)
    assert got["written"] == 0 and got["already_filed"] == 1
    assert conn.execute("SELECT COUNT(*) FROM financials WHERE company_id=3").fetchone()[0] == 1
    conn.close()


def test_the_committed_file_holds_no_johnson_and_johnson_53_week_years():
    years = {r["fiscal_year"] for r in RB.rows() if r["ticker"] == "JNJ"}
    assert 2009 not in years and 2015 not in years
