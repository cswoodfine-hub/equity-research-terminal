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


# --- a brand CMS only names by its container -------------------------------
_PRESENTATIONS = json.loads((_FIX / "cms_demand_presentations.json").read_text())


def _seed_presentation_assets(db_file):
    """Repatha, Fasenra and Lyrica as CMS's own 2024 Part D payload finds them."""
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    amgn = conn.execute("SELECT id FROM companies WHERE ticker='AMGN'").fetchone()[0]
    for brand, generic in (("Repatha", "Evolocumab"), ("Fasenra", "Benralizumab"),
                           ("Lyrica", "Pregabalin"), ("Esbriet", "Pirfenidone")):
        conn.execute("INSERT INTO assets (owner_company_id, brand_name, generic_name,"
                     " is_marketed) VALUES (?, ?, ?, 1)", (amgn, brand, generic))
    conn.commit()
    conn.close()


def test_base_brand_takes_a_container_and_leaves_a_different_product():
    from fetchers.demand_cms import base_brand
    # The same drug in a different box.
    assert base_brand("repatha sureclick") == "repatha"
    assert base_brand("repatha pushtronex system") == "repatha"
    assert base_brand("dupixent pen") == "dupixent"
    assert base_brand("cosentyx (2 syringes)") == "cosentyx"
    assert base_brand("victoza 2-pak") == "victoza"
    # Not the same drug in a different box.
    assert base_brand("lyrica cr") is None           # a release profile
    assert base_brand("arthrotec 50") is None        # a strength
    assert base_brand("haldol decanoate 100") is None  # a salt and a route
    assert base_brand("invega trinza") is None       # a separate long-acting product
    assert base_brand("vfend iv") is None            # a route
    assert base_brand("prevnar 20") is None          # a different vaccine
    assert base_brand("kisqali femara co-pack") is None   # leaves no name behind
    assert base_brand("repatha") is None             # nothing to strip


def test_presentations_of_one_molecule_are_summed_into_one_row(tmp_path):
    db_file = tmp_path / "t.db"
    _seed_presentation_assets(db_file)
    fetcher = DemandCmsFetcher(db_file)
    rows = fetcher.normalise([{**r, "_part": "D"} for r in _PRESENTATIONS])

    by_brand = {r["brand"]: r for r in rows if r["year"] == 2024}
    # CMS publishes no "Repatha" row at all, only three containers. Before this the
    # molecule had no demand series; now it has one, and it says how it was built.
    repatha = by_brand["Repatha (3 presentations)"]
    assert repatha["total_spending"] == 1709589708.1 + 195984122.84 + 56546546.3
    assert repatha["total_beneficiaries"] == 382461 + 58146 + 19325     # 459,932
    assert repatha["total_claims"] == 1943941 + 233776 + 68043
    assert "counted twice" in repatha["source"]
    assert "Repatha Sureclick" in repatha["source"]

    # Half of Fasenra was being dropped: the syringe matched and the pen did not.
    assert by_brand["Fasenra (2 presentations)"]["total_beneficiaries"] == 3087 + 8489

    # Lyrica CR is not Lyrica in a different box, so it is not folded into Lyrica. It
    # stays unmatched, as it was before, rather than being merged on a guess.
    assert not [r for r in rows if "Lyrica" in r["brand"]]


def test_one_row_per_asset_part_year_survives_the_sum(tmp_path):
    db_file = tmp_path / "t.db"
    _seed_presentation_assets(db_file)
    fetcher = DemandCmsFetcher(db_file)
    rows = fetcher.normalise([{**r, "_part": "D"} for r in _PRESENTATIONS])
    fetcher.upsert(rows)
    conn = db.get_connection(db_file)
    try:
        # Three Repatha containers, one stored row a year, and nothing overwritten.
        got = conn.execute(
            """SELECT d.year, d.total_beneficiaries FROM drug_demand d
                 JOIN assets a ON a.id = d.asset_id
                WHERE a.brand_name = 'Repatha' AND d.part = 'D' AND d.year = 2024"""
        ).fetchall()
        assert len(got) == 1 and got[0]["total_beneficiaries"] == 459932
    finally:
        conn.close()


def test_a_brand_is_not_blended_with_its_own_generic(tmp_path):
    """CMS lists Esbriet and Pirfenidone, and the generic fallback points both at one
    asset. They used to collide on the unique key and the last one written won, so the
    stored series depended on payload order. The branded row wins now, because the row is
    read as a branded price per beneficiary and a blend of brand and generic is neither."""
    db_file = tmp_path / "t.db"
    _seed_presentation_assets(db_file)
    fetcher = DemandCmsFetcher(db_file)
    rows = fetcher.normalise([{**r, "_part": "D"} for r in _PRESENTATIONS])
    esbriet = [r for r in rows if r["year"] == 2024 and r["brand"].startswith("Esbriet")]
    assert len(esbriet) == 1
    assert esbriet[0]["total_beneficiaries"] == 719          # not 719 + 9,121
    assert "not added in" in esbriet[0]["source"]
    assert "Pirfenidone" in esbriet[0]["source"]


def test_a_phase_of_a_course_is_not_a_container():
    """A starter pack is what the same patient takes before the maintenance pack, so
    adding its beneficiaries to theirs counts them twice and prices the drug too cheaply.
    A pack size is a real alternative and does add."""
    from fetchers.demand_cms import base_brand
    assert base_brand("venclexta starting pack") != "venclexta"
    assert base_brand("cobenfy starter pack") != "cobenfy"
    assert base_brand("tyvaso refill kit") is None
    assert base_brand("orenitram month 1 titration kt") is None
    assert base_brand("avonex (4 pack)") == "avonex"
    assert base_brand("victoza 2-pak") == "victoza"
