"""Valuation scaffold: the annuity factor, and the protected-revenue NPV per product
with its honest gaps (no cliff, past LOE). No network."""

import datetime as dt

import db
import seed
import valuation


def test_annuity_factor_discounts_and_zeroes_past_loe():
    # Ten years at 10% is the textbook 6.1446 annuity factor.
    assert round(valuation.annuity_factor(10, 0.10), 4) == 6.1446
    assert valuation.annuity_factor(0) == 0.0          # at LOE, nothing left to discount
    assert valuation.annuity_factor(-3) == 0.0
    assert valuation.annuity_factor(None) == 0.0


def _seed(db_file):
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    lly = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]

    def asset(brand, modality):
        return conn.execute(
            "INSERT INTO assets (owner_company_id, brand_name, modality, is_marketed)"
            " VALUES (?, ?, ?, 1)", (lly, brand, modality)).lastrowid

    # A small molecule with a patent cliff and USD revenue: valued.
    small = asset("Verzenio", "small molecule")
    # A biologic whose only date is orphan exclusivity: revenue, but no cliff to value.
    biologic = asset("Kisunla", "biologic")
    this_year = dt.date.today().year
    conn.execute("INSERT INTO exclusivities (asset_id, protection_type, expiry_date)"
                 " VALUES (?, 'patent', ?)", (small, f"{this_year + 10}-06-01"))
    conn.execute("INSERT INTO exclusivities (asset_id, protection_type, expiry_date)"
                 " VALUES (?, 'orphan exclusivity', ?)", (biologic, f"{this_year + 8}-01-01"))
    for asset_id in (small, biologic):
        conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, value, unit)"
                     " VALUES (?, ?, 1000000000, 'USD')", (asset_id, this_year - 1))
    conn.commit()
    conn.close()


def test_company_valuation_values_the_cliffed_product_only(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    v = valuation.company_valuation(db_file, "LLY")

    assert [r["brand"] for r in v["valued"]] == ["Verzenio"]
    verzenio = v["valued"][0]
    # 1bn revenue over ten years at 10% is the annuity factor times the revenue.
    assert round(verzenio["rnpv_usd"] / 1e9, 4) == 6.1446
    assert verzenio["years_protected"] == 10 and verzenio["reason"] == "valued"
    assert round(v["protected_value_usd"] / 1e9, 4) == 6.1446

    # The biologic is earning but has no cliff, so it is named, not dropped or zeroed.
    assert [r["brand"] for r in v["unvalued"]] == ["Kisunla"]
    assert v["unvalued"][0]["reason"] == "no_cliff"
    assert v["unvalued_revenue_usd"] == 1000000000


def test_derived_biologic_loe_values_an_orphan_only_biologic(tmp_path):
    db_file = tmp_path / "t.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    lly = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    this_year = dt.date.today().year
    asset_id = conn.execute(
        "INSERT INTO assets (owner_company_id, brand_name, modality, is_marketed)"
        " VALUES (?, 'Ebglyss', 'biologic', 1)", (lly,)).lastrowid
    conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, value, unit)"
                 " VALUES (?, ?, 1000000000, 'USD')", (asset_id, this_year - 1))
    # Only an orphan date on the books, so the published cliff is excluded; a derived
    # biologic LOE ten years out is what gives it a value.
    conn.execute("INSERT INTO exclusivities (asset_id, protection_type, expiry_date)"
                 " VALUES (?, 'orphan exclusivity', ?)", (asset_id, f"{this_year + 4}-01-01"))
    conn.execute("INSERT INTO biologic_loe (asset_id, loe_year, loe_date, basis,"
                 " floor_year, disclosed_year) VALUES (?, ?, ?, '10-K and statutory floor',"
                 " ?, ?)", (asset_id, this_year + 10, f"{this_year + 10}-06-30",
                           this_year + 8, this_year + 10))
    conn.commit()
    conn.close()

    v = valuation.company_valuation(db_file, "LLY")
    assert [r["brand"] for r in v["valued"]] == ["Ebglyss"]
    row = v["valued"][0]
    assert row["years_protected"] == 10
    assert row["loe_basis"] == "10-K and statutory floor"   # the derived date, not orphan
    assert round(row["rnpv_usd"] / 1e9, 4) == 6.1446


def test_unknown_ticker_is_none(tmp_path):
    db_file = tmp_path / "t.db"
    db.init(db_file)
    seed.load_companies(db_file)
    assert valuation.company_valuation(db_file, "NOPE") is None
