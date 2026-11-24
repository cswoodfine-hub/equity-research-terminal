"""A product years past its loss of exclusivity is not climbing to a peak. Its recent
growth fades over the length measured on products that far past their cliff, not over the
climb fade, and a hand entered regional split is checked against its own quoted total."""

import pytest

import assumptions
import db
import forecast as F
import growth_analogues as G
import regional_loe as R

SELLING = {"kind": "biosimilar", "since": "2016-12", "basis": "filer's report"}
MEASURED = {"after_years": 3, "median": 3.0, "low": 1, "high": 3.0, "n": 9,
            "observations": 18, "peaked": 5, "censored": 4, "source": "measured"}


def _csv(tmp_path, series):
    path = tmp_path / "analogues.csv"
    lines = ["# c", "ticker,product,fiscal_year,revenue,unit,scope,accession,form,quote,note"]
    for (ticker, product), years in series.items():
        lines += [f"{ticker},{product},{y},{v},USD,worldwide,0000000000-00-000000,10-K,q,"
                  for y, v in years.items()]
    path.write_text("\n".join(lines) + "\n")
    return path


def _settled(first_year, rises):
    """A product that peaks in its second year, falls 40%, holds three years, then rises
    by ``rises`` in turn and holds again: its growth stops when the rises do."""
    years = {first_year: 900.0, first_year + 1: 1000.0, first_year + 2: 600.0}
    level, year = 600.0, first_year + 2
    for _ in range(3):
        year += 1
        years[year] = level
    for rise in rises:
        year += 1
        level *= 1 + rise
        years[year] = level
    for _ in range(3):
        year += 1
        years[year] = level
    return years


def test_growth_is_counted_only_three_years_past_the_cliff(tmp_path):
    years = _settled(2000, (0.05,))
    years[2003] = 640.0                       # a rise the year after the cliff is not counted
    obs = G.past_cliff_observations(G.load(_csv(tmp_path, {("SNY", "Old"): years})))
    assert [o["year"] for o in obs] == [2006]
    assert obs[0]["fade"] == 1 and obs[0]["censored"] is False


def test_the_past_cliff_fade_needs_three_products_seen_to_stop(tmp_path):
    two = {("A", "One"): _settled(2000, (0.06, 0.04)), ("B", "Two"): _settled(2001, (0.08,))}
    assert G.measure_past_cliff(_csv(tmp_path, two)) is None
    three = {**two, ("C", "Three"): _settled(2002, (0.05, 0.03))}
    got = G.measure_past_cliff(_csv(tmp_path, three))
    assert got["n"] == 3 and got["peaked"] == 3 and got["after_years"] == 3
    assert got["median"] in (1, 2)
    assert "3 or more years past a fall of 20%" in G.past_cliff_source(got)


def _old(growth=0.064, loe=2012, fade=10, stated=False, measured=MEASURED, **over):
    scalars = {"therapy_mode": "marketed", "base_revenue": 1000.0, "revenue_growth_pct": growth,
               "terminal_growth_pct": 0.0, "growth_fade_years": fade, "wacc": 0.08,
               "forecast_start_year": 2026, "forecast_years": 10, "cogs_pct": 0.2,
               "sga_pct": 0.2, "rd_pct": 0.1, "tax_rate": 0.2, "pos": 1.0}
    scalars.update(over)
    return {"scalars": scalars, "indications": [], "is_marketed": True, "modality": "biologic",
            "loe": {"year": loe, "basis": "reference product exclusivity (12y)"},
            "erosion_defaults": {}, "regions": [], "competitor": SELLING,
            "past_cliff_fade": measured, "fade_stated": stated}


def test_a_product_a_decade_off_exclusivity_fades_its_growth_over_the_measured_years():
    climb, settled = F.build(_old(measured=None)), F.build(_old())
    assert settled["revenue_after_loe"][3:] == pytest.approx([settled["revenue_after_loe"][2]] * 7)
    assert settled["revenue_after_loe"][-1] < climb["revenue_after_loe"][-1]
    assert settled["rnpv"] < climb["rnpv"]
    assert any("growth fades over 3 years" in n and "past their cliff" in n
               for n in settled["notes"])
    assert any("fading to +0.0% over 3 years" in n for n in settled["notes"])


def test_a_stated_fade_a_recent_cliff_a_cliff_ahead_and_a_fall_are_left_alone():
    for inputs in (_old(stated=True), _old(loe=2023), _old(loe=2030), _old(growth=-0.05)):
        alone = F.build({**inputs, "past_cliff_fade": None})
        assert F.build(inputs)["revenue_after_loe"] == pytest.approx(alone["revenue_after_loe"])
    # a fade already shorter than the measured one stands
    short = _old(fade=2)
    assert F.build(short)["revenue_after_loe"] == pytest.approx(
        F.build({**short, "past_cliff_fade": None})["revenue_after_loe"])


def test_a_term_that_lapsed_with_nothing_copying_it_keeps_its_own_fade():
    uncopied = _old()
    uncopied["competitor"] = None
    assert F.build(uncopied)["revenue_after_loe"] == pytest.approx(
        F.build({**uncopied, "past_cliff_fade": None})["revenue_after_loe"])
    # a launch on file is a cliff that happened, competitor record or not
    observed = {**uncopied, "loe": {"year": 2012, "basis": "generic marketed", "observed": True}}
    assert any("past their cliff" in n for n in F.build(observed)["notes"])


def test_a_product_with_no_date_takes_the_statutory_term_from_its_approval():
    inputs = {**_old(), "loe": None, "approval_year": 2000,
              "loe_defaults": {"biologic": {"years_from_launch": 12, "source": "BPCIA"}}}
    assert any("exclusivity was lost 2012" in n for n in F.build(inputs)["notes"])
    # a stated LOE ahead of the forecast is a cliff still to come
    inputs["scalars"] = {**inputs["scalars"], "loe_year": 2031}
    assert not any("past their cliff" in n for n in F.build(inputs)["notes"])


def test_only_a_judgement_counts_as_a_stated_fade():
    def merged(evidence):
        return {(None, "US", "growth_fade_years", None): {"source": "s", "evidence": evidence}}
    assert assumptions._fade_stated(merged("analogue")) is False
    assert assumptions._fade_stated(merged("convention")) is False
    assert assumptions._fade_stated(merged("judgement")) is True
    assert assumptions._fade_stated({}) is False


# --- a hand entered split checked against its own quoted total -------------------------
QUOTE = "Lantus | 1,733 | +6.4% | +10.3% | 808 | +32.1% | 297 | -12.4% | 628 | +0.8%"


def _lantus(tmp_path, quote=QUOTE, parts=(("US", 808), ("EU", 297), ("ROW", 628))):
    path = str(tmp_path / "s.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'SNY', 'Sanofi')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Lantus Solostar', 1)")
    for region, value in parts:
        conn.execute("INSERT INTO asset_revenue_regions (asset_id, fiscal_year, member, region,"
                     " value, unit, source, note, is_curated) VALUES (1, 2025, ?, ?, ?, 'EUR',"
                     " 'annual report table', ?, 1)", (region, region, value * 1e6, quote))
    conn.commit()
    return conn


def test_a_curated_split_with_no_worldwide_figure_is_checked_against_its_quote(tmp_path):
    got = R.split(_lantus(tmp_path), 1)
    assert [p["region"] for p in got["parts"]] == ["US", "EU", "ROW"]
    assert got["total"] == pytest.approx(1733e6)


def test_a_quote_that_does_not_print_the_sum_refuses_the_split(tmp_path):
    # Europe left out: 808 and 628 make 1,436, which the line does not print
    assert R.split(_lantus(tmp_path, parts=(("US", 808), ("ROW", 628))), 1) is None


def test_the_row_is_read_after_its_heading_and_its_largest_figure_is_the_total(tmp_path):
    quote = ("Specialty Medicines turnover – year ended 31 December 2025 | Total | US ... "
             "Rukobia | 169 | 5 | 8 | 150 | 1 | 4 | 10 | 25 | 25 | 9 | >100 | >100")
    got = R.split(_lantus(tmp_path, quote=quote, parts=(("US", 150), ("EU", 10), ("ROW", 9))), 1)
    assert got["total"] == pytest.approx(169e6)


def test_a_growth_figure_that_equals_the_sum_is_not_the_total(tmp_path):
    # GSK prints growth with no percent sign; 25 is a growth rate here, not the total
    quote = "Thing | 300 | 25 | 25 | 20 | 1 | 5"
    assert R.split(_lantus(tmp_path, quote=quote, parts=(("US", 20), ("ROW", 5))), 1) is None


def test_a_percentage_is_not_a_total(tmp_path):
    quote = "Thing | 10.3% | 4 | 6"
    conn = _lantus(tmp_path, quote=quote, parts=(("US", 4), ("ROW", 6.3)))
    assert R.split(conn, 1) is None
