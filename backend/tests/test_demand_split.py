"""The Medicare growth split (docs/design/medicare-demand-split.md).

The identity is tested on live CMS rows saved in ``fixtures/cms_demand_split.json``
(captured 2026-10-05), so a change in what CMS serves shows up here first. No network.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import cms
import demand_split as ds

_FIX = Path(__file__).resolve().parent / "fixtures" / "cms_demand_split.json"
_DATA = json.loads(_FIX.read_text())


def _row(part: str, name: str) -> dict:
    rows = _DATA["part_d" if part == "D" else "part_b"]
    return next(r for r in rows if r["Brnd_Name"] == name)


def _series(part: str, name: str) -> list[dict]:
    """The fixture row as the split reads it, one record per year."""
    return [{"year": r["year"], "spending": r["total_spending"], "claims": r["total_claims"],
             "beneficiaries": r["total_beneficiaries"], "units": r["total_dosage_units"]}
            for r in cms.parse_row(_row(part, name), part)]


def _year(series, year):
    return next(r for r in series if r["year"] == year)


# --- the fixture holds the anchor values -----------------------------------------------
def test_fixture_is_the_live_payload_with_every_column():
    eliquis = _row("D", "Eliquis")
    assert eliquis["Mftr_Name"] == "Overall"
    for col in ("Tot_Spndng_2024", "Tot_Clms_2024", "Tot_Benes_2024", "Tot_Dsg_Unts_2024",
                "Avg_Spnd_Per_Clm_2024", "Outlier_Flag_2024",
                "Chg_Avg_Spnd_Per_Dsg_Unt_23_24", "CAGR_Avg_Spnd_Per_Dsg_Unt_20_24"):
        assert col in eliquis
    prolia = _row("B", "Prolia*")
    assert prolia["HCPCS_Cd"] == "J0897" and "Avg_DY24_ASP_Price" in prolia
    assert _row("B", "Keytruda")["HCPCS_Cd"] == "J9271"
    assert _row("D", "Tremfya*") and _row("D", "Tremfya Pen")


def test_parse_row_gives_the_eliquis_totals():
    s = _series("D", "Eliquis")
    y23, y24 = _year(s, 2023), _year(s, 2024)
    assert y23["spending"] == 18_273_451_967 and y24["spending"] == 20_774_929_225
    assert y23["beneficiaries"] == 3_927_848 and y24["beneficiaries"] == 4_424_796
    assert y23["claims"] == 21_195_452 and y24["claims"] == 24_061_332


# --- the identity --------------------------------------------------------------------
def test_eliquis_2024_splits_into_the_anchor_factors():
    s = _series("D", "Eliquis")
    st = ds.step(_year(s, 2023), _year(s, 2024))
    assert st["from"] == 2023 and st["to"] == 2024
    assert st["spend"] == pytest.approx(0.136894, abs=5e-6)
    assert st["patients"] == pytest.approx(0.126518, abs=5e-6)
    assert st["intensity"] == pytest.approx(0.0077, abs=5e-5)
    assert st["price"] == pytest.approx(0.0015, abs=5e-5)
    assert st["units_per_claim"] == pytest.approx(0.0129, abs=5e-5)
    assert st["price_per_unit"] == pytest.approx(-0.0112, abs=5e-5)
    product = (1 + st["patients"]) * (1 + st["intensity"]) * (1 + st["price"])
    assert product == pytest.approx(1.136891, abs=5e-6)
    assert product == pytest.approx(1 + st["spend"], abs=1e-9)
    pts = ds.points(st)
    assert pts["patients"] * 100 == pytest.approx(12.71, abs=0.005)
    assert pts["intensity"] * 100 == pytest.approx(0.82, abs=0.005)
    assert pts["price"] * 100 == pytest.approx(0.16, abs=0.005)


@pytest.mark.parametrize("part,name", [("D", "Eliquis"), ("D", "Tremfya*"),
                                       ("B", "Keytruda"), ("B", "Prolia*")])
def test_every_step_multiplies_back_and_its_points_add_up(part, name):
    s = _series(part, name)
    for prev, cur in zip(s, s[1:]):
        st = ds.step(prev, cur)
        product = (1 + st["patients"]) * (1 + st["intensity"]) * (1 + st["price"])
        assert product == pytest.approx(1 + st["spend"], abs=1e-9)
        assert sum(ds.points(st).values()) == pytest.approx(st["spend"], abs=1e-9)
        per_unit = (1 + st["units_per_claim"]) * (1 + st["price_per_unit"])
        assert per_unit == pytest.approx(1 + st["price"], abs=1e-9)


def test_the_span_cagrs_multiply_and_hold_the_anchor():
    s = _series("D", "Eliquis")
    sp = ds.span(s, 2020, 2024)
    assert sp["years"] == 4
    assert sp["spend"] == pytest.approx(0.2025, abs=5e-5)
    assert sp["patients"] == pytest.approx(0.1376, abs=5e-5)
    assert sp["intensity"] == pytest.approx(-0.0082, abs=5e-5)
    assert sp["price"] == pytest.approx(0.0658, abs=5e-5)
    product = (1 + sp["patients"]) * (1 + sp["intensity"]) * (1 + sp["price"])
    assert product == pytest.approx(1 + sp["spend"], abs=1e-9)
    assert sum(sp["points"].values()) == pytest.approx(sp["spend"], abs=1e-9)


def test_span_needs_both_end_years():
    s = _series("D", "Tremfya Pen")                    # a 2024 row only
    assert ds.span(s, 2020, 2024) is None
    assert ds.span(_series("D", "Eliquis"), 2024, 2024) is None


# --- the edges -----------------------------------------------------------------------
def _yr(year, s, c, b, u=None):
    return {"year": year, "spending": s, "claims": c, "beneficiaries": b, "units": u}


def test_a_missing_patient_count_splits_into_claims_and_price():
    st = ds.step(_yr(2023, 1000.0, 100, 50), _yr(2024, 1210.0, 110, None))
    assert st["patients"] is None and st["intensity"] is None
    assert st["claims"] == pytest.approx(0.10) and st["price"] == pytest.approx(0.10)
    assert ds.factors_of(st) == ("claims", "price")
    pts = ds.points(st)
    assert set(pts) == {"claims", "price"}
    assert sum(pts.values()) == pytest.approx(st["spend"], abs=1e-12)


def test_a_flat_year_does_not_divide_by_zero():
    st = ds.step(_yr(2023, 1000.0, 100, 50, 300.0), _yr(2024, 1000.0, 110, 55, 330.0))
    assert st["spend"] == 0.0
    pts = ds.points(st)
    assert pts["patients"] == pytest.approx(math.log(1.1))
    assert sum(pts.values()) == pytest.approx(0.0, abs=1e-12)


def test_nothing_missing_reads_as_zero():
    st = ds.step(_yr(2023, None, None, None), _yr(2024, 100.0, 0, 0, 0))
    for key in ("spend", "claims", "patients", "intensity", "price", "units_per_claim",
                "price_per_unit"):
        assert st[key] is None
    assert ds.points(st) is None
    assert ds.factors_of(st) is None
    unit_less = ds.step(_yr(2023, 10.0, 2, 1, None), _yr(2024, 12.0, 2, 1, 0.0))
    assert unit_less["units_per_claim"] is None and unit_less["price_per_unit"] is None


def test_combine_weights_each_part_by_its_prior_spend():
    # Prolia-shaped, $mm: Part D 673.7 to 772, Part B 2190 to 2431.
    d = ds.step(_yr(2023, 673.7, 403.6, 255.6), _yr(2024, 772.0, 450.9, 285.0))
    b = ds.step(_yr(2023, 2190.0, 1311.5, 680.1), _yr(2024, 2431.0, 1339.3, 700.7))
    out = ds.combine([{"part": "D", "prior_spend": 673.7, "step": d},
                      {"part": "B", "prior_spend": 2190.0, "step": b}])
    w_d = 673.7 / (673.7 + 2190.0)
    assert out["weights"]["D"] == pytest.approx(w_d) and w_d == pytest.approx(0.235, abs=5e-4)
    assert out["spend"] == pytest.approx(w_d * d["spend"] + (1 - w_d) * b["spend"])
    assert out["spend"] == pytest.approx((772.0 + 2431.0) / (673.7 + 2190.0) - 1)
    assert d["spend"] == pytest.approx(0.146, abs=5e-4)
    assert b["spend"] == pytest.approx(0.110, abs=5e-4)
    assert sum(out["by_part"].values()) == pytest.approx(out["spend"], abs=1e-12)
    assert sum(out["points"].values()) == pytest.approx(out["spend"], abs=1e-12)
    assert "beneficiaries" not in out and "patients_total" not in out


# --- series, flags and the baseline, on a seeded database ------------------------------
import db  # noqa: E402
import seed  # noqa: E402
from fetchers.demand_cms import DemandCmsFetcher  # noqa: E402


def _asset(conn, ticker, brand, generic=None):
    cid = conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()[0]
    cur = conn.execute("INSERT INTO assets (owner_company_id, brand_name, generic_name,"
                       " is_marketed) VALUES (?, ?, ?, 1)", (cid, brand, generic))
    return cur.lastrowid


def _demand(conn, aid, part, year, spend, claims, benes, name, units=None, source="cms"):
    conn.execute("INSERT INTO drug_demand (asset_id, part, brand_name, year, total_spending,"
                 " total_claims, total_beneficiaries, total_dosage_units, source)"
                 " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (aid, part, name, year, spend, claims, benes, units, source))


def _scalar(conn, aid, key, value=None, text=None, scenario="base"):
    conn.execute("INSERT INTO assumptions (asset_id, key, scenario, value, text_value, source)"
                 " VALUES (?, ?, ?, ?, ?, 'test')", (aid, key, scenario, value, text))


_BASAGLAR_2 = ("cms, summed over the presentations CMS lists separately: Basaglar Kwikpen "
               "U-100, Basaglar Tempo Pen U-100. Beneficiaries are the sum of the distinct "
               "counts, so a patient who changed container during the year is counted twice")


@pytest.fixture
def book(tmp_path):
    """Live CMS rows run through the real fetcher, plus hand rows for the edges."""
    path = tmp_path / "split.db"
    db.init(path)
    seed.load_companies(path)
    conn = db.get_connection(path)
    ids = {
        "eliquis": _asset(conn, "BMY", "Eliquis", "Apixaban"),
        "eliquis_pfe": _asset(conn, "PFE", "Eliquis", "Apixaban"),
        "tremfya": _asset(conn, "JNJ", "Tremfya", "Guselkumab"),
        "keytruda": _asset(conn, "MRK", "Keytruda", "Pembrolizumab"),
        "prolia": _asset(conn, "AMGN", "Prolia", "Denosumab"),
        "basaglar": _asset(conn, "LLY", "Basaglar", "Insulin Glargine"),
        "zepbound": _asset(conn, "LLY", "Zepbound", "Tirzepatide"),
        "newdrug": _asset(conn, "LLY", "Newdrug", "Newmab"),
        "smalldrug": _asset(conn, "LLY", "Smalldrug", "Smallnib"),
        "eurodrug": _asset(conn, "SNY", "Eurodrug", "Euromab"),
        "nothing": _asset(conn, "LLY", "Nothing", "Nonib"),
    }
    conn.commit()
    conn.close()
    fetcher = DemandCmsFetcher(path)
    raw = ([{**r, "_part": "D"} for r in _DATA["part_d"]]
           + [{**r, "_part": "B"} for r in _DATA["part_b"]])
    fetcher.upsert(fetcher.normalise(raw))

    conn = db.get_connection(path)
    # Prolia also fills in Part D (2024 Book: $673.7mm to $772.0mm).
    _demand(conn, ids["prolia"], "D", 2023, 673286886.73, 403592, 255565, "Prolia", 403776.8)
    _demand(conn, ids["prolia"], "D", 2024, 771837558.17, 450858, 284965, "Prolia", 451003.1)
    # Basaglar goes from one container to two in 2023.
    _demand(conn, ids["basaglar"], "D", 2022, 706582383.99, 1701833, 379615,
            "Basaglar Kwikpen U-100", 30961681.4)
    _demand(conn, ids["basaglar"], "D", 2023, 647790847.51, 1538697, 352531,
            "Basaglar (2 presentations)", 27949162.0, _BASAGLAR_2)
    # Zepbound: CMS gives no 2024 patient count.
    _demand(conn, ids["zepbound"], "D", 2023, 80e6, 800, 300, "Zepbound", 3200.0)
    _demand(conn, ids["zepbound"], "D", 2024, 120e6, 1100, None, "Zepbound", 4400.0)
    # A launch in 2022, after the file's first year.
    for year, spend, claims, benes in ((2022, 30e6, 3000, 900), (2023, 120e6, 11000, 3000),
                                       (2024, 200e6, 17000, 4500)):
        _demand(conn, ids["newdrug"], "D", year, spend, claims, benes, "Newdrug", claims * 30.0)
    conn.execute("INSERT INTO approvals (asset_id, region, agency, approval_date)"
                 " VALUES (?, 'US', 'FDA', '2022-03-01')", (ids["newdrug"],))
    # A $40mm brand is too small for the baseline.
    _demand(conn, ids["smalldrug"], "D", 2023, 40e6, 1000, 400, "Smalldrug", 30000.0)
    _demand(conn, ids["smalldrug"], "D", 2024, 80e6, 1500, 600, "Smalldrug", 45000.0)
    # A euro filer with a Medicare series.
    _demand(conn, ids["eurodrug"], "D", 2023, 100e6, 1000, 500, "Eurodrug", 30000.0)
    _demand(conn, ids["eurodrug"], "D", 2024, 110e6, 1050, 520, "Eurodrug", 31500.0)
    for fy, world, us in ((2023, 1000e6, 600e6), (2024, 1100e6, 690e6)):
        conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit)"
                     " VALUES (?, ?, 'FY', ?, 'EUR')", (ids["eurodrug"], fy, world))
        conn.execute("INSERT INTO asset_revenue_regions (asset_id, fiscal_year, member,"
                     " region, value, unit, source) VALUES (?, ?, 'US', 'US', ?, 'EUR',"
                     " 'sec_fsds')", (ids["eurodrug"], fy, us))
    # Eliquis: revenue, a US split, a model and a negotiated price.
    for fy, world in ((2023, 12206e6), (2024, 13333e6), (2025, 14443e6)):
        conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit)"
                     " VALUES (?, ?, 'FY', ?, 'USD')", (ids["eliquis"], fy, world))
    for fy, us in ((2023, 8000e6), (2024, 9000e6)):
        conn.execute("INSERT INTO asset_revenue_regions (asset_id, fiscal_year, member,"
                     " region, value, unit, source) VALUES (?, ?, 'US', 'US', ?, 'USD',"
                     " 'sec_fsds')", (ids["eliquis"], fy, us))
    _scalar(conn, ids["eliquis"], "therapy_mode", text="marketed")
    _scalar(conn, ids["eliquis"], "revenue_growth_pct", 0.189372)
    _scalar(conn, ids["eliquis"], "revenue_growth_pct", -0.05, scenario="bear")
    _scalar(conn, ids["eliquis"], "terminal_growth_pct", 0.0)
    _scalar(conn, ids["eliquis"], "growth_fade_years", 5.0)
    _scalar(conn, ids["eliquis"], "forecast_start_year", 2026.0)
    _scalar(conn, ids["keytruda"], "therapy_mode", text="franchise")
    _scalar(conn, ids["keytruda"], "franchise_growth_pct", 0.037909)
    _scalar(conn, ids["keytruda"], "forecast_start_year", 2026.0)
    _scalar(conn, ids["zepbound"], "therapy_mode", text="marketed")
    # Prolia is shown to BMY as a partner, for the access test.
    _scalar(conn, ids["prolia"], "partner_ticker", text="BMY")
    conn.execute("INSERT INTO negotiated_prices (drug, ipay, ndc9, mfp_30des,"
                 " effective_from, source) VALUES ('ELIQUIS', 2026, '00003-0893', 231.0,"
                 " '2026-01-01', 'test')")
    conn.commit()
    conn.close()
    return path, ids


def _codes(st):
    return {f["code"] for f in st["flags"]}


def _part(out, part):
    return next(p for p in out["parts"] if p["part"] == part)


def _step(part, frm, to):
    return next(s for s in part["steps"] if (s["from"], s["to"]) == (frm, to))


def test_the_series_reads_containers_from_the_fetcher_note(book):
    path, ids = book
    conn = db.get_connection(path)
    try:
        tremfya = ds._series(conn, ids["tremfya"])["D"]
        basaglar = ds._series(conn, ids["basaglar"])["D"]
    finally:
        conn.close()
    assert [r["presentations"] for r in tremfya] == [1, 1, 1, 1, 2]
    assert set(tremfya[-1]["names"]) == {"Tremfya Pen", "Tremfya*"}
    assert tremfya[0]["starred"] and tremfya[-1]["starred"]
    assert basaglar[-1]["names"] == ["Basaglar Kwikpen U-100", "Basaglar Tempo Pen U-100"]


def test_container_changes_flag_the_step_and_hatch_it(book):
    path, ids = book
    tremfya = _part(ds.for_asset(path, "JNJ", ids["tremfya"]), "D")
    last = _step(tremfya, 2023, 2024)
    assert {"containers_changed", "containers_summed", "units_blend"} <= _codes(last)
    assert last["like_for_like"] is False
    assert "containers_changed" not in _codes(_step(tremfya, 2022, 2023))
    basaglar = _part(ds.for_asset(path, "LLY", ids["basaglar"]), "D")
    assert "containers_changed" in _codes(_step(basaglar, 2022, 2023))


def test_a_missing_patient_count_is_flagged_and_split_two_ways(book):
    path, ids = book
    zep = _step(_part(ds.for_asset(path, "LLY", ids["zepbound"]), "D"), 2023, 2024)
    assert "beneficiaries_suppressed" in _codes(zep)
    assert zep["patients"] is None and zep["factors"] == ["claims", "price"]
    assert set(zep["points"]) == {"claims", "price"}


def test_a_starred_part_b_code_is_footnoted(book):
    path, ids = book
    b = _step(_part(ds.for_asset(path, "AMGN", ids["prolia"]), "B"), 2023, 2024)
    flag = next(f for f in b["flags"] if f["code"] == "footnoted_name")
    assert "other brands" in flag["words"]


def test_a_launch_year_is_flagged_only_after_the_files_first_year(book):
    path, ids = book
    new = _part(ds.for_asset(path, "LLY", ids["newdrug"]), "D")
    launch = next(f for f in _step(new, 2022, 2023)["flags"]
                  if f["code"] == "launch_part_year")
    assert "2022-03-01" in launch["words"]
    assert "launch_part_year" not in _codes(_step(new, 2023, 2024))
    eliquis = _part(ds.for_asset(path, "BMY", ids["eliquis"]), "D")
    assert "launch_part_year" not in _codes(_step(eliquis, 2020, 2021))


def test_the_baseline_drops_small_brands_and_changed_containers(book):
    path, _ids = book
    conn = db.get_connection(path)
    try:
        base = ds.baseline(conn)
    finally:
        conn.close()
    pair = base[("D", 2023, 2024)]
    # Eliquis, Newdrug, Prolia's Part D and Eurodrug count. Smalldrug starts at $40mm,
    # Zepbound has no 2024 patient count and Tremfya changed its containers.
    assert pair["n"] == 4
    counted = sorted([4424796 / 3927848 - 1, 4500 / 3000 - 1, 284965 / 255565 - 1,
                      520 / 500 - 1])
    assert pair["patients"] == pytest.approx((counted[1] + counted[2]) / 2)
    assert ("D", 2022, 2023) in base and base[("D", 2022, 2023)]["n"] >= 1
    assert all(k[0] in ("D", "B") for k in base)


def test_the_negotiated_price_flags_the_latest_step(book):
    path, ids = book
    d = _part(ds.for_asset(path, "BMY", ids["eliquis"]), "D")
    flag = next(f for f in d["steps"][-1]["flags"] if f["code"] == "negotiated_price")
    assert "from 2026" in flag["words"]
    assert all("negotiated_price" not in _codes(s) for s in d["steps"][:-1])


def test_a_brand_on_two_records_is_read_from_the_one_that_holds_it(book):
    path, ids = book
    pfe = ds.for_asset(path, "PFE", ids["eliquis_pfe"])
    bmy = ds.for_asset(path, "BMY", ids["eliquis"])
    assert pfe["ok"] and pfe["held_on"] == {"asset_id": ids["eliquis"], "ticker": "BMY"}
    assert pfe["shared_with"] == ["BMY"] and bmy["shared_with"] == ["PFE"]
    assert bmy["held_on"] is None
    assert _part(pfe, "D")["steps"][-1]["spend"] == _part(bmy, "D")["steps"][-1]["spend"]


def test_an_asset_with_no_cms_rows_says_so(book):
    path, ids = book
    out = ds.for_asset(path, "LLY", ids["nothing"])
    assert out["ok"] is False and out["reason"] == "not in the CMS files"
    assert out["parts"] == [] and out["sentence"] is None


# --- comparators -----------------------------------------------------------------------
def test_model_growth_reads_the_base_row_and_its_fade(book):
    path, ids = book
    conn = db.get_connection(path)
    try:
        m = ds.model_growth(conn, ids["eliquis"])
        k = ds.model_growth(conn, ids["keytruda"])
        z = ds.model_growth(conn, ids["zepbound"])
        n = ds.model_growth(conn, ids["nothing"])
    finally:
        conn.close()
    assert m["key"] == "revenue_growth_pct" and m["value"] == pytest.approx(0.189372)
    assert m["fade_to"] == 0.0 and m["fade_years"] == 5.0 and m["from_fy"] == 2025
    assert k["key"] == "franchise_growth_pct" and k["value"] == pytest.approx(0.037909)
    assert k["from_fy"] == 2025                         # forecast start less one
    assert z is None and n is None                      # no growth row, no number


def test_reported_growth_pairs_cms_2024_with_fy2024_only(book):
    path, ids = book
    d = _part(ds.for_asset(path, "BMY", ids["eliquis"]), "D")
    s24 = _step(d, 2023, 2024)
    assert s24["global_growth"] == pytest.approx(13333 / 12206 - 1)
    assert s24["us_growth"] == pytest.approx(9000 / 8000 - 1)
    assert s24["gap_pts"] == pytest.approx(s24["us_growth"] - s24["spend"])
    s23 = _step(d, 2022, 2023)
    assert s23["global_growth"] is None and s23["us_growth"] is None
    assert s23["gap_pts"] is None


def test_a_euro_filer_carries_its_currency_and_no_gap(book):
    path, ids = book
    s = _part(ds.for_asset(path, "SNY", ids["eurodrug"]), "D")["steps"][-1]
    assert s["us_growth"] == pytest.approx(0.15)
    assert s["us_note"] == "in EUR, so it carries the dollar's move"
    assert s["global_note"] == "in EUR, so it carries the dollar's move"
    assert s["gap_pts"] is None


def test_direction_disagrees_beyond_the_deadband_only():
    assert ds.direction_disagrees(0.18, {"patients": -0.03}) is True
    assert ds.direction_disagrees(0.18, {"patients": 0.12}) is False
    assert ds.direction_disagrees(0.18, {"patients": -0.005}) is False
    assert ds.direction_disagrees(-0.004, {"patients": 0.05}) is False
    assert ds.direction_disagrees(0.18, {"patients": None, "claims": -0.05}) is True
    assert ds.direction_disagrees(None, {"patients": -0.05}) is None


# --- the readers -----------------------------------------------------------------------
def test_for_asset_carries_the_label_sentence_and_parts(book):
    path, ids = book
    out = ds.for_asset(path, "BMY", ids["eliquis"])
    assert out["ok"] and out["latest_year"] == 2024 and out["lag_years"] == 1
    assert out["label"].startswith("Medicare only.")
    assert "CMS calendar 2024, 1 year behind the FY2025 filing" in out["label"]
    assert out["sentence"].startswith("Medicare patients on Eliquis rose 12.7% in 2024")
    assert "The model grows it 18.9% a year from FY2025." in out["sentence"]
    d = _part(out, "D")
    assert d["factor_labels"]["intensity"] == "Fills per patient"
    assert d["span"]["from"] == 2020 and d["span"]["to"] == 2024
    assert out["beside"]["direction_disagrees"] is False


def test_a_two_part_brand_is_split_per_part_and_totalled_in_points(book):
    path, ids = book
    out = ds.for_asset(path, "AMGN", ids["prolia"])
    assert [p["part"] for p in out["parts"]] == ["B", "D"]
    assert all(p["material"] for p in out["parts"])
    assert _part(out, "B")["factor_labels"]["intensity"] == "Claims per patient"
    total = out["brand_total"][-1]
    assert (total["from"], total["to"]) == (2023, 2024)
    assert sum(total["points"].values()) == pytest.approx(total["spend"], abs=1e-12)
    assert total["spend"] == pytest.approx(
        (2430935308 + 771837558.17) / (2190209346 + 673286886.73) - 1)


def test_a_minor_part_is_reported_not_split(book):
    path, ids = book
    conn = db.get_connection(path)
    _demand(conn, ids["keytruda"], "D", 2023, 116820430.15, 9668, 1523, "Keytruda")
    _demand(conn, ids["keytruda"], "D", 2024, 140055039.83, 11882, 1906, "Keytruda")
    conn.commit()
    conn.close()
    out = ds.for_asset(path, "MRK", ids["keytruda"])
    minor = _part(out, "D")
    assert minor["material"] is False and minor["spend_share"] < ds.MATERIAL_PART_SHARE
    assert set(minor["steps"][-1]) >= {"from", "to", "spend"}
    assert "patients" not in minor["steps"][-1] and minor["span"] is None
    assert out["brand_total"] == []


def test_access_follows_the_forecast_owner_or_partner(book):
    path, ids = book
    assert ds.for_asset(path, "PFE", ids["keytruda"]) is None
    assert ds.for_asset(path, "BMY", ids["prolia"])["ok"]     # partner_ticker BMY
    assert ds.for_asset(path, "ZZZZ", ids["eliquis"]) is None


def test_company_split_rows_are_sorted_by_spend_with_the_median(book):
    path, ids = book
    out = ds.company_split(path, "LLY")
    brands = [r["brand"] for r in out["brands"]]
    assert brands[0] == "Basaglar" and "Nothing" not in brands
    spends = [r["spending"] for r in out["brands"]]
    assert spends == sorted(spends, reverse=True)
    assert out["baseline"]["D"]["n"] == 4 and out["baseline"]["D"]["to"] == 2024
    bmy = ds.company_split(path, "BMY")
    assert {(r["brand"], r["part"]) for r in bmy["brands"]} >= {("Eliquis", "D"),
                                                                ("Prolia", "B")}
    pfe = ds.company_split(path, "PFE")
    assert pfe["brands"][0]["held_on"]["ticker"] == "BMY"
    assert ds.company_split(path, "ZZZZ") is None
