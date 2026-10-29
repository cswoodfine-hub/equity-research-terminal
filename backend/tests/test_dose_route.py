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
    assert why == "small molecule" and oral["year1_pct"] == 0.71
    non, why = forecast.erosion_default({"modality": "small molecule",
                                         "route": "non-oral",
                                         "erosion_defaults": defaults})
    assert why == "small molecule, non-oral route" and non["year1_pct"] == 0.52
    # No route on file keeps the modality's row; a biologic is never routed.
    assert forecast.erosion_default({"modality": "small molecule",
                                     "erosion_defaults": defaults})[1] == "small molecule"
    assert forecast.erosion_default({"modality": "biologic", "route": "non-oral",
                                     "erosion_defaults": defaults})[1] == "biologic"


def test_the_measured_rows_reproduce_the_measurement():
    """The average Part D cost kept after a first generic launch, from
    work/patents/tools/erosion_study.py --wide (each launch capped at 1.0): oral n=134,
    non-oral n=28. Averages, not medians, because the book adds products into totals."""
    rows = assumptions.erosion_defaults()

    def path(row):
        return [forecast.erosion_factor(k, row["year1_pct"], row["decay_pct"],
                                        row["late_decay_pct"], row["late_from_year"])
                for k in range(1, 7)]

    measured = {"small molecule": [0.299, 0.192, 0.138, 0.115, 0.078, 0.062],
                "small molecule (non-oral)": [0.463, 0.334, 0.207, 0.177, 0.171, 0.153]}
    for name, want in measured.items():
        for got, expected in zip(path(rows[name]), want):
            assert abs(got - expected) <= 0.02, (name, got, expected)


def test_the_biologic_decay_is_the_filers_later_years():
    """Year one 0.25 from nine filer US cliffs (median 26.5%), then 0.25 a year from ten
    later-year observations (median 25.2%)."""
    row = assumptions.erosion_defaults()["biologic"]
    assert (row["year1_pct"], row["decay_pct"]) == (0.25, 0.25)


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
