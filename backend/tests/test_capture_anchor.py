"""The one number 65% of the pipeline book rests on, derived rather than written out.

The tests that matter here are the ones that pin the conventions. The rate is not forced
by the data: how the latest year is annualised, whether the engine's incidence term sits
in the denominator, and whether the opening stock is carried all move it, and each moved
it silently while the fact lived in seven hand-written paragraphs.
"""

import pytest

import capture_anchor as CA
import db
import evidence


ZEPBOUND = 139

# Other assets' revenue, laid out as a rebuilt database lays it out. Camzyos holds id 13,
# the id Zepbound held when the anchor was written, and Mounjaro shares its generic.
OTHERS = ((13, 2, "Mavacamten", "Camzyos"), (31, 1, "Tirzepatide", "Mounjaro"))
OTHER_REVENUE = ((2023, "FY", 231e6), (2024, "FY", 602e6), (2025, "FY", 1010e6),
                 (2026, "Q1", 290e6), (2026, "Q2", 318e6))


def _seed(tmp_path, revenue=(), price=0.006642, gtn=0.5, stop=0.648,
          prevalence=107_592_242.0, incidence=4_478_747.0, zepbound=True):
    path = str(tmp_path / "anchor.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name, reporting_currency)"
                 " VALUES (1, 'LLY', 'Eli Lilly', 'USD')")
    conn.execute("INSERT INTO companies (id, ticker, name, reporting_currency)"
                 " VALUES (2, 'BMY', 'Bristol-Myers Squibb', 'USD')")
    for asset_id, owner, generic, brand in OTHERS:
        conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, brand_name,"
                     " is_marketed) VALUES (?, ?, ?, ?, 1)",
                     (asset_id, owner, generic, brand))
        for year, period, value in OTHER_REVENUE:
            conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period,"
                         " value, unit, source) VALUES (?, ?, ?, ?, 'USD', 'test')",
                         (asset_id, year, period, value))
    if zepbound:
        conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, brand_name,"
                     " is_marketed) VALUES (?, 1, 'Tirzepatide', 'Zepbound', 1)",
                     (ZEPBOUND,))
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (20, 1, 'Retatrutide', 0)")
    for year, period, value in revenue:
        conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value,"
                     " unit, source) VALUES (?, ?, ?, ?, 'USD', 'test')",
                     (ZEPBOUND, year, period, value))
    for key, value in (("list_price_per_patient", price), ("gross_to_net_pct", gtn),
                       ("discontinuation_pct", stop), ("prevalence", prevalence),
                       ("incidence", incidence)):
        if value is None:
            continue
        conn.execute("INSERT INTO assumptions (asset_id, region, scenario, key, value)"
                     " VALUES (20, 'US', 'base', ?, ?)", (key, value))
    conn.commit()
    return conn


BOOK = ((2023, "FY", 176e6), (2024, "FY", 4926e6), (2025, "FY", 13542e6),
        (2026, "Q1", 4160e6), (2026, "Q2", 4928e6))


def test_it_reproduces_the_rate_the_book_already_carries(tmp_path):
    """Importing the module must not move a valuation. The default conventions are the
    ones the seven seeds were written on."""
    conn = _seed(tmp_path, revenue=BOOK)
    got = CA.measure(conn, 20)
    conn.close()
    assert got["rate"] == pytest.approx(0.043882, abs=5e-6)
    assert [round(s["rate"], 4) for s in got["series"]] == [0.0138, 0.0335, 0.0439]


def test_zepbound_is_found_by_filer_and_brand_rather_than_by_id(tmp_path):
    """Asset ids move between rebuilds. A constant 13 read Camzyos in the published
    database and measured 0.36%; matching on generic would read Mounjaro."""
    conn = _seed(tmp_path, revenue=BOOK)
    assert CA.zepbound_id(conn) == ZEPBOUND
    got = CA.measure(conn, 20)
    conn.close()
    assert got["rate"] == pytest.approx(0.043882, abs=5e-6)


def test_a_database_without_zepbound_has_no_anchor(tmp_path):
    """No Zepbound, no anchor. Someone else's revenue must never stand in for it."""
    conn = _seed(tmp_path, zepbound=False)
    assert CA.zepbound_id(conn) is None
    assert CA.measure(conn, 20) is None
    conn.close()


def test_the_net_price_is_read_from_the_asset_rather_than_hard_coded(tmp_path):
    conn = _seed(tmp_path, revenue=BOOK)
    assert CA.net_price(conn, 20) == pytest.approx(0.003321)
    conn.close()


def test_annualising_the_half_year_instead_of_the_quarter_lowers_it(tmp_path):
    """A real choice, not a detail: the same evidence reads 3.94% on the other basis."""
    conn = _seed(tmp_path, revenue=BOOK)
    got = CA.measure(conn, 20, annualise="half")
    conn.close()
    assert got["rate"] == pytest.approx(0.039372, abs=5e-6)


def test_the_engine_pool_adds_incidence_and_lowers_the_rate(tmp_path):
    """forecast.patients_for_indication multiplies penetration by pool PLUS incidence,
    so a rate measured against the pool alone is measured on a denominator the consuming
    code does not use."""
    conn = _seed(tmp_path, revenue=BOOK)
    got = CA.measure(conn, 20, pool="engine")
    conn.close()
    assert got["rate"] < 0.043882
    assert got["rate"] == pytest.approx(0.042045, abs=5e-6)


def test_carrying_the_opening_stock_lowers_the_first_year_only(tmp_path):
    """The seeds dropped Zepbound's 2023 revenue, which flatters 2024."""
    conn = _seed(tmp_path, revenue=BOOK)
    with_open = CA.measure(conn, 20, opening=True)
    without = CA.measure(conn, 20)
    conn.close()
    assert with_open["series"][0]["rate"] < without["series"][0]["rate"]
    assert round(with_open["series"][0]["rate"], 4) == 0.0136


def test_a_missing_input_returns_none_rather_than_a_number(tmp_path):
    """Never fabricate a value. An anchor with no price is not an anchor."""
    conn = _seed(tmp_path, revenue=BOOK, price=None)
    assert CA.measure(conn, 20) is None
    conn.close()
    short = tmp_path / "b"
    short.mkdir()
    conn = _seed(short, revenue=((2024, "FY", 4926e6),))
    assert CA.measure(conn, 20) is None, "a series that stops short is not an anchor"
    conn.close()


def test_the_basis_names_the_filings_so_the_row_grades_as_filed(tmp_path):
    """The anchor is arithmetic on a filer's own reported revenue. Written without the
    accessions it matched no rule at all and graded as nothing, and the grade was then
    decided by whatever incidental word appeared in the note, such as amylin analogue."""
    conn = _seed(tmp_path, revenue=BOOK)
    text = CA.basis(CA.measure(conn, 20))
    conn.close()
    assert evidence.grade(text) == "filed"
    assert "0000059478-26-000013" in text
    assert "4.39% in 2026" in text
    assert "latest quarter annualised" in text


def test_a_row_carrying_both_the_anchor_and_a_multiple_grades_as_the_judgement(tmp_path):
    """The repository's rule is that a row naming more than one kind of evidence takes
    the weakest. An asset's own rate is filed arithmetic times an analyst's call on its
    competitive position, so the row is a judgement and should say so."""
    conn = _seed(tmp_path, revenue=BOOK)
    text = (CA.basis(CA.measure(conn, 20)) + ". This asset is set at 0.500x that rate, "
            "an analyst's judgement of its competitive position: half")
    conn.close()
    assert evidence.grade(text) == "judgement"
