"""Reading product revenue out of the MD&A table, and refusing the tables that are not."""

import pytest

import revenue_mdna

LILLY = ("The following table summarizes our revenue by product in 2025: "
         "U.S. Outside U.S. Total Total Percent Change "
         "Mounjaro $ 13,651 $ 9,315 $ 22,965 $ 11,540 99 "
         "Zepbound (1) 13,484 58 13,542 4,926 175 "
         "Verzenio 3,464 2,259 5,723 5,307 8")

# Gilead splits three ways before the total, and prints patent expiries elsewhere in
# the same section keyed by the same product names.
GILEAD = ("Product sales: (in millions) U.S. Europe Other Total "
          "Biktarvy $ 11,467 $ 1,676 $ 1,190 $ 14,334 "
          "Descovy 2,559 93 105 2,758")
GILEAD_PATENTS = ("Patent expiration (in millions) Epclusa 2033 2032 "
                  "Biktarvy 2036 (6) 2033 Veklury 2036 (7) 2035")


def test_reads_a_total_from_split_columns():
    out = revenue_mdna.parse(LILLY, ["Mounjaro", "Zepbound", "Verzenio"])
    assert out["Mounjaro"] == 22_965e6
    assert out["Zepbound"] == 13_542e6      # 13,484 + 58
    assert out["Verzenio"] == 5_723e6


def test_reads_a_three_way_split():
    out = revenue_mdna.parse(GILEAD, ["Biktarvy", "Descovy"])
    # The US column alone is not the revenue: 11,467 + 1,676 + 1,190 = 14,333.
    assert out["Biktarvy"] == 14_334e6
    assert out["Descovy"] == 2_758e6


def test_refuses_a_patent_expiry_table():
    # "Veklury 2036 (7) 2035" is a patent year, not two billion dollars of revenue.
    assert revenue_mdna.parse(GILEAD_PATENTS, ["Epclusa", "Biktarvy", "Veklury"]) == {}


def test_reads_revenue_then_growth():
    amgen = ("Worldwide product sales (dollar amounts in millions): "
             "Prolia $ 4,414 1 % $ 4,374 8 % Repatha 3,016 36 % 2,222 36 %")
    out = revenue_mdna.parse(amgen, ["Prolia", "Repatha"])
    assert out == {"Prolia": 4_414e6, "Repatha": 3_016e6}


def test_a_bare_year_is_never_money():
    assert revenue_mdna.read_row("2033 2032") is None
    assert revenue_mdna.read_row("2036 (7) 2035") is None
    assert revenue_mdna.read_row("1,234 5 %") == 1234


def test_a_value_above_company_revenue_is_not_revenue():
    assert revenue_mdna.parse(LILLY, ["Mounjaro"], company_revenue=1e9) == {}


def test_no_table_means_no_values():
    assert revenue_mdna.parse("Revenue increased in 2025 driven by Mounjaro.",
                              ["Mounjaro"]) == {}
    assert revenue_mdna.parse("", ["Mounjaro"]) == {}


def test_scale_is_read_from_the_table():
    assert revenue_mdna.scale("(in thousands)") == 1e3
    assert revenue_mdna.scale("(dollars in millions)") == 1e6
    assert revenue_mdna.scale("no statement") == 1e6      # what every filer here uses


# The foreign filers, whose 20-F tables are laid out three more ways again.
def test_reads_thousands_separated_by_spaces():
    # Novartis writes 7,748 as "7 748". The row itself cannot say whether "93 105" is
    # one number or two, so the table decides: one that uses commas is not spaced.
    novartis = ("2025 USD m 2024 USD m Change % "
                "Entresto 7 748 7 822 - 1 Leqvio 1 198 754 59")
    out = revenue_mdna.parse(novartis, ["Entresto", "Leqvio"])
    assert out["Entresto"] == 7_748e6
    assert out["Leqvio"] == 1_198e6


def test_a_comma_table_never_merges_across_spaces():
    # "93 105" is two numbers here, and reading it as 93,105 would inflate a row
    # thirtyfold.
    assert revenue_mdna.read_row("2,559 93 105 2,758") == 2_758e0 * 1e0 or True
    assert revenue_mdna.read_row("2,559 93 105 2,758") == 2758


def test_reads_a_signed_percentage_column():
    # Sanofi writes growth as "+20.2%", which has a decimal point and so is not a bare
    # integer; the percent sign is what settles it.
    sanofi = ("Net sales Change (at CER) "
              "Dupixent 15,714 +20.2% +25.2% 11,538 +26.7% "
              "Kevzara 507 +19.6% +23.6% 321 +36.6%")
    assert revenue_mdna.parse(sanofi, ["Dupixent", "Kevzara"])["Dupixent"] == 15_714e6


def test_reads_a_total_printed_before_its_parts():
    # Novo gives world sales first, then the regions that add up to it.
    novo = ("Total sales in 2025 (in DKK million) US Operations International "
            "Wegovy ® 79,106 51,015 28,091")
    assert revenue_mdna.parse(novo, ["Wegovy"])["Wegovy"] == 79_106e6


def test_a_trademark_symbol_does_not_hide_the_row():
    assert revenue_mdna.parse("(in DKK million) Victoza ® 3,020 471 2,549",
                              ["Victoza"])["Victoza"] == 3_020e6


# --- a product broken out by geography ------------------------------------------------

def test_a_geography_label_between_the_name_and_its_figure():
    """AbbVie reports every product by region, so the name is followed by "United
    States" rather than by a number and the whole table read as empty."""
    window = ("(dollars in millions) 2025 2024 2023 Skyrizi United States $ 15,202 "
              "$ 10,086 $ 6,753 50.7 % 49.3 % International 2,360 1,632 1,010 44.6 % "
              "61.6 % Total $ 17,562 $ 11,718 $ 7,763 49.9 % 50.9 %")
    found = revenue_mdna.parse(window, ["Skyrizi"], 61.2e9)
    assert found["Skyrizi"] == pytest.approx(17_562e6)


def test_the_geographic_total_is_taken_not_the_domestic_figure():
    """The first number after the name is the United States column. Reading it
    understates the product by a third."""
    window = ("(in millions) Rinvoq United States $ 5,940 $ 4,259 39.5 % "
              "International 2,364 1,712 38.0 % Total $ 8,304 $ 5,971 39.1 %")
    found = revenue_mdna.parse(window, ["Rinvoq"], 61.2e9)
    assert found["Rinvoq"] == pytest.approx(8_304e6)
    assert found["Rinvoq"] != pytest.approx(5_940e6)


def test_a_negative_percentage_outside_its_bracket_still_closes_the_row():
    """Humira's row ends "(49.5) %", with the sign outside the bracket. A cell token
    that closed at the bracket left the percent behind, so the figure read as a fourth
    money column and the row was refused for having nothing to close it."""
    window = ("(in millions) Humira United States $ 3,062 $ 7,142 (57.1) % "
              "International 1,478 1,851 (20.2) % Total $ 4,540 $ 8,993 (49.5) %")
    found = revenue_mdna.parse(window, ["Humira"], 61.2e9)
    assert found["Humira"] == pytest.approx(4_540e6)


def test_a_product_cannot_borrow_the_next_products_total():
    """A product with no total of its own must report nothing rather than collect the
    figure belonging to whatever follows it."""
    window = ("(in millions) Alpha United States $ 100 International 50 "
              "Beta United States $ 900 International 100 Total $ 1,000")
    found = revenue_mdna.parse(window, ["Alpha", "Beta"], 5e9)
    assert "Alpha" not in found


def test_year_columns_with_no_growth_column():
    """The commonest mid-cap layout. Every shape the reader knew relied on a percentage
    to close the run, so a table of nothing but year columns read as nothing."""
    assert revenue_mdna.read_row("$ 2,513.7 $ 2,313.5 $ 1,836.0 ") == pytest.approx(2513.7)


def test_a_bare_year_is_still_not_money():
    """BioMarin prints patent expiries keyed by product name, and the year-column rule
    must not turn "VOXZOGO 2030 2029" into two billion dollars."""
    assert revenue_mdna.read_row("2030 2029 ") is None


# --- reading a table whose products are not known in advance --------------------------

NBIX_TABLE = ("Revenues Year Ended December 31, (in millions) 2025 2024 2023 "
              "INGREZZA $ 2,513.7 $ 2,313.5 $ 1,836.0 CRENESSITY 301.2 1.7 - "
              "Other 19.0 15.4 24.6 Total net product sales 2,833.9 2,330.6 1,860.6")


def test_products_are_discovered_when_none_are_known():
    """The brand-matched path cannot help a company whose marketed products are not on
    file, which is most of the mid-caps: Neurocrine holds only pipeline rows derived
    from trials, so there was never a name to search its table for."""
    found = revenue_mdna.discover(NBIX_TABLE, 2.9e9)
    assert found == {"INGREZZA": pytest.approx(2_513.7e6),
                     "CRENESSITY": pytest.approx(301.2e6)}


def test_a_discovered_table_must_add_up_to_its_own_total():
    """This is what makes reading unknown labels safe. A table that does not balance was
    either misread or was never a revenue table."""
    broken = NBIX_TABLE.replace("2,833.9", "9,999.9")
    assert revenue_mdna.discover(broken, 2.9e9) == {}


def test_an_unnamed_row_counts_toward_the_total_without_becoming_a_product():
    """Neurocrine's table carries a 19m "Other". Leaving it out of the sum left the
    total short and threw away a table that had been read correctly."""
    found = revenue_mdna.discover(NBIX_TABLE, 2.9e9)
    assert "Other" not in found
    assert len(found) == 2


def test_an_expense_schedule_is_not_a_revenue_table():
    """An expense schedule balances exactly as well and is laid out identically, so
    arithmetic alone cannot tell them apart. This found Neurocrine's payroll and
    Alnylam's research and development instead of their products."""
    expenses = ("(in millions) 2025 2024 Payroll and benefits 306.4 280.1 "
                "Clinical trial costs 244.2 210.0 "
                "Total research and development expenses 550.6 490.1")
    assert revenue_mdna.discover(expenses, 2.9e9) == {}


def test_a_total_that_does_not_name_revenue_is_not_accepted():
    balanced = ("(in millions) 2025 Alpha 600.0 Beta 400.0 Total operating costs 1,000.0")
    assert revenue_mdna.discover(balanced, 5e9) == {}


def test_a_name_joined_to_the_one_before_it_is_a_group_not_a_row():
    """Merck prints "GARDASIL/GARDASIL 9 1,169" and "PROQUAD, M-M-R II and VARIVAX 2,451".
    The last name on each line is followed by the figure and was being booked it."""
    import revenue_mdna as M
    window = ("Second Quarter\n$ in millions\n2026\n2025\nChange\n"
              "GARDASIL/GARDASIL 9\n1,169\n1,126\n4 %\n"
              "PROQUAD, M-M-R II and VARIVAX\n1,003\n940\n7 %\n"
              "BRIDION\n469\n429\n9 %\n")
    found = M.parse(window, ["Gardasil 9", "Varivax", "Bridion", "Gardasil"])
    assert found == {"Bridion": 469e6}


def test_a_bracketed_fall_does_not_prove_a_rise():
    """Regeneron prints Libtayo as the United States, elsewhere, and the total, for this
    quarter and for last, then 30%. Both 489.4 over 376.5 and 342.6 over 489.4 come to
    thirty per cent, one up and one down, and reading the percentage as a magnitude took
    whichever it reached first. It reached the wrong one, and turned a product growing
    30% into one falling 30%. The filer had said which: it brackets its falls."""
    row = "$ 342.6 $ 146.8 $ 489.4 $ 247.8 $ 128.7 $ 376.5 30 % "
    assert revenue_mdna.read_growth(row) == (489.4, 376.5)


def test_a_bracketed_percentage_proves_the_fall_it_marks():
    """EYLEA on the same page, which Regeneron reports down and brackets to say so. The
    bracket closes after the percent sign, and while the cell pattern stopped at "(52 "
    the row lost the very figure that proves it: every fall Regeneron reports was
    unreadable, so only its rising products could be seen at all."""
    row = "$ 412.2 $ 300.2 $ 712.4 $ 754.3 $ 736.0 $ 1,490.3 (52 %) "
    assert revenue_mdna.read_growth(row) == (712.4, 1490.3)


def test_signs_are_left_alone_where_the_row_does_not_show_them():
    """A row this reads two percentages from, where the sign pattern finds a different
    number of them, is proved on magnitude as before rather than on a guessed sign."""
    row = "4,591 3,926 17 % "
    assert revenue_mdna.read_growth(row) == (4591.0, 3926.0)


def test_the_bracket_is_read_on_either_side_of_the_percent_sign():
    """Bristol writes "(6) %" where Regeneron writes "(52 %)". Opdivo: 2,485 against
    2,560 is a fall of 3%, printed as (3) %, and a pattern that knew only Regeneron's
    bracket found no sign on this row at all."""
    row = "$ 1,417 $ 1,068 $ 2,485 $ 1,506 $ 1,053 $ 2,560 (6) % 1 % (3) % (6) % (1) % (4) % "
    assert revenue_mdna.read_growth(row) == (2485.0, 2560.0)


def test_on_a_row_of_parts_and_totals_only_the_totals_are_paired():
    """Bristol's Abraxane: the United States, the rest of the world and the total, this
    quarter and last, then six percentages. 43 against 72 is a fall of 40% and the row
    prints a 40%, because that is what the international column did. It is a true pair
    and the wrong one. The product is 55 against 105."""
    row = "12 43 55 33 72 105 (62) % (40) % (47) % (62) % (40) % (47) % "
    # The caller says whether the table spaces its thousands, read off the whole table.
    # Bristol's does not, and left to this one row "72 105" would read as one number.
    assert revenue_mdna.read_growth(row, spaced=False) == (55.0, 105.0)


def test_totals_are_preferred_on_the_half_year_row_too():
    """Eliquis for the six months: 6,434 and 2,183 make 8,617; 5,299 and 1,946 make
    7,245; and 8,617 over 7,245 is the 19% printed third."""
    row = "6,434 2,183 8,617 5,299 1,946 7,245 21 % 12 % 19 % 21 % 6 % 17 % "
    assert revenue_mdna.read_growth(row) == (8617.0, 7245.0)


def test_a_row_with_no_totals_is_read_as_before():
    row = "4,591 3,926 17 % "
    assert revenue_mdna.read_growth(row) == (4591.0, 3926.0)
