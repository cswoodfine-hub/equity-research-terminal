"""A revenue line that names several products, and the evidence filed under each."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import brand_components as bc                                        # noqa: E402
import db                                                            # noqa: E402


def _book(tmp_path):
    path = str(tmp_path / "b.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'PFE', 'Pfizer')")
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (2, 'X', 'Other')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name,"
                 " is_marketed) VALUES (808, 1, 'Nurtec ODT / Vydura', NULL, 1)")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name,"
                 " is_marketed) VALUES (202, 1, 'Nurtec Odt', 'Rimegepant Sulfate', 1)")
    # Same brand, different company: never a component of Pfizer's line.
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (900, 2, 'Vydura', 1)")
    conn.execute("INSERT INTO drug_demand (asset_id, part, brand_name, year,"
                 " total_spending, total_beneficiaries)"
                 " VALUES (202, 'D', 'Nurtec ODT', 2023, 478240312, 83811)")
    conn.commit()
    return path, conn


def test_a_combined_line_splits_into_its_products():
    assert bc.parts("Nurtec ODT / Vydura") == ["Nurtec ODT", "Vydura"]
    assert bc.parts("Novo Mix And Novo Log Mix") == ["Novo Mix", "Novo Log Mix"]


def test_a_reported_line_drops_the_words_that_are_not_a_product():
    """"Prevnar / Prevenar family" names two vaccines and a noun."""
    assert bc.parts("Prevnar / Prevenar family") == ["Prevnar", "Prevenar"]


def test_a_single_product_is_its_own_only_part():
    assert bc.parts("Verzenio") == ["Verzenio"]


def test_a_single_product_has_no_components(tmp_path):
    """Only a line naming several products resolves to anything, so a caller can ask
    about any asset without checking first."""
    path, conn = _book(tmp_path)
    assert bc.components(conn, 202) == []
    conn.close()


def test_a_combined_line_finds_its_own_company_s_products(tmp_path):
    path, conn = _book(tmp_path)
    assert bc.components(conn, 808) == [202]
    conn.close()


def test_the_line_itself_is_never_its_own_component(tmp_path):
    """Returning it would double count anything summed over the result."""
    path, conn = _book(tmp_path)
    assert 808 not in bc.components(conn, 808)
    conn.close()


def test_another_company_s_product_is_not_a_component(tmp_path):
    """Vydura exists under a second company here. A brand match across companies is a
    coincidence, not a franchise."""
    path, conn = _book(tmp_path)
    assert 900 not in bc.components(conn, 808)
    conn.close()


def test_demand_reaches_the_component_when_the_line_files_none(tmp_path):
    """The whole point: rimegepant's Part D series is filed against the single-brand
    row while the model and the revenue anchor sit on the combined one."""
    path, conn = _book(tmp_path)
    rows = bc.demand_rows(conn, 808)
    assert [r["total_beneficiaries"] for r in rows] == [83811]
    conn.close()


def test_a_line_with_its_own_demand_is_not_mixed_with_a_component_s(tmp_path):
    """Its own rows win, so a franchise that does file demand is never summed with a
    component's and counted twice."""
    path, conn = _book(tmp_path)
    conn.execute("INSERT INTO drug_demand (asset_id, part, brand_name, year,"
                 " total_spending, total_beneficiaries)"
                 " VALUES (808, 'D', 'Nurtec ODT / Vydura', 2023, 500000000, 90000)")
    conn.commit()
    rows = bc.demand_rows(conn, 808)
    assert [r["total_beneficiaries"] for r in rows] == [90000]
    conn.close()
