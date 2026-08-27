"""The book: the one table that records what was believed rather than what happened.

The two verdicts are the point. A position can be right about the biology and lose money,
or wrong about it and make money, and a record that keeps only the second cannot tell
judgement from luck.
"""

import db


def _open(path):
    return db.get_connection(path)


def _row(conn, **kw):
    fields = {"ticker": "MRNA", "theme": "mRNA oncology",
              "entry_date": "2026-08-18", "entry_price": 62.96,
              "thesis": "INTerpath-001 reads out positive and the platform reprices",
              "market_implied": "a failed COVID franchise with no oncology option",
              "disconfirming": "RFS misses, or the effect is confined to Stage IV",
              "science_call": "open", "trade_call": "open"}
    fields.update(kw)
    cols = ", ".join(fields)
    marks = ", ".join("?" * len(fields))
    cur = conn.execute(f"INSERT INTO positions ({cols}) VALUES ({marks})",
                       tuple(fields.values()))
    conn.commit()
    return cur.lastrowid


def test_a_position_records_the_view_and_the_price_it_disagreed_with(tmp_path):
    path = tmp_path / "p.db"
    db.init(path)
    conn = _open(path)
    pid = _row(conn)

    row = conn.execute("SELECT * FROM positions WHERE id = ?", (pid,)).fetchone()
    assert row["ticker"] == "MRNA" and row["entry_price"] == 62.96
    # The counterfactual is kept, so the thesis stays falsifiable after the fact.
    assert "no oncology option" in row["market_implied"]
    # And what would have changed the analyst's mind, written while they still believed.
    assert "RFS misses" in row["disconfirming"]
    conn.close()


def test_the_science_call_and_the_trade_call_are_scored_apart(tmp_path):
    path = tmp_path / "p.db"
    db.init(path)
    conn = _open(path)
    # Right about the drug, wrong about the entry: bought after the move.
    pid = _row(conn, entry_date="2026-08-19", entry_price=174.38,
               exit_date="2026-08-20", exit_price=133.32,
               science_call="right", trade_call="wrong")

    row = conn.execute("SELECT * FROM positions WHERE id = ?", (pid,)).fetchone()
    assert (row["science_call"], row["trade_call"]) == ("right", "wrong")
    assert row["exit_price"] < row["entry_price"]
    conn.close()


def test_an_open_position_has_no_exit(tmp_path):
    path = tmp_path / "p.db"
    db.init(path)
    conn = _open(path)
    _row(conn)
    row = conn.execute("SELECT exit_date, exit_price FROM positions").fetchone()
    assert row["exit_date"] is None and row["exit_price"] is None
    conn.close()


def test_a_price_carries_the_currency_it_was_quoted_in(tmp_path):
    """Novo is quoted in kroner and Roche in francs. A bare price cannot be compared."""
    path = tmp_path / "p.db"
    db.init(path)
    conn = _open(path)
    _row(conn)
    assert conn.execute("SELECT currency FROM positions").fetchone()["currency"] == "USD"
    _row(conn, ticker="NVO", entry_price=372.4, currency="DKK")
    assert conn.execute("SELECT currency FROM positions WHERE ticker = 'NVO'"
                        ).fetchone()["currency"] == "DKK"
    conn.close()


def test_a_position_can_be_taken_in_something_the_universe_does_not_cover(tmp_path):
    # Free text rather than a companies foreign key, the same choice annotations made.
    # Refusing the entry because the coverage list is short would lose the one that
    # matters most.
    path = tmp_path / "p.db"
    db.init(path)
    conn = _open(path)
    _row(conn, ticker="NEWCO")
    assert conn.execute("SELECT COUNT(*) FROM positions WHERE ticker = 'NEWCO'"
                        ).fetchone()[0] == 1
    conn.close()


def test_the_migration_runs_exactly_once(tmp_path):
    path = tmp_path / "p.db"
    db.init(path)
    db.init(path)
    conn = _open(path)
    applied = conn.execute("SELECT COUNT(*) FROM schema_migrations"
                           " WHERE filename = '044_positions.sql'").fetchone()[0]
    assert applied == 1
    conn.close()


# --- what the book made ----------------------------------------------------

def test_the_direction_decides_whether_a_fall_is_a_loss(tmp_path):
    """174 in and 133 out is a loss on a long and a gain on a short. The two prices are
    identical either way, which is why direction is a column and not a convention."""
    import positions
    path = tmp_path / "p.db"
    db.init(path)
    conn = _open(path)
    _row(conn, ticker="LONG", direction="long", entry_date="2026-08-19",
         entry_price=174.38, exit_date="2026-08-20", exit_price=133.32)
    _row(conn, ticker="SHORT", direction="short", entry_date="2026-08-19",
         entry_price=174.38, exit_date="2026-08-20", exit_price=133.32)
    conn.close()

    by = {p["ticker"]: p for p in positions.book(path)}
    assert round(by["LONG"]["return_pct"], 4) == -0.2355
    assert round(by["SHORT"]["return_pct"], 4) == 0.2355


def test_an_open_position_has_not_made_anything_yet(tmp_path):
    import positions
    path = tmp_path / "p.db"
    db.init(path)
    conn = _open(path)
    _row(conn)
    conn.close()

    p = positions.book(path)[0]
    assert p["is_open"] is True
    assert p["return_pct"] is None and p["exit_price_usd"] is None


def test_a_dollar_position_needs_no_conversion(tmp_path):
    import positions
    path = tmp_path / "p.db"
    db.init(path)
    conn = _open(path)
    _row(conn, entry_price=100.0, exit_date="2026-08-20", exit_price=110.0)
    conn.close()

    p = positions.book(path)[0]
    assert p["entry_price_usd"] == 100.0
    assert round(p["return_pct_usd"], 4) == round(p["return_pct"], 4) == 0.1
    assert p["fx_note"] is None


def _rate(conn, base, as_of, rate):
    conn.execute("INSERT INTO fx_rates (base, quote, rate, as_of)"
                 " VALUES (?, 'USD', ?, ?)", (base, rate, as_of))
    conn.commit()


def test_each_leg_converts_at_its_own_rate(tmp_path):
    """Converting both ends at one rate rescales them identically and hands back the
    local return wearing a dollar sign. The dollar return has to carry the currency
    move, or it is not the number a dollar investor experienced."""
    import positions
    path = tmp_path / "p.db"
    db.init(path)
    conn = _open(path)
    _rate(conn, "DKK", "2026-08-01", 0.16)
    _rate(conn, "DKK", "2026-08-20", 0.14)      # the krone fell between the two legs
    _row(conn, ticker="NVO", currency="DKK", entry_date="2026-08-01", entry_price=100.0,
         exit_date="2026-08-20", exit_price=110.0)
    conn.close()

    p = positions.book(path)[0]
    assert round(p["return_pct"], 4) == 0.1                  # up 10% in kroner
    assert p["entry_price_usd"] == 16.0 and round(p["exit_price_usd"], 4) == 15.4
    # And down in dollars, because the currency took more than the trade made.
    assert round(p["return_pct_usd"], 4) == -0.0375
    assert "each leg at its own rate" in p["fx_note"]


def test_a_rate_is_rolled_back_to_the_last_published_one(tmp_path):
    # Exit on a Saturday takes Friday's reference rate, not tomorrow's.
    import positions
    path = tmp_path / "p.db"
    db.init(path)
    conn = _open(path)
    _rate(conn, "DKK", "2026-08-21", 0.155)
    _row(conn, ticker="NVO", currency="DKK", entry_date="2026-08-22", entry_price=100.0)
    conn.close()

    p = positions.book(path)[0]
    assert p["fx_entry_rate_date"] == "2026-08-21"


def test_a_position_older_than_the_rate_history_is_told_so(tmp_path):
    """Never today's rate standing in for a rate nobody recorded."""
    import positions
    path = tmp_path / "p.db"
    db.init(path)
    conn = _open(path)
    _rate(conn, "DKK", "2026-08-20", 0.14)
    _row(conn, ticker="NVO", currency="DKK", entry_date="2024-01-05", entry_price=100.0,
         exit_date="2026-08-20", exit_price=110.0)
    conn.close()

    p = positions.book(path)[0]
    assert p["entry_price_usd"] is None
    assert p["return_pct_usd"] is None
    # The local return still stands, because the call was still right or wrong.
    assert round(p["return_pct"], 4) == 0.1
    assert "reference set begins" in p["fx_note"]


def test_the_book_can_be_read_for_one_name(tmp_path):
    import positions
    path = tmp_path / "p.db"
    db.init(path)
    conn = _open(path)
    _row(conn, ticker="MRNA")
    _row(conn, ticker="MRK")
    conn.close()
    assert [p["ticker"] for p in positions.book(path, ticker="mrk")] == ["MRK"]
