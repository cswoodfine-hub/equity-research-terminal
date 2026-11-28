"""The Lilly seeds written on 2026-11-27 bind to their assets and build.

Seven assets carried no forecast on the published book of that day: tersolisib (held
as three rows), EloraTZP, mazdutide (refused), amezosvatein and bimagrumab (bought with
Curevo and Versanis), BPL-003 (bought with AtaiBeckley) and LY4515100 (its seed bound to
nothing). Each now has a seed in the book's shape. These tests read the built book, as
the unloaded seeds test does, and skip without one: a seed that stops binding or stops
building is the gap this work closed coming back.
"""

import pytest

import assumptions as A
import db
import forecast

# brand in the seed file, the file, and the launch year each file states
SEEDS = (
    ("Tersolisib", "lly_tersolisib.csv", 2031),
    ("EloraTZP", "lly_eloratzp.csv", 2031),
    ("mazdutide", "lly_ly3305677.csv", 2032),
    ("amezosvatein", "lly_amezosvatein.csv", 2032),
    ("BPL-003", "lly_bpl_003.csv", 2031),
    ("Bimagrumab", "lly_bimagrumab.csv", 2032),
    ("LY4515100", "lly_ly4515100.csv", 2031),
)


def _conn():
    if not db.DB_PATH.exists():
        pytest.skip(f"no built database at {db.DB_PATH}")
    return db.get_connection()


def _asset(conn, brand):
    return conn.execute(
        """SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
            WHERE c.ticker = 'LLY' AND (LOWER(TRIM(COALESCE(a.brand_name, ''))) = LOWER(?)
                   OR LOWER(TRIM(COALESCE(a.generic_name, ''))) = LOWER(?))""",
        (brand, brand)).fetchall()


@pytest.mark.parametrize("brand, file, launch", SEEDS)
def test_the_seed_binds_to_one_lilly_asset_and_builds(brand, file, launch):
    conn = _conn()
    try:
        found = _asset(conn, brand)
        assert len(found) == 1, f"{file}: {len(found)} Lilly assets answer to {brand!r}"
        inputs = A.load(conn, found[0]["id"])
        assert inputs["scalars"].get("forecast_start_year") == launch, (
            f"{file}: the book holds launch {inputs['scalars'].get('forecast_start_year')}, "
            f"the file says {launch}; has the seed loaded?")
        try:
            built = forecast.build(inputs)
        except forecast.ForecastError as err:
            pytest.fail(f"{file} refused: {err.missing}")
        assert built.get("rnpv") and built["rnpv"] > 0, f"{file} builds to nothing"
        assert max(built.get("revenue") or [0]) > 0
    finally:
        conn.close()


def test_every_seed_file_is_on_disk():
    for _brand, file, _launch in SEEDS:
        assert (A.SEED_DIR / file).exists(), file
