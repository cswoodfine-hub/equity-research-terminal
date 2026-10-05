"""Migrations 080 and 081 apply once, are recorded, and a second init changes nothing."""

from __future__ import annotations

import db

_TABLES = ("drug_codes", "drug_code_lookups", "partd_prescribing",
           "partd_prescriber_specialties", "partd_prescriber_releases")


def test_payer_migrations_apply_once(tmp_path):
    path = tmp_path / "m.db"
    db.init(path)
    conn = db.get_connection(path)
    try:
        applied = {r[0] for r in conn.execute("SELECT filename FROM schema_migrations")}
        assert {"080_drug_codes.sql", "081_partd_prescribing.sql"} <= applied
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert set(_TABLES) <= tables
        conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'X', 'X')")
        conn.execute("INSERT INTO assets (id, owner_company_id) VALUES (1, 1)")
        conn.execute("INSERT INTO drug_codes (asset_id, code_type, code, basis)"
                     " VALUES (1, 'rxcui', '1', 'curated')")
        conn.commit()
    finally:
        conn.close()
    db.init(path)                                   # a second run is a no-op
    conn = db.get_connection(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM drug_codes").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE filename"
                            " IN ('080_drug_codes.sql', '081_partd_prescribing.sql')"
                            ).fetchone()[0] == 2
    finally:
        conn.close()
