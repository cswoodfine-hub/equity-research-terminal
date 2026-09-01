"""Product revenue read from an 8-K earnings exhibit, and the period it belongs to.

The fixture is Biogen's Q2 2026 exhibit, cut to the two product tables. It is the case
the module exists for and the case that breaks a naive reader: the six month table and
the three month table state the same products, and the six month heading appears first.
"""

from pathlib import Path

import pytest

import asset_identity
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

    # Merged rather than keyed on the last table of each period: Biogen prints a second
    # three month table, the total revenue one, and it states no products at all.
    per_period = {}
    for period, _, _, body in RE.tables(BIIB):
        per_period.setdefault(period, {}).update(revenue_mdna.parse(body, BRANDS))
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


# --- Table shapes revenue_mdna does not read --------------------------------

GILD = (Path(__file__).parent / "fixtures" / "gild_8k_geography_blocks.txt").read_text()
PFE = (Path(__file__).parent / "fixtures" / "pfe_8k_worldwide_rows.txt").read_text()

GILD_BRANDS = ["Biktarvy", "Descovy", "Genvoya", "Odefsey", "Yeztugo"]
PFE_BRANDS = ["Eliquis", "Ibrance", "Padcev", "Nurtec ODT/Vydura", "Comirnaty", "Paxlovid",
              "Abrysvo"]


def test_geography_block_takes_the_worldwide_total_not_the_us_column():
    """Gilead's brand line carries only the United States figure and the worldwide total
    is a bare line under the regions. Reading the row left to right gives 2,573 for
    Biktarvy, which is the US number and a quarter light."""
    found = RE.read_geography_blocks(GILD)
    assert found["Biktarvy"] == pytest.approx(3361)      # not 2573
    assert found["Descovy"] == pytest.approx(807)        # not 761
    assert found["Yeztugo"] == pytest.approx(166)


def test_geography_block_drops_a_row_that_does_not_reconcile():
    """The gate that makes reading an unlabelled column safe: the regions have to add up
    to the total the filer prints, or the row is not this shape and is not stored."""
    broken = ("Biktarvy U.S. $ 2,573 $ 2,474\n"
              "Europe 437 375\n"
              "Rest of World 352 301\n"
              "9,999 3,150\n")
    assert RE.read_geography_blocks(broken) == {}


def test_worldwide_row_reads_the_first_column():
    """Pfizer leads with worldwide, and puts the name on its own line where a footnote
    marker follows it, so Eliquis's figures are on the line below its name."""
    found = RE.read_worldwide_rows(PFE)
    assert found["Eliquis"] == pytest.approx(2166)
    assert found["Ibrance"] == pytest.approx(1008)
    assert found["Padcev"] == pytest.approx(591)


def test_worldwide_row_drops_a_row_that_does_not_reconcile():
    """United States plus international must equal worldwide."""
    broken = "Eliquis (b)\n9,999 1,923 13% 8% 1,435 1,299 10% 731 624 17% 4%\n"
    assert RE.read_worldwide_rows(broken) == {}


def test_read_table_only_returns_names_it_was_given():
    """A subtotal row is shaped exactly like a product row. "Total HIV" reconciles as
    cleanly as Biktarvy does, so the brand list is the only thing separating them."""
    found = RE.read_table(GILD, GILD_BRANDS)
    assert set(found) <= set(GILD_BRANDS)
    assert "Total HIV" not in found
    assert found["Biktarvy"] == pytest.approx(3361e6)


def test_pfizer_period_comes_from_its_own_heading():
    """FIRST-QUARTER 2026, hyphenated, which the sentence form never matched."""
    assert RE.read_heading("FIRST-QUARTER 2026 and 2025 - (UNAUDITED)") == (
        "Q1", "2026-03-31", 2026)


def test_a_period_named_in_prose_is_not_a_heading():
    """Pfizer's exhibit carries a 418 character footnote explaining that its
    international subsidiaries close a month early. It names a period and is not a
    column header, and the table it was governing belonged to someone else."""
    footnote = (
        "(1) The financial statements present the three months ended March 29, 2026 and "
        "March 30, 2025, while Pfizer's first quarter for subsidiaries operating outside "
        "the U.S. reflects the three months ended on February 22, 2026 and February 23, "
        "2025, and certain amounts may not add due to rounding of the underlying values.")
    assert RE.tables(footnote) == []


def test_prose_that_says_ended_on_is_never_a_heading():
    assert RE.tables("the three months ended on March 29, 2026") == []


def test_a_line_item_is_not_a_product():
    for name in ("Launches", "License", "Grant", "Royalty", "Total product sales",
                 "Product And Service Other", "Other HIV"):
        assert not asset_identity.looks_like_a_product(name), name
    for name in ("Eliquis", "Biktarvy", "Padcev", "Livdelzi", "Nurtec ODT/Vydura"):
        assert asset_identity.looks_like_a_product(name), name


# --- Two headings on one line -----------------------------------------------
#
# Vertex prints one product table under both periods side by side. Biogen's case is two
# tables stacked, which the reader handles by taking the nearest heading above. Stacked
# is not this: here the periods run left to right along with the columns, and the figures
# the readers return are the leftmost ones.

VRTX = (Path(__file__).parent / "fixtures" / "vrtx_8k_side_by_side_periods.txt").read_text()

VRTX_BRANDS = ["TRIKAFTA/KAFTRIO", "ALYFTREK", "CASGEVY", "JOURNAVX"]


def test_side_by_side_headings_collapse_to_the_leftmost():
    """The line reads "Three Months Ended June 30, Six Months Ended June 30,". Only the
    second states a year on the line, the first taking it from the shared row beneath, so
    the second was the only heading read and it governed the whole table."""
    assert [(period, end) for period, end, _, _ in RE.tables(VRTX)] == [("Q2", "2026-06-30")]


def test_the_quarter_column_is_not_filed_as_the_half_year():
    """Casgevy's June quarter is 76.4 and its first half is 119.3, two columns to the
    right. Binding the row to the nearest heading above stored 76.4 as six months."""
    found = RE.parse(VRTX, VRTX_BRANDS)
    assert found["CASGEVY"]["value"] == pytest.approx(76.4e6)
    assert found["CASGEVY"]["period"] == "Q2"
    assert found["JOURNAVX"]["value"] == pytest.approx(49.6e6)
    assert found["JOURNAVX"]["period"] == "Q2"


def test_the_half_year_column_is_left_alone_rather_than_guessed():
    """No reader here reaches past the first pair of columns, so the six month figures
    are not extracted at all. Absent beats attributed to the wrong period."""
    values = {brand: row["value"] for brand, row in RE.parse(VRTX, VRTX_BRANDS).items()}
    assert 119.3e6 not in values.values()
    assert 78.6e6 not in values.values()


def test_a_heading_with_no_year_of_its_own_takes_its_neighbours():
    """The first heading on the line ends at "June 30," with the year a row below. Read
    alone it is not a period at all, which is why it was being dropped."""
    line = "Three Months Ended June 30, Six Months Ended June 30,\n2026 2025 2026 2025\n"
    assert [head[:3] for head in RE.tables(line)] == [("Q2", "2026-06-30", 2026)]


# --- Merck: a stacked header, a grouped row, and a grid that must not be read ---------
#
# Merck's exhibit prints its column header one token to a line, "Second Quarter / $ in
# millions / 2026 / 2025", and its full-year table under "Year Ended / $ in millions /
# Dec. 31, 2025". Neither was a heading the reader knew, so the product tables had none
# and were claimed from thousands of characters up the page. Then Table 3, the
# franchise grid, prints every quarter of two years on one row, and read_row proved
# 7,205 + 7,956 = 15,161 and 7,205 + 7,956 + 8,142 + 8,337 = 31,641 as totals: a half
# year stored as Q2 and a full year as Q4, on the product that is half of Merck.

MRK_Q2 = (Path(__file__).parent / "fixtures" / "mrk_8k_stacked_header.txt").read_text()
MRK_Q4 = (Path(__file__).parent / "fixtures" / "mrk_8k_year_ended.txt").read_text()


def test_a_bare_ordinal_over_a_scale_line_is_a_quarter_heading():
    heads = [(p, e, y) for p, e, y, _ in RE.tables(MRK_Q2)]
    assert ("Q2", "2026-06-30", 2026) in heads


def test_year_ended_over_a_scale_line_is_a_full_year_heading():
    heads = [(p, e, y) for p, e, y, _ in RE.tables(MRK_Q4)]
    assert ("Q4", "2025-12-31", 2025) in heads
    assert ("FY", "2025-12-31", 2025) in heads          # "Year Ended / $ in millions / Dec. 31, 2025"


def test_the_quarter_heading_does_not_reach_into_the_full_year_table():
    bodies = {p: body for p, _, _, body in RE.tables(MRK_Q4)}
    assert "31,680" not in bodies["Q4"]
    assert "31,680" in bodies["FY"]


def test_the_grid_is_fenced_and_never_read_as_a_quarter():
    """Table 3's Keytruda row sums three ways. None of those sums may come back."""
    found = RE.parse(MRK_Q2, ["Keytruda", "Keytruda Qlex", "Bridion"])
    values = {round(v["value"] / 1e6) for v in found.values()}
    assert not values & {15161, 15810, 31641, 7906, 7904}
    for _, _, _, body in RE.tables(MRK_Q2):
        assert "15,161" not in body                     # the grid is inside no heading's reach


def test_a_group_member_is_not_booked_the_group():
    """"KEYTRUDA/ KEYTRUDA QLEX 8,366": the first name was never read, the second was."""
    found = RE.parse(MRK_Q2, ["Keytruda", "Keytruda Qlex", "Gardasil", "Gardasil 9"])
    assert "Keytruda Qlex" not in found
    assert "Gardasil 9" not in found
    assert "Keytruda" not in found and "Gardasil" not in found


def test_a_product_on_its_own_line_is_read_from_the_stacked_table():
    """"WINREVAIR 588 336 75 % 75 %": a row of bare figures under a thousand, which the
    money test refused outright until a percentage closing the row made them readable."""
    found = RE.parse(MRK_Q2, ["Winrevair", "Keytruda", "Gardasil 9"])
    assert found["Winrevair"]["value"] == pytest.approx(588e6)
    assert found["Winrevair"]["period"] == "Q2"
    assert found["Winrevair"]["fiscal_year"] == 2026


def test_a_month_can_be_abbreviated():
    heads = [(p, e) for p, e, _, _ in RE.tables("Year Ended\n$ in millions\nDec. 31, 2025\n")]
    assert heads == [("FY", "2025-12-31")]
    heads = [(p, e) for p, e, _, _ in RE.tables("Three Months Ended Sept. 30, 2025\n")]
    assert heads == [("Q3", "2025-09-30")]


def test_a_long_year_ended_line_is_still_a_fence_not_a_heading():
    """Bristol Myers' 190-character column header names "Year Ended" three times and is
    too long to be a heading. Reading "year ended" as a span must not promote it."""
    line = ("($ amounts in millions) Year Ended December 31, 2025 % Change from Year Ended "
            "December 31, 2024 % Change from Year Ended December 31, 2024 Ex-F/X**\n"
            "Eliquis 10,239 4,205 14,443 6 % 14 % 8 %\n")
    assert RE.tables(line) == []
    assert RE._unread_headings(line, set()) == [0]


# --- BioMarin: the same header, wrapped ----------------------------------------------
#
# One header over six columns and two headings across three lines:
#
#     Three Months Ended
#     June 30, Six Months Ended
#     June 30,
#     2026 2025 % Change 2026 2025 % Change
#
# Keyed on a shared line, the three month heading was invisible and the six month one
# took the table, so VOXZOGO's June quarter of $253mm was filed as a half year against
# the $472mm printed three columns along.

BMRN = (Path(__file__).parent / "fixtures" / "bmrn_8k_wrapped_header.txt").read_text()

BMRN_BRANDS = ["Voxzogo", "Vimizim", "Naglazyme", "Palynziq", "Brineura"]


def test_a_wrapped_header_still_collapses_to_its_leftmost_heading():
    assert [(p, e, y) for p, e, y, _ in RE.tables(BMRN)] == [("Q2", "2026-06-30", 2026)]


def test_the_quarter_column_is_read_not_the_half_year_three_along():
    found = RE.parse(BMRN, BMRN_BRANDS)
    assert found["Voxzogo"]["value"] == pytest.approx(253e6)
    assert found["Voxzogo"]["period"] == "Q2"
    assert found["Vimizim"]["value"] == pytest.approx(194e6)
    values = {round(v["value"] / 1e6) for v in found.values()}
    assert not values & {472, 405, 265}          # none of the six month columns


def test_the_dropped_half_of_a_header_does_not_fence_its_own_table():
    """The six month heading sits on a line of its own once the header wraps. Fencing
    there cut the table off from the heading just chosen for it, and nothing was read."""
    assert RE.parse(BMRN, BMRN_BRANDS)
