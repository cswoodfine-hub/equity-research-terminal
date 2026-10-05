"""The brand-to-code map from RxNav: identifier lookups, NDC history, labelers, conflicts,
overrides and the per-asset guard. Fixtures are live RxNav payloads for Eliquis
(2026-10-05); no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import db
from fetchers.codes_rxnav import DrugCodesRxNavFetcher, find_conflicts, parse_history

_FIX = Path(__file__).resolve().parent / "fixtures"


def _load(name):
    return json.loads((_FIX / name).read_text())


def _routes():
    props = _load("rxnav_properties_eliquis.json")
    bn = _load("rxnav_bn_eliquis.json")
    routes = {
        "/REST/version.json": {"version": "05-Oct-2026", "apiVersion": "3.1.355"},
        "/REST/rxcui.json?idtype=NDA&id=NDA202155": _load("rxnav_nda202155.json"),
        "/REST/rxcui/1364441/allhistoricalndcs.json":
            _load("rxnav_allhistoricalndcs_1364441.json"),
        "/REST/ndcproperties.json?id=1364441": _load("rxnav_ndcproperties_1364441.json"),
        "/REST/rxcui.json?name=Eliquis&search=2": bn["rxcui.json?name=Eliquis&search=2"],
        "/REST/rxcui/1364436/properties.json": bn["rxcui/1364436/properties.json"],
        "/REST/rxcui/1364436/related.json?tty=SBD+BPCK":
            _load("rxnav_bn_related_eliquis.json"),
    }
    for rxcui, payload in props.items():
        routes[f"/REST/rxcui/{rxcui}/properties.json"] = payload
    return routes


class _Fake:
    """RxNav as the fixtures saw it. Anything not saved answers empty, as RxNav does for
    an id it does not know."""

    def __init__(self):
        self.routes = _routes()
        self.paths = []

    def __call__(self, path):
        self.paths.append(path)
        return self.routes.get(path, {})


def _db(tmp_path, assets):
    """assets: [(id, company_id, brand, generic, [application numbers])]."""
    path = str(tmp_path / "codes.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name, openfda_manufacturer,"
                 " orange_book_applicant) VALUES"
                 " (1, 'BMY', 'Bristol-Myers Squibb Co', 'Bristol-Myers Squibb',"
                 "  'BRISTOL|CELGENE'),"
                 " (2, 'PFE', 'Pfizer Inc', 'Pfizer', 'PFIZER|WYETH'),"
                 " (3, 'XYZ', 'Other Co', NULL, NULL)")
    for asset_id, company, brand, generic, apps in assets:
        conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name,"
                     " is_marketed) VALUES (?, ?, ?, ?, 1)",
                     (asset_id, company, brand, generic))
        for app in apps:
            conn.execute("INSERT INTO approvals (asset_id, application_number)"
                         " VALUES (?, ?)", (asset_id, app))
    conn.commit()
    conn.close()
    return path


def _run(path, fake, overrides=None, tmp_path=None):
    if overrides is None:
        overrides = (tmp_path or Path(path).parent) / "none.csv"
    fetcher = DrugCodesRxNavFetcher(path, get=fake, overrides_path=overrides)
    fetcher.force = True
    return fetcher.run()


def _codes(path, asset_id, code_type):
    conn = db.get_connection(path)
    try:
        return {r["code"]: dict(r) for r in conn.execute(
            "SELECT * FROM drug_codes WHERE asset_id = ? AND code_type = ?",
            (asset_id, code_type))}
    finally:
        conn.close()


def test_nda202155_gives_eliquis_two_tablets_and_its_starter_pack(tmp_path):
    path = _db(tmp_path, [(198, 1, "Eliquis", "Apixaban", ["NDA202155"])])
    result = _run(path, _Fake())
    assert not result.errors
    rxcuis = _codes(path, 198, "rxcui")
    assert {c: r["tty"] for c, r in rxcuis.items()} == {
        "1364441": "SBD", "1364447": "SBD", "1992428": "BPCK"}
    assert all(r["brand_specific"] == 1 for r in rxcuis.values())
    assert {r["basis"] for r in rxcuis.values()} == {"rxnav_application"}
    assert {r["application_number"] for r in rxcuis.values()} == {"NDA202155"}


def test_historical_ndcs_become_product_codes_and_repackagers_are_not_the_owner(tmp_path):
    path = _db(tmp_path, [(198, 1, "Eliquis", "Apixaban", ["NDA202155"])])
    _run(path, _Fake())
    ndc9s = _codes(path, 198, "ndc9")
    own = ndc9s["00003-0893"]
    assert (own["first_ym"], own["last_ym"]) == ("201302", "202610")
    assert own["labeler_code"] == "00003" and own["rxcui"] == "1364441"
    assert own["is_owner_labeler"] == 1            # E.R. Squibb & Sons is BMS
    assert own["labeler_name"] == "E.R. Squibb & Sons, L.L.C."
    assert ndc9s["50090-1436"]["is_owner_labeler"] == 0     # A-S Medication Solutions
    assert ndc9s["55154-0612"]["is_owner_labeler"] == 0     # Cardinal Health
    assert ndc9s["71610-0811"]["is_owner_labeler"] == 0     # Aphena Pharma Solutions
    # 54569 (A-S Medication's older code) and 63629 have no active NDC under Eliquis, so
    # RxNav names neither, and neither is called someone's on a guess.
    assert ndc9s["54569-6513"]["is_owner_labeler"] is None
    assert ndc9s["63629-8432"]["is_owner_labeler"] is None
    # Two package codes of one product are one product code, spanning both.
    assert ndc9s["55154-0612"]["first_ym"] == "201505"


def test_an_unprefixed_number_is_never_sent_and_the_brand_route_is_labelled(tmp_path):
    path = _db(tmp_path, [(198, 1, "Eliquis", "Apixaban", ["202155"])])
    fake = _Fake()
    result = _run(path, fake)
    assert not any("idtype" in p for p in fake.paths)
    rxcuis = _codes(path, 198, "rxcui")
    assert {r["basis"] for r in rxcuis.values()} == {"rxnav_brand_name"}
    assert {"1364441", "1364447", "1992428"} <= set(rxcuis)
    assert all(r["tty"] in ("SBD", "BPCK") for r in rxcuis.values())
    conn = db.get_connection(path)
    note = conn.execute("SELECT note FROM drug_code_lookups WHERE asset_id = 198"
                        ).fetchone()["note"]
    conn.close()
    assert "202155 is not an NDA, BLA or ANDA number" in note
    assert not result.errors


def test_a_generic_named_product_never_takes_the_brand_route(tmp_path):
    path = _db(tmp_path, [(5, 2, "Latanoprost", "Latanoprost", [])])
    fake = _Fake()
    _run(path, fake)
    assert not any("name=" in p for p in fake.paths)
    assert _codes(path, 5, "rxcui") == {}


def test_co_marketed_assets_keep_a_code_and_different_molecules_lose_it(tmp_path):
    path = _db(tmp_path, [(198, 1, "Eliquis", "Apixaban", ["NDA202155"]),
                          (812, 2, "Eliquis", "Apixaban", ["NDA202155"]),
                          (900, 3, "Wrongly Filed", "Rivaroxaban", ["NDA202155"])])
    result = _run(path, _Fake())
    # All three claim the codes, and one is a different molecule: nobody keeps them.
    assert _codes(path, 198, "rxcui") == {} and _codes(path, 900, "rxcui") == {}
    assert any("different molecules" in n and "1364447" in n for n in result.notes)

    (tmp_path / "b").mkdir()
    path2 = _db(tmp_path / "b", [(198, 1, "Eliquis", "Apixaban", ["NDA202155"]),
                                 (812, 2, "Eliquis", "Apixaban", ["NDA202155"])])
    _run(path2, _Fake())
    assert set(_codes(path2, 198, "rxcui")) == set(_codes(path2, 812, "rxcui")) == {
        "1364441", "1364447", "1992428"}


def test_find_conflicts_reads_salts_as_one_molecule():
    assets = {1: {"generic_name": "Ozanimod Hydrochloride"}, 2: {"generic_name": "Ozanimod"},
              3: {"generic_name": "Insulin Lispro"}, 4: {"generic_name": "Insulin Glargine"}}
    claims = {("rxcui", "a"): {1, 2}, ("rxcui", "b"): {3, 4}}
    assert find_conflicts(claims, assets) == [("rxcui", "b", [3, 4])]


def test_overrides_add_and_remove_and_survive_the_next_fetch(tmp_path):
    path = _db(tmp_path, [(198, 1, "Eliquis", "Apixaban", ["NDA202155"])])
    overrides = tmp_path / "overrides.csv"
    overrides.write_text(
        "# test\n"
        "asset_brand,ticker,code_type,code,tty,action,source\n"
        "Eliquis,BMY,rxcui,2749583,SBD,add,RxNav related.json for BN 1364436\n"
        "Eliquis,BMY,ndc9,50090-1436,,remove,repackager kept out for the test\n"
        "Eliquis,BMY,rxcui,999,,add,\n")
    result = _run(path, _Fake(), overrides=overrides)
    rxcuis = _codes(path, 198, "rxcui")
    assert rxcuis["2749583"]["basis"] == "curated"
    assert rxcuis["2749583"]["brand_specific"] == 1
    assert "50090-1436" not in _codes(path, 198, "ndc9")
    assert "999" not in rxcuis                               # no source, not applied
    assert any("incomplete" in n for n in result.notes)


def test_a_looked_up_asset_is_not_fetched_again_inside_30_days_even_forced(tmp_path):
    path = _db(tmp_path, [(198, 1, "Eliquis", "Apixaban", ["NDA202155"])])
    _run(path, _Fake())

    def refuse(_path):
        raise AssertionError("no request should be made")

    result = _run(path, refuse)
    assert not result.errors
    assert any("nothing was fetched" in n for n in result.notes)
    conn = db.get_connection(path)
    payload = json.loads(conn.execute(
        "SELECT payload FROM snapshots WHERE source = 'rxnav_codes'"
        " ORDER BY id DESC LIMIT 1").fetchone()[0])
    conn.close()
    assert payload["fetch_kind"] == "cache" and payload["rxcuis"] == 3

    # A changed application number makes the asset due again.
    conn = db.get_connection(path)
    conn.execute("INSERT INTO approvals (asset_id, application_number)"
                 " VALUES (198, 'NDA999999')")
    conn.commit()
    conn.close()
    fake = _Fake()
    _run(path, fake)
    assert "/REST/rxcui.json?idtype=NDA&id=NDA999999" in fake.paths


def test_history_parser_reads_every_package_once():
    rows = parse_history(_load("rxnav_allhistoricalndcs_1364441.json"))
    assert len(rows) == 14
    assert {"ndc11": "00003089341", "start": "201302", "end": "201712"} in rows


# --- book guard -------------------------------------------------------------------------
def test_every_negotiated_ndc9_of_a_book_brand_is_in_its_codes(book):
    """CMS names the product codes of each drug it negotiated. Where the drug is a brand
    the book carries and the asset has codes at all, every one of them should be among
    them, since both come from the same labels."""
    import cms
    if not book.execute("SELECT name FROM sqlite_master WHERE name = 'drug_codes'"
                        ).fetchone():
        pytest.skip("migration 080 has not been applied to this book")
    if not book.execute("SELECT COUNT(*) FROM drug_codes").fetchone()[0]:
        pytest.skip("the codes fetcher has not run on this book")
    brands = {}
    for row in book.execute("SELECT id, brand_name FROM assets WHERE is_marketed = 1"
                            " AND brand_name IS NOT NULL"):
        brands.setdefault(cms.norm(row["brand_name"]), []).append(row["id"])
    coded = {r[0] for r in book.execute("SELECT DISTINCT asset_id FROM drug_codes")}
    missing = []
    for row in book.execute("SELECT DISTINCT drug, ndc9 FROM negotiated_prices"
                            " WHERE ndc9 IS NOT NULL"):
        for name in row["drug"].split(";"):
            for asset_id in brands.get(cms.norm(name), []):
                if asset_id not in coded:
                    continue
                hit = book.execute("SELECT 1 FROM drug_codes WHERE asset_id = ?"
                                   " AND code_type = 'ndc9' AND code = ?",
                                   (asset_id, row["ndc9"])).fetchone()
                if hit is None:
                    missing.append((name.strip(), row["ndc9"], asset_id))
    assert not missing, missing[:20]


def test_labelers_already_named_are_not_asked_about_again(tmp_path):
    """Repackagers recur across hundreds of drugs. Once an active NDC's labeler is named,
    another RxCUI listing only named labelers makes no ndcproperties call."""
    path = _db(tmp_path, [(198, 1, "Eliquis", "Apixaban", ["NDA202155"])])
    fake = _Fake()
    fake.routes["/REST/rxcui/1364447/allhistoricalndcs.json"] = _load(
        "rxnav_allhistoricalndcs_1364441.json")
    _run(path, fake)
    assert "/REST/ndcproperties.json?id=1364441" in fake.paths
    assert "/REST/ndcproperties.json?id=1364447" not in fake.paths
    # The names still reach the second RxCUI's codes.
    assert _codes(path, 198, "ndc9")["00003-0893"]["is_owner_labeler"] == 1


def test_rxnav_version_reads_as_the_month_its_history_ends_on():
    from fetchers.codes_rxnav import _version_month
    assert _version_month("05-Oct-2026") == "202610"
    assert _version_month(None) is None
    assert _version_month("2026-10-05") is None
