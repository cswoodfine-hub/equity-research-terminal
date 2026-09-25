"""Eight drugs cannot each have the whole population.

forecast.build values one asset at a time and depletes the pool by that asset's patients
alone. Run once per competitor it hands each of them a private copy of the same people.
These tests pin the arithmetic that counts the population once.
"""

import pytest

import pool_crowding as PC


def _claim(name, peak, start=2027, prevalence=100e6, incidence=1e6, stop=0.648,
           eligible=1.0, multiple=1.0, midpoint=5.0, steepness=1.0, carryover=None):
    return {"asset_id": abs(hash(name)) % 10_000, "name": name, "ticker": "AAA",
            "indication": "Obesity", "start": start, "prevalence": prevalence,
            "eligible_pct": eligible, "incidence": incidence, "peak": peak,
            "midpoint": midpoint, "steepness": steepness, "funnel": 1.0,
            "multiple": multiple, "stop": stop, "carryover": carryover}


def test_one_asset_alone_is_unchanged_by_the_shared_solve():
    """The correction must be nil where there is nothing to share with, or it is not a
    crowding correction."""
    got = PC.solve([_claim("only", 0.04)], years=20)
    asset = got["assets"][0]
    assert asset["ratio"] == pytest.approx(1.0)
    assert asset["crowded"] == pytest.approx(asset["uncrowded"])


def test_competitors_take_from_each_other(tmp_path=None):
    got = PC.solve([_claim("a", 0.04), _claim("b", 0.04), _claim("c", 0.04)], years=20)
    for asset in got["assets"]:
        assert asset["ratio"] < 1.0
    alone = PC.solve([_claim("a", 0.04)], years=20)["assets"][0]
    assert max(got["assets"][0]["crowded"]) < max(alone["uncrowded"])


def test_the_shared_pool_is_never_oversubscribed():
    """Ten aggressive claimants cannot start more patients than exist."""
    claims = [_claim(f"a{i}", 0.30) for i in range(10)]
    got = PC.solve(claims, years=20)
    for row in got["shared"]:
        assert row["started"] <= row["pool"] + 1e-6
    assert got["rationed_years"] > 0, "the cap must actually bind on this input"


def test_when_the_pool_runs_out_every_claimant_is_cut_by_the_same_factor():
    """The neutral rule. Scaling one competitor more than another would be a view about
    who wins, which this module is not entitled to take."""
    claims = [_claim("big", 0.80), _claim("small", 0.40)]
    got = PC.solve(claims, years=20)
    year = next(i for i, r in enumerate(got["shared"]) if r["rationed"])
    big, small = got["assets"][0]["crowded"][year], got["assets"][1]["crowded"][year]
    assert big / small == pytest.approx(0.80 / 0.40, rel=1e-6)


def test_a_pool_of_the_years_own_diagnoses_carries_nothing_over():
    """Prevalence stated equal to incidence is the engine's annual-cohort pool: nothing
    carries into the next year and there is no opening stock. Two claimants whose shares
    never exceed a year's diagnoses then crowd each other not at all, as the engine,
    which never lets that pool run short, would have them. Read as carrying over, the
    pair was cut by 5% and 7%."""
    cohort = dict(prevalence=14.2e6, incidence=14.2e6, eligible=0.070423,
                  midpoint=1.75, steepness=0.53, stop=0.2537)
    got = PC.solve([_claim("felcorekibart", 0.0193, start=2031, **cohort),
                    _claim("lunsekimig", 0.01544, start=2032, **cohort)], years=25)
    for asset in got["assets"]:
        assert asset["ratio"] == pytest.approx(1.0)
    # A stated carryover still wins over the convention, as it does in the engine.
    stated = PC.solve([_claim("a", 0.30, carryover=1.0, **dict(cohort, midpoint=1.0)),
                       _claim("b", 0.30, carryover=1.0, **dict(cohort, midpoint=1.0))],
                      years=25)
    assert min(a["ratio"] for a in stated["assets"]) < 1.0


def test_a_later_entrant_finds_the_pool_already_drawn_down():
    early = _claim("early", 0.05, start=2027)
    late = _claim("late", 0.05, start=2035)
    got = PC.solve([early, late], years=25, first_year=2027)
    by_name = {a["name"]: a for a in got["assets"]}
    assert by_name["late"]["ratio"] < by_name["early"]["ratio"]


def test_recycling_returns_the_patients_who_stop():
    """These drugs are stopped by most starters within a year. Without recycling a
    patient who takes one month of therapy is treated for ever and the pool drains to
    nothing, which puts more people on treatment than exist."""
    claims = [_claim(f"a{i}", 0.05) for i in range(6)]
    on = PC.solve(claims, years=25, recycle=True)
    off = PC.solve(claims, years=25, recycle=False)
    treated_on = max(r["treated"] for r in on["shared"])
    assert treated_on < on["pool"], "nobody may treat more people than exist"
    assert max(a["ratio"] for a in on["assets"]) > max(a["ratio"] for a in off["assets"])


def test_an_ex_us_multiple_does_not_remove_an_asset_from_the_domestic_pool():
    """The multiple is a filed ex-US to US revenue ratio, so an asset carrying one still
    sells to the same contested US patients. Grouping on it put every such asset in a
    pool of its own, which dissolved the crowding correction exactly when an ex-US figure
    was added: storing one would have handed back most of what counting the population
    once took away."""
    us = [_claim("us1", 0.04), _claim("us2", 0.04)]
    ex = _claim("also sells abroad", 0.04, multiple=1.55)
    got = PC.solve(us + [ex], years=20)
    by_name = {a["name"]: a for a in got["assets"]}
    assert got["unpooled"] == []
    assert all(a["pooled"] for a in got["assets"])
    assert by_name["also sells abroad"]["ratio"] < 1.0
    # And it is crowded on the same terms as its US-only rivals, not on a bigger pool.
    assert by_name["also sells abroad"]["ratio"] == pytest.approx(by_name["us1"]["ratio"])


def test_a_genuinely_different_population_is_still_not_pooled():
    """Prevalence times the eligible share is the population. Two assets treating
    different diseases, or different slices of one, do not compete for the same people."""
    shared = [_claim("a", 0.04), _claim("b", 0.04)]
    other = _claim("other disease", 0.04, prevalence=2e6)
    narrow = _claim("narrow slice", 0.04, eligible=0.25)
    got = PC.solve(shared + [other, narrow], years=20)
    by_name = {a["name"]: a for a in got["assets"]}
    assert by_name["other disease"]["pooled"] is False
    assert by_name["narrow slice"]["pooled"] is False
    assert sorted(u["name"] for u in got["unpooled"]) == ["narrow slice", "other disease"]


def test_an_asset_that_has_not_launched_claims_nothing():
    got = PC.solve([_claim("early", 0.05, start=2027),
                    _claim("late", 0.05, start=2040)], years=20, first_year=2027)
    late = next(a for a in got["assets"] if a["name"] == "late")
    assert late["crowded"][0] == 0.0
    assert late["uncrowded"][0] == 0.0


def test_summary_reports_what_was_claimed_against_what_one_pool_supplies():
    claims = [_claim(f"a{i}", 0.12) for i in range(5)]
    got = PC.solve(claims, years=20)
    s = PC.summary(got)
    assert s["uncrowded_share"] > s["crowded_share"]
    assert 0 < s["crowded_share"] <= 1.0
    assert len(s["by_year"]) == len(got["years"])


def test_no_claimants_returns_an_empty_answer_rather_than_raising():
    assert PC.solve([])["assets"] == []
    assert PC.summary({"shared": []}) == {}


def _pool_db(tmp_path, grouped=True):
    """Two assets on Obesity and one on Weight Loss, all on one population."""
    import db as db_module
    path = str(tmp_path / "group.db")
    db_module.init(path)
    conn = db_module.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name, reporting_currency)"
                 " VALUES (1, 'LLY', 'Eli Lilly', 'USD')")
    conn.execute("INSERT INTO indications (id, name) VALUES (367, 'Obesity'),"
                 " (332, 'Weight Loss'), (900, 'Something Else')")
    if not grouped:
        conn.execute("DELETE FROM indication_groups")
    for asset_id, name, ind in ((1, "alpha", 367), (2, "beta", 367), (3, "gamma", 332),
                                (4, "delta", 900)):
        conn.execute("INSERT INTO assets (id, owner_company_id, generic_name,"
                     " is_marketed) VALUES (?, 1, ?, 0)", (asset_id, name))
        for key, value in (("prevalence", 100e6), ("eligible_pct", 1.0),
                           ("incidence", 1e6), ("penetration_peak_pct", 0.04),
                           ("ramp_midpoint_year", 5.0), ("ramp_steepness", 1.0)):
            conn.execute("INSERT INTO assumptions (asset_id, indication_id, region,"
                         " scenario, key, value) VALUES (?, ?, 'US', 'base', ?, ?)",
                         (asset_id, ind, key, value))
        conn.execute("INSERT INTO assumptions (asset_id, region, scenario, key, value)"
                     " VALUES (?, 'US', 'base', 'forecast_start_year', 2027)", (asset_id,))
        conn.execute("INSERT INTO assumptions (asset_id, region, scenario, key, value)"
                     " VALUES (?, 'US', 'base', 'discontinuation_pct', 0.648)", (asset_id,))
    conn.commit()
    return conn


def test_one_population_written_under_two_names_is_one_pool(tmp_path):
    """Seven obesity assets sit on Obesity and Viking's sits on Weight Loss. Keyed on the
    indication id alone, Viking would get a private copy of the same adults, which is the
    error the crowding correction exists to remove."""
    conn = _pool_db(tmp_path)
    PC.clear_cache()
    names = {c["name"] for c in PC.claimants(conn, 367)}
    conn.close()
    assert names == {"alpha", "beta", "gamma"}, "Weight Loss belongs with Obesity"


def test_either_name_reaches_the_same_group(tmp_path):
    conn = _pool_db(tmp_path)
    PC.clear_cache()
    assert PC.group_of(conn, 332) == PC.group_of(conn, 367) == "obesity"
    assert {c["name"] for c in PC.claimants(conn, 332)} == {"alpha", "beta", "gamma"}
    conn.close()


def test_an_indication_in_no_group_competes_only_with_itself(tmp_path):
    """The table is deliberately incomplete. Nothing may depend on an indication being
    in it."""
    conn = _pool_db(tmp_path)
    PC.clear_cache()
    assert PC.group_of(conn, 900) == "indication:900"
    assert {c["name"] for c in PC.claimants(conn, 900)} == {"delta"}
    assert PC.ratios(conn, 900) == {}, "one claimant is not a crowd"
    conn.close()


def test_without_the_group_the_two_names_would_not_pool(tmp_path):
    """The failure the group table prevents, shown rather than asserted."""
    conn = _pool_db(tmp_path, grouped=False)
    PC.clear_cache()
    names = {c["name"] for c in PC.claimants(conn, 367)}
    conn.close()
    assert names == {"alpha", "beta"}, "gamma is stranded without the group"


def test_an_asset_that_takes_its_pool_from_the_disease_file_is_still_a_claimant(tmp_path):
    """A claimant is an asset that draws a share, which a penetration says, not one that
    writes its own prevalence. Obesity now has a row in data/epidemiology.csv, so a new
    obesity asset need not state 107,592,242, and keyed on a stated prevalence it would
    have escaped the crowding correction and claimed an uncrowded share of a pool eight
    other drugs are rationed on."""
    conn = _pool_db(tmp_path)
    # Asset beta states no pool of its own; everything else is as before.
    conn.execute("DELETE FROM assumptions WHERE asset_id = 2"
                 " AND key IN ('prevalence', 'incidence')")
    conn.commit()
    PC.clear_cache()
    claims = {c["name"]: c for c in PC.claimants(conn, 367)}
    conn.close()
    assert set(claims) == {"alpha", "beta", "gamma"}
    # Filled from the file, which carries the CDC figure every obesity seed already agrees on.
    assert claims["beta"]["prevalence"] == 107_592_242
    assert claims["beta"]["incidence"] == 4_478_747


def test_an_asset_that_states_a_pool_but_draws_no_share_is_not_a_claimant(tmp_path):
    """Pelacarsen carries a prevalence and deliberately no penetration, because its trial
    failed and there is no label for a share to be of. It takes nothing from the pool."""
    conn = _pool_db(tmp_path)
    conn.execute("DELETE FROM assumptions WHERE asset_id = 2"
                 " AND key = 'penetration_peak_pct'")
    conn.commit()
    PC.clear_cache()
    names = {c["name"] for c in PC.claimants(conn, 367)}
    conn.close()
    assert names == {"alpha", "gamma"}
