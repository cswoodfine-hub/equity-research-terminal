"""CMS Medicare demand: parsing a spending row into a per-year series, matching a drug
to an asset by brand, and the company roll-up the view reads. No network."""

import json
from pathlib import Path

import cms
import db
import demand as demand_module
import seed
from fetchers.demand_cms import DemandCmsFetcher

_FIX = Path(__file__).resolve().parent / "fixtures"
_ROWS = json.loads((_FIX / "cms_demand.json").read_text())


# --- parsing --------------------------------------------------------------
def test_parse_row_yields_one_record_per_year_with_suppressed_as_null():
    records = cms.parse_row(_ROWS[0], "D")
    assert cms.years_in(_ROWS[0]) == [2023, 2024]
    assert len(records) == 2
    y2024 = next(r for r in records if r["year"] == 2024)
    assert y2024["total_spending"] == 2000.75
    assert y2024["total_claims"] == 80
    assert y2024["total_beneficiaries"] is None      # CMS suppressed, read as null
    assert y2024["part"] == "D"


def test_parse_row_skips_empty_brand():
    assert cms.parse_row(_ROWS[2], "D") == []        # no brand, nothing to attribute


# --- fetcher --------------------------------------------------------------
def _seed(db_file):
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    lly = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, generic_name,"
                 " is_marketed) VALUES (?, 'Zepbound', 'Tirzepatide', 1)", (lly,))
    conn.commit()
    conn.close()


def _raw(part="D"):
    return [{**r, "_part": part} for r in _ROWS]


def test_fetcher_matches_brand_to_asset_and_drops_the_rest(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    fetcher = DemandCmsFetcher(db_file)
    rows = fetcher.normalise(_raw("D"))
    # Only Zepbound is in the universe; the other drug and the empty brand are dropped.
    assert {r["brand"] for r in rows} == {"Zepbound"}
    assert {r["year"] for r in rows} == {2023, 2024}

    fetcher.upsert(rows)
    conn = db.get_connection(db_file)
    try:
        stored = conn.execute("SELECT COUNT(*) FROM drug_demand").fetchone()[0]
    finally:
        conn.close()
    assert stored == 2


def test_upsert_is_idempotent_on_asset_part_year(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    fetcher = DemandCmsFetcher(db_file)
    fetcher.upsert(fetcher.normalise(_raw("D")))
    fetcher.upsert(fetcher.normalise(_raw("D")))         # twice
    conn = db.get_connection(db_file)
    try:
        assert conn.execute("SELECT COUNT(*) FROM drug_demand").fetchone()[0] == 2
    finally:
        conn.close()


def test_company_demand_rolls_up_latest_prior_and_series(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    fetcher = DemandCmsFetcher(db_file)
    fetcher.upsert(fetcher.normalise(_raw("D")))

    drugs = demand_module.company_demand(db_file, "LLY")
    assert len(drugs) == 1
    z = drugs[0]
    assert z["brand"] == "Zepbound" and z["part"] == "D"
    assert z["latest_year"] == 2024
    assert z["spending"] == 2000.75
    assert z["prior_spending"] == 1000.50            # the year before, for direction
    assert z["beneficiaries"] is None                # 2024 was suppressed
    assert [p["year"] for p in z["series"]] == [2023, 2024]
