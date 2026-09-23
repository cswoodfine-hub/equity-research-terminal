"""The house gross-to-net convention against CMS's own negotiated prices. No network."""

import db
import gross_to_net
import seed


def _seed(db_file, rows):
    """A negotiated price and a demand row for each drug, as CMS publishes them."""
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    lly = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    for brand, mfp, spending, benes, units in rows:
        cur = conn.execute("INSERT INTO assets (owner_company_id, brand_name,"
                           " generic_name, is_marketed) VALUES (?, ?, ?, 1)",
                           (lly, brand, brand.lower()))
        conn.execute("INSERT INTO negotiated_prices (drug, ingredient, ipay, mfp_30des,"
                     " effective_from, source)"
                     " VALUES (?, ?, 2026, ?, '2026-01-01', 'cms_mfp')",
                     (brand.upper(), brand.lower(), mfp))
        if spending is not None:
            conn.execute("INSERT INTO drug_demand (asset_id, part, brand_name, year,"
                         " total_spending, total_beneficiaries, total_dosage_units)"
                         " VALUES (?, 'D', ?, 2024, ?, ?, ?)",
                         (cur.lastrowid, brand, spending, benes, units))
    conn.commit()
    return conn


def test_annual_mfp_is_a_thirty_day_price_as_a_year():
    assert gross_to_net.annual_mfp(231.0) == 231.0 * 365 / 30       # Eliquis, IPAY 2026


def test_convention_is_measured_against_the_negotiated_price(tmp_path):
    conn = _seed(tmp_path / "t.db", [
        # Eliquis and Januvia as CMS publishes them: the first lands close, the second
        # does not, because sitagliptin's rebate is far deeper than half.
        ("Eliquis", 231.0, 20_774_929_225.0, 4_424_796, 2_156_238_529.0),
        ("Januvia", 113.0, 243_460_231.0, 52_958, 13_557_248.0),
    ])
    try:
        got = gross_to_net.calibration(conn)
    finally:
        conn.close()
    by_drug = {r["drug"]: r for r in got["rows"]}
    eliquis = by_drug["ELIQUIS"]
    assert round(eliquis["gross_per_beneficiary"], 2) == 4695.12
    assert round(eliquis["negotiated_annual"], 0) == 2810
    assert round(eliquis["ratio"], 3) == 0.835      # 17% below a negotiated net price
    assert by_drug["JANUVIA"]["ratio"] > 1.5        # and well above one on Januvia
    assert got["n"] == 2


def test_a_negotiated_drug_with_no_demand_row_is_reported_not_dropped(tmp_path):
    """A calibration quietly built on fewer drugs than it claims is the failure mode, so
    a drug CMS negotiated that the demand table cannot answer is named."""
    conn = _seed(tmp_path / "t.db", [
        ("Eliquis", 231.0, 20_774_929_225.0, 4_424_796, 2_156_238_529.0),
        ("Novolog", 119.0, None, None, None),
    ])
    try:
        got = gross_to_net.calibration(conn)
    finally:
        conn.close()
    assert got["missing"] == ["NOVOLOG"]
    assert got["n"] == 1
