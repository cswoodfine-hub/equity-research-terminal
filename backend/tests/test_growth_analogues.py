"""Growth length measured from drugs that have peaked."""

import math

import pytest

import growth_analogues as G


def _csv(tmp_path, rows):
    path = tmp_path / "analogues.csv"
    lines = ["# c", "ticker,product,fiscal_year,revenue,unit,scope,accession,form,quote,note"]
    lines += [f"{t},{p},{y},{v},USD,worldwide,0000000000-00-000000,10-K,q," for t, p, y, v in rows]
    path.write_text("\n".join(lines) + "\n")
    return path


def _grow(start, growth, fade, first_year, after=()):
    """A drug that follows the engine's own fade exactly, then falls."""
    years, level = {first_year: start}, start
    for i in range(fade):
        level *= 1 + growth * (1 - i / fade)
        years[first_year + i + 1] = level
    for j, drop in enumerate(after, 1):
        years[first_year + fade + j] = level * drop
    return years


def test_the_engines_own_path_is_fitted_back_to_its_fade():
    for growth, fade in ((0.6, 4), (0.2, 7), (0.08, 3)):
        assert G.fitted_fade(growth, G.fade_path(growth, fade)) == fade


def test_a_peaked_drug_gives_one_observation_a_year_before_its_peak(tmp_path):
    years = _grow(1000, 0.30, 6, 2010, after=(0.85, 0.75))
    path = _csv(tmp_path, [("MRK", "Drug", y, v) for y, v in years.items()])
    got = G.measure(path)
    obs = got["observations"]
    # 2011 is growth out of the first year on file, a launch year, and is not measured.
    assert [o["year"] for o in obs] == list(range(2012, 2016))
    assert obs[0]["years_to_peak"] == 4
    assert 3 <= obs[0]["fade"] <= 5
    assert got["censored"] == []


def test_a_drug_still_near_its_best_or_cut_by_exclusivity_is_censored(tmp_path):
    growing = _grow(1000, 0.30, 6, 2018, after=(0.97,))
    cliff = _grow(1000, 0.30, 6, 2000, after=(0.62, 0.35))
    path = _csv(tmp_path, [("LLY", "Climber", y, v) for y, v in growing.items()]
                + [("ABBV", "Cliff", y, v) for y, v in cliff.items()])
    got = G.measure(path)
    assert got["censored"] == ["ABBV Cliff (lost exclusivity at its peak)",
                               "LLY Climber (still near its best)"]
    assert got["observations"] and all(o["censored"] for o in got["observations"])


def test_kaplan_meier_reads_a_censored_length_as_at_least():
    # Four drugs stop at 2, 4, 6 and 8 years; two more are still growing at 5 and 9.
    values = [(2, False), (4, False), (5, True), (6, False), (8, False), (9, True)]
    curve = G.kaplan_meier(values)
    assert curve[0] == (2, pytest.approx(5 / 6))
    assert G.km_quantile(curve, 0.5) == 6          # a plain median of the four is 5
    assert G.km_quantile([(2, 0.9), (4, 0.8)], 0.5) is None


def test_bands_count_each_drug_once_and_need_three_for_quartiles(tmp_path):
    rows = []
    for name, fade in (("A", 3), ("B", 5), ("C", 8), ("D", 10)):
        years = _grow(1000, 0.18, fade, 2000, after=(0.85, 0.8))
        rows += [("PFE", name, y, v) for y, v in years.items()]
    got = G.measure(_csv(tmp_path, rows))
    band = next(b for b in got["bands"] if b["band"] == (0.10, 0.25))
    assert band["n"] == 4 and band["products"] == ["PFE A", "PFE B", "PFE C", "PFE D"]
    assert band["low"] <= band["median"] <= band["high"]
    assert G.for_growth(got, 0.15) is band
    assert G.for_growth(got, -0.02) is None and G.for_growth(got, 0.0) is None
    assert G.for_growth(got, 0.7) is None           # a band with no drugs has no quartiles


def test_a_drug_that_changed_hands_is_one_series(tmp_path):
    rows = [("CELG", "Revlimid", 2016, 100), ("CELG", "Revlimid", 2017, 120),
            ("BMY", "Revlimid", 2020, 150), ("BMY", "Revlimid", 2021, 160),
            ("ABBV", "Imbruvica", 2020, 50), ("JNJ", "Imbruvica", 2020, 30)]
    series = G.load(_csv(tmp_path, rows))
    assert sorted(series) == ["ABBV Imbruvica", "BMY Revlimid", "JNJ Imbruvica"]
    assert series["BMY Revlimid"]["years"] == {2016: 100, 2017: 120, 2020: 150, 2021: 160}
    assert G.band_words((1.0, math.inf)) == "more than 100% a year"


def test_a_basis_break_is_not_growth_and_a_part_year_is_not_a_year(tmp_path):
    path = tmp_path / "a.csv"
    years = _grow(1000, 0.30, 6, 2010, after=(0.8, 0.6))
    lines = ["ticker,product,fiscal_year,revenue,unit,scope,accession,form,quote,note,basis_break,partial_year"]
    for y, v in years.items():
        lines.append(f"BIIB,Drug,{y},{v},USD,worldwide,a,10-K,q,,{1 if y == 2012 else ''},")
    lines.append("BIIB,Drug,2009,10,USD,worldwide,a,10-K,q,,,1")
    path.write_text("\n".join(lines) + "\n")
    series = G.load(path)
    assert 2009 not in series["BIIB Drug"]["years"]
    assert 2012 not in [o["year"] for o in G.measure(path)["observations"]]


def test_a_measured_fade_applies_to_filed_growth_only():
    marketed = {"therapy_mode": "marketed", "revenue_growth_pct": 0.2, "terminal_growth_pct": 0.0}
    filed = [{"key": "revenue_growth_pct", "indication_id": None, "source": "the 2026 the filed quarters imply"}]
    solved = [{"key": "revenue_growth_pct", "indication_id": None, "source": "solved, not observed: the rate"}]
    assert G.applies(marketed, filed) == ("revenue_growth_pct", 0.2)
    assert G.applies(marketed, solved) is None
    assert G.applies({**marketed, "revenue_growth_pct": -0.03}, filed) is None
    assert G.applies({**marketed, "terminal_growth_pct": None}, filed) is None
    franchise = {"therapy_mode": "franchise", "franchise_growth_pct": 0.04, "terminal_growth_pct": 0.0}
    assert G.applies(franchise, []) == ("franchise_growth_pct", 0.04)
    assert G.applies({"therapy_mode": "chronic"}, []) is None


def test_the_fade_source_names_the_band_the_count_and_the_censoring():
    row = {"band": (0.10, 0.25), "n": 9, "censored": 3, "median": 6.0, "low": 4.0, "high": None,
           "high_at_least": 11.0}
    text = G.fade_source(row)
    assert "9 drugs that grew 10% to 25% a year: the median took 6 years" in text
    assert "quartiles 4 to at least 11" in text and "3 of them censored" in text
    assert "growth_analogues.csv" in text
