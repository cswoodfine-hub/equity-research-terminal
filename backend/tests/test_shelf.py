"""Where a marketed product stands: still sold, off patent, or withdrawn in the US.

"Marketed" meant "was approved and nobody has said otherwise", which put a product the
company stopped selling beside one the filer does not break out, both with a blank
revenue column and nothing to tell them apart.
"""

import datetime as dt

import db
import shelf

TODAY = dt.date(2026, 11, 2)


def _book(tmp_path, assets):
    """assets: [(name, [statuses], loe_date, revenue)]"""
    path = str(tmp_path / "s.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AAA', 'AAA')")
    for i, (name, statuses, loe_date, revenue) in enumerate(assets, start=1):
        conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                     " VALUES (?, 1, ?, 1)", (i, name))
        for j, status in enumerate(statuses):
            conn.execute(
                "INSERT INTO approvals (asset_id, region, agency, approval_date,"
                " application_number, source, marketing_status)"
                " VALUES (?, 'US', 'FDA', ?, ?, 'openfda', ?)",
                (i, f"201{j}-01-01", f"NDA{i}{j}", status))
        if loe_date:
            conn.execute(
                "INSERT INTO exclusivities (asset_id, region, protection_type,"
                " identifier, expiry_date, source, patent_kind)"
                " VALUES (?, 'US', 'patent', ?, ?, 'orange_book', 'substance')",
                (i, f"P{i}", loe_date))
        if revenue:
            conn.execute(
                "INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit)"
                " VALUES (?, 2025, 'FY', ?, 'USD')", (i, revenue * 1e6))
    conn.commit()
    conn.close()
    return path


def test_a_discontinued_application_is_not_a_product_nobody_modelled(tmp_path):
    """The question this answers: a blank revenue column meant both 'the company stopped
    selling it' and 'no free source breaks it out', and they need opposite responses."""
    path = _book(tmp_path, [("Dead", ["Discontinued"], "2020-01-01", 0)])
    out = shelf.for_company(path, "AAA", today=TODAY)
    assert out["rows"][0]["state"] == "withdrawn in the US"
    assert out["no_revenue"]["withdrawn in the US"] == 1


def test_a_past_exclusivity_on_a_selling_product_is_generic_competition(tmp_path):
    path = _book(tmp_path, [("Old", ["Prescription"], "2020-01-01", 500)])
    out = shelf.for_company(path, "AAA", today=TODAY)
    assert out["rows"][0]["state"] == "selling, off patent"
    assert out["totals"]["selling, off patent"]["revenue"] == 500


def test_a_future_exclusivity_on_a_selling_product_is_protected(tmp_path):
    path = _book(tmp_path, [("New", ["Prescription"], "2033-01-01", 900)])
    out = shelf.for_company(path, "AAA", today=TODAY)
    assert out["rows"][0]["state"] == "selling, protected"


def test_one_live_application_keeps_the_product_selling(tmp_path):
    """A brand whose superseded formulation is discontinued and whose current one is not
    is still sold. Reading the newest application alone withdrew $11.7bn of revenue."""
    path = _book(tmp_path, [("Both", ["Prescription", "Discontinued"], "2033-01-01", 700)])
    out = shelf.for_company(path, "AAA", today=TODAY)
    assert out["rows"][0]["state"] == "selling, protected"


def test_the_two_unknowns_are_kept_apart(tmp_path):
    """A product the FDA says is on sale with no exclusivity on file is a gap in the
    patent data; one the FDA does not resolve is a gap in the registry. Together they put
    $216.9bn under one word that meant neither."""
    path = _book(tmp_path, [("NoLoe", ["Prescription"], None, 100),
                            ("NoStatus", [], "2033-01-01", 200)])
    states = {r["name"]: r["state"] for r in shelf.for_company(path, "AAA", today=TODAY)["rows"]}
    assert states["NoLoe"] == "selling, exclusivity unknown"
    assert states["NoStatus"] == "status unknown"
