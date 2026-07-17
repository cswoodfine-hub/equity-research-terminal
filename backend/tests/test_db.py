"""db.init() must create every table declared in schema.sql and be idempotent."""

import re

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
