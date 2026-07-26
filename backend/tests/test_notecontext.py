"""The company snapshot the morning note leads with. Pure DB read, no network."""

import datetime as dt

import db
import notecontext
import seed


def _company(conn, ticker):
    return conn.execute("SELECT id FROM companies WHERE ticker = ?",
                        (ticker.upper(),)).fetchone()[0]


def _seed(db_file):
    db.init(db_file)
    seed.load_companies(db_file)
    return db_file


def _fin(conn, cid, metric, year, value, unit="USD"):
    conn.execute(
        "INSERT INTO financials (company_id, period_end, period_type, metric, value,"
        " unit, fiscal_year, fiscal_period, source) VALUES (?, ?, 'FY', ?, ?, ?, ?,"
        " '12M', 'test')",
        (cid, f"{year}-12-31", metric, value, unit, year))


def test_context_is_empty_for_unknown_ticker(tmp_path):
    _seed(tmp_path / "t.db")
    assert notecontext.company_context(tmp_path / "t.db", "ZZZZ") == ""


def test_context_is_empty_when_nothing_is_stored(tmp_path):
    _seed(tmp_path / "t.db")
    assert notecontext.company_context(tmp_path / "t.db", "LLY") == ""


def test_financials_line_carries_the_year_on_year_change(tmp_path):
    db_file = _seed(tmp_path / "t.db")
    conn = db.get_connection(db_file)
    cid = _company(conn, "LLY")
    _fin(conn, cid, "Revenues", 2024, 45.0e9)
    _fin(conn, cid, "Revenues", 2025, 65.2e9)
    _fin(conn, cid, "NetIncomeLoss", 2025, 20.6e9)
    conn.commit()
    conn.close()

    out = notecontext.company_context(db_file, "LLY")
    assert "Revenue FY2025 65.2B USD, +45% vs FY2024." in out
    assert "Net income FY2025 20.6B USD." in out       # no prior year, so no ratio


def test_year_on_year_uses_the_year_before_not_the_second_row(tmp_path):
    """A gap in the reported history must not mislabel the comparison."""
    db_file = _seed(tmp_path / "t.db")
    conn = db.get_connection(db_file)
    cid = _company(conn, "LLY")
    _fin(conn, cid, "Revenues", 2022, 20.0e9)          # a hole in 2024
    _fin(conn, cid, "Revenues", 2025, 65.2e9)
    conn.commit()
    conn.close()

    out = notecontext.company_context(db_file, "LLY")
    assert "Revenue FY2025 65.2B USD." in out           # 2024 absent, so no percentage


def test_foreign_filer_keeps_its_reporting_currency(tmp_path):
    db_file = _seed(tmp_path / "t.db")
    conn = db.get_connection(db_file)
    cid = _company(conn, "NVO")
    _fin(conn, cid, "Revenues", 2024, 290.0e9, unit="DKK")
    _fin(conn, cid, "Revenues", 2025, 309.1e9, unit="DKK")
    conn.commit()
    conn.close()

    out = notecontext.company_context(db_file, "NVO")
    assert "309.1B DKK" in out and "USD" not in out


def test_quarter_line_matches_the_year_ago_quarter_by_date_window(tmp_path):
    db_file = _seed(tmp_path / "t.db")
    conn = db.get_connection(db_file)
    cid = _company(conn, "LLY")
    for end, value in (("2025-03-31", 12.7e9), ("2026-03-31", 19.8e9)):
        conn.execute(
            "INSERT INTO financials (company_id, period_end, period_type, metric, value,"
            " unit, fiscal_period, source) VALUES (?, ?, 'Q', 'Revenues', ?, 'USD', '3M',"
            " 'test')", (cid, end, value))
    conn.commit()
    conn.close()

    out = notecontext.company_context(db_file, "LLY")
    assert "Q ending 2026-03-31 revenue 19.8B USD, +56% YoY." in out


def test_price_line_reports_the_move_over_a_month_and_a_quarter(tmp_path):
    db_file = _seed(tmp_path / "t.db")
    conn = db.get_connection(db_file)
    cid = _company(conn, "LLY")
    # 64 daily bars, newest last; 100 sixty-three bars back up to 130 at the last bar.
    base = dt.date(2026, 1, 1)
    closes = [100 + i * 0.5 for i in range(64)]       # 100.0 .. 131.5
    for i, close in enumerate(closes):
        conn.execute("INSERT INTO prices (company_id, as_of, close, interval, source)"
                     " VALUES (?, ?, ?, '1d', 'test')",
                     (cid, (base + dt.timedelta(days=i)).isoformat(), close))
    conn.commit()
    conn.close()

    out = notecontext.company_context(db_file, "LLY")
    assert "Share price: last close 131.50" in out
    assert "over 3 months" in out


def test_signed_trial_readouts_appear_recent_first(tmp_path):
    db_file = _seed(tmp_path / "t.db")
    conn = db.get_connection(db_file)
    cid = _company(conn, "NVO")
    today = dt.date(2026, 7, 26)
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase,"
                 " outcome, event_date) VALUES ('a1', ?, 'CagriSema', 3, 'negative',"
                 " '2026-02-23')", (cid,))
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase,"
                 " outcome, event_date) VALUES ('a2', ?, 'nothing', 3, 'none',"
                 " '2026-03-01')", (cid,))          # read, no readout: excluded
    conn.commit()
    conn.close()

    out = notecontext.company_context(db_file, "NVO", today=today)
    assert "Phase 3 negative readout for CagriSema (2026-02-23)." in out
    assert "nothing" not in out


def _news(conn, cid, title, date):
    conn.execute("INSERT INTO news (company_id, source, title, url, published_at)"
                 " VALUES (?, 'test', ?, ?, ?)", (cid, title, f"u{date}{title[:6]}", date))


def test_deal_headlines_are_named_and_stages_collapse(tmp_path):
    """The IR headline names the counterparty, and the three stages of one acquisition
    (agreed, tendered, completed) collapse to the latest, while a separate deal stays."""
    db_file = _seed(tmp_path / "t.db")
    conn = db.get_connection(db_file)
    cid = _company(conn, "GSK")
    today = dt.date(2026, 7, 26)
    _news(conn, cid, "6-K: GSK ENTERS AGREEMENT TO ACQUIRE NUVALENT, INC.", "2026-06-09")
    _news(conn, cid, "6-K: GSK ANNOUNCES TENDER OFFER TO ACQUIRE NUVALENT", "2026-06-24")
    _news(conn, cid, "6-K: GSK COMPLETES ACQUISITION OF NUVALENT, INC", "2026-07-15")
    _news(conn, cid, "6-K: COLLABORATION WITH CTTQ FOR BEPIROVIRSEN", "2026-05-11")
    _news(conn, cid, "6-K: DIRECTOR/PDMR SHAREHOLDING", "2026-07-20")   # not a deal
    conn.commit()
    conn.close()

    lines = notecontext._deal_lines(db.get_connection(db_file), _company(
        db.get_connection(db_file), "GSK"), today)
    joined = " ".join(lines)
    assert "COMPLETES ACQUISITION OF NUVALENT" in joined            # latest stage kept
    assert "TENDER OFFER" not in joined and "ENTERS AGREEMENT" not in joined  # collapsed
    assert "COLLABORATION WITH CTTQ" in joined                      # a separate deal
    assert "SHAREHOLDING" not in joined                             # not a deal
    assert "6-K:" not in joined                                     # form prefix stripped


def test_deals_are_absent_when_only_routine_news(tmp_path):
    db_file = _seed(tmp_path / "t.db")
    conn = db.get_connection(db_file)
    cid = _company(conn, "MRK")
    _news(conn, cid, "8-K: Results of Operations", "2026-07-01")
    _news(conn, cid, "8-K: Director or officer change", "2026-07-02")
    conn.commit()
    conn.close()
    assert "Recent deals" not in notecontext.company_context(db_file, "MRK")
