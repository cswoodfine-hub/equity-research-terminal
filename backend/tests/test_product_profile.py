"""product_profile assembly and curated-notes upsert over a seeded DB, no network."""

import db
import product_profile as pp
import seed


def _asset(conn, ticker, brand, modality="small molecule"):
    cid = conn.execute("SELECT id FROM companies WHERE ticker=?", (ticker,)).fetchone()[0]
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, generic_name,"
                 " modality, is_marketed) VALUES (?,?,?,?,1)",
                 (cid, brand, brand.lower(), modality))
    return conn.execute("SELECT id FROM assets WHERE brand_name=?", (brand,)).fetchone()[0]


def _seed_product(tmp_path):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    aid = _asset(conn, "LLY", "Testdrug")
    conn.execute("INSERT INTO approvals (asset_id, region, agency, approval_date,"
                 " application_number, source) VALUES (?, 'US', 'FDA', '2022-05-13',"
                 " 'NDA111', 'drugsfda')", (aid,))
    for expiry in ("2030-01-01", "2038-06-01"):
        conn.execute("INSERT INTO exclusivities (asset_id, protection_type, identifier,"
                     " expiry_date, source) VALUES (?, 'patent', 'X', ?, 'orange_book')",
                     (aid, expiry))
    conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, value, unit, source)"
                 " VALUES (?, 2025, 1000000000, 'USD', 'sec_fsds')", (aid,))
    for year, spend in ((2023, 100.0), (2024, 150.0)):
        conn.execute("INSERT INTO drug_demand (asset_id, part, brand_name, year,"
                     " total_spending, total_claims, total_beneficiaries, source)"
                     " VALUES (?, 'D', 'Testdrug', ?, ?, 10, 5, 'cms')", (aid, year, spend))
    conn.commit()
    conn.close()
    return db_file, aid


def test_profile_assembles_sourced_fields_and_merges_loe(tmp_path):
    db_file, aid = _seed_product(tmp_path)
    p = pp.product_profile(db_file, "LLY", aid)

    assert p["brand"] == "Testdrug"
    assert p["ticker"] == "LLY"
    assert p["first_approval"] == "2022-05-13"
    # LOE is the latest listed patent; the earliest is kept for the range.
    assert p["loe"]["loe_year"] == 2038
    assert p["loe"]["loe_earliest_year"] == 2030
    assert p["revenue"][0]["value"] == 1000000000
    # Demand is the latest year with the year-on-year direction from the one before.
    assert p["demand"]["year"] == 2024
    assert p["demand"]["spend"] == 150.0
    assert round(p["demand"]["spend_growth"], 2) == 0.50
    # No note written yet: every curated field is null, not a placeholder.
    assert p["notes"] == {"market_size": None, "peak_sales": None, "competitors": None,
                          "thesis": None, "updated_at": None}


def test_profile_is_scoped_to_the_owning_company(tmp_path):
    db_file, aid = _seed_product(tmp_path)
    # The asset belongs to LLY, so asking under another ticker must not leak it.
    assert pp.product_profile(db_file, "PFE", aid) is None
    assert pp.product_profile(db_file, "ZZZZ", aid) is None


def test_save_notes_upserts_and_blank_clears(tmp_path):
    db_file, aid = _seed_product(tmp_path)
    assert pp.save_notes(db_file, aid, {"market_size": "  ~$20bn US by 2030  ",
                                        "peak_sales": "", "competitors": "drugX, drugY",
                                        "thesis": None})
    notes = pp.product_profile(db_file, "LLY", aid)["notes"]
    assert notes["market_size"] == "~$20bn US by 2030"   # trimmed
    assert notes["peak_sales"] is None                    # blank stored as null
    assert notes["competitors"] == "drugX, drugY"
    assert notes["updated_at"] is not None

    # A second save overwrites, and clearing a field returns it to null.
    assert pp.save_notes(db_file, aid, {"market_size": "", "peak_sales": "$8bn peak",
                                        "competitors": None, "thesis": "lead asset"})
    notes = pp.product_profile(db_file, "LLY", aid)["notes"]
    assert notes["market_size"] is None
    assert notes["peak_sales"] == "$8bn peak"
    assert notes["thesis"] == "lead asset"


def test_save_notes_rejects_unknown_asset(tmp_path):
    db_file, _ = _seed_product(tmp_path)
    assert pp.save_notes(db_file, 999999, {"market_size": "x"}) is False
