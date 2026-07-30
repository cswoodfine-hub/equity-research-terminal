"""Revenue lines that name a disease, and the two cases the map must refuse.

The resolutions are the easy half. What makes a curated map safe to trust is that it
curates membership and never dates, and that it declines a franchise it cannot place
rather than resolving it to whichever member suits.
"""

import pytest

import db
import franchises


MAP_CSV = """# a comment line that must be ignored
ticker,franchise,brand,seasonal,note
GSK,Shingles,Shingrix,0,the only one
GSK,Meningitis,Bexsero,0,group B
GSK,Meningitis,Penmenvy,0,newest
GSK,Influenza,Fluarix,1,reformulated each season
GSK,RSVArexvy,Arexvy,0,run together in the filing
"""

CUTOFF = "2021-07-30"


@pytest.fixture()
def loaded(tmp_path):
    path = tmp_path / "map.csv"
    path.write_text(MAP_CSV)
    return franchises.load(path)


def _company(tmp_path, brands):
    """brands: {brand: (first_marketed, approval_date or None)}"""
    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('GSK', 'GSK plc')")
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    for brand, (marketed, approved) in brands.items():
        if marketed:
            conn.execute("INSERT INTO ndc_products (company_id, brand_name,"
                         "  first_marketed) VALUES (?, ?, ?)", (cid, brand, marketed))
        if approved:
            conn.execute("INSERT INTO assets (owner_company_id, brand_name, is_marketed)"
                         " VALUES (?, ?, 1)", (cid, brand))
            aid = conn.execute("SELECT id FROM assets WHERE brand_name = ?",
                               (brand,)).fetchone()[0]
            conn.execute("INSERT INTO approvals (asset_id, region, agency,"
                         "  approval_date, application_number, source)"
                         " VALUES (?, 'US', 'FDA', ?, 'X', 't')", (aid, approved))
    conn.commit()
    return conn


def test_comments_and_blank_columns_are_ignored(loaded):
    assert ("GSK", "shingles") in loaded
    assert len(loaded[("GSK", "meningitis")]) == 2


def test_the_label_is_matched_however_the_filing_punctuates_it(loaded):
    """The filing runs the disease and the brand together as "RSVArexvy"."""
    assert ("GSK", "rsvarexvy") in loaded


def test_a_single_member_franchise_resolves(tmp_path, loaded):
    conn = _company(tmp_path, {"Shingrix": ("2017-10-20", None)})
    date, route = franchises.resolve(conn, "GSK", "Shingles", CUTOFF, loaded)
    conn.close()
    assert date == "2017-10-20"
    assert route == "curated franchise membership"


def test_members_on_the_same_side_of_the_cutoff_resolve(tmp_path):
    """The answer to "is this revenue from a recent approval" is the same whichever
    member earned it, so the franchise can be placed without splitting it."""
    path = tmp_path / "m.csv"
    path.write_text("ticker,franchise,brand,seasonal,note\n"
                    "GSK,Both,Alpha,0,\nGSK,Both,Beta,0,\n")
    mapping = franchises.load(path)
    conn = _company(tmp_path, {"Alpha": ("2023-01-01", None),
                               "Beta": ("2024-01-01", None)})
    date, _route = franchises.resolve(conn, "GSK", "Both", CUTOFF, mapping)
    conn.close()
    assert date == "2023-01-01"


def test_members_straddling_the_cutoff_are_refused(tmp_path, loaded):
    """GSK's meningitis revenue comes from products first marketed in 2016 and in 2025,
    and there is no way to say how the 1.6bn splits. Picking the one that suits would be
    inventing the number."""
    conn = _company(tmp_path, {"Bexsero": ("2016-12-01", None),
                               "Penmenvy": ("2025-02-14", None)})
    date, why = franchises.resolve(conn, "GSK", "Meningitis", CUTOFF, loaded)
    conn.close()
    assert date is None
    assert why == franchises.STRADDLES


def test_a_seasonal_vaccine_franchise_is_refused(tmp_path, loaded):
    """The register keeps one entry per formulation and delists the old ones, so Fluarix
    reads 2026 for a franchise licensed decades earlier. That is the one direction the
    error must never run, and it is the only date available."""
    conn = _company(tmp_path, {"Fluarix": ("2026-07-01", None)})
    date, why = franchises.resolve(conn, "GSK", "Influenza", CUTOFF, loaded)
    conn.close()
    assert date is None
    assert why == franchises.SEASONAL


def test_a_member_with_no_date_refuses_the_franchise(tmp_path, loaded):
    """An undated member could sit either side, which leaves the franchise as unresolved
    as if the members disagreed."""
    conn = _company(tmp_path, {"Bexsero": ("2016-12-01", None), "Penmenvy": (None, None)})
    date, why = franchises.resolve(conn, "GSK", "Meningitis", CUTOFF, loaded)
    conn.close()
    assert date is None
    assert why == franchises.STRADDLES


def test_an_approval_beats_the_register(tmp_path, loaded):
    """The register gives a marketing date, which can only be later than the approval,
    so a real approval is the better record where both exist."""
    conn = _company(tmp_path, {"Shingrix": ("2019-01-01", "2017-10-20")})
    date, _route = franchises.resolve(conn, "GSK", "Shingles", CUTOFF, loaded)
    conn.close()
    assert date == "2017-10-20"


def test_a_label_not_in_the_map_is_not_a_franchise(tmp_path, loaded):
    """Absence must read as "not a franchise" rather than as a refusal, or every
    ordinary drug name would arrive here with a reason attached."""
    conn = _company(tmp_path, {"Shingrix": ("2017-10-20", None)})
    assert franchises.resolve(conn, "GSK", "Trelegy Ellipta", CUTOFF, loaded) == (None, None)
    conn.close()


def test_another_company_does_not_borrow_the_map(tmp_path, loaded):
    conn = _company(tmp_path, {"Shingrix": ("2017-10-20", None)})
    assert franchises.resolve(conn, "MRK", "Shingles", CUTOFF, loaded) == (None, None)
    conn.close()


def test_a_missing_file_is_an_empty_map(tmp_path):
    assert franchises.load(tmp_path / "nothing.csv") == {}


def test_the_shipped_map_loads():
    """The file in data/ is the one the app reads, so a syntax error in it must fail a
    test rather than silently disable the whole route."""
    mapping = franchises.load()
    assert ("GSK", "shingles") in mapping
    assert all(brand for members in mapping.values() for brand, _s, _n in members)
