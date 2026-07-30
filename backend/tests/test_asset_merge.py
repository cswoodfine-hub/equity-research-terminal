"""Folding a derived compound into the marketed product it turns out to be."""

import asset_merge
import db
from fetchers.approvals_openfda import parse_drugsfda


def _seed(tmp_path):
    path = str(tmp_path / "merge.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('LLY', 'Eli Lilly')")
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('MRK', 'Merck')")
    conn.commit()
    return path, conn


def _asset(conn, ticker, brand=None, generic=None, marketed=0, code=None):
    cid = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                       (ticker,)).fetchone()["id"]
    cur = conn.execute(
        "INSERT INTO assets (owner_company_id, brand_name, generic_name,"
        "                    internal_code, is_marketed) VALUES (?, ?, ?, ?, ?)",
        (cid, brand, generic, code, marketed))
    conn.commit()
    return cur.lastrowid


def _trial(conn, asset_id, nct):
    conn.execute("INSERT INTO trials (nct_id, asset_id, title, phase)"
                 " VALUES (?, ?, 'A study', 'Phase 4')", (nct, asset_id))
    conn.commit()


def test_reads_the_generic_name_off_the_payload():
    payload = {"results": [{
        "application_number": "NDA216059",
        "products": [{"brand_name": "JAYPIRCA", "marketing_status": "Prescription",
                      "active_ingredients": [{"name": "PIRTOBRUTINIB",
                                              "strength": "50MG"}]}],
        "submissions": [{"submission_type": "ORIG", "submission_status": "AP",
                         "submission_status_date": "20230127"}],
    }]}
    row = parse_drugsfda(payload, "LLY")[0]
    assert row["brand"] == "Jaypirca"
    assert row["generic"] == "Pirtobrutinib"


def test_falls_back_to_the_openfda_block():
    payload = {"results": [{
        "application_number": "BLA125469",
        "openfda": {"generic_name": ["DULAGLUTIDE"]},
        "products": [{"brand_name": "TRULICITY"}],
        "submissions": [{"submission_type": "ORIG", "submission_status": "AP",
                         "submission_status_date": "20140918"}],
    }]}
    assert parse_drugsfda(payload, "LLY")[0]["generic"] == "Dulaglutide"


def test_states_no_generic_when_the_payload_gives_none():
    payload = {"results": [{
        "application_number": "NDA000001",
        "products": [{"brand_name": "SOMETHING"}],
        "submissions": [{"submission_type": "ORIG", "submission_status": "AP",
                         "submission_status_date": "20200101"}],
    }]}
    assert parse_drugsfda(payload, "LLY")[0]["generic"] is None


def test_merges_the_derived_row_into_the_marketed_one(tmp_path):
    path, conn = _seed(tmp_path)
    marketed = _asset(conn, "LLY", brand="Jaypirca", generic="Pirtobrutinib",
                      marketed=1, code="NDA216059")
    derived = _asset(conn, "LLY", generic="Pirtobrutinib")
    _trial(conn, derived, "NCT0001")
    _trial(conn, derived, "NCT0002")
    conn.close()

    assert asset_merge.merge(path) == {"merged": 1, "trials_moved": 2, "by_code": 0}

    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM assets WHERE id = ?",
                        (derived,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM trials WHERE asset_id = ?",
                        (marketed,)).fetchone()[0] == 2
    conn.close()

    # A second run has nothing left to do.
    assert asset_merge.merge(path) == {"merged": 0, "trials_moved": 0, "by_code": 0}


def test_never_merges_across_companies(tmp_path):
    path, conn = _seed(tmp_path)
    _asset(conn, "MRK", brand="Keytruda", generic="Pembrolizumab", marketed=1)
    derived = _asset(conn, "LLY", generic="Pembrolizumab")
    _trial(conn, derived, "NCT0003")
    conn.close()

    # Two firms can name the same molecule; a merge across owners would invent a
    # relationship the data does not state.
    assert asset_merge.merge(path)["merged"] == 0


def test_leaves_an_ambiguous_name_alone(tmp_path):
    path, conn = _seed(tmp_path)
    _asset(conn, "LLY", brand="Brand one", generic="Shared", marketed=1)
    _asset(conn, "LLY", brand="Brand two", generic="Shared", marketed=1)
    derived = _asset(conn, "LLY", generic="Shared")
    _trial(conn, derived, "NCT0004")
    conn.close()

    # A name held by two marketed rows identifies neither.
    assert asset_merge.merge(path)["merged"] == 0


def test_moves_the_rows_that_hang_off_the_derived_asset(tmp_path):
    path, conn = _seed(tmp_path)
    marketed = _asset(conn, "LLY", brand="Jaypirca", generic="Pirtobrutinib",
                      marketed=1)
    derived = _asset(conn, "LLY", generic="Pirtobrutinib")
    _trial(conn, derived, "NCT0005")
    conn.execute("INSERT INTO product_notes (asset_id, thesis) VALUES (?, 'mine')",
                 (derived,))
    conn.execute("INSERT INTO trial_asset_map (nct_id, asset_id) VALUES ('NCT0005', ?)",
                 (derived,))
    conn.commit()
    conn.close()

    assert asset_merge.merge(path)["merged"] == 1

    conn = db.get_connection(path)
    note = conn.execute("SELECT asset_id, thesis FROM product_notes").fetchone()
    mapped = conn.execute("SELECT asset_id FROM trial_asset_map").fetchone()
    conn.close()
    assert note["asset_id"] == marketed and note["thesis"] == "mine"
    assert mapped["asset_id"] == marketed


# --- the second pass: two derived rows for one programme -------------------------------

def _codes(name):
    return asset_merge.development_codes(name)


def test_a_code_is_read_out_of_a_parenthetical():
    """canonical() strips parentheticals, which is right for a study's own abbreviation
    and wrong for the development code Dyne registers its Phase 3 under."""
    assert _codes("zeleciment basivarsen (DYNE-101)") == {"DYNE-101"}


def test_a_target_is_not_a_development_code():
    """"KYV-101 anti-CD19 CAR-T cell therapy" names one programme, not two."""
    assert _codes("KYV-101 anti-CD19 CAR-T cell therapy") == {"KYV-101"}


def test_an_isotope_is_not_a_development_code():
    assert _codes("[177Lu]Lu-PSMA-617") == {"PSMA-617"}


def test_two_spellings_of_one_programme_merge(tmp_path):
    """Dyne's Phase 1/2 registers DYNE-101 and its Phase 3 registers the same drug under
    its INN with the code in brackets. The pipeline showed four programmes for two."""
    path, conn = _seed(tmp_path)
    bare = _asset(conn, "LLY", generic="DYNE-101")
    named = _asset(conn, "LLY", generic="zeleciment basivarsen (DYNE-101)")
    _trial(conn, bare, "NCT0101")
    _trial(conn, named, "NCT0102")
    conn.close()

    result = asset_merge.merge(path)
    assert result["by_code"] == 1
    assert result["trials_moved"] == 1

    conn = db.get_connection(path)
    rows = conn.execute("SELECT id, generic_name, internal_code FROM assets").fetchall()
    trials = conn.execute("SELECT COUNT(*) FROM trials WHERE asset_id = ?",
                          (named,)).fetchone()[0]
    conn.close()
    assert len(rows) == 1
    # The survivor is the name that carries both the INN and the code, and the code that
    # identified the merge is written down.
    assert rows[0]["generic_name"] == "zeleciment basivarsen (DYNE-101)"
    assert rows[0]["internal_code"] == "DYNE-101"
    assert trials == 2

    assert asset_merge.merge(path)["by_code"] == 0


def test_the_row_with_the_most_trials_survives(tmp_path):
    path, conn = _seed(tmp_path)
    busy = _asset(conn, "LLY", generic="AZD6234")
    quiet = _asset(conn, "LLY", generic="AZD6234 Formulation 1 given weekly")
    _trial(conn, busy, "NCT0201")
    _trial(conn, busy, "NCT0202")
    _trial(conn, quiet, "NCT0203")
    conn.close()

    asset_merge.merge(path)
    conn = db.get_connection(path)
    rows = conn.execute("SELECT id FROM assets").fetchall()
    conn.close()
    assert [r["id"] for r in rows] == [busy]


def test_a_combination_is_not_a_duplicate(tmp_path):
    """"MET233 and MET097" is two compounds. Folding it into MET097 would attribute one
    drug's study to the other."""
    path, conn = _seed(tmp_path)
    single = _asset(conn, "LLY", generic="MET097")
    combo = _asset(conn, "LLY", generic="MET233 and MET097")
    _trial(conn, single, "NCT0301")
    _trial(conn, combo, "NCT0302")
    conn.close()

    assert asset_merge.merge(path)["by_code"] == 0


def test_a_diagnostic_and_a_therapeutic_are_not_one_programme(tmp_path):
    """Novartis develops [68Ga]Ga-DWJ155 for imaging and [177Lu]Lu-DWJ155 to treat. Same
    targeting molecule, two products."""
    path, conn = _seed(tmp_path)
    imaging = _asset(conn, "LLY", generic="[68Ga]Ga-DWJ155")
    therapy = _asset(conn, "LLY", generic="[177Lu]Lu-DWJ155")
    _trial(conn, imaging, "NCT0401")
    _trial(conn, therapy, "NCT0402")
    conn.close()

    assert asset_merge.merge(path)["by_code"] == 0


def test_the_same_isotope_written_two_ways_still_merges(tmp_path):
    path, conn = _seed(tmp_path)
    one = _asset(conn, "LLY", generic="68Ga-NNS309")
    two = _asset(conn, "LLY", generic="[68Ga]Ga-NNS309")
    _trial(conn, one, "NCT0501")
    _trial(conn, two, "NCT0502")
    conn.close()

    assert asset_merge.merge(path)["by_code"] == 1


def test_the_code_pass_never_crosses_companies(tmp_path):
    path, conn = _seed(tmp_path)
    mine = _asset(conn, "LLY", generic="ABC-101")
    theirs = _asset(conn, "MRK", generic="ABC-101")
    _trial(conn, mine, "NCT0601")
    _trial(conn, theirs, "NCT0602")
    conn.close()

    assert asset_merge.merge(path)["by_code"] == 0


def test_a_marketed_row_is_left_to_the_first_pass(tmp_path):
    """The code pass only folds derived rows. Two marketed products can share a token,
    and Novartis markets both Locametz and Netspot as gallium Ga-68 agents."""
    path, conn = _seed(tmp_path)
    _asset(conn, "LLY", generic="Gallium Ga-68 Gozetotide", marketed=1)
    _asset(conn, "LLY", generic="Gallium Dotatate Ga-68", marketed=1)
    conn.close()

    assert asset_merge.merge(path) == {"merged": 0, "trials_moved": 0, "by_code": 0}
