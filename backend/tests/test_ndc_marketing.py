"""The marketed register, and the care a marketing date needs.

drugsfda is CDER's and carries no CBER biologics, so every vaccine and most gene
therapies had no approval anywhere and nothing they earn could be dated. The NDC
directory lists them, but what it gives is when a package began marketing, not when the
drug was approved. That distinction is what most of these tests are about.
"""

import pytest

import approval_dates
import db
from fetchers import ndc_marketing as N


def test_the_earliest_package_dates_the_brand():
    """A vaccine reformulated each season carries one record per season, and the newest
    says nothing about when the drug arrived."""
    payload = {"results": [
        {"brand_name": "Shingrix", "marketing_start_date": "20250716",
         "labeler_name": "GlaxoSmithKline Biologicals SA", "application_number": "BLA125614"},
        {"brand_name": "Shingrix", "marketing_start_date": "20171020",
         "labeler_name": "GlaxoSmithKline Biologicals SA", "application_number": "BLA125614"},
    ]}
    found = N.parse_ndc(payload, {"glaxosmithkline"})
    assert found["Shingrix"][0] == "2017-10-20"


def test_a_repackager_is_not_the_company():
    """The directory is full of them, and a product distributed by someone else is not a
    product of this company."""
    payload = {"results": [
        {"brand_name": "Ours", "marketing_start_date": "20200101",
         "labeler_name": "Alnylam Pharmaceuticals Inc"},
        {"brand_name": "Theirs", "marketing_start_date": "20200101",
         "labeler_name": "Golden State Medical Supply"},
    ]}
    assert set(N.parse_ndc(payload, {"alnylam"})) == {"Ours"}


def test_a_shared_surname_is_not_a_shared_company():
    """"SC Johnson Professional" sells hand sanitiser and shares a word with Johnson &
    Johnson. Verifying against the company name let a dozen of its products in as J&J
    drugs, which is why the configured openFDA name is the authority instead."""
    payload = {"results": [
        {"brand_name": "Alcare Foaming Antiseptic", "marketing_start_date": "20210601",
         "labeler_name": "SC Johnson Professional USA Inc"},
    ]}
    assert N.parse_ndc(payload, {"janssen"}) == {}


def test_a_record_with_no_date_is_dropped():
    payload = {"results": [{"brand_name": "Nameless", "labeler_name": "Alnylam Inc"}]}
    assert N.parse_ndc(payload, {"alnylam"}) == {}


# --- how the date is used --------------------------------------------------------------

def _seed(tmp_path, brand, marketed, company="Sarepta Therapeutics, Inc."):
    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('SRPT', ?)", (company,))
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, is_marketed)"
                 " VALUES (?, ?, 1)", (cid, brand))
    aid = conn.execute("SELECT id FROM assets").fetchone()[0]
    conn.execute("INSERT INTO ndc_products (company_id, brand_name, first_marketed)"
                 " VALUES (?, ?, ?)", (cid, brand.upper(), marketed))
    conn.commit()
    return path, conn, cid, aid


def test_a_biologic_is_dated_from_the_marketed_register(tmp_path):
    """Elevidys is a BLA, so drugsfda returns 404 for it and no other route reaches it."""
    path, conn, _cid, aid = _seed(tmp_path, "Elevidys", "2023-06-22")
    date, route = approval_dates.first_approval(conn, aid, "Elevidys", {})
    conn.close()
    assert date == "2023-06-22"
    assert route == "NDC first marketing"


def test_the_route_says_marketing_not_approval(tmp_path):
    """A product cannot be marketed before it is approved, so this errs one way only,
    toward looking newer. The label has to carry that."""
    path, conn, _cid, aid = _seed(tmp_path, "Elevidys", "2023-06-22")
    _date, route = approval_dates.first_approval(conn, aid, "Elevidys", {})
    conn.close()
    assert "marketing" in route.lower()
    assert "approval" not in route.lower()


def test_a_real_approval_beats_the_marketing_date(tmp_path):
    """The register is the last resort. Where an approval is on file it is the better
    record and the marketing date must not displace it."""
    path, conn, cid, aid = _seed(tmp_path, "Amondys 45", "2021-02-25")
    conn.execute("INSERT INTO approvals (asset_id, region, agency, approval_date,"
                 "  application_number, source) VALUES (?, 'US', 'FDA', '2021-02-25',"
                 "  'NDA1', 't')", (aid,))
    conn.commit()
    _date, route = approval_dates.first_approval(conn, aid, "Amondys 45", {})
    conn.close()
    assert route == "openFDA approval"


# --- the whole-register verdict ---------------------------------------------------------

def _company_with_register(tmp_path, dates):
    import productivity

    path = str(tmp_path / "v.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('MRNA', 'Moderna, Inc.')")
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    for i, date in enumerate(dates):
        conn.execute("INSERT INTO ndc_products (company_id, brand_name, first_marketed)"
                     " VALUES (?, ?, ?)", (cid, f"Brand{i}", date))
    conn.commit()
    return conn, cid, productivity


def test_a_register_entirely_inside_the_window_places_a_franchise_label(tmp_path):
    """Moderna discloses "COVID 19" and no free source maps a disease to a product: the
    label endpoint returns 404 for every vaccine. It markets Spikevax, mNEXSPIKE and
    mRESVIA and nothing else, all recent, so the revenue is fresh however it is worded."""
    conn, cid, productivity = _company_with_register(
        tmp_path, ["2024-05-31", "2025-08-27", "2025-08-27"])
    recent, old, n = productivity.portfolio_verdict(conn, cid, "2021-07-30")
    conn.close()
    assert (recent, old, n) == (True, False, 3)


def test_a_register_entirely_outside_the_window_places_it_the_other_way(tmp_path):
    conn, cid, productivity = _company_with_register(
        tmp_path, ["2001-07-01", "2014-03-01", "2021-05-26"])
    recent, old, _n = productivity.portfolio_verdict(conn, cid, "2021-07-30")
    conn.close()
    assert (recent, old) == (False, True)


def test_a_register_straddling_the_cutoff_gives_no_verdict(tmp_path):
    """GSK markets vaccines first sold between 2016 and 2026, so its "Meningitis" line
    could be either and the honest answer is that this cannot say."""
    conn, cid, productivity = _company_with_register(
        tmp_path, ["2016-12-01", "2023-05-03", "2025-02-14"])
    recent, old, _n = productivity.portfolio_verdict(conn, cid, "2021-07-30")
    conn.close()
    assert (recent, old) == (False, False)


def test_an_empty_register_gives_no_verdict(tmp_path):
    conn, cid, productivity = _company_with_register(tmp_path, [])
    recent, old, n = productivity.portfolio_verdict(conn, cid, "2021-07-30")
    conn.close()
    assert (recent, old, n) == (False, False, 0)
