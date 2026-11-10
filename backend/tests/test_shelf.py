"""Where a marketed product stands: still sold, off patent, or withdrawn in the US.

"Marketed" meant "was approved and nobody has said otherwise", which put a product the
company stopped selling beside one the filer does not break out, both with a blank
revenue column and nothing to tell them apart.
"""

import datetime as dt

import db
import loe
import marketing_status
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


def test_a_withdrawn_product_that_still_earns_is_its_own_state(tmp_path):
    """The FDA status is American and the revenue line beside it is worldwide. Pfizer's
    Vyndaqel is discontinued here, because Vyndamax replaced it, and carries $6,380mm of
    the tafamidis family's sales. Calling that withdrawn reads as $6.4bn of dead revenue
    and calling it selling contradicts the FDA, so it is neither."""
    path = _book(tmp_path, [("Gone", ["Discontinued"], "2033-01-01", 0),
                            ("Earning", ["Discontinued"], "2033-01-01", 6380)])
    states = {r["name"]: r["state"]
              for r in shelf.for_company(path, "AAA", today=TODAY)["rows"]}
    assert states["Gone"] == "withdrawn in the US"
    assert states["Earning"] == "withdrawn in the US, still earning"


def test_a_withdrawn_product_that_earns_nothing_has_no_us_cliff(tmp_path):
    """It cannot lose US exclusivity: it is not sold here. Vizimpro sat in the 2032
    column of the cliff chart on a patent protecting a product Pfizer stopped selling."""
    path = _book(tmp_path, [("Gone", ["Discontinued"], "2033-01-01", 0)])
    conn = db.get_connection(path)
    try:
        assert loe.for_assets(conn, [1]).get(1) is None
        assert loe.for_assets(conn).get(1) is None
    finally:
        conn.close()


def test_a_withdrawn_product_that_earns_keeps_its_cliff(tmp_path):
    """Revenue is the evidence that something under the row is still sold. The $6,380mm
    on Vyndaqel's application is the family's, and the molecule patent does gate it, so
    dropping the date would hand a real cliff back five years of annuity."""
    path = _book(tmp_path, [("Earning", ["Discontinued"], "2033-01-01", 6380)])
    conn = db.get_connection(path)
    try:
        assert (loe.for_assets(conn, [1]).get(1) or {})["date"] == "2033-01-01"
    finally:
        conn.close()


def test_the_strongest_status_across_applications_is_read_once_for_every_caller(tmp_path):
    """shelf and loe have to agree about what is sold, so the rule lives in one module."""
    path = _book(tmp_path, [("Both", ["Discontinued", "Prescription"], None, 0)])
    conn = db.get_connection(path)
    try:
        assert marketing_status.for_assets(conn, [1]) == {1: "Prescription"}
        assert marketing_status.for_assets(conn, []) == {}
    finally:
        conn.close()


def test_the_status_read_is_batched_so_a_long_list_cannot_exceed_the_bind_limit(tmp_path):
    """The cliff reads this for every asset carrying a date still ahead of it, 558 of
    them today, and SQLite's parameter limit is a build option the call site must not
    have to know."""
    path = _book(tmp_path, [(f"P{i}", ["Prescription"], None, 0) for i in range(950)])
    conn = db.get_connection(path)
    try:
        ids = list(range(1, 951))
        assert marketing_status._BATCH < len(ids)
        assert marketing_status.for_assets(conn, ids) == marketing_status.for_assets(conn)
    finally:
        conn.close()
