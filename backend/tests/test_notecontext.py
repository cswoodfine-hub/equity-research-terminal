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


def _deal(conn, cid, acc, dtype, counterparty, date, value=None, area=None):
    conn.execute("INSERT INTO deals (accession, company_id, deal_type, counterparty,"
                 " announced_value, area, event_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (acc, cid, dtype, counterparty, value, area, date))


def test_deals_merge_to_the_earliest_date_with_the_stated_value(tmp_path):
    """One acquisition is filed twice: the earlier agreement names no price, the later
    completion names it. The deal reads once, dated to the earlier filing (when the
    market first saw it) but carrying the value from the later one. A separate deal stays;
    a filing read as no deal never shows."""
    db_file = _seed(tmp_path / "t.db")
    conn = db.get_connection(db_file)
    cid = _company(conn, "BIIB")
    today = dt.date(2026, 7, 26)
    _deal(conn, cid, "a0", "acquisition", "Apellis Pharmaceuticals, Inc.", "2026-04-02")
    _deal(conn, cid, "a1", "acquisition", "Apellis Pharmaceuticals, Inc.", "2026-05-14",
          value="$41 per share", area="complement-driven diseases")
    _deal(conn, cid, "b1", "licensing", "HI-Bio", "2026-02-10", area="IgA nephropathy")
    _deal(conn, cid, "c1", "none", None, "2026-03-01")                 # read, no deal
    conn.commit()
    conn.close()

    out = notecontext.company_context(db_file, "BIIB", today=today)
    assert ("Acquired Apellis Pharmaceuticals, Inc. for $41 per share "
            "(complement-driven diseases), 2026-04-02." in out)     # earliest date, later value
    assert out.count("Apellis") == 1                                  # filed twice, read once
    assert "Licensing deal with HI-Bio (IgA nephropathy), 2026-02-10." in out


def test_deals_absent_when_nothing_stored(tmp_path):
    db_file = _seed(tmp_path / "t.db")
    conn = db.get_connection(db_file)
    _deal(conn, _company(conn, "MRK"), "z1", "none", None, "2026-07-01")  # read, no deal
    conn.commit()
    conn.close()
    assert "Recent deals" not in notecontext.company_context(db_file, "MRK")


def test_deal_areas_read_against_the_pipeline(tmp_path):
    import notecontext
    path = str(tmp_path / "areas.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('LLY', 'Eli Lilly')")
    cid = conn.execute("SELECT id FROM companies").fetchone()["id"]
    # One unapproved compound in neuroscience, none in haematology.
    conn.execute("INSERT INTO assets (owner_company_id, generic_name, is_marketed)"
                 " VALUES (?, 'LY000001', 0)", (cid,))
    aid = conn.execute("SELECT id FROM assets").fetchone()["id"]
    conn.execute("INSERT INTO trials (nct_id, asset_id, title, phase, conditions)"
                 " VALUES ('NCT01', ?, 'A study', 'Phase 2',"
                 " '[\"Alzheimer Disease\"]')", (aid,))
    conn.commit()

    lines = notecontext._deal_area_lines(conn, cid, [
        {"counterparty": "AtaiBeckley", "area": "treatment-resistant depression",
         "quote": "Lilly to acquire AtaiBeckley"},
        {"counterparty": "Ajax Therapeutics", "area": "myelofibrosis", "quote": ""},
        # A modality is not a disease, so this one is left out rather than guessed.
        {"counterparty": "Kelonia", "area": "in vivo CAR-T cell therapies",
         "quote": "Eli Lilly Enters Agreement to Acquire Kelonia"},
    ])
    conn.close()
    assert lines == [
        "AtaiBeckley is Neuroscience, where it already runs 1 compound.",
        "Ajax Therapeutics is Haematology, where it runs none, so the deal is an entry.",
    ]


def test_the_note_gets_the_structure_not_the_headline_figure(tmp_path):
    """"Collaboration with Sail for $2.58 billion" and "for 785m upfront, of which 465m is
    equity, and 2.58bn only on the option" are different sentences about one deal, and a
    note written from the first cannot say what the company is spending this year."""
    import db as _db
    import notecontext as _nc
    path = str(tmp_path / "note.db")
    _db.init(path)
    conn = _db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('JNJ', 'J&J')")
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    conn.execute(
        "INSERT INTO deals (company_id, deal_type, counterparty, event_date, quote,"
        "  announced_value, upfront_usd, equity_usd, milestones_usd, option_usd,"
        "  headline_usd) VALUES (?, 'collaboration', 'Sail Biomedicines', '2026-07-29',"
        "  'q', '$2.58 billion', 785e6, 465e6, 140e6, 2.58e9, 2.58e9)", (cid,))
    conn.commit()

    lines, _rows = _nc._deal_lines(conn, cid, dt.date(2026, 7, 30))
    conn.close()
    assert "785m upfront" in lines[0] and "$465m equity" in lines[0]


def test_the_note_falls_back_to_the_announced_figure(tmp_path):
    import db as _db
    import notecontext as _nc
    path = str(tmp_path / "note2.db")
    _db.init(path)
    conn = _db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('JNJ', 'J&J')")
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    conn.execute(
        "INSERT INTO deals (company_id, deal_type, counterparty, event_date, quote,"
        "  announced_value) VALUES (?, 'acquisition', 'Firefly Bio', '2026-06-08', 'q',"
        "  '$1 billion')", (cid,))
    conn.commit()

    lines, _rows = _nc._deal_lines(conn, cid, dt.date(2026, 6, 9))
    conn.close()
    assert "for $1 billion" in lines[0]
