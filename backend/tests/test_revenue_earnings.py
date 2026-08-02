"""Product revenue read from an 8-K earnings exhibit, and the period it belongs to.

The fixture is Biogen's Q2 2026 exhibit, cut to the two product tables. It is the case
the module exists for and the case that breaks a naive reader: the six month table and
the three month table state the same products, and the six month heading appears first.
"""

from pathlib import Path

import pytest

import revenue_earnings as RE

FIXTURE = Path(__file__).parent / "fixtures" / "biib_8k_product_revenue.txt"
BIIB = FIXTURE.read_text()

BRANDS = ["Tecfidera", "Vumerity", "Avonex", "Plegridy", "Tysabri", "Spinraza",
          "Skyclarys", "Qalsody", "Syfovre", "Empaveli", "Byooviz", "Zurzuvae"]

# The Q2 2026 total column, as printed.
QUARTER = {"Tecfidera": 90.9, "Vumerity": 196.5, "Avonex": 170.0, "Plegridy": 55.1,
           "Tysabri": 450.8, "Spinraza": 401.9, "Skyclarys": 167.9, "Qalsody": 31.9,
           "Syfovre": 97.4, "Empaveli": 30.4, "Byooviz": 0.1, "Zurzuvae": 70.8}


def test_reads_every_product_in_the_quarter():
    found = RE.parse(BIIB, BRANDS)
    assert set(found) == set(QUARTER)
    for brand, millions in QUARTER.items():
        assert found[brand]["value"] == pytest.approx(millions * 1e6), brand


def test_the_quarter_wins_over_the_half_year():
    """The trap this module is built around.

    Biogen prints six months before three months, so a reader that takes the first
    heading in the document files 775.9m of half-year Spinraza as one quarter. Every
    product must come back as Q2.
    """
    found = RE.parse(BIIB, BRANDS)
    assert {d["period"] for d in found.values()} == {"Q2"}
    assert found["Spinraza"]["value"] == pytest.approx(401.9e6)


def test_the_half_year_is_still_read_correctly_where_it_is_asked_for():
    """The quarter winning is a choice about what to store, not a failure to read the
    half year. Read on its own the six month table gives the six month figure, and
    401.9 plus the 374.0 of the March quarter is exactly it."""
    import revenue_mdna

    bodies = [body for period, _, _, body in RE.tables(BIIB) if period == "H1"]
    assert bodies, "the six month table should be found"
    halves = [got["Spinraza"] for body in bodies
              if "Spinraza" in (got := revenue_mdna.parse(body, BRANDS))]
    assert halves == [pytest.approx(775.9e6)]


def test_a_product_absent_from_one_table_is_absent_rather_than_wrong():
    """Byooviz has a June quarter figure and no half year row. The missing row must
    stay missing: carrying the quarter into the half year would invent a figure."""
    import revenue_mdna

    per_period = {period: revenue_mdna.parse(body, BRANDS)
                  for period, _, _, body in RE.tables(BIIB)}
    assert "Byooviz" in per_period["Q2"]
    assert "Byooviz" not in per_period["H1"]


def test_period_end_and_fiscal_year_come_from_the_heading():
    found = RE.parse(BIIB, BRANDS)
    assert found["Empaveli"]["period_end"] == "2026-06-30"
    assert found["Empaveli"]["fiscal_year"] == 2026


def test_a_product_acquired_mid_year_is_read():
    """Empaveli and Syfovre joined Biogen in May 2026, so they are in no FY2025 data set
    and in no 10-K until 2027. The exhibit is the only source, which is the point."""
    found = RE.parse(BIIB, BRANDS)
    assert found["Empaveli"]["value"] == pytest.approx(30.4e6)
    assert found["Syfovre"]["value"] == pytest.approx(97.4e6)


def test_text_with_no_period_heading_yields_nothing():
    """Never guess. A table with no readable heading is skipped, not dated by the
    filing date or by whatever heading happened to appear earlier."""
    assert RE.tables("SPINRAZA $ 204.3 $ 197.6 $ 401.9") == []
    assert RE.parse("SPINRAZA $ 204.3 $ 197.6 $ 401.9", BRANDS) == {}


def test_read_heading_takes_the_last_one():
    """Biogen's document order. The heading that governs a table is the one directly
    above it, so the later of two is the answer, never the first."""
    text = "For the Six Months Ended June 30, 2026 For the Three Months Ended June 30, 2026"
    assert RE.read_heading(text) == ("Q2", "2026-06-30", 2026)


@pytest.mark.parametrize("months, end_month, expected", [
    (12, 12, "FY"),
    (3, 3, "Q1"),
    (3, 6, "Q2"),
    (3, 9, "Q3"),
    (3, 12, "Q4"),
    (6, 6, "H1"),
    (9, 9, None),        # year to date is neither a quarter nor a year
    (6, 12, None),       # a second half is not a period any caller here asks for
])
def test_span_to_period(months, end_month, expected):
    assert RE.span_to_period(months, end_month) == expected


def test_quarter_label_heading():
    assert RE.read_heading("Second Quarter 2026") == ("Q2", "2026-06-30", 2026)
    assert RE.read_heading("Q4 2025") == ("Q4", "2025-12-31", 2025)


def test_extract_writes_quarters_and_is_idempotent(tmp_path):
    import db

    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'BIIB', 'Biogen')")
    for i, brand in enumerate(BRANDS, start=1):
        conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name)"
                     " VALUES (?, 1, ?, ?)", (i, brand, brand.lower()))
    conn.execute(
        "INSERT INTO filing_sections (company_id, accession, form_type, filed_date,"
        "                             section, char_count, text)"
        " VALUES (1, 'acc', '8-K', '2026-07-29', 'exhibit', ?, ?)", (len(BIIB), BIIB))
    conn.commit()
    conn.close()

    # Twelve products in the quarter and eleven in the half year: Byooviz was sold in
    # 2025, so it carries a June quarter figure of 0.1m and no half year row at all.
    first = RE.extract(path)
    assert first["written"] == len(QUARTER) + 11

    conn = db.get_connection(path)
    row = conn.execute(
        "SELECT ar.value, ar.period, ar.period_end, ar.fiscal_year, ar.source"
        "  FROM asset_revenue ar JOIN assets a ON a.id = ar.asset_id"
        " WHERE a.brand_name = 'Empaveli' AND ar.period = 'Q2'").fetchone()
    assert row["value"] == pytest.approx(30.4e6)
    assert row["period_end"] == "2026-06-30"
    assert row["fiscal_year"] == 2026
    assert row["source"] == RE.SOURCE
    conn.close()

    assert RE.extract(path)["written"] == 0          # running again writes nothing


def test_extract_leaves_an_existing_figure_alone(tmp_path):
    """The data sets and a hand entered correction both outrank this."""
    import db

    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'BIIB', 'Biogen')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name)"
                 " VALUES (1, 1, 'Spinraza', 'nusinersen')")
    conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit,"
                 "                           source, is_curated)"
                 " VALUES (1, 2026, 'Q2', 1.0, 'USD', 'hand', 1)")
    conn.execute(
        "INSERT INTO filing_sections (company_id, accession, form_type, filed_date,"
        "                             section, char_count, text)"
        " VALUES (1, 'acc', '8-K', '2026-07-29', 'exhibit', ?, ?)", (len(BIIB), BIIB))
    conn.commit()
    conn.close()

    RE.extract(path)
    conn = db.get_connection(path)
    kept = conn.execute("SELECT value, source FROM asset_revenue WHERE asset_id = 1"
                        "  AND period = 'Q2'").fetchone()
    assert kept["value"] == 1.0 and kept["source"] == "hand"
    conn.close()
