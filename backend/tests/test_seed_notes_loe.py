"""A year a seed's horizon note states agrees with the year the engine resolves.

A seed's forecast_years row says why its horizon is as long as it is, and most say "set
to run past the YYYY loss of exclusivity". The engine resolves that year itself
(loe.for_assets: the compound patent where the book flags one, the filer's own
biosimilar date, the statutory floor), and nothing held the two together. Lilly's
Mounjaro note said 2041 while the engine used the 2036 compound patent; Zepbound,
Taltz, Trulicity and Jardiance disagreed too. Measured across the universe on
2026-11-27, 98 of 210 notes disagreed with the engine. The Lilly five are corrected;
the rest are listed in data/loe_note_disagreements.txt so the list cannot grow
unnoticed, as data/unloaded_seed_files.txt does for seeds that bind to nothing. Reads
the built book and skips without one.
"""

from __future__ import annotations

import csv
import pathlib
import re

import pytest

import assumptions as A
import db
import loe

KNOWN = db.BACKEND_DIR.parent / "data" / "loe_note_disagreements.txt"
# "set to run past the 2036 loss of exclusivity", "three years past the 2032-05-31 loss
# of exclusivity", "the 2029 loss of exclusivity the engine resolves".
_YEAR_BEFORE = re.compile(r"\b(20\d\d)(?:-\d\d-\d\d)?[^.;]{0,40}?loss of exclusivity", re.I)
_YEAR_AFTER = re.compile(r"loss of exclusivity[^.;]{0,60}?\b(20\d\d)\b", re.I)


def stated_year(text: str) -> int | None:
    """The loss-of-exclusivity year a note states, or None where it states none."""
    for pattern in (_YEAR_BEFORE, _YEAR_AFTER):
        found = pattern.search(text or "")
        if found:
            return int(found.group(1))
    return None


def _asset(conn, ticker: str, brand: str):
    return conn.execute(
        """SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
            WHERE c.ticker = ? AND (LOWER(TRIM(a.brand_name)) = LOWER(?)
                   OR LOWER(TRIM(a.generic_name)) = LOWER(?))
            ORDER BY (LOWER(TRIM(COALESCE(a.brand_name, ''))) = LOWER(?)) DESC,
                     a.is_marketed DESC, a.id LIMIT 1""",
        (ticker, brand, brand, brand)).fetchone()


def disagreements(conn, directory=None) -> dict:
    """{seed file: (stated year, engine year)} for every horizon note whose year is
    not the engine's."""
    source_dir = pathlib.Path(directory) if directory else A.SEED_DIR
    resolved = loe.for_assets(conn)
    out = {}
    for path in sorted(source_dir.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            rows = csv.DictReader(line for line in handle if not line.lstrip().startswith("#"))
            for row in rows:
                if (row.get("key") or "").strip() != "forecast_years":
                    continue
                year = stated_year((row.get("note") or "") + " " + (row.get("source") or ""))
                if year is None:
                    continue
                asset = _asset(conn, (row.get("ticker") or "").strip().upper(),
                               (row.get("brand") or "").strip())
                if asset is None:
                    continue
                found = resolved.get(asset["id"]) or {}
                engine = int(found["date"][:4]) if found.get("date") else None
                if engine != year:
                    out[path.name] = (year, engine)
    return out


def test_the_year_a_horizon_note_states_is_the_year_the_engine_resolves():
    if not db.DB_PATH.exists():
        pytest.skip(f"no built database at {db.DB_PATH}")
    known = {line.split("#")[0].strip() for line in KNOWN.read_text().splitlines()
             if line.strip() and not line.startswith("#")}
    conn = db.get_connection()
    try:
        got = disagreements(conn)
    finally:
        conn.close()
    new = {f: v for f, v in got.items() if f not in known}
    assert not new, ("seed notes that state a loss-of-exclusivity year the engine does "
                     f"not resolve (file: stated, engine): {new}")
    fixed = known - set(got)
    assert not fixed, (f"these notes now agree with the engine, remove them from "
                       f"data/loe_note_disagreements.txt: {sorted(fixed)}")


def test_lilly_notes_agree():
    """The five corrected on 2026-11-27 stay corrected whatever the list holds."""
    if not db.DB_PATH.exists():
        pytest.skip(f"no built database at {db.DB_PATH}")
    conn = db.get_connection()
    try:
        got = disagreements(conn)
    finally:
        conn.close()
    assert not [f for f in got if f.startswith("lly_")], {f: got[f] for f in got
                                                           if f.startswith("lly_")}


@pytest.mark.parametrize("text, year", [
    ("set to run past the 2041 loss of exclusivity", 2041),
    ("long enough to carry the ramp and run past the 2036 loss of exclusivity on file", 2036),
    ("2026 to 2035, long enough to run three years past the 2032-05-31 loss of exclusivity "
     "the book holds", 2032),
    ("the engine's terminal value is a zero-growth perpetuity", None),
    ("no exclusivity on file", None),
])
def test_the_stated_year_is_read_from_the_note(text, year):
    assert stated_year(text) == year
