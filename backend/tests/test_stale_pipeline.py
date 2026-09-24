"""Assets the book calls pipeline whose molecule is already approved. No network.

The fixture is five real drugsfda responses, one per flavour of the problem: an approval
under a licensee, a generic under a third party, an approval under an acquired subsidiary,
an approval under the company itself, and a molecule with no approval at all.
"""

import json
import pathlib

import db
import seed
import stale_pipeline

_FIX = pathlib.Path(__file__).resolve().parent / "fixtures"
_PAYLOADS = json.loads((_FIX / "drugsfda_stale_pipeline.json").read_text())


# --- which names are worth a request -------------------------------------
def test_an_ingredient_name_is_checked_and_a_development_code_is_not():
    assert stale_pipeline.ingredient_of(None, "Linerixibat") == "Linerixibat"
    assert stale_pipeline.ingredient_of(None, "Fenebrutinib") == "Fenebrutinib"
    # A multi-word name gives up its first word only where that word could be a molecule.
    assert stale_pipeline.ingredient_of(None, "Efgartigimod PH20 SC") == "Efgartigimod"
    assert stale_pipeline.ingredient_of(None, "HZ/su vaccine") is None
    # Codes return nothing from a register, so checking them only spends requests.
    assert stale_pipeline.ingredient_of(None, "GSK4532990") is None
    assert stale_pipeline.ingredient_of(None, "PF-07055480") is None
    assert stale_pipeline.ingredient_of("MK-1406", None) is None


def test_a_regimen_or_a_dose_arm_is_not_a_molecule():
    for name in ("Acalabrutinib + R-CHOP standard of care", "Ritlecitinib higher dose",
                 "Ocrelizumab Co-formulated With rHuPH20", "Ocrelizumab Test Formulation",
                 "Neoadjuvant Olaparib monotherapy"):
        assert stale_pipeline.ingredient_of(None, name) is None, name


# --- reading an approval record -------------------------------------------
def test_an_approval_under_a_licensee_is_read_with_its_sponsor():
    """Linerixibat is GSK's molecule and Lynavoy is Intercept's label."""
    got = stale_pipeline.read_approval(_PAYLOADS["linerixibat"])
    assert got["application"] == "NDA220295"
    assert got["sponsor"] == "INTERCEPT"
    assert got["brands"] == ["LYNAVOY"]
    assert got["first_approval"] == "20260317"
    assert got["is_generic"] is False


def test_a_generic_is_flagged_as_one():
    """Zydus' eltrombopag is a loss of exclusivity for Novartis' Promacta, not an approval
    Novartis won, and promoting it to marketed revenue would have been backwards."""
    got = stale_pipeline.read_approval(_PAYLOADS["eltrombopag"])
    assert got["is_generic"] is True
    assert got["sponsor"] == "ZYDUS PHARMS"


def test_no_approval_reads_as_none():
    assert stale_pipeline.read_approval(_PAYLOADS["fenebrutinib"]) is None
    assert stale_pipeline.read_approval({}) is None


def test_a_sponsor_is_matched_to_the_owner_loosely_and_says_so():
    assert stale_pipeline.owned_by("PFIZER", "Pfizer Inc")
    assert stale_pipeline.owned_by("NOVARTIS", "Novartis AG")
    # Array Biopharma is Pfizer and ImmunoGen is AbbVie, so a false here means the sponsor
    # is someone else's name rather than that the value is not the company's.
    assert not stale_pipeline.owned_by("ARRAY BIOPHARMA INC", "Pfizer Inc")
    assert not stale_pipeline.owned_by("INTERCEPT", "GSK plc")
    assert not stale_pipeline.owned_by(None, "GSK plc")


# --- the report ------------------------------------------------------------
def test_each_flavour_gets_its_own_reading():
    rows = [
        {"asset_id": 1, "ticker": "GSK", "ingredient": "Linerixibat", "owned": False,
         "approval": stale_pipeline.read_approval(_PAYLOADS["linerixibat"])},
        {"asset_id": 2, "ticker": "NVS", "ingredient": "Eltrombopag", "owned": False,
         "approval": stale_pipeline.read_approval(_PAYLOADS["eltrombopag"])},
        {"asset_id": 3, "ticker": "PFE", "ingredient": "Ritlecitinib", "owned": True,
         "approval": stale_pipeline.read_approval(_PAYLOADS["ritlecitinib"])},
        {"asset_id": 4, "ticker": "ROG", "ingredient": "Fenebrutinib", "owned": False,
         "approval": stale_pipeline.read_approval(_PAYLOADS["fenebrutinib"])},
    ]
    got = {r["asset_id"]: r["reading"] for r in stale_pipeline.findings(rows)}
    assert 4 not in got                              # no approval, nothing to report
    assert "generic" in got[2]
    assert "stale" in got[3]
    assert "licence" in got[1]


def test_candidates_only_offers_unmodelled_late_stage_rows(tmp_path):
    path = tmp_path / "s.db"
    db.init(path)
    seed.load_companies(path)
    conn = db.get_connection(path)
    company = conn.execute("SELECT id FROM companies WHERE ticker='GSK'").fetchone()["id"]
    ids = {}
    for brand, generic, marketed in (("Lynavoy", "Linerixibat", 0),
                                     ("Shingrix", "Zoster Vaccine", 1),
                                     (None, "GSK4532990", 0)):
        cur = conn.execute("INSERT INTO assets (owner_company_id, brand_name, generic_name,"
                           " is_marketed) VALUES (?, ?, ?, ?)",
                           (company, brand, generic, marketed))
        ids[generic] = cur.lastrowid
    phase = conn.execute("INSERT INTO indications (name) VALUES ('Cholestasis')").lastrowid
    for generic in ids:
        conn.execute("INSERT INTO asset_indications (asset_id, indication_id, phase)"
                     " VALUES (?, ?, 'Phase 3')", (ids[generic], phase))
    conn.commit()
    try:
        got = stale_pipeline.candidates(conn)
    finally:
        conn.close()
    names = {r["ingredient"] for r in got}
    assert names == {"Linerixibat"}      # the marketed one is out, the code has no ingredient
