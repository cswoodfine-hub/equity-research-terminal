"""Lilly's rows in the naming registers resolve on the built book.

A register row that names an asset the book does not hold is inert: the alias map skips
a brand it cannot find, and programme_names skips a name no row answers to. Both say
so only in a count nobody reads, which is how a seed file sat bound to nothing for six
weeks (data/unloaded_seed_files.txt). These tests read the built book, as the unloaded
seeds test does, and skip without one.
"""

import csv

import pytest

import asset_merge
import db
import programme_alias


def _rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return [r for r in csv.DictReader(
            line for line in handle if not line.lstrip().startswith("#"))]


def _conn():
    if not db.DB_PATH.exists():
        pytest.skip(f"no built database at {db.DB_PATH}")
    return db.get_connection()


def _asset(conn, ticker, name):
    return conn.execute(
        """SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
            WHERE c.ticker = ? AND (LOWER(TRIM(COALESCE(a.brand_name, ''))) = LOWER(?)
                   OR LOWER(TRIM(COALESCE(a.generic_name, ''))) = LOWER(?)
                   OR LOWER(TRIM(COALESCE(a.internal_code, ''))) = LOWER(?)
                   OR a.id IN (SELECT asset_id FROM asset_aliases
                                WHERE LOWER(TRIM(internal_code)) = LOWER(?)))""",
        (ticker, name, name, name, name)).fetchall()


def test_every_lilly_alias_row_names_a_product_the_book_holds():
    conn = _conn()
    try:
        for row in _rows(programme_alias.CURATED):
            if row["ticker"].strip().upper() != "LLY":
                continue
            assert _asset(conn, "LLY", row["brand"].strip()), (
                f"asset_alias_map.csv: no Lilly asset answers to {row['brand']!r}, so the "
                f"row for {row['programme_name']!r} folds nothing")
    finally:
        conn.close()


def test_every_lilly_programme_name_has_taken_effect_or_can():
    """Once the merge has run, the INN is on the row; before it, the registry spelling
    is. Either way one Lilly asset answers to the row."""
    conn = _conn()
    try:
        for row in _rows(asset_merge.PROGRAMME_NAMES):
            if row["ticker"].strip().upper() != "LLY":
                continue
            found = _asset(conn, "LLY", row["inn"].strip()) or _asset(
                conn, "LLY", row["name"].strip())
            assert found, (f"programme_names.csv: no Lilly asset answers to "
                           f"{row['name']!r} or {row['inn']!r}")
    finally:
        conn.close()


def test_the_lilly_arms_the_registers_name_are_no_longer_pipeline_rows():
    """The fold and the rename have run on this book: tersolisib is one row and the
    abemaciclib dose arm of ADAPTcycle sits on Verzenio."""
    conn = _conn()
    try:
        tersolisib = _asset(conn, "LLY", "Tersolisib")
        assert len({r["id"] for r in tersolisib}) == 1
        for spelling in ("LY4064809", "STX-478"):
            assert {r["id"] for r in _asset(conn, "LLY", spelling)} == {tersolisib[0]["id"]}
        arm = conn.execute(
            "SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id"
            " WHERE c.ticker = 'LLY' AND a.generic_name LIKE 'Abemaciclib 50 MG%'").fetchall()
        assert not arm
    finally:
        conn.close()
