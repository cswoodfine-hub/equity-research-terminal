"""db.init() must create every table declared in schema.sql and be idempotent, and it
must be the only caller that creates anything."""

import re

import pytest

import db


def _schema_table_names() -> set[str]:
    text = db.SCHEMA_PATH.read_text()
    return set(re.findall(r"CREATE\s+TABLE\s+(\w+)", text, flags=re.IGNORECASE))


def test_init_creates_every_schema_table(tmp_path):
    expected = _schema_table_names()
    assert expected, "no CREATE TABLE statements found in schema.sql"

    db_file = tmp_path / "test.db"
    db.init(db_file)

    conn = db.get_connection(db_file)
    try:
        existing = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()

    missing = expected - existing
    assert not missing, f"init() did not create tables: {sorted(missing)}"


def test_init_is_idempotent(tmp_path):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    db.init(db_file)  # must not raise on a second run


def test_opening_a_database_that_is_not_there_is_refused(tmp_path):
    """sqlite3.connect makes a file out of any path it is handed, so a call that put a
    ticker where a path belongs used to leave an empty database named AZN beside the real
    one and fail later on a missing table. Three of those reached the repository."""
    missing = tmp_path / "AZN"
    with pytest.raises(db.NoDatabase):
        db.get_connection(missing)
    assert not missing.exists(), "the refusal must not leave the file it refused"


def test_init_is_the_one_caller_that_may_create(tmp_path):
    path = tmp_path / "fresh.db"
    db.init(path)
    assert path.exists()
    conn = db.get_connection(path)
    conn.close()


def test_a_string_db_path_is_refused_the_same_way(tmp_path):
    with pytest.raises(db.NoDatabase):
        db.get_connection(str(tmp_path / "LLY"))


def test_the_default_path_is_honoured_when_a_test_replaces_it(tmp_path, monkeypatch):
    """DB_PATH is a module global a test may replace with a string, and the existence
    check has to cope with either."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "nothing-here.db"))
    with pytest.raises(db.NoDatabase):
        db.get_connection()
