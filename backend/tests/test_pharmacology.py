"""What a drug is, from ChEMBL and the openFDA label: mechanism, target, class, warning."""

import json
from pathlib import Path

import db
from fetchers import pharmacology as P

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text())


def test_the_parsers_read_the_live_payloads():
    mol = P.parse_molecules(_load("chembl_molecule_tirzepatide.json"))
    assert mol == [{"chembl_id": "CHEMBL4297839", "name": "TIRZEPATIDE",
                    "molecule_type": "Protein"}]
    mechs = P.parse_mechanisms(_load("chembl_mechanism_tirzepatide.json"))
    assert {m["mechanism"] for m in mechs} == {
        "Glucagon-like peptide 1 receptor agonist",
        "Gastric inhibitory polypeptide receptor agonist"}
    assert all(m["action_type"] == "AGONIST" for m in mechs)
    target = P.parse_target(_load("chembl_target_glp1r.json"))
    assert target["name"] == "Glucagon-like peptide 1 receptor"
    assert target["organism"] == "Homo sapiens"
    label = P.parse_label(_load("openfda_label_tirzepatide.json"))
    assert "GLP-1 Receptor Agonist [EPC]" in label["epc"]
    assert label["route"] == ["SUBCUTANEOUS"]
    assert label["boxed"].startswith("WARNING: RISK OF THYROID C-CELL TUMORS")


def test_no_label_and_no_molecule_are_empty_not_errors():
    assert P.parse_label({}) is None
    assert P.parse_molecules({}) == []
    assert P.parse_target({}) is None


def test_names_try_the_ingredient_then_without_its_salt_and_skip_application_numbers():
    names = P.names_for({"generic_name": "Raloxifene Hydrochloride", "brand_name": "Evista",
                         "internal_code": "NDA20815",
                         "active_ingredients": '["Raloxifene Hydrochloride"]'})
    assert names == ["Raloxifene Hydrochloride", "Raloxifene", "Evista"]


def test_a_combination_resolves_each_ingredient():
    assert P.ingredient_names({"active_ingredients": '["A", "B"]'}) == ["A", "B"]
    assert P.ingredient_names({"active_ingredients": '["A"]'}) == []


def _book(tmp_path):
    path = str(tmp_path / "pharm.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Eli Lilly')")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, brand_name,"
                 " is_marketed) VALUES (1, 1, 'Tirzepatide', 'Mounjaro', 1)")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (2, 1, 'LY9999999', 0)")
    conn.execute("INSERT INTO indications (id, name) VALUES (1, 'Obesity')")
    conn.execute("INSERT INTO asset_indications (asset_id, indication_id, phase)"
                 " VALUES (2, 1, 'Phase 2')")
    conn.commit()
    conn.close()
    return path


def _fake_get(url, params=None):
    params = params or {}
    if url.endswith("/molecule.json"):
        name = (params.get("molecule_synonyms__molecule_synonym__iexact")
                or params.get("pref_name__iexact") or "").lower()
        return _load("chembl_molecule_tirzepatide.json") if name == "tirzepatide" \
            else {"molecules": []}
    if url.endswith("/mechanism.json"):
        return _load("chembl_mechanism_tirzepatide.json")
    if "/target/" in url:
        return _load("chembl_target_glp1r.json")
    if url == P.OPENFDA_LABEL:
        return _load("openfda_label_tirzepatide.json")
    raise AssertionError(url)


def test_a_run_writes_mechanisms_targets_classes_and_the_warning(tmp_path, monkeypatch):
    path = _book(tmp_path)
    monkeypatch.setattr(P, "get_json", _fake_get)
    monkeypatch.setattr(P, "_POLITE_SLEEP_S", 0)
    result = P.PharmacologyFetcher("LLY", path).run()
    assert not result.errors
    conn = db.get_connection(path)
    rows = {(r["kind"], r["value"]) for r in conn.execute(
        "SELECT kind, value FROM asset_pharmacology WHERE asset_id = 1")}
    assert ("mechanism", "Glucagon-like peptide 1 receptor agonist") in rows
    assert ("target", "Glucagon-like peptide 1 receptor") in rows
    assert ("epc_class", "GLP-1 Receptor Agonist [EPC]") in rows
    assert any(k == "boxed_warning" for k, _ in rows)
    # A code ChEMBL does not know is left without a row, and the gap is said aloud.
    assert conn.execute("SELECT COUNT(*) FROM asset_pharmacology WHERE asset_id = 2"
                        ).fetchone()[0] == 0
    assert any("match no ChEMBL molecule" in n for n in result.notes)
    conn.close()


def test_two_molecules_for_one_name_is_not_a_match(tmp_path, monkeypatch):
    path = _book(tmp_path)
    two = {"molecules": [{"molecule_chembl_id": "CHEMBL1", "pref_name": "A"},
                         {"molecule_chembl_id": "CHEMBL2", "pref_name": "B"}]}
    monkeypatch.setattr(P, "get_json", lambda url, params=None: two
                        if url.endswith("/molecule.json") else {})
    monkeypatch.setattr(P, "_POLITE_SLEEP_S", 0)
    fetcher = P.PharmacologyFetcher("LLY", path)
    assert fetcher._molecule("ambiguous") is None
