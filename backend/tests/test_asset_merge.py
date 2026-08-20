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

    got = asset_merge.merge(path)
    assert (got["merged"], got["trials_moved"], got["by_code"], got["by_brand"]) \
        == (1, 2, 0, 0)

    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM assets WHERE id = ?",
                        (derived,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM trials WHERE asset_id = ?",
                        (marketed,)).fetchone()[0] == 2
    conn.close()

    # A second run has nothing left to do.
    got = asset_merge.merge(path)
    assert (got["merged"], got["trials_moved"], got["by_code"], got["by_brand"]) \
        == (0, 0, 0, 0)


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

    got = asset_merge.merge(path)
    assert (got["merged"], got["trials_moved"], got["by_code"], got["by_brand"]) \
        == (0, 0, 0, 0)


# --- one product filed under several application numbers -------------------

def test_a_salt_is_the_same_molecule():
    """Calquence is filed as acalabrutinib and acalabrutinib maleate, Mekinist as
    trametinib and trametinib dimethyl sulfoxide. A salt is how a molecule is formulated,
    not which molecule it is."""
    same = asset_merge.canonical_generic
    assert same("Acalabrutinib") == same("Acalabrutinib Maleate")
    assert same("Trametinib") == same("Trametinib Dimethyl Sulfoxide")
    assert same("Lenacapavir") == same("Lenacapavir Sodium")
    assert same("Ivabradine") == same("Ivabradine Hydrochloride")


def test_a_different_active_is_not_a_salt():
    """Emend covers aprepitant and fosaprepitant, an oral drug and an intravenous prodrug.
    They differ before any salt is stripped, so they stay apart."""
    same = asset_merge.canonical_generic
    assert same("Aprepitant") != same("Fosaprepitant Dimeglumine")


def test_seven_applications_for_one_drug_become_one_product(tmp_path):
    """Zithromax is seven NDAs for azithromycin, one per formulation and strength. Left
    alone the universe counts one product as seven, and every revenue, exclusivity and
    indication lookup sees a fraction of it."""
    path, conn = _seed(tmp_path)
    ids = [_asset(conn, "LLY", brand="Zithromax", generic="Azithromycin", marketed=1,
                  code=f"NDA5071{n}") for n in range(7)]
    conn.commit()
    out = asset_merge.merge(path)
    assert out["by_formulation"] == 6
    conn = db.get_connection(path)
    rows = conn.execute("SELECT id FROM assets WHERE brand_name = 'Zithromax'").fetchall()
    assert [r["id"] for r in rows] == [min(ids)]      # the oldest survives, stably
    conn.close()


def test_two_brands_of_one_molecule_are_left_alone(tmp_path):
    """Same molecule, different brand, is two products. Folding them would merge a
    company's own competitor into it."""
    path, conn = _seed(tmp_path)
    _asset(conn, "LLY", brand="Brandone", generic="Azithromycin", marketed=1, code="NDA1")
    _asset(conn, "LLY", brand="Brandtwo", generic="Azithromycin", marketed=1, code="NDA2")
    conn.commit()
    assert asset_merge.merge(path)["by_formulation"] == 0


def test_one_brand_covering_two_molecules_is_left_alone(tmp_path):
    path, conn = _seed(tmp_path)
    _asset(conn, "LLY", brand="Emend", generic="Aprepitant", marketed=1, code="NDA1")
    _asset(conn, "LLY", brand="Emend", generic="Fosaprepitant Dimeglumine",
           marketed=1, code="NDA2")
    conn.commit()
    assert asset_merge.merge(path)["by_formulation"] == 0


def test_two_companies_are_never_merged(tmp_path):
    path, conn = _seed(tmp_path)
    _asset(conn, "LLY", brand="Same", generic="Azithromycin", marketed=1, code="NDA1")
    _asset(conn, "MRK", brand="Same", generic="Azithromycin", marketed=1, code="NDA2")
    conn.commit()
    assert asset_merge.merge(path)["by_formulation"] == 0


# --- the merge has to survive the next refresh -----------------------------

def test_an_absorbed_application_number_still_resolves(tmp_path):
    """A product is looked up by application number, so a folded row would be recreated by
    the next openFDA or Orange Book refresh and the merge would undo itself daily."""
    import assets_util
    path, conn = _seed(tmp_path)
    keep = _asset(conn, "LLY", brand="Zithromax", generic="Azithromycin", marketed=1,
                  code="NDA1")
    _asset(conn, "LLY", brand="Zithromax", generic="Azithromycin", marketed=1, code="NDA2")
    conn.commit()
    asset_merge.merge(path)
    conn = db.get_connection(path)
    company = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    again = assets_util.upsert_asset(conn, company, "NDA2", "Zithromax",
                                     "Azithromycin", "small molecule")
    assert again == keep
    assert conn.execute("SELECT COUNT(*) FROM assets WHERE brand_name='Zithromax'"
                        ).fetchone()[0] == 1
    conn.close()


def test_the_earliest_paragraph_iv_is_the_one_kept(tmp_path):
    """Two formulations are challenged separately and the table holds one row per asset,
    so the merge has to choose. Keeping the survivor's own date put Ozempic's first
    challenge two and a half years late and Nexium's eight years late."""
    path, conn = _seed(tmp_path)
    keep = _asset(conn, "LLY", brand="Ozempic", generic="Semaglutide", marketed=1,
                  code="NDA1")
    other = _asset(conn, "LLY", brand="Ozempic", generic="Semaglutide", marketed=1,
                   code="NDA2")
    conn.execute("INSERT INTO patent_challenges (asset_id, application_number,"
                 " first_submission) VALUES (?, 'NDA1', '2024-07-15')", (keep,))
    conn.execute("INSERT INTO patent_challenges (asset_id, application_number,"
                 " first_submission) VALUES (?, 'NDA2', '2021-12-06')", (other,))
    conn.commit()
    asset_merge.merge(path)
    conn = db.get_connection(path)
    rows = conn.execute("SELECT asset_id, first_submission FROM patent_challenges").fetchall()
    assert len(rows) == 1
    assert rows[0]["first_submission"] == "2021-12-06"
    conn.close()


def test_a_collapse_that_drops_a_row_says_so(tmp_path):
    """A row that will not move collided with one the survivor already holds. Reported,
    because a real loss would look exactly the same in silence."""
    path, conn = _seed(tmp_path)
    a = _asset(conn, "LLY", brand="Zithromax", generic="Azithromycin", marketed=1, code="N1")
    b = _asset(conn, "LLY", brand="Zithromax", generic="Azithromycin", marketed=1, code="N2")
    for asset_id in (a, b):
        conn.execute("INSERT INTO patent_challenges (asset_id, application_number,"
                     " first_submission) VALUES (?, 'X', '2024-01-01')", (asset_id,))
    conn.commit()
    out = asset_merge.merge(path)
    assert out["duplicate_rows_collapsed"].get("patent_challenges") == 1


def test_folding_is_idempotent(tmp_path):
    path, conn = _seed(tmp_path)
    for n in range(4):
        _asset(conn, "LLY", brand="Neoral", generic="Cyclosporine", marketed=1,
               code=f"NDA{n}")
    conn.commit()
    assert asset_merge.merge(path)["by_formulation"] == 3
    assert asset_merge.merge(path)["by_formulation"] == 0


# --- the self-reference that stopped the daily refresh ---------------------
# Molecule grouping points a row at the head of its own molecule, in
# assets.molecule_id. Nothing moved that pointer on a merge, so absorbing a head
# broke a foreign key and every scheduled run died on it for five days, on Otezla.

def test_the_schema_walk_finds_the_assets_table_pointing_at_itself(tmp_path):
    import assets_util
    path, conn = _seed(tmp_path)
    columns = assets_util.referring_columns(conn)
    assert ("assets", "molecule_id") in columns
    assert ("trials", "asset_id") in columns
    # The older helper still answers the question its callers ask: other tables,
    # keyed by asset_id, which is the shape their SQL is written around.
    tables = assets_util.referring_tables(conn)
    assert "assets" not in tables and "trials" in tables
    conn.close()


def test_absorbing_a_molecule_head_repoints_its_siblings(tmp_path):
    path, conn = _seed(tmp_path)
    marketed = _asset(conn, "MRK", brand="Otezla", generic="Apremilast",
                      marketed=1, code="NDA205437")
    derived = _asset(conn, "MRK", generic="Apremilast")
    # The row about to be absorbed is the head of the molecule, and the row absorbing
    # it is one of the rows naming it. That is the Otezla case exactly, and it raised
    # IntegrityError: FOREIGN KEY constraint failed on every scheduled run.
    conn.execute("UPDATE assets SET molecule_id = ? WHERE id IN (?, ?)",
                 (derived, derived, marketed))
    conn.commit()
    conn.close()

    assert asset_merge.merge(path)["merged"] == 1

    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM assets WHERE id = ?",
                        (derived,)).fetchone()[0] == 0
    # The survivor heads the molecule it just absorbed the head of, which is the
    # convention the rest of the table already keeps.
    head = conn.execute("SELECT molecule_id FROM assets WHERE id = ?",
                        (marketed,)).fetchone()["molecule_id"]
    assert head == marketed
    conn.close()


def test_the_orphan_prune_will_not_delete_a_row_another_asset_names(tmp_path):
    import trial_mapping
    path, conn = _seed(tmp_path)
    head = _asset(conn, "LLY", generic="Retatrutide")
    sibling = _asset(conn, "LLY", generic="Retatrutide", marketed=1)
    conn.execute("UPDATE assets SET molecule_id = ? WHERE id = ?", (head, sibling))
    conn.commit()
    conn.close()

    trial_mapping.prune_orphan_pipeline_assets(path)

    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM assets WHERE id = ?",
                        (head,)).fetchone()[0] == 1
    conn.close()
