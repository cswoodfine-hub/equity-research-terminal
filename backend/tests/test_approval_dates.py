"""Dating a drug's first approval from every free route, and refusing to guess.

Each route here exists because a real large-cap company's revenue was mostly undated
without it. The negative tests matter as much: a date attached to the wrong drug makes a
portfolio look younger than it is, which is the direction that flatters.
"""

import pytest

import approval_dates as ad
import db


def _seed(conn, ticker, brand, approval=None, generic=None, exclusivity=None):
    conn.execute("INSERT OR IGNORE INTO companies (ticker, name) VALUES (?, ?)",
                 (ticker, ticker + " Inc"))
    cid = conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()[0]
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, generic_name,"
                 "  is_marketed) VALUES (?, ?, ?, 1)", (cid, brand, generic))
    aid = conn.execute("SELECT id FROM assets WHERE brand_name = ?", (brand,)).fetchone()[0]
    if approval:
        conn.execute("INSERT INTO approvals (asset_id, region, agency, approval_date,"
                     "  application_number, source) VALUES (?, 'US', 'FDA', ?, 'X', 't')",
                     (aid, approval))
    if exclusivity:
        conn.execute("INSERT INTO exclusivities (asset_id, region, protection_type,"
                     "  expiry_date, source) VALUES (?, 'US',"
                     "  'reference product exclusivity (12y)', ?, 'purple_book')",
                     (aid, exclusivity))
    return aid


@pytest.fixture()
def conn(tmp_path):
    path = str(tmp_path / "t.db")
    db.init(path)
    c = db.get_connection(path)
    yield c
    c.close()


# --- normalisation -------------------------------------------------------------------

def test_parentheticals_are_stripped():
    """drugsfda writes "Paxlovid (Copackaged)" for the product a revenue table calls
    "Paxlovid"."""
    assert ad.normalise("Paxlovid (Copackaged)") == ad.normalise("Paxlovid")


def test_punctuation_and_case_do_not_matter():
    assert ad.normalise("Nurtec ODT") == ad.normalise("nurtec-odt")


# --- the routes ----------------------------------------------------------------------

def test_a_drug_with_its_own_approval_uses_it(conn):
    aid = _seed(conn, "AAA", "OwnDrug", approval="2020-05-01")
    conn.commit()
    date, route = ad.first_approval(conn, aid, "OwnDrug")
    assert (date, route) == ("2020-05-01", "openFDA approval")


def test_a_biologic_is_dated_from_the_exclusivity_floor(conn):
    """drugsfda is CDER's register and carries no BLAs, so Shingrix, Comirnaty and
    Casgevy have no row. The Purple Book's twelve-year exclusivity is counted from first
    licensure, so subtracting twelve years recovers it."""
    aid = _seed(conn, "BBB", "Biologic", exclusivity="2038-04-24")
    conn.commit()
    date, route = ad.first_approval(conn, aid, "Biologic")
    assert date == "2026-04-24"
    assert route == "Purple Book licensure"


def test_an_alliance_product_is_dated_from_the_approval_holder(conn):
    """Pfizer books Eliquis revenue and Bristol Myers holds the application. Looking only
    under the company reporting the revenue finds nothing, though the date is already on
    file under someone else."""
    _seed(conn, "BMY", "Eliquis", approval="2012-12-28")
    partner = _seed(conn, "PFE", "Eliquis alliance revenue")
    conn.commit()
    index = ad.build_name_index(conn)
    date, route = ad.first_approval(conn, partner, "Eliquis", index)
    assert date == "2012-12-28"
    assert route == "approved to another company"


def test_a_combined_revenue_line_matches_the_product_inside_it(conn):
    """Vertex's largest line is "TRIKAFTAKAFTRIO", one product under the two names it
    sells as."""
    _seed(conn, "VRTX", "Trikafta", approval="2019-10-21")
    combined = _seed(conn, "VRT2", "TRIKAFTAKAFTRIO")
    conn.commit()
    index = ad.build_name_index(conn)
    date, route = ad.first_approval(conn, combined, "TRIKAFTAKAFTRIO", index)
    assert date == "2019-10-21"
    assert "combined" in route


def test_a_combined_line_takes_the_earliest_of_what_it_contains(conn):
    """The question is when the product was first approved, and the answer must not
    depend on which match the index happens to yield first."""
    _seed(conn, "AAA", "Simponi", approval="2009-04-24")
    _seed(conn, "AA2", "Simponi Aria", approval="2013-07-18")
    combined = _seed(conn, "AA3", "Simponi Simponi Aria")
    conn.commit()
    index = ad.build_name_index(conn)
    date, _ = ad.first_approval(conn, combined, "Simponi Simponi Aria", index)
    assert date == "2009-04-24"


def test_a_short_name_does_not_match_by_containment(conn):
    """Three or four characters sit inside a dozen brand names, and a coincidence here
    dates a drug wrongly rather than leaving it undated."""
    _seed(conn, "AAA", "Onpattro", approval="2018-08-10")
    other = _seed(conn, "BBB", "RSV")
    conn.commit()
    index = ad.build_name_index(conn)
    assert ad.first_approval(conn, other, "RSV", index) == (None, None)


def test_an_unknown_drug_is_undated_not_guessed(conn):
    aid = _seed(conn, "AAA", "Mysterious Product")
    conn.commit()
    assert ad.first_approval(conn, aid, "Mysterious Product", {}) == (None, None)


# --- which revenue lines are products ------------------------------------------------

@pytest.mark.parametrize("name", [
    "Royalty", "License And Royalty", "Collaboration Arrangement Including",
    "Grant", "Reimbursement Of Commercialization Related", "Product And Service Other",
    "Manufactured Product Other", "Collaborativeand Royalty", "Contract Manufacturing",
    "", None,
])
def test_a_way_of_earning_is_not_a_product(name):
    """These are XBRL member labels for how revenue arose, not for what was sold.
    Counting them as drugs put "Grant" in the denominator of a freshness figure where it
    could never be dated, so it always read as an ageing portfolio."""
    assert ad.is_product_line(name) is False


@pytest.mark.parametrize("name", [
    "Eliquis", "Dupixent", "TRIKAFTAKAFTRIO", "Prevnar Prevenar Family",
    # A franchise label is deliberately still a product: it is revenue a drug earned,
    # and the filing simply did not say which drug. Dropping it would flatter the
    # coverage figure rather than report the gap.
    "Shingles", "COVID 19", "Launches",
])
def test_a_product_or_franchise_line_is_kept(name):
    assert ad.is_product_line(name) is True
