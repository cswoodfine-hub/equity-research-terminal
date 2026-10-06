"""Whether a loss of exclusivity is already in the reported revenue, and what a moved
LOE does on either side of the base date."""

from __future__ import annotations

import pytest

import forecast as F


def test_a_cliff_before_the_window_takes_its_drop_and_every_year_of_decay():
    """A 2023 cliff on a window opening in 2026 is three years into its curve by then:
    the year-one drop and two years of decay. Stepping from the first year skipped both,
    so the earlier date was worth more than a 2025 one."""
    years = list(range(2026, 2031))
    flat = [100.0] * len(years)
    got = F.erode(flat, years, 2023, 0.6, 0.35)
    assert got[0] == pytest.approx(100.0 * 0.4 * 0.65 ** 2)
    assert got[1] == pytest.approx(100.0 * 0.4 * 0.65 ** 3)
    # The late rate takes over on its own year counted from the cliff, not the window.
    slowed = F.erode(flat, years, 2023, 0.6, 0.35, 0.10, 4)
    assert slowed[0] == pytest.approx(100.0 * 0.4 * 0.65 ** 2)
    assert slowed[1] == pytest.approx(100.0 * 0.4 * 0.65 ** 2 * 0.9)
    # Each year is the same curve whatever year the window opens in.
    longer = F.erode([100.0] * 10, list(range(2021, 2031)), 2023, 0.6, 0.35, 0.10, 4)
    assert longer[5:] == pytest.approx(slowed)


def test_an_earlier_cliff_is_never_worth_more_in_any_year():
    years = list(range(2026, 2046))
    flat = [100.0] * len(years)
    for late, late_from in ((None, None), (0.10, 4)):
        previous = None
        for loe in range(2050, 2005, -1):
            got = F.erode(flat, years, loe, 0.6, 0.35, late, late_from)
            if previous is not None:
                assert all(a <= b + 1e-12 for a, b in zip(got, previous)), loe
            previous = got


# --- the record decides the base, a stated year only moves the cliff -----------------

def _product(record=None, past=False, regions=None, late=False, stated=None,
             actuals=None, **over):
    """A marketed product opening in 2026 on a 2025 base. ``record`` is the exclusivity
    on file, ``past`` a loss on file with no date, ``stated`` a loe_year scalar."""
    scalars = {"therapy_mode": "marketed", "base_revenue": 1000.0,
               "revenue_growth_pct": 0.05, "terminal_growth_pct": 0.0,
               "forecast_start_year": 2026, "forecast_years": 10, "wacc": 0.08,
               "pos": 1.0, "cogs_pct": 0.2, "sga_pct": 0.2, "rd_pct": 0.1,
               "tax_rate": 0.15}
    if late:
        scalars.update(erosion_year1_pct=0.6, erosion_decay_pct=0.35,
                       erosion_late_decay_pct=0.10, erosion_late_from_year=4)
    else:
        scalars.update(erosion_year1_pct=0.25, erosion_decay_pct=0.20)
    if stated is not None:
        scalars["loe_year"] = stated
    scalars.update(over)
    loe = ({"year": record, "basis": "compound patent"} if record is not None
           else {"year": None, "basis": "lost before the window", "in_base": True}
           if past else None)
    return {"scalars": scalars, "indications": [], "loe": loe,
            "regions": regions or [], "actuals": actuals or [], "valuation_year": 2025,
            "is_marketed": True}


def _carried(built, years=range(2036, 2121)):
    """{year: revenue} the terminal value carries past the horizon, part by part."""
    tail = built["terminal_tail"]
    final = built["revenue_after_loe"][built["years"].index(tail["end"])]
    out = {y: 0.0 for y in years}
    for weight, loe, in_base in tail["parts"]:
        path = F.terminal_path(tail["growth"], tail["end"], loe, in_base,
                               tail["year1_pct"], tail["decay_pct"],
                               tail["late_decay_pct"], tail["late_from_year"], list(years))
        for y in years:
            out[y] += weight * final * path[y]
    return out


def test_a_stated_year_on_a_record_in_the_base_does_nothing():
    """Orencia's 2017 date is in the base: the reported revenue already carries it. A
    stated year, before or after the window, cannot take it out or put it in again."""
    for record, past in ((2017, False), (None, True)):
        base = F.build(_product(record=record, past=past))
        assert base["loe_in_base"]
        for stated in (2010, 2017, 2023, 2025, 2027, 2040):
            got = F.build(_product(record=record, past=past, stated=stated))
            assert got["loe_in_base"] and got["loe_year"] == base["loe_year"]
            assert got["loe_basis"] == base["loe_basis"]
            assert got["rnpv"] == base["rnpv"]
            assert got["revenue_after_loe"] == base["revenue_after_loe"]
            assert any(f"a stated LOE of {stated} is not applied" in n for n in got["notes"])


def test_a_stated_year_before_a_record_still_ahead_erodes_along_the_curve():
    base = F.build(_product(record=2027))
    assert not base["loe_in_base"]
    by_year = {s: F.build(_product(record=2027, stated=s)) for s in (2023, 2025, 2027)}
    for stated, got in by_year.items():
        assert not got["loe_in_base"] and got["loe_year"] == stated
        assert got["loe_basis"] == "assumed"
    # 2023 is three years down the curve in 2026: the drop and two years of decay.
    first = by_year[2023]["revenue"][0]
    assert by_year[2023]["revenue_after_loe"][0] == pytest.approx(first * 0.75 * 0.8 ** 2)
    assert by_year[2027]["rnpv"] == pytest.approx(base["rnpv"])
    assert by_year[2023]["rnpv"] < by_year[2025]["rnpv"] < by_year[2027]["rnpv"]


def test_with_nothing_on_file_a_stated_year_is_never_in_the_base():
    got = F.build(_product(stated=2010))
    assert not got["loe_in_base"] and got["loe_year"] == 2010
    assert got["revenue_after_loe"][0] == pytest.approx(
        got["revenue"][0] * F.erosion_factor(16, 0.25, 0.20))
    assert F.build(_product())["rnpv"] > got["rnpv"]
    # A blank stated cell is no statement.
    assert F.build(_product(record=2030, stated=""))["rnpv"] == \
        F.build(_product(record=2030))["rnpv"]


def test_a_dateless_region_with_a_past_floor_follows_the_us_record():
    europe = [{"region": "EU", "label": "Europe", "share": 0.3, "share_basis": "filed",
               "year": None, "in_base": False, "basis": None, "floor_year": 2024,
               "floor_basis": "EU data and market protection"}]
    # The US record is in the base, so the past floor is too: the region stays whole.
    kept = F.build(_product(record=2017, regions=europe))
    assert kept["regions"][0]["in_base"] and kept["regions"][0]["loe_year"] == 2024
    assert kept["revenue_after_loe"] == pytest.approx(kept["revenue"])
    # A lever moves the US date before the floor: the region loses exclusivity on its
    # floor, two years down the curve by 2026, rather than staying whole.
    moved = F.build(_product(record=2030, regions=europe, stated=2020))
    region = moved["regions"][0]
    assert not region["in_base"] and region["loe_year"] == 2024
    assert region["revenue_after_loe"][0] == pytest.approx(
        moved["revenue"][0] * 0.3 * 0.75 * 0.8)
    at_floor = F.build(_product(record=2030, regions=europe, stated=2024))
    assert moved["rnpv"] < at_floor["rnpv"]


_RECORDS = {"2030": dict(record=2030), "2025": dict(record=2025), "none": {}}
_REGIONS = {
    "none": None,
    "dateless with a floor": [{"region": "EU", "label": "Europe", "share": 0.3,
                               "share_basis": "filed", "year": None, "in_base": False,
                               "basis": None, "floor_year": 2024,
                               "floor_basis": "EU data and market protection"}],
    "own date": [{"region": "EU", "label": "Europe", "share": 0.3, "share_basis": "filed",
                  "year": 2028, "in_base": False, "basis": "stated"}],
}


@pytest.mark.parametrize("late", [False, True], ids=["one rate", "late rate"])
@pytest.mark.parametrize("regions", list(_REGIONS), ids=list(_REGIONS))
@pytest.mark.parametrize("record", list(_RECORDS), ids=[f"record {k}" for k in _RECORDS])
def test_value_never_falls_as_the_stated_year_moves_later(record, regions, late):
    """The principle: a product's own improvement never lowers its value. A later LOE is
    an improvement, so the rNPV, every year's revenue and the revenue the terminal value
    carries past the horizon must each hold or rise as the stated year moves later, on
    either side of the base date."""
    previous = None
    for stated in range(2005, 2046):
        got = F.build(_product(regions=_REGIONS[regions], late=late, stated=stated,
                               **_RECORDS[record]))
        now = (got["rnpv"], got["revenue_after_loe"], _carried(got))
        if previous is not None:
            assert now[0] >= previous[0] - 1e-9, stated
            assert all(a >= b - 1e-9 for a, b in zip(now[1], previous[1])), stated
            assert all(now[2][y] >= previous[2][y] - 1e-9 for y in now[2]), stated
        previous = now


def test_value_is_flat_in_the_stated_year_when_the_record_is_in_the_base():
    europe = _REGIONS["dateless with a floor"]
    values = {F.build(_product(record=2020, regions=europe, stated=s))["rnpv"]
              for s in range(2005, 2046)}
    assert values == {F.build(_product(record=2020, regions=europe))["rnpv"]}


def _db(tmp_path, approved: str):
    """One biologic on file with no exclusivity row, so its record is the statutory
    twelve years from approval."""
    import assumptions as A
    import db
    path = str(tmp_path / "loe.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'BMY', 'Bristol')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed,"
                 " modality) VALUES (1, 1, 'Orencia', 1, 'biologic')")
    conn.execute("INSERT INTO approvals (asset_id, approval_date) VALUES (1, ?)",
                 (approved,))
    rows = [{"key": k, "value": v, "source": "t"} for k, v in (
        ("base_revenue", 3600.0), ("revenue_growth_pct", 0.03),
        ("terminal_growth_pct", 0.0), ("cogs_pct", 0.2), ("sga_pct", 0.2),
        ("rd_pct", 0.15), ("tax_rate", 0.15), ("wacc", 0.08), ("pos", 1.0),
        ("forecast_start_year", 2026), ("forecast_years", 10))]
    rows.append({"key": "therapy_mode", "text_value": "marketed", "source": "t"})
    A.save(conn, 1, rows)
    conn.commit()
    conn.close()
    return path


def test_the_slider_and_the_loe_grid_say_a_loss_in_the_base_cannot_move(tmp_path):
    import assumptions as A
    import db
    import forecast_view as V
    path = _db(tmp_path, "2005-12-23")
    got = V.whatif(path, "BMY", 1, loe_year=2031)
    assert got["base"]["loe_year"] == got["varied"]["loe_year"] == 2017
    assert got["varied"]["rnpv"] == got["base"]["rnpv"]
    assert "already in the reported revenue" in got["ignored"]["loe_year"]
    grid = V.sensitivity(path, "BMY", 1, preset="loe")
    assert grid["ok"] is False and "already in the reported revenue" in grid["missing"][0]
    conn = db.get_connection(path)
    inputs = A.load(conn, 1)
    conn.close()
    keys = [lever[1] for lever in V.lever_specs(inputs, F.build(inputs))]
    assert "loe_year" not in keys and "erosion_year1_pct" not in keys


def test_the_slider_never_falls_as_the_year_moves_later(tmp_path):
    import forecast_view as V
    path = _db(tmp_path, "2016-06-01")
    base = V.whatif(path, "BMY", 1)
    assert base["base"]["loe_year"] == 2028 and not base["ignored"]
    values = [V.whatif(path, "BMY", 1, loe_year=y)["varied"]["rnpv"]
              for y in range(2020, 2034)]
    assert all(b >= a for a, b in zip(values, values[1:]))
    assert values[0] < values[-1]
    assert values[2028 - 2020] == pytest.approx(base["base"]["rnpv"])


# --- a recent date on file needs the revenue to agree --------------------------------

def _on_file(record, full_years, stated=None, modality="biologic"):
    """A product on the curated erosion shape for its modality, with its reported full
    years as actuals (in millions, as assumptions.load hands them over)."""
    import assumptions as A
    inputs = _product(record=record, stated=stated)
    for key in ("erosion_year1_pct", "erosion_decay_pct"):
        inputs["scalars"].pop(key)
    inputs["modality"] = modality
    inputs["erosion_defaults"] = A.erosion_defaults()
    inputs["actuals"] = [{"fiscal_year": y, "period": "FY", "value": v}
                         for y, v in full_years.items()]
    return inputs


YERVOY = {2023: 2238.0, 2024: 2530.0, 2025: 2900.0}


def test_a_recent_cliff_with_no_fall_since_lands_in_the_first_forecast_year():
    """Yervoy's record is the 2023 statutory floor and it has grown every year since.
    No cliff has happened, so it lands in 2026 rather than never."""
    import evidence
    got = F.build(_on_file(2023, YERVOY))
    assert not got["loe_in_base"] and got["loe_year"] == 2025
    assert got["loe_basis"] == ("compound patent of 2023, but no fall in the reported "
                                "revenue since, so by convention the cliff lands in 2026")
    assert evidence.grade(got["loe_basis"]) == "convention"
    assert got["revenue_after_loe"][0] == pytest.approx(got["revenue"][0] * 0.75)
    assert got["rnpv"] < F.build(_on_file(2017, YERVOY))["rnpv"]


def test_a_recent_cliff_the_revenue_shows_stays_in_the_base():
    """Victoza's 2024 date shows: 8,664mm, 5,482mm, 3,020mm."""
    got = F.build(_on_file(2024, {2023: 8664.0, 2024: 5482.0, 2025: 3020.0},
                           modality="small molecule"))
    assert got["loe_in_base"] and got["loe_year"] == 2024
    assert got["revenue_after_loe"] == got["revenue"]


def test_an_old_date_stays_in_the_base_whatever_the_revenue_did():
    """Orencia's 2017 date is past every erosion shape's steep years: the rule the base
    has always had stands, with or without a fall since."""
    got = F.build(_on_file(2017, {2023: 3600.0, 2024: 3700.0, 2025: 3800.0}))
    assert got["loe_in_base"] and got["loe_year"] == 2017


def test_the_window_is_four_years_on_the_biologic_shape():
    rising = {2021: 900.0, 2022: 950.0, 2023: 1000.0, 2024: 1050.0, 2025: 1100.0}
    assert F.build(_on_file(2022, rising))["loe_in_base"]
    inside = F.build(_on_file(2023, rising))
    assert not inside["loe_in_base"] and inside["loe_year"] == 2025


def test_a_single_reported_year_is_no_evidence_either_way():
    """Perjeta's 2024 date with only FY2025 on file keeps the old rule."""
    got = F.build(_on_file(2024, {2025: 2968.0}))
    assert got["loe_in_base"] and got["loe_year"] == 2024


def test_fell_since_reads_full_years_from_the_loe_year_on():
    fy = lambda **years: [{"fiscal_year": int(y[1:]), "period": "FY", "value": v}
                          for y, v in years.items()]
    assert F.fell_since([], 2023) is None
    assert F.fell_since(fy(y2020=5.0, y2021=4.0), 2023) is None     # nothing since
    assert F.fell_since(fy(y2025=5.0), 2023) is None                # no pair to compare
    assert F.fell_since(fy(y2022=5.0, y2023=4.0), 2023) is True     # the LOE year counts
    assert F.fell_since(fy(y2020=5.0, y2021=4.0, y2023=6.0, y2024=6.0), 2023) is False
    assert F.fell_since(fy(y2023=6.0, y2024=7.0, y2025=6.5), 2023) is True
    # A quarter is not a year, and a gap leaves no pair.
    quarters = [{"fiscal_year": 2025, "period": "Q1", "value": 1.0}]
    assert F.fell_since(fy(y2023=6.0, y2024=7.0) + quarters, 2023) is False
    assert F.fell_since(fy(y2022=6.0, y2024=1.0), 2023) is None


def test_the_window_falls_back_to_the_earliest_curated_late_year():
    import assumptions as A
    defaults = A.erosion_defaults()
    assert F.cliff_window({"erosion_defaults": defaults}) == \
        int(defaults["small molecule"]["late_from_year"]) == 4
    assert F.cliff_window({"erosion_defaults": defaults}, 6) == 6
    assert F.cliff_window({}) is None


def test_a_lever_on_a_cliff_not_yet_landed_moves_one_way_and_starts_from_the_base():
    base = F.build(_on_file(2023, YERVOY))
    shown = F.build(_on_file(2023, YERVOY, stated=base["loe_year"]))
    assert shown["rnpv"] == pytest.approx(base["rnpv"])
    assert shown["revenue_after_loe"] == pytest.approx(base["revenue_after_loe"])
    values = [F.build(_on_file(2023, YERVOY, stated=s))["rnpv"] for s in range(2010, 2041)]
    assert all(b >= a - 1e-9 for a, b in zip(values, values[1:]))
    assert values[0] < base["rnpv"] < values[-1]
