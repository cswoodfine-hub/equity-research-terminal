"""Reading product revenue out of the MD&A table, and refusing the tables that are not."""

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
