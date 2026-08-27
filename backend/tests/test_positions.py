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
