"""What a member on the product axis is, and what to do with the rows already created.

A filer puts its brands, its therapeutic areas, its business segments and its income
statement line items on the same XBRL axis. Everything here is a name taken from a real
filing in the universe.
"""

import pytest

import db
from fetchers.product_revenue_sec import (CREATED_NOTE, display_name, is_aggregate,
                                          prune)


@pytest.mark.parametrize("member", [
    # Income statement lines. Moderna's grant income and Regeneron's reimbursed expenses
    # arrive on the same axis as the drugs.
    "License", "Grant", "Royalty", "Service", "Commercial", "ContractManufacturing",
    "ProductAndServiceOther", "TechnologyOptions", "InitialLicense", "Launches",
    "CollaborationArrangementIncludingArrangementsWithAffiliate",
    "ReimbursementOfCommercializationRelatedExpenses", "RoyaltyContractAndOther",
    "SpinrazaRoyalties", "ManufacturedProductOther", "Antibodies",
    # Johnson & Johnson's MedTech categories. Never drugs.
    "ADVANCED", "ELECTROPHYSIOLOGY", "GENERAL", "HIPS", "KNEES", "TRAUMA",
    "SPINESPORTSOTHER", "CONTACTLENSESOTHER",
    # Indications a franchise is reported under.
    "Influenza", "Meningitis", "Shingles", "COVID19", "RSV",
    # Franchise groupings.
    "DiovanGroup", "ExforgeGroup", "GalvusGroup",
    # A company, acquired and reported as a line.
    "ShockwaveMedicalInc",
])
def test_members_that_are_not_products(member):
    assert is_aggregate(member), member


@pytest.mark.parametrize("member", [
    "Biktarvy", "Keytruda", "Eliquis", "Jakavi", "Flumist", "Darzalex", "Spinraza",
    # A line naming several brands is still a line about drugs, and the filing reports
    # one number for it.
    "GardasilGardasil9", "TRIKAFTAKAFTRIO", "BraftoviMektovi",
])
def test_members_that_are_products(member):
    assert not is_aggregate(member), member


@pytest.mark.parametrize("member, expected", [
    ("HIVProductsBiktarvy", "Biktarvy"),
    ("HIVProductsDescovy", "Descovy"),
    ("CellTherapyProductsTecartus", "Tecartus"),
    ("LiverDiseaseProductsVemlidy", "Vemlidy"),
    ("RSVVaccinesBeyfortus", "Beyfortus"),
    ("RSVArexvy", "Arexvy"),
    ("AllianceRevenueLynparza", "Lynparza"),
])
def test_a_category_prefix_comes_off(member, expected):
    """Gilead files its whole catalogue under the category it sits in, so the same drug
    arrives as Biktarvy from one filing and HIVProductsBiktarvy from another."""
    assert display_name(member) == expected
    assert not is_aggregate(member), member


def test_the_category_alone_is_still_a_category():
    """Stripping a prefix must not turn the franchise into a product. HIV on its own is
    the whole franchise; RSV on its own is Moderna's respiratory line."""
    assert is_aggregate("HIV")
    assert is_aggregate("RSV")


def _seed(tmp_path):
    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'JNJ', 'J&J')")
    return path, conn


def _member_asset(conn, asset_id, brand):
    conn.execute(
        "INSERT INTO assets (id, owner_company_id, brand_name, is_marketed, notes)"
        " VALUES (?, 1, ?, 1, ?)", (asset_id, brand, CREATED_NOTE))
    conn.execute(
        "INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit, source)"
        " VALUES (?, 2025, 'FY', 1000.0, 'USD', 'sec_fsds')", (asset_id,))


def test_prune_retires_a_member_that_is_not_a_product(tmp_path):
    path, conn = _seed(tmp_path)
    _member_asset(conn, 10, "KNEES")
    _member_asset(conn, 11, "Darzalex")
    conn.commit()
    conn.close()

    assert prune(path) == {"retired": 1, "renamed": 0, "kept": 0}
    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM assets WHERE id = 10").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM assets WHERE id = 11").fetchone()[0] == 1
    # The revenue goes with it: it was never attributable to a product, and it stays in
    # the company total as the unattributed remainder.
    assert conn.execute(
        "SELECT COUNT(*) FROM asset_revenue WHERE asset_id = 10").fetchone()[0] == 0
    conn.close()


def test_prune_renames_a_brand_behind_a_prefix(tmp_path):
    path, conn = _seed(tmp_path)
    _member_asset(conn, 10, "HIVProducts Biktarvy")
    conn.commit()
    conn.close()

    assert prune(path) == {"retired": 0, "renamed": 1, "kept": 0}
    conn = db.get_connection(path)
    assert conn.execute(
        "SELECT brand_name FROM assets WHERE id = 10").fetchone()[0] == "Biktarvy"
    conn.close()


def test_prune_only_touches_rows_this_fetcher_created(tmp_path):
    """A row from openFDA or the Orange Book is not this module's to retire, whatever
    its name looks like."""
    path, conn = _seed(tmp_path)
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (10, 1, 'KNEES', 1)")
    conn.commit()
    conn.close()

    assert prune(path)["retired"] == 0
    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM assets WHERE id = 10").fetchone()[0] == 1
    conn.close()


def test_an_approval_saves_a_row_for_a_person_to_look_at(tmp_path):
    """An application number is identity the FDA issued, not a name match. Something real
    reached this row and deleting it would throw that away."""
    path, conn = _seed(tmp_path)
    _member_asset(conn, 10, "KNEES")
    conn.execute("INSERT INTO approvals (asset_id, application_number, approval_date)"
                 " VALUES (10, 'NDA1', '2020-01-01')")
    conn.commit()
    conn.close()

    assert prune(path) == {"retired": 0, "renamed": 0, "kept": 1}
    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM assets WHERE id = 10").fetchone()[0] == 1
    conn.close()


def test_a_label_does_not_save_a_row(tmp_path):
    """DailyMed matched a label to KNEES because an ointment is indicated "for temporary
    relief of pain", and to License because a hand sanitiser is a licensed product. Both
    matched on the name, and the name is the thing that is wrong."""
    path, conn = _seed(tmp_path)
    _member_asset(conn, 10, "KNEES")
    conn.execute("INSERT INTO labels (asset_id, setid, effective_time, indications_text)"
                 " VALUES (10, 'x', '2024-01-01', 'For temporary relief of pain')")
    conn.commit()
    conn.close()

    assert prune(path)["retired"] == 1
    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM labels WHERE asset_id = 10").fetchone()[0] == 0
    conn.close()


def test_a_trial_keeps_its_record_and_loses_the_mapping(tmp_path):
    """The study is real and its NCT number is real. Only the mapping was wrong."""
    path, conn = _seed(tmp_path)
    _member_asset(conn, 10, "KNEES")
    conn.execute("INSERT INTO trials (nct_id, sponsor_company_id, asset_id, title)"
                 " VALUES ('NCT0001', 1, 10, 'A study')")
    conn.commit()
    conn.close()

    assert prune(path)["retired"] == 1
    conn = db.get_connection(path)
    row = conn.execute("SELECT asset_id FROM trials WHERE nct_id = 'NCT0001'").fetchone()
    assert row is not None and row["asset_id"] is None
    conn.close()
