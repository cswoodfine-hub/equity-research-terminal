"""The route a product is taken by, and the erosion row it chooses."""

import assumptions
import dose_route
import forecast


def test_route_from_the_orange_book_column():
    assert dose_route.from_orange_book("TABLET;ORAL") == "oral"
    assert dose_route.from_orange_book("TABLET, FILM COATED;ORAL") == "oral"
    assert dose_route.from_orange_book("TABLET;SUBLINGUAL") == "oral"
    assert dose_route.from_orange_book("SOLUTION;SUBCUTANEOUS") == "non-oral"
    assert dose_route.from_orange_book("AEROSOL, METERED;INHALATION") == "non-oral"
    assert dose_route.from_orange_book("GEL;TOPICAL") == "non-oral"
    assert dose_route.from_orange_book("") is None
    assert dose_route.from_orange_book(None) is None


def test_the_orange_book_parse_carries_one_route_per_application():
    import pathlib
    from fetchers.exclusivity_orangebook import parse_orange_book
    from fetchers.exclusivity_orangebook import APPLICANT_MAP
    fix = pathlib.Path(__file__).resolve().parent / "fixtures"
    rows = parse_orange_book((fix / "orange_book_products.txt").read_text(),
                             (fix / "orange_book_patent.txt").read_text(),
                             (fix / "orange_book_exclusivity.txt").read_text(),
                             APPLICANT_MAP)
    routes = {r["brand"]: r["route"] for r in rows}
    assert routes["Mounjaro"] == "non-oral"            # SOLUTION;SUBCUTANEOUS
    assert routes["Corlanor"] == "oral"                # TABLET;ORAL


def test_a_non_oral_small_molecule_takes_its_own_measured_row():
    defaults = assumptions.erosion_defaults()
    oral, why = forecast.erosion_default({"modality": "small molecule", "route": "oral",
                                          "erosion_defaults": defaults})
    assert why == "small molecule" and oral["year1_pct"] == 0.77
    non, why = forecast.erosion_default({"modality": "small molecule",
                                         "route": "non-oral",
                                         "erosion_defaults": defaults})
    assert why == "small molecule, non-oral route" and non["year1_pct"] == 0.58
    # No route on file keeps the modality's row; a biologic is never routed.
    assert forecast.erosion_default({"modality": "small molecule",
                                     "erosion_defaults": defaults})[1] == "small molecule"
    assert forecast.erosion_default({"modality": "biologic", "route": "non-oral",
                                     "erosion_defaults": defaults})[1] == "biologic"


def test_the_measured_rows_reproduce_the_measurement():
    """Part D cost retained after a first generic launch, medians from
    work/patents/tools/erosion_study.py: oral n=86, non-oral n=18."""
    rows = assumptions.erosion_defaults()

    def path(row):
        return [forecast.erosion_factor(k, row["year1_pct"], row["decay_pct"],
                                        row["late_decay_pct"], row["late_from_year"])
                for k in range(1, 7)]

    measured = {"small molecule": [0.245, 0.098, 0.061, 0.043, 0.030, 0.024],
                "small molecule (non-oral)": [0.412, 0.285, 0.172, 0.137, 0.110, 0.069]}
    for name, want in measured.items():
        for got, expected in zip(path(rows[name]), want):
            assert abs(got - expected) <= 0.02, (name, got, expected)


def test_the_assets_own_application_sets_its_route(tmp_path):
    """Ozempic's asset also holds Rybelsus's oral NDA; its line is the injection."""
    import db
    from fetchers.exclusivity_orangebook import record_listing
    path = str(tmp_path / "r.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'NVO', 'Novo')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, internal_code)"
                 " VALUES (1, 1, 'Ozempic', 'NDA209637'), (2, 1, 'Mixed', 'NDA1')")
    for code, route in (("NDA209637", "non-oral"), ("NDA213051", "oral")):
        record_listing(conn, {"internal_code": code, "route": route}, 1)
    for code, route in (("NDA213051", "oral"), ("NDA209637", "non-oral")):  # either order
        record_listing(conn, {"internal_code": code, "route": route}, 1)
    # No own application listed and the others disagree: no route.
    for code, route in (("NDA2", "oral"), ("NDA3", "non-oral")):
        record_listing(conn, {"internal_code": code, "route": route}, 2)
    assert dose_route.for_asset(conn, 1) == "non-oral"
    assert dose_route.for_asset(conn, 2) is None
