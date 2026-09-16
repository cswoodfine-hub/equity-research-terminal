"""Curated product revenue and the exposure built from it, over a seeded DB.

No network. Figures here are obviously synthetic and live only in a tmp_path database;
nothing in this file is a claim about what any company earned.
"""

import pytest

import asset_revenue
import assumptions
import db
import seed


def _asset(db_file, ticker, brand, code, expiries):
    """A marketed product with exclusivity, as the Orange Book fetcher would leave it.

    ``expiries`` are (date, protection_type) pairs.
    """
    conn = db.get_connection(db_file)
    try:
        company_id = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()["id"]
        cur = conn.execute(
            """
            INSERT INTO assets (owner_company_id, brand_name, generic_name,
                                internal_code, modality, is_marketed)
            VALUES (?, ?, ?, ?, 'small molecule', 1)
            """,
            (company_id, brand, brand.lower(), code),
        )
        asset_id = cur.lastrowid
        for expiry, kind in expiries:
            conn.execute(
                """
                INSERT INTO exclusivities (asset_id, region, protection_type,
                                           identifier, expiry_date, source)
                VALUES (?, 'US', ?, ?, ?, 'orange_book')
                """,
                (asset_id, kind, "9999999", expiry),
            )
        conn.commit()
        return asset_id
    finally:
        conn.close()


@pytest.fixture
def loaded(tmp_path):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    _asset(db_file, "LLY", "Alfadrug", "NDA100001", [("2029-03-01", "patent")])
    _asset(db_file, "LLY", "Betadrug", "NDA100002", [("2029-11-30", "patent")])
    _asset(db_file, "LLY", "Gammadrug", "NDA100003", [("2033-01-15", "patent")])
    # Orphan exclusivity is not a cliff and must never reach the exposure.
    _asset(db_file, "LLY", "Orphadrug", "NDA100004",
           [("2027-06-01", "orphan exclusivity")])
    return db_file


def test_revenue_resolves_by_application_number(loaded):
    revenue_id = asset_revenue.set_revenue(loaded, "LLY", "NDA100001", 2025, 4.0e9)
    assert revenue_id
    rows = asset_revenue.list_revenue(loaded, "LLY")
    assert [r["brand_name"] for r in rows] == ["Alfadrug"]
    assert rows[0]["value"] == 4.0e9


def test_revenue_will_not_attach_to_another_companys_product(loaded):
    """Scoping to the company is what stops a figure landing on the wrong cliff."""
    with pytest.raises(ValueError, match="no product"):
        asset_revenue.set_revenue(loaded, "PFE", "NDA100001", 2025, 4.0e9)


def test_unknown_application_number_is_refused(loaded):
    with pytest.raises(ValueError, match="no product"):
        asset_revenue.set_revenue(loaded, "LLY", "NDA000000", 2025, 1.0e9)


def test_a_patent_number_is_not_an_application_number(loaded):
    """Regression: the resolver first matched exclusivities.identifier, which holds
    patent numbers. A figure could bind to whichever product shared those digits."""
    with pytest.raises(ValueError, match="no product"):
        asset_revenue.set_revenue(loaded, "LLY", "9999999", 2025, 1.0e9)


def test_implausible_input_is_refused(loaded):
    with pytest.raises(ValueError, match="zero or positive"):
        asset_revenue.set_revenue(loaded, "LLY", "NDA100001", 2025, -1.0)
    with pytest.raises(ValueError, match="fiscal year"):
        asset_revenue.set_revenue(loaded, "LLY", "NDA100001", 1850, 1.0e9)


def test_a_product_year_is_upserted_not_duplicated(loaded):
    asset_revenue.set_revenue(loaded, "LLY", "NDA100001", 2025, 4.0e9)
    asset_revenue.set_revenue(loaded, "LLY", "NDA100001", 2025, 5.0e9)
    rows = asset_revenue.list_revenue(loaded, "LLY")
    assert len(rows) == 1 and rows[0]["value"] == 5.0e9


def test_exposure_counts_every_product_and_prices_the_covered_ones(loaded):
    asset_revenue.set_revenue(loaded, "LLY", "NDA100001", 2025, 4.0e9)
    exposure = asset_revenue.build_exposure(loaded, "LLY")

    # Three patent-protected products; the orphan one is excluded.
    assert exposure["products_at_risk"] == 3
    assert exposure["products_covered"] == 1
    assert exposure["products_uncovered"] == 2
    assert exposure["revenue_at_risk"] == 4.0e9
    assert exposure["coverage"] == pytest.approx(1 / 3)


def test_orphan_exclusivity_never_reaches_the_cliff(loaded):
    """It lapses without the product losing anything, so counting it overstates."""
    exposure = asset_revenue.build_exposure(loaded, "LLY")
    brands = [p["brand_name"] for b in exposure["buckets"]
              for p in b["covered"] + b["uncovered"]]
    assert "Orphadrug" not in brands
    assert set(brands) == {"Alfadrug", "Betadrug", "Gammadrug"}


def test_an_uncovered_product_is_unknown_rather_than_zero(loaded):
    """The uncovered ones stay in the bucket so a thin table reads as thin."""
    exposure = asset_revenue.build_exposure(loaded, "LLY")
    year = next(b for b in exposure["buckets"] if b["year"] == 2029)
    assert year["products"] == 2          # both 2029 products are present
    assert year["revenue"] == 0.0         # and neither is priced
    assert all(p["revenue"] is None for p in year["uncovered"])


def test_revenue_lands_in_the_year_the_product_expires(loaded):
    asset_revenue.set_revenue(loaded, "LLY", "NDA100002", 2025, 7.0e9)
    exposure = asset_revenue.build_exposure(loaded, "LLY")
    by_year = {b["year"]: b for b in exposure["buckets"]}

    assert by_year[2029]["revenue"] == 7.0e9      # Betadrug expires 2029-11-30
    assert by_year[2033]["revenue"] == 0.0        # Gammadrug is unpriced


def test_the_latest_fiscal_year_wins_for_a_product(loaded):
    asset_revenue.set_revenue(loaded, "LLY", "NDA100001", 2023, 2.0e9)
    asset_revenue.set_revenue(loaded, "LLY", "NDA100001", 2025, 6.0e9)
    exposure = asset_revenue.build_exposure(loaded, "LLY")
    assert exposure["revenue_at_risk"] == 6.0e9


def test_mixed_currencies_refuse_to_total(loaded):
    """Two currencies cannot be added, and no rate in this app is allowed to try."""
    asset_revenue.set_revenue(loaded, "LLY", "NDA100001", 2025, 4.0e9, unit="USD")
    asset_revenue.set_revenue(loaded, "LLY", "NDA100002", 2025, 3.0e9, unit="DKK")
    exposure = asset_revenue.build_exposure(loaded, "LLY")

    assert exposure["mixed_currency"] is True
    assert exposure["currency"] is None


def test_deleting_a_figure_returns_the_product_to_uncovered(loaded):
    revenue_id = asset_revenue.set_revenue(loaded, "LLY", "NDA100001", 2025, 4.0e9)
    assert asset_revenue.delete_revenue(loaded, revenue_id) is True
    exposure = asset_revenue.build_exposure(loaded, "LLY")

    assert exposure["products_covered"] == 0
    assert exposure["products_at_risk"] == 3      # still at risk, just unpriced again
    assert asset_revenue.delete_revenue(loaded, revenue_id) is False


def test_unknown_ticker_has_no_exposure(loaded):
    assert asset_revenue.build_exposure(loaded, "NOPE") is None
    assert asset_revenue.list_revenue(loaded, "NOPE") == []


# --- one reported line valued twice ----------------------------------------------------

def _book(tmp_path):
    """One company, no products yet."""
    path = str(tmp_path / "book.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'TST', 'Test')")
    return conn


def _product(conn, asset_id, brand, base=None, revenue=()):
    """A marketed product, modelled when ``base`` is given. ``revenue`` holds
    (fiscal_year, period, value, source) rows, value as reported."""
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (?, 1, ?, 1)", (asset_id, brand))
    for year, period, value, source in revenue:
        conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value,"
                     " source, is_curated) VALUES (?, ?, ?, ?, ?, 0)",
                     (asset_id, year, period, value, source))
    if base is not None:
        assumptions.save(conn, asset_id, [{"key": "base_revenue", "value": base,
                                           "source": "t"}])


def test_a_model_anchored_on_another_products_line_is_named(tmp_path):
    """Fiasp Penfill: no revenue of its own, valued on the figure Fiasp reports."""
    conn = _book(tmp_path)
    _product(conn, 1, "Penfill", base=2818.0)
    _product(conn, 2, "Fiasp", base=2818.0,
             revenue=[(2024, "FY", 1869e6, "sec_fsds"), (2025, "FY", 2818e6, "sec_fsds")])
    found = asset_revenue.shared_lines(conn, 1)
    assert [(f["kind"], f["asset_id"], f["other_id"], f["periods"]) for f in found] == [
        ("base_revenue", 1, 2, [(2025, "FY")])]


def test_two_products_holding_one_sources_figures_are_named(tmp_path):
    """Nebulised Tyvaso held Tyvaso DPI's two earlier years from the same data set."""
    conn = _book(tmp_path)
    _product(conn, 1, "Tyvaso", base=585.7,
             revenue=[(2023, "FY", 731.1e6, "sec_fsds"), (2024, "FY", 1033.6e6, "sec_fsds"),
                      (2025, "FY", 585.7e6, "filing_table")])
    _product(conn, 2, "Tyvaso DPI", base=1292.5,
             revenue=[(2023, "FY", 731.1e6, "sec_fsds"), (2024, "FY", 1033.6e6, "sec_fsds"),
                      (2025, "FY", 1292.5e6, "sec_fsds")])
    found = asset_revenue.shared_lines(conn, 1)
    assert [(f["kind"], f["asset_id"], f["other_id"], f["periods"]) for f in found] == [
        ("revenue_rows", 1, 2, [(2023, "FY"), (2024, "FY")])]

    # Put right, the two lines are two lines.
    conn.execute("UPDATE asset_revenue SET value = ? WHERE asset_id = 1 AND fiscal_year = ?",
                 (502.6e6, 2023))
    conn.execute("UPDATE asset_revenue SET value = ? WHERE asset_id = 1 AND fiscal_year = ?",
                 (586.8e6, 2024))
    assert asset_revenue.shared_lines(conn, 1) == []


def test_a_figure_two_products_happen_to_share_is_not_a_line(tmp_path):
    """Each reports the figure itself, or differs in another period."""
    conn = _book(tmp_path)
    # Sanofi: Rezurock and Thymoglobulin at 490mm euro each, read from two tables.
    _product(conn, 1, "Rezurock", base=490.0,
             revenue=[(2024, "FY", 470e6, "sec_fsds"), (2025, "FY", 490e6, "sec_fsds")])
    _product(conn, 2, "Thymoglobulin", base=490.0,
             revenue=[(2025, "FY", 490e6, "mdna_10k")])
    # Incyte: 144,578 thousand rounds to the 144.6 the other product reports exactly.
    _product(conn, 3, "Minjuvi", base=144.6,
             revenue=[(2025, "FY", 144_578_000.0, "sec_fsds")])
    _product(conn, 4, "Olumiant", base=144.6,
             revenue=[(2025, "FY", 144_600_000.0, "sec_fsds")])
    # One quarter equal to the million, the next one not.
    _product(conn, 5, "Abraxane", revenue=[(2026, "Q1", 50e6, "earnings_exhibit"),
                                           (2026, "Q2", 55e6, "earnings_exhibit")])
    _product(conn, 6, "Krazati", revenue=[(2026, "Q1", 50e6, "earnings_exhibit"),
                                          (2026, "Q2", 61e6, "earnings_exhibit")])
    for asset_id in (5, 6):
        assumptions.save(conn, asset_id, [{"key": "therapy_mode",
                                           "text_value": "marketed", "source": "t"}])
    # A pipeline seed at a zero base beside a product that reported nothing, twice.
    _product(conn, 7, "Compound A", base=0.0)
    _product(conn, 8, "Compound B", base=0.0,
             revenue=[(2024, "FY", 0.0, "sec_fsds"), (2025, "FY", 0.0, "sec_fsds")])
    _product(conn, 9, "Compound C", base=0.0,
             revenue=[(2024, "FY", 0.0, "sec_fsds"), (2025, "FY", 0.0, "sec_fsds")])
    assert asset_revenue.shared_lines(conn, 1) == []


def test_a_line_only_one_model_counts_is_not_named(tmp_path):
    """No double count without two models: the product that reports the line has none."""
    conn = _book(tmp_path)
    _product(conn, 1, "Penfill", base=2818.0)
    _product(conn, 2, "Fiasp", revenue=[(2024, "FY", 1869e6, "sec_fsds"),
                                        (2025, "FY", 2818e6, "sec_fsds")])
    _product(conn, 3, "Fiasp FlexTouch", revenue=[(2024, "FY", 1869e6, "sec_fsds"),
                                                  (2025, "FY", 2818e6, "sec_fsds")])
    assert asset_revenue.shared_lines(conn, 1) == []
