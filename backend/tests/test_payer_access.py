"""The payer access reader (backend/payer_access.py) on real rows.

``fixtures/payer_access/book_rows.json`` is the payer tables of a copy of the book after
build 5's four fetchers ran on 2026-10-05, cut to nine assets: Eliquis on both its owners
(BMS 198, Pfizer 812), Keytruda (a Part B drug with a Part D sliver), Verzenio (a reused
product code), Shingrix (a vaccine), Comirnaty and Prevnar 20 (Part B only), Eliquis
Sprinkle (looked up, no RxNorm code) and one of Lilly's pipeline rows. Loaded into a
temporary database; nothing reads the book.

Then the route, the profile key, and the static guard that keeps every payer table out
of the valuation path.
"""

from __future__ import annotations

import ast
import copy
import json
import pathlib
import re

import pytest

import db
import payer_access as pa
import product_profile

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ROWS = json.loads((BACKEND / "tests" / "fixtures" / "payer_access" / "book_rows.json")
                  .read_text())
BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")
EM_DASH = "—"
ELIQUIS_BMY, ELIQUIS_PFE, KEYTRUDA, VERZENIO, SHINGRIX = 198, 812, 412, 12, 1453
COMIRNATY, PREVNAR, SPRINKLE, PIPELINE = 822, 365, 92, 1491

TABLES = ("companies", "assets", "drug_codes", "drug_code_lookups", "partd_prescribing",
          "partd_prescriber_specialties", "partd_prescriber_releases",
          "partd_formulary_releases", "partd_formulary_access", "medicaid_sdud_releases",
          "medicaid_utilization", "drug_demand", "asset_themes")


def _load(path, rows=ROWS, skip=()):
    db.init(path)
    conn = db.get_connection(path)
    for table in TABLES:
        if table in skip:
            continue
        for row in rows[table]:
            cols = ",".join(row)
            conn.execute(f"INSERT INTO {table} ({cols}) VALUES"
                         f" ({','.join('?' * len(row))})", tuple(row.values()))
    conn.commit()
    return conn


@pytest.fixture
def conn(tmp_path):
    c = _load(str(tmp_path / "payer.db"))
    yield c
    c.close()


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


# --- prescribing ----------------------------------------------------------------------
def test_eliquis_reads_the_same_on_both_owners_with_the_label(conn):
    bmy, pfe = pa.for_asset(conn, ELIQUIS_BMY), pa.for_asset(conn, ELIQUIS_PFE)
    p = bmy["prescribing"]
    assert p["scope_label"] == "Medicare Part D only, 2024"
    assert p["national"]["prescribers"] == 556431
    assert p["national"]["beneficiaries"] == 4423497      # the Prescribers file's count
    assert [s["year"] for s in p["series"]] == [2020, 2021, 2022, 2023, 2024]
    assert pfe["prescribing"]["national"] == p["national"]
    assert bmy["co_marketed"] == {"owners": ["PFE"],
                                  "label": "Brand totals, not this company's share"}
    assert pfe["co_marketed"]["owners"] == ["BMY"]


def test_file_figures_name_their_population_and_volume_deciles_stay_null(conn):
    p = pa.for_asset(conn, ELIQUIS_BMY)["prescribing"]
    assert p["file"]["population"].startswith("prescribers with 11 or more claims")
    assert p["file"]["deciles"][0] == pytest.approx(0.490333)
    assert len(p["file"]["deciles"]) == 10
    assert p["volume_deciles"]["value"] is None
    assert "fewer than 11 claims" in p["volume_deciles"]["note"]
    assert any("leaves out any prescriber with fewer than 11" in c for c in p["caveats"])


def test_the_days_covered_proxy_is_labelled_and_never_capped(conn):
    dc = pa.for_asset(conn, ELIQUIS_BMY)["prescribing"]["days_covered"]
    assert dc["value"] == pytest.approx(0.7202) and dc["label"] == "a proxy, not a PDC"
    assert dc["applies"] and not dc["above_one"]
    conn.execute("UPDATE partd_prescribing SET days_covered_share = 1.53"
                 " WHERE asset_id = ? AND data_year = 2024", (ELIQUIS_BMY,))
    dc = pa.for_asset(conn, ELIQUIS_BMY)["prescribing"]["days_covered"]
    assert dc["value"] == 1.53 and dc["above_one"]
    assert "pass 1 for a drug given more often than monthly" in pa.PROXY_CAVEAT


def test_a_vaccine_holds_the_proxy_but_says_it_does_not_apply(conn):
    dc = pa.for_asset(conn, SHINGRIX)["prescribing"]["days_covered"]
    assert dc["value"] == pytest.approx(0.1115)
    assert dc["applies"] is False and "vaccine" in dc["note"]


def test_a_part_b_drug_says_so_rather_than_no_free_data(conn):
    key = pa.for_asset(conn, KEYTRUDA)
    assert "CMS Spending by Drug, 2024: Part B is 98%" in key["prescribing"]["part_b_note"]
    f = key["formulary"]
    assert f["formularies_listing"] == 0 and f["formularies_total"] == 328
    assert f["zero_reason"] == pa.PART_B_FORMULARY
    only = pa.for_asset(conn, COMIRNATY)
    assert only["why_empty"]["prescribing"] == pa.PART_B_ONLY
    assert only["why_empty"]["formulary"] == pa.PART_B_ONLY
    assert pa.for_asset(conn, PREVNAR)["formulary"]["zero_reason"] == pa.PART_B_FORMULARY
    for view in (key, only):
        assert not [s for s in _strings(view) if "no free data" in s]


def test_a_listed_nowhere_brand_counts_its_codes_in_words(conn):
    conn.execute("DELETE FROM drug_demand WHERE asset_id = ?", (KEYTRUDA,))
    f = pa.for_asset(conn, KEYTRUDA)["formulary"]
    assert f["zero_reason"] == ("Its one brand RxNorm code is on no Part D formulary in "
                                "this release")
    conn.execute("UPDATE partd_formulary_access SET rxcuis_known = 3 WHERE asset_id = ?",
                 (KEYTRUDA,))
    assert pa.for_asset(conn, KEYTRUDA)["formulary"]["zero_reason"] == (
        "None of its 3 brand RxNorm codes is on a Part D formulary in this release")


# --- formulary ------------------------------------------------------------------------
def test_formulary_scope_counts_and_tiers_for_eliquis(conn):
    f = pa.for_asset(conn, ELIQUIS_BMY)["formulary"]
    assert f["scope_label"] == ("Medicare Part D plans only, Sep 2026 release, contract "
                                "year 2026")
    assert (f["formularies_listing"], f["formularies_total"]) == (328, 328)
    assert (f["pa_formularies"], f["st_formularies"]) == (0, 0)
    assert f["tiers"] == [{"tier": 1, "formularies": 61}, {"tier": 2, "formularies": 10},
                          {"tier": 3, "formularies": 257}]
    assert f["listed_share"] == 1.0 and f["selected_drug"]
    assert "employer, PACE and demonstration plans" in f["caveats"][0]
    assert "not people" in f["caveats"][0]
    assert f["by_plan_type"] is None            # the entries were not carried here


def test_the_plan_split_reads_the_newest_release_entries(conn):
    conn.executemany(
        "INSERT INTO partd_plans (contract_id, plan_id, segment_id, formulary_id,"
        " plan_type, suppressed, release_date) VALUES (?, ?, '0', ?, ?, ?, '2026-09-16')",
        [("H0001", "001", "F1", "MA-PD", 0), ("H0001", "002", "F2", "MA-PD", 0),
         ("S0001", "001", "F1", "PDP", 0), ("S0001", "002", "F3", "PDP", 1)])
    conn.executemany(
        "INSERT INTO partd_formulary_entries (formulary_id, rxcui, tier, quantity_limit,"
        " prior_auth, step_therapy, release_date) VALUES (?, ?, 3, ?, ?, 0, '2026-09-16')",
        [("F1", "1364441", 1, 0), ("F1", "1364447", 0, 1), ("F2", "1364441", 0, 0),
         ("F3", "1364441", 1, 1), ("F2", "9999999", 1, 1)])
    split = pa.for_asset(conn, ELIQUIS_BMY)["formulary"]["by_plan_type"]
    assert split["MA-PD"] == {"plans": 2, "listing": 2, "pa": 1, "st": 0, "ql": 1}
    # The suppressed PDP plan is in no count; another drug's RxCUI flags nothing.
    assert split["PDP"] == {"plans": 1, "listing": 1, "pa": 1, "st": 0, "ql": 1}


def test_a_brand_with_no_rxnorm_code_says_why(conn):
    why = pa.for_asset(conn, SPRINKLE)["why_empty"]
    assert why["formulary"] == "No RxNorm code yet, so plan coverage cannot be read"
    assert why["medicaid"] == "No product codes yet, so Medicaid claims cannot be matched"
    assert why["prescribing"].startswith("CMS lists no national Part D Prescribers row")


# --- medicaid -------------------------------------------------------------------------
def test_eliquis_medicaid_years_match_the_national_rows(conn):
    m = pa.for_asset(conn, ELIQUIS_BMY)["medicaid"]
    assert m["scope_label"] == "Medicaid only, before rebates"
    years = {y["year"]: y for y in m["years"]}
    assert years[2024]["prescriptions"] == 2048557
    assert years[2025]["prescriptions"] == 2188265
    assert years[2025]["growth"] == pytest.approx(2188265 / 2048557 - 1)
    # The paediatric pack's suppressed rows make 2025 Q4 a lower bound, not a zero.
    assert m["latest"]["year"] == 2025 and m["latest"]["quarter"] == 4
    assert m["latest"]["lower_bound"] and m["latest"]["prescriptions"] == 556404
    assert len(m["quarters"]) == 8 and m["reused_codes"] is None
    assert pa.for_asset(conn, ELIQUIS_PFE)["medicaid"]["years"] == m["years"]
    assert "before Medicaid rebates" in m["caveats"][0]


def test_a_reused_product_code_is_left_out_by_name_and_month(conn):
    m = pa.for_asset(conn, VERZENIO)["medicaid"]
    assert m["reused_codes"]["codes"] == ["00002-4415"]       # ZYPREXA in CMS's listing
    assert m["reused_codes"]["prescriptions"] == 665
    kept = sum(y["prescriptions"] for y in m["years"])
    assert kept == 27676 + 28782


def test_a_row_outside_the_months_that_names_the_brand_is_kept():
    names = pa._words("Eliquis", "Apixaban")
    assert pa._outside_rxnorm_months(2025, 4, "202609", "202610")
    assert pa._shares_a_word("Eliquis", names)
    assert pa._shares_a_word("ABEMACICLI", pa._words("Verzenio", "Abemaciclib"))
    assert not pa._shares_a_word("ZYPREXA", pa._words("Verzenio", "Abemaciclib"))
    assert not pa._outside_rxnorm_months(2025, 3, "202509", "202610")


def test_a_vaccine_with_no_medicaid_rows_names_the_codes(conn):
    assert (pa.for_asset(conn, SHINGRIX)["why_empty"]["medicaid"]
            == "No Medicaid claims on file for this brand's NDCs")


# --- empty and unread -----------------------------------------------------------------
def test_a_pipeline_row_is_not_marketed_in_every_block(conn):
    view = pa.for_asset(conn, PIPELINE)
    assert set(view["why_empty"].values()) == {pa.NOT_MARKETED}
    assert pa.for_asset(conn, 999999) is None


def test_a_book_the_fetchers_have_not_reached_says_so(tmp_path):
    c = _load(str(tmp_path / "unread.db"),
              skip=("partd_prescribing", "partd_prescriber_releases",
                    "partd_formulary_access", "partd_formulary_releases",
                    "medicaid_utilization", "medicaid_sdud_releases"))
    try:
        why = pa.for_asset(c, ELIQUIS_BMY)["why_empty"]
    finally:
        c.close()
    assert why == {
        "prescribing": "The Part D Prescribers files have not been read into this book yet",
        "formulary": "The Part D formulary file has not been read into this book yet",
        "medicaid": "The Medicaid State Drug Utilization Data has not been read into this "
                    "book yet"}


def test_codes_carry_the_nlm_attribution(conn):
    view = pa.for_asset(conn, ELIQUIS_BMY)
    assert view["codes"]["brand_rxcuis"] == 8
    assert view["attribution"].startswith("This product uses publicly available data from "
                                          "the U.S. National Library of Medicine")


# --- the company list -----------------------------------------------------------------
def test_the_company_list_names_brands_and_never_totals_them(conn):
    out = pa.for_company(conn, "BMY")
    brands = [b["brand"] for b in out["brands"]]
    assert brands == ["Eliquis"]                 # the Sprinkle has nothing to show yet
    row = out["brands"][0]
    assert row["prescribers"] == 556431 and row["formularies_listing"] == 328
    assert row["co_marketed"]["owners"] == ["PFE"]
    assert not [k for k in out if "total" in k]
    assert pa.for_company(conn, "ZZZZ") is None


def test_house_style_in_every_string(conn):
    for asset_id in (ELIQUIS_BMY, KEYTRUDA, VERZENIO, SHINGRIX, COMIRNATY, SPRINKLE,
                     PIPELINE):
        for s in _strings(pa.for_asset(conn, asset_id)):
            assert EM_DASH not in s, s
            assert not [w for w in BANNED if re.search(rf"\b{w}\b", s.lower())], s


# --- the route and the profile --------------------------------------------------------
def test_the_route_and_the_profile_key(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import main

    path = str(tmp_path / "payer.db")
    _load(path).close()
    monkeypatch.setattr(db, "DB_PATH", path)
    client = TestClient(main.app)
    body = client.get("/companies/bmy/payer-access")
    assert body.status_code == 200 and body.json()["brands"][0]["brand"] == "Eliquis"
    assert client.get("/companies/ZZZZ/payer-access").status_code == 404
    profile = product_profile.product_profile(path, "BMY", ELIQUIS_BMY)
    assert profile["access"]["formulary"]["formularies_listing"] == 328
    assert profile["access"]["co_marketed"]["owners"] == ["PFE"]


# --- the static guard -----------------------------------------------------------------
GUARDED = ("forecast.py", "forecast_view.py", "valuation.py", "fair_value.py",
           "pos_granular.py", "company_score.py")
PAYER_MODULES = {"payer_access", "fetchers.codes_rxnav", "fetchers.prescribers_cms",
                 "fetchers.utilization_medicaid", "fetchers.formulary_cms"}
PAYER_TABLES = ("drug_codes", "drug_code_lookups", "partd_prescribing",
                "partd_prescriber_specialties", "partd_prescriber_releases",
                "medicaid_utilization", "medicaid_sdud_releases",
                "partd_formulary_releases", "partd_plans", "partd_formulary_entries",
                "partd_formulary_access")


def _imports(path: pathlib.Path) -> set:
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def _module_file(name: str):
    path = BACKEND.joinpath(*name.split(".")).with_suffix(".py")
    return path if path.exists() else None


def test_no_valuation_module_reaches_the_payer_data():
    """Not by name and not through anything it imports: every figure here is gross of
    rebates or a count of plans, and neither is revenue."""
    for start in GUARDED:
        seen, todo = set(), [start[:-3]]
        while todo:
            name = todo.pop()
            if name in seen:
                continue
            seen.add(name)
            path = _module_file(name)
            if path is None:
                continue
            assert name not in PAYER_MODULES, f"{start} reaches {name}"
            text = path.read_text()
            named = [t for t in PAYER_TABLES if re.search(rf"\b{t}\b", text)]
            assert not named, f"{start} reaches {name}, which names {named}"
            todo.extend(m for m in _imports(path) if _module_file(m))
