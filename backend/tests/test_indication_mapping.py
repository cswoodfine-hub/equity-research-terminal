"""Assets to indications, the pair CLAUDE.md calls the unit of analysis.

The fixture is two real studies of the same disease, chosen because the registry indexes
them differently: NCT06926621 puts twelve descriptors in ``meshes`` ending in "Nervous
System Diseases", and NCT05027269 puts two there and the broad ones in ``ancestors``. Any
rule that trusts that split gets one of them wrong.
"""

import json
import pathlib

import db
import indication_mapping as im
from fetchers.trials_ctgov import _meshes

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
STUDIES = json.loads((FIXTURES / "ctgov_condition_browse.json").read_text())["studies"]
BY_NCT = {s["protocolSection"]["identificationModule"]["nctId"]: s for s in STUDIES}


def _conditions(study):
    return study["protocolSection"]["conditionsModule"]["conditions"]


# --- reading the payload ---------------------------------------------------

def test_both_halves_of_the_browse_module_are_kept():
    """Neither alone says which term is the indication, so neither is thrown away."""
    for study in STUDIES:
        got = _meshes(study)
        assert got["meshes"]
        assert all(t["id"] and t["term"] for t in got["meshes"] + got["ancestors"])


def test_the_registry_indexes_the_same_disease_two_ways():
    """The fixture's whole point, and the reason the ancestors split is not the rule."""
    wide = _meshes(BY_NCT["NCT06926621"])["meshes"]
    narrow = _meshes(BY_NCT["NCT05027269"])["meshes"]
    assert len(wide) > len(narrow)
    assert "Nervous System Diseases" in [t["term"] for t in wide]
    assert "Nervous System Diseases" not in [t["term"] for t in narrow]


# --- deciding which descriptor is the indication ---------------------------

def test_the_sponsors_words_pick_the_indication_out_of_a_polluted_list():
    study = BY_NCT["NCT06926621"]
    got = im.indications_for(_conditions(study), _meshes(study))
    terms = [t["term"] for t in got]
    assert "Myotonic Dystrophy" in terms
    assert "Nervous System Diseases" not in terms
    assert "Musculoskeletal Diseases" not in terms


def test_both_studies_of_one_disease_land_on_the_same_descriptor():
    """Different indexing, same answer, which is what makes the pair countable."""
    ids = []
    for study in STUDIES:
        got = im.indications_for(_conditions(study), _meshes(study))
        ids.append({t["id"] for t in got})
    assert ids[0] & ids[1]


def test_a_spelling_the_sponsor_invented_still_resolves():
    """"Type 1 Diabetes" and "Diabetes Mellitus, Type 1" are one indication. An earlier
    rule dropped the digits as noise and lost every diabetes trial."""
    browse = {"meshes": [{"id": "D003922", "term": "Diabetes Mellitus, Type 1"}],
              "ancestors": []}
    got = im.indications_for(["Type 1 Diabetes"], browse)
    assert [t["id"] for t in got] == ["D003922"]


def test_type_1_does_not_answer_to_type_2():
    browse = {"meshes": [{"id": "D003924", "term": "Diabetes Mellitus, Type 2"}],
              "ancestors": []}
    assert im.indications_for(["Type 1 Diabetes"], browse) == []


def test_sickle_cell_disease_finds_anemia_sickle_cell():
    browse = {"meshes": [{"id": "D000755", "term": "Anemia, Sickle Cell"}], "ancestors": []}
    assert [t["id"] for t in im.indications_for(["Sickle Cell Disease"], browse)] \
        == ["D000755"]


def test_a_healthy_volunteer_study_has_no_indication():
    """"Healthy", "Healthy Volunteers" and "Healthy Participants" are 141 Phase 1 studies
    describing who was dosed, not what was treated."""
    browse = {"meshes": [{"id": "D006262", "term": "Health"}], "ancestors": []}
    assert im.indications_for(["Healthy Volunteers"], browse) == []
    assert not im.is_indication("Healthy")
    assert not im.is_indication("Healthy Participants")


def test_a_branch_of_the_tree_is_refused_even_when_the_sponsor_writes_it():
    """A sponsor writing "Neoplasms" has named a branch. An asset filed there is an asset
    filed nowhere, and the list of these is short and explicit rather than inferred."""
    browse = {"meshes": [{"id": "D009369", "term": "Neoplasms"}], "ancestors": []}
    assert im.indications_for(["Neoplasms"], browse) == []
    assert not im.is_indication("Lymphoma")
    # but a real disease that merely contains the word is untouched
    assert im.is_indication("Lymphoma, Non-Hodgkin")
    assert im.is_indication("Lung Neoplasms")


def test_the_sectors_biggest_indications_survive():
    """Refusing every descriptor that parents another was tried and lost obesity across
    143 trials, lupus across 53 and breast cancer across 34, each named in plain words."""
    for mesh_id, term, said in (("D009765", "Obesity", "Obesity"),
                                ("D008180", "Lupus Erythematosus, Systemic",
                                 "Systemic Lupus Erythematosus"),
                                ("D001943", "Breast Neoplasms", "Breast Cancer")):
        browse = {"meshes": [{"id": mesh_id, "term": term}], "ancestors": []}
        assert [t["id"] for t in im.indications_for([said], browse)] == [mesh_id], term


# --- rolling studies up into a pair ----------------------------------------

def test_the_phase_is_the_highest_the_asset_has_reached():
    """A company running Phase 1 and Phase 3 in one disease is in Phase 3 there."""
    browse = json.dumps({"meshes": [{"id": "D000755", "term": "Anemia, Sickle Cell"}]})
    rows = [{"asset_id": 1, "conditions": '["Sickle Cell Disease"]', "mesh_terms": browse,
             "phase": "Phase 1", "overall_status": "Completed", "enrollment": 20,
             "first_posted": "2021-01-01"},
            {"asset_id": 1, "conditions": '["Sickle Cell Disease"]', "mesh_terms": browse,
             "phase": "Phase 3", "overall_status": "Recruiting", "enrollment": 300,
             "first_posted": "2024-01-01"}]
    pairs = im.pairs_from_trials(rows)
    entry = pairs[(1, "D000755")]
    assert entry["phase"] == "Phase 3"
    assert entry["trials"] == 2
    assert entry["first_posted"] == "2021-01-01"    # earliest, so an advance is visible


def test_a_live_study_beats_a_stopped_one():
    """A terminated Phase 2 beside a recruiting Phase 3 is a live programme, and reading
    the terminated study alone would retire it."""
    assert im.status_for(["Terminated", "Recruiting"]) == "Recruiting"
    assert im.status_for(["Terminated", "Withdrawn"]) == "Terminated"
    assert im.status_for([]) == "Unknown"


def test_one_trial_in_three_diseases_makes_three_pairs():
    browse = json.dumps({"meshes": [
        {"id": "D000755", "term": "Anemia, Sickle Cell"},
        {"id": "D013789", "term": "Thalassemia"}]})
    rows = [{"asset_id": 7, "conditions": '["Sickle Cell Disease", "Thalassemia"]',
             "mesh_terms": browse, "phase": "Phase 2", "overall_status": "Recruiting",
             "enrollment": 40, "first_posted": "2023-01-01"}]
    assert set(im.pairs_from_trials(rows)) == {(7, "D000755"), (7, "D013789")}


def test_a_trial_with_no_asset_is_not_a_pair():
    rows = [{"asset_id": None, "conditions": '["Obesity"]',
             "mesh_terms": json.dumps({"meshes": [{"id": "D009765", "term": "Obesity"}]}),
             "phase": "Phase 3", "overall_status": "Recruiting", "enrollment": 1,
             "first_posted": None}]
    assert im.pairs_from_trials(rows) == {}


def test_the_older_stored_shape_still_reads():
    """mesh_terms was written as a bare list before ancestors were stored."""
    got = im.parse_browse(json.dumps([{"id": "D009765", "term": "Obesity"}]))
    assert got["meshes"][0]["id"] == "D009765"
    assert got["ancestors"] == []
    assert im.parse_browse(None)["meshes"] == []
    assert im.parse_browse("not json")["meshes"] == []


# --- the build -------------------------------------------------------------

def _seed(tmp_path):
    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'X', 'X Pharma')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name) VALUES (1, 1, 'A')")
    browse = json.dumps({"meshes": [{"id": "D000755", "term": "Anemia, Sickle Cell"}]})
    for nct, phase, status in (("NCT1", "Phase 1", "Completed"),
                               ("NCT2", "Phase 3", "Recruiting")):
        conn.execute(
            "INSERT INTO trials (nct_id, asset_id, sponsor_company_id, conditions,"
            " mesh_terms, phase, overall_status, enrollment, first_posted)"
            " VALUES (?, 1, 1, ?, ?, ?, ?, 100, '2022-01-01')",
            (nct, '["Sickle Cell Disease"]', browse, phase, status))
    conn.commit(); conn.close()
    return path


def test_build_writes_the_pair(tmp_path):
    path = _seed(tmp_path)
    summary = im.build(path)
    assert summary["pairs"] == 1 and summary["assets"] == 1
    conn = db.get_connection(path)
    row = dict(conn.execute(
        "SELECT ai.phase, ai.development_status, ai.is_lead, ai.first_seen_phase, i.name,"
        " i.mesh_id FROM asset_indications ai JOIN indications i"
        " ON i.id = ai.indication_id").fetchone())
    assert row["phase"] == "Phase 3"
    assert row["development_status"] == "Recruiting"
    assert row["is_lead"] == 1
    assert row["mesh_id"] == "D000755"
    conn.close()


def test_a_rebuild_keeps_the_phase_it_was_first_seen_at(tmp_path):
    """Otherwise a phase advance is invisible: the table would say Phase 3 was always so."""
    path = _seed(tmp_path)
    im.build(path)
    conn = db.get_connection(path)
    conn.execute("UPDATE asset_indications SET first_seen_phase = 'Phase 1'")
    conn.execute("UPDATE trials SET phase = 'Phase 4' WHERE nct_id = 'NCT2'")
    conn.commit(); conn.close()
    im.build(path)
    conn = db.get_connection(path)
    row = conn.execute("SELECT phase, first_seen_phase FROM asset_indications").fetchone()
    assert row[0] == "Phase 4"
    assert row[1] == "Phase 1"
    conn.close()


def test_an_override_removes_a_pair_the_derivation_got_wrong(tmp_path):
    path = _seed(tmp_path)
    im.build(path)
    conn = db.get_connection(path)
    indication_id = conn.execute("SELECT id FROM indications").fetchone()[0]
    conn.execute("INSERT INTO asset_indication_overrides (asset_id, indication_id,"
                 " exclude, note) VALUES (1, ?, 1, 'comparator arm, not our asset')",
                 (indication_id,))
    conn.commit(); conn.close()
    summary = im.build(path)
    assert summary["pairs"] == 0 and summary["excluded_by_override"] == 1


def test_an_override_can_force_the_phase(tmp_path):
    path = _seed(tmp_path)
    im.build(path)
    conn = db.get_connection(path)
    indication_id = conn.execute("SELECT id FROM indications").fetchone()[0]
    conn.execute("INSERT INTO asset_indication_overrides (asset_id, indication_id, phase)"
                 " VALUES (1, ?, 'Phase 2')", (indication_id,))
    conn.commit(); conn.close()
    im.build(path)
    conn = db.get_connection(path)
    assert conn.execute("SELECT phase FROM asset_indications").fetchone()[0] == "Phase 2"
    conn.close()


def test_a_pair_with_no_trial_left_stops_being_asserted(tmp_path):
    path = _seed(tmp_path)
    im.build(path)
    conn = db.get_connection(path)
    conn.execute("DELETE FROM trials")
    conn.commit(); conn.close()
    assert im.build(path)["pairs"] == 0


def test_an_override_removes_a_co_morbidity_read_as_an_indication(tmp_path):
    """Omvoh is an interleukin-23 antibody for ulcerative colitis. It was tagged Obesity
    because two trials study it alongside tirzepatide in colitis patients whose
    conditions read "Obesity or Overweight", which is a body-mass eligibility band and
    not a disease it treats. Every automatic signal tested for this ran at 5% to 30%
    precision, so the exclusion is recorded as the judgement it is."""
    db_file = tmp_path / "override.db"
    db.init(db_file)
    conn = db.get_connection(db_file)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Lilly')")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (35, 1, 'Mirikizumab', 1)")
    conn.execute(
        """INSERT INTO trials (nct_id, asset_id, phase, conditions, mesh_terms,
                               overall_status, enrollment)
           VALUES ('NCT06937086', 35, 'Phase 3',
                   '["Ulcerative Colitis", "Obesity or Overweight"]',
                   '{"meshes": [{"id": "D003093", "term": "Colitis, Ulcerative"},
                                {"id": "D009765", "term": "Obesity"}]}',
                   'Recruiting', 100)""")
    conn.commit()
    conn.close()

    im.build(db_file)
    conn = db.get_connection(db_file)
    names = {r[0] for r in conn.execute(
        """SELECT i.name FROM asset_indications ai JOIN indications i
             ON i.id = ai.indication_id WHERE ai.asset_id = 35""")}
    assert "Obesity" in names, "without an override the defect is present"
    obesity_id = conn.execute(
        "SELECT id FROM indications WHERE name = 'Obesity'").fetchone()[0]
    conn.execute("INSERT INTO asset_indication_overrides (asset_id, indication_id,"
                 " exclude, note) VALUES (35, ?, 1, 'enrolment criterion')", (obesity_id,))
    conn.commit()
    conn.close()

    got = im.build(db_file)
    conn = db.get_connection(db_file)
    names = {r[0] for r in conn.execute(
        """SELECT i.name FROM asset_indications ai JOIN indications i
             ON i.id = ai.indication_id WHERE ai.asset_id = 35""")}
    conn.close()
    assert "Obesity" not in names
    assert "Colitis, Ulcerative" in names, "the real indication must survive"
    assert got["excluded_by_override"] == 1


def test_the_rebuild_releases_a_catalyst_before_deleting_the_row_it_points_at(tmp_path):
    """catalysts.asset_indication_id references a row the wholesale rebuild deletes.
    Once filings began carrying that link, the rebuild raised a foreign key error and
    would have broken every refresh."""
    db_file = tmp_path / "fk.db"
    db.init(db_file)
    conn = db.get_connection(db_file)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Lilly')")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (7, 1, 'a drug', 0)")
    conn.execute("INSERT INTO indications (id, name) VALUES (5, 'Colitis, Ulcerative')")
    conn.execute("INSERT INTO asset_indications (id, asset_id, indication_id, phase,"
                 " region) VALUES (99, 7, 5, 'Phase 3', 'US')")
    conn.execute("INSERT INTO catalysts (company_id, asset_id, asset_indication_id,"
                 " catalyst_type, expected_date, title) VALUES"
                 " (1, 7, 99, 'PDUFA', '2027-01-01', 'a drug PDUFA, colitis')")
    conn.commit()
    conn.close()

    im.build(db_file)          # must not raise
    conn = db.get_connection(db_file)
    left = conn.execute("SELECT asset_indication_id FROM catalysts").fetchone()[0]
    conn.close()
    assert left is None, "the link is released, and applications.resolve reattaches it"


# --- the sponsor's English against MeSH's register (2026-10-10) ------------
#
# Saruparib's, AAA817's, mevrometostat's and Mim8's Phase 3s were filed under no indication,
# so their readouts sat outside the gate model: "Prostate Cancer" shares no word with
# "Prostatic Neoplasms", nor "Haemophilia A" with "Hemophilia A".

def _browse(*terms):
    return {"meshes": [{"id": f"D{i}", "term": t} for i, t in enumerate(terms)],
            "ancestors": []}


def _found(conditions, *terms):
    return [t["term"] for t in im.indications_for(json.dumps(conditions), _browse(*terms))]


def test_prostate_cancer_is_prostatic_neoplasms():
    assert _found(["Metastatic Castration-Sensitive Prostate Cancer"],
                  "Prostatic Neoplasms", "Neoplasm Metastasis",
                  "Genital Neoplasms, Male") == ["Prostatic Neoplasms"]


def test_a_british_spelling_is_the_same_disease():
    assert _found(["Haemophilia A", "Haemophilia A With Inhibitors"],
                  "Hemophilia A") == ["Hemophilia A"]


def test_gastric_cancer_is_stomach_neoplasms():
    assert _found(["Gastric Cancer"], "Stomach Neoplasms") == ["Stomach Neoplasms"]


def test_sharing_only_the_word_for_a_kind_of_disease_is_no_match():
    """Once cancer reads as neoplasms, every cancer shares that word with every MeSH
    neoplasm. Lung cancer is lung neoplasms, not bronchial ones or neoplasms by site."""
    assert _found(["Lung Cancer"], "Bronchial Neoplasms", "Neoplasms by Site",
                  "Thoracic Neoplasms", "Lung Neoplasms") == ["Lung Neoplasms"]


def _with_additions(tmp_path, monkeypatch, rows):
    path = _seed(tmp_path)
    conn = db.get_connection(path)
    aids = json.dumps({"meshes": [{"id": "D000163", "term": "Acquired Immunodeficiency Syndrome"}]})
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name) VALUES (2, 1, 'Prepx')")
    conn.execute("INSERT INTO trials (nct_id, asset_id, sponsor_company_id, conditions,"
                 " mesh_terms, phase, overall_status, enrollment)"
                 " VALUES ('NCT9', 2, 1, '[\"HIV Pre-Exposure Prophylaxis\"]', ?, 'Phase 3',"
                 " 'Recruiting', 4000)", (aids,))
    conn.commit(); conn.close()
    csv_path = tmp_path / "additions.csv"
    csv_path.write_text("# comment\nticker,asset,mesh_id,term,nct_ids,basis\n" + rows)
    monkeypatch.setattr(im, "ADDITIONS_CSV", csv_path)
    im.build(path)
    conn = db.get_connection(path)
    got = [dict(r) for r in conn.execute(
        "SELECT ai.asset_id, ai.phase, ai.development_status, i.mesh_id, i.name"
        " FROM asset_indications ai JOIN indications i ON i.id = ai.indication_id"
        " WHERE ai.asset_id = 2")]
    conn.close()
    return got


def test_a_pair_no_vocabulary_reaches_is_added_by_hand_with_its_trials_phase(tmp_path,
                                                                             monkeypatch):
    got = _with_additions(tmp_path, monkeypatch,
                          'X,Prepx,D015658,HIV Infections,NCT9,"indexed only under AIDS"\n')
    assert got == [{"asset_id": 2, "phase": "Phase 3", "development_status": "Recruiting",
                    "mesh_id": "D015658", "name": "HIV Infections"}]


def test_an_added_pair_asserts_nothing_unless_its_trials_are_the_assets(tmp_path,
                                                                       monkeypatch):
    # NCT1 is asset 1's study, so naming it for asset 2 adds no pair.
    assert _with_additions(tmp_path, monkeypatch,
                           'X,Prepx,D015658,HIV Infections,NCT1,"wrong study"\n') == []


def test_an_accent_or_a_dropped_apostrophe_is_the_same_disease():
    """Before generic words stopped counting, these matched on "syndrome" or "disease"
    alone, so the guard would have lost them: Sotyktu's Sjogren's Phase 3 among them."""
    assert _found(["Sjögren's Syndrome"], "Sjogren's Syndrome") == ["Sjogren's Syndrome"]
    assert _found(["Crohns Disease"], "Crohn Disease") == ["Crohn Disease"]
    assert _found(["Urothelial Carcinoma"], "Carcinoma, Transitional Cell") \
        == ["Carcinoma, Transitional Cell"]


def test_a_disease_that_shares_only_the_word_disease_is_another_disease():
    assert _found(["Thyroid Eye Disease"], "Graves Disease") == []
    assert _found(["Carcinoid Syndrome"], "Serotonin Syndrome") == []


def test_a_study_the_vocabulary_misses_answers_with_its_added_descriptor(tmp_path,
                                                                        monkeypatch):
    """The gate views ask which indication a study is in. A pair the additions file made
    has to answer there too, and only for a study mapped to the row's own asset."""
    _with_additions(tmp_path, monkeypatch,
                    'X,Prepx,D015658,HIV Infections,NCT9 NCT1,"indexed only under AIDS"\n')
    conn = db.get_connection(str(tmp_path / "t.db"))
    try:
        assert im.curated_terms(conn, "NCT9") == [{"id": "D015658",
                                                   "term": "HIV Infections"}]
        assert im.curated_terms(conn, "NCT1") == []      # asset 1's study, not Prepx's
        assert im.curated_terms(conn, "NCT404") == []
    finally:
        conn.close()


# --- which indication a readout reads out in -------------------------------
_CTGOV = "https://clinicaltrials.gov/study/"


def _with_catalyst(tmp_path, nct="NCT2", second_mesh=None):
    """The build's fixture plus a readout catalyst pointing at one of its studies."""
    path = _seed(tmp_path)
    conn = db.get_connection(path)
    if second_mesh:
        # A study the registry indexes under two of the asset's own diseases.
        conn.execute("UPDATE trials SET conditions = ?, mesh_terms = ? WHERE nct_id = ?",
                     ('["Sickle Cell Disease", "beta-Thalassemia"]',
                      json.dumps({"meshes": [
                          {"id": "D000755", "term": "Anemia, Sickle Cell"},
                          {"id": "D017086", "term": "beta-Thalassemia"}]}), nct))
    conn.execute(
        "INSERT INTO catalysts (company_id, asset_id, catalyst_type, title,"
        " expected_date, status, source_url)"
        " VALUES (1, 1, 'readout', 'A readout', '2030-01-01', 'pending', ?)",
        (_CTGOV + nct,))
    conn.commit(); conn.close()
    return path


def test_a_readout_is_linked_to_the_indication_its_study_is_in(tmp_path):
    """A readout is an event in one disease, not in the asset as a whole. Until the
    catalyst says which, a label expansion on an approved drug cannot be priced as the
    indication it opens, and 794 of the 812 catalysts on the book named none."""
    path = _with_catalyst(tmp_path)
    summary = im.build(path)
    assert summary["catalysts_linked"] == 1

    conn = db.get_connection(path)
    row = conn.execute(
        "SELECT i.name FROM catalysts cat"
        "  JOIN asset_indications ai ON ai.id = cat.asset_indication_id"
        "  JOIN indications i ON i.id = ai.indication_id").fetchone()
    assert row["name"] == "Anemia, Sickle Cell"
    conn.close()


def test_a_readout_in_two_of_the_assets_diseases_is_left_unlinked(tmp_path):
    """One readout standing for two indications cannot be priced as either without a
    guess about which the market is reading. Unlinked it stays unpriced and says so."""
    path = _with_catalyst(tmp_path, second_mesh=True)
    summary = im.build(path)
    assert summary["catalysts_linked"] == 0
    assert summary["catalysts_ambiguous"] == 1

    conn = db.get_connection(path)
    assert conn.execute(
        "SELECT asset_indication_id FROM catalysts").fetchone()[0] is None
    conn.close()


def test_the_link_uses_the_same_rule_the_pairs_are_built_with(tmp_path):
    """A catalyst and the forecast it prices against must not disagree about what the
    study is in, so the link reads indications_for, not a second rule of its own."""
    path = _with_catalyst(tmp_path)
    im.build(path)
    conn = db.get_connection(path)
    linked, pair = conn.execute(
        "SELECT cat.asset_indication_id, ai.id FROM catalysts cat, asset_indications ai"
    ).fetchone()
    assert linked == pair
    conn.close()


def test_a_catalyst_with_no_study_behind_it_is_left_alone(tmp_path):
    """A curated catalyst or an FDA filing is applications.resolve's to attach."""
    path = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute(
        "INSERT INTO catalysts (company_id, asset_id, catalyst_type, title,"
        " expected_date, status, source_url)"
        " VALUES (1, 1, 'pdufa', 'A decision', '2030-01-01', 'pending', NULL)")
    conn.commit(); conn.close()

    assert im.build(path)["catalysts_linked"] == 0


# --- a readout in children is not a readout in the adults ------------------
def _paediatric_db(tmp_path, with_paediatric_row=True):
    """The fixture's asset, an adult Crohn pair, optionally a paediatric one, and a
    catalyst on a study whose title says children."""
    path = str(tmp_path / "p.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'X', 'X Pharma')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name) VALUES (1, 1, 'A')")
    browse = json.dumps({"meshes": [{"id": "D003424", "term": "Crohn Disease"}]})
    conn.execute(
        "INSERT INTO trials (nct_id, asset_id, sponsor_company_id, conditions, mesh_terms,"
        " phase, overall_status, enrollment, first_posted, title)"
        " VALUES ('NCT9', 1, 1, ?, ?, 'Phase 3', 'Recruiting', 100, '2022-01-01', ?)",
        ('["Crohn Disease"]', browse,
         "A Study of A (LY1) in Pediatric Participants With Crohn's Disease"))
    if with_paediatric_row:
        conn.execute("INSERT INTO indications (id, name, mesh_id)"
                     " VALUES (99, 'Pediatric Crohn''s disease', 'C536215')")
    conn.execute(
        "INSERT INTO catalysts (company_id, asset_id, catalyst_type, title,"
        " expected_date, status, source_url)"
        " VALUES (1, 1, 'readout', 'A readout', '2030-01-01', 'pending', ?)",
        (_CTGOV + "NCT9",))
    conn.commit(); conn.close()
    return path


def test_a_paediatric_readout_goes_to_the_paediatric_row(tmp_path):
    """MeSH indexes a study of children with Crohn's disease as "Crohn Disease", the
    same descriptor the adult study gets, so Omvoh's paediatric readout landed on the
    adult row. That row is an approved indication, so the product's one genuine gate
    read as already decided."""
    path = _paediatric_db(tmp_path)
    conn = db.get_connection(path)
    # The paediatric pair is curated rather than MeSH-derived, so it is written after
    # the rebuild the way curated_additions puts it there.
    im.build(path)
    conn.execute("INSERT INTO asset_indications (asset_id, indication_id, phase, region)"
                 " VALUES (1, 99, 'Phase 3', 'US')")
    conn.commit(); conn.close()

    summary = im.attach_catalyst_indications(db.get_connection(path))
    conn = db.get_connection(path)
    im.attach_catalyst_indications(conn)
    conn.commit()
    row = conn.execute(
        "SELECT i.name FROM catalysts cat"
        "  JOIN asset_indications ai ON ai.id = cat.asset_indication_id"
        "  JOIN indications i ON i.id = ai.indication_id").fetchone()
    assert row and row["name"] == "Pediatric Crohn's disease"
    conn.close()


def test_a_paediatric_readout_with_no_paediatric_row_is_left_unlinked(tmp_path):
    """The adult row is not the fallback. A readout in children does not decide the
    indication the adults are already approved in, so unlinked and unpriced is the
    honest answer."""
    path = _paediatric_db(tmp_path, with_paediatric_row=False)
    summary = im.build(path)
    assert summary["catalysts_linked"] == 0
    assert summary["catalysts_paediatric_unmatched"] == 1

    conn = db.get_connection(path)
    assert conn.execute(
        "SELECT asset_indication_id FROM catalysts").fetchone()[0] is None
    conn.close()


def test_an_adult_study_is_unaffected(tmp_path):
    """Only an explicit paediatric title diverts a readout; everything else keeps the
    behaviour it had."""
    path = _paediatric_db(tmp_path, with_paediatric_row=False)
    conn = db.get_connection(path)
    conn.execute("UPDATE trials SET title = 'A Study of A in Adults' WHERE nct_id = 'NCT9'")
    conn.commit(); conn.close()

    summary = im.build(path)
    assert summary["catalysts_linked"] == 1
    assert summary["catalysts_paediatric_unmatched"] == 0


def test_the_paediatric_title_test():
    for title in ("A Study in Pediatric Participants", "Paediatric extension",
                  "A study in children", "Juvenile idiopathic arthritis study",
                  "Adolescents with Crohn's"):
        assert im._is_paediatric(title), title
    for title in ("A Study of A in Adults", "A long-term extension study", "", None):
        assert not im._is_paediatric(title), title


# --- a parent term beside its own child ----------------------------------------------

def _pair(asset_id, mesh_id, term, phase="Phase 3"):
    return ((asset_id, mesh_id), {"term": term, "phase": phase, "statuses": [],
                                  "enrollment": 100, "ncts": []})


def test_a_site_term_goes_when_the_asset_carries_its_own_child():
    """MeSH indexes a non-small-cell study under the disease and under the site, and the
    layer model then prices a lung expansion for a drug whose lung expansion is the row
    above. Twelve marketed assets carried this pair."""
    pairs = dict([_pair(1, "D008175", "Lung Neoplasms"),
                  _pair(1, "D002289", "Carcinoma, Non-Small-Cell Lung")])
    assert im.drop_parent_of_child(pairs) == 1
    assert [e["term"] for e in pairs.values()] == ["Carcinoma, Non-Small-Cell Lung"]


def test_a_site_term_alone_is_kept():
    """An asset studied in lung cancer and nothing more specific still has an indication."""
    pairs = dict([_pair(1, "D008175", "Lung Neoplasms")])
    assert im.drop_parent_of_child(pairs) == 0
    assert len(pairs) == 1


def test_breast_neoplasms_is_not_treated_as_a_parent():
    """An asset studied in triple-negative and in hormone-receptor positive disease
    carries both terms honestly, so suppressing the parent would delete the second
    indication rather than a duplicate."""
    pairs = dict([_pair(1, "D001943", "Breast Neoplasms"),
                  _pair(1, "D064726", "Triple Negative Breast Neoplasms")])
    assert im.drop_parent_of_child(pairs) == 0
    assert len(pairs) == 2


def test_one_asset_s_parent_does_not_drop_another_s():
    pairs = dict([_pair(1, "D008175", "Lung Neoplasms"),
                  _pair(2, "D008175", "Lung Neoplasms"),
                  _pair(1, "D002289", "Carcinoma, Non-Small-Cell Lung")])
    assert im.drop_parent_of_child(pairs) == 1
    assert (2, "D008175") in pairs, "the other asset has no child, so it keeps the site"


def test_a_family_term_goes_for_any_of_its_children():
    for child in ("Lymphoma, Large B-Cell, Diffuse",
                  "Leukemia, Lymphocytic, Chronic, B-Cell"):
        pairs = dict([_pair(1, "D008228", "Lymphoma, Non-Hodgkin"),
                      _pair(1, "X", child)])
        assert im.drop_parent_of_child(pairs) == 1, child


def _mixed_age_db(tmp_path, title):
    """One asset, an adult Crohn pair, and a catalyst on a study with the given title."""
    path = str(tmp_path / "m.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'X', 'X Pharma')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name) VALUES (1, 1, 'A')")
    browse = json.dumps({"meshes": [{"id": "D003424", "term": "Crohn Disease"}]})
    conn.execute(
        "INSERT INTO trials (nct_id, asset_id, sponsor_company_id, conditions, mesh_terms,"
        " phase, overall_status, enrollment, first_posted, title)"
        " VALUES ('NCT9', 1, 1, ?, ?, 'Phase 3', 'Recruiting', 100, '2022-01-01', ?)",
        ('["Crohn Disease"]', browse, title))
    conn.execute(
        "INSERT INTO catalysts (company_id, asset_id, catalyst_type, title,"
        " expected_date, status, source_url)"
        " VALUES (1, 1, 'readout', 'A readout', '2030-01-01', 'pending', ?)",
        (_CTGOV + "NCT9",))
    conn.commit(); conn.close()
    return path


def test_a_study_of_adults_and_adolescents_is_the_adult_readout(tmp_path):
    """Remibrutinib's, upadacitinib's and icotrokinra's pivotal studies name both ages
    in the title. They are adult label expansions that happen to enrol down to twelve,
    and diverting them to a paediatric row the book does not carry left 21 readouts
    unpriced. The paediatric rule exists to stop a readout in children deciding the
    adults' approved indication, not to discard a readout that decides both."""
    path = _mixed_age_db(
        tmp_path, "A Study of A in Adult and Adolescent Participants With Crohn's Disease")
    im.build(path)
    conn = db.get_connection(path)
    im.attach_catalyst_indications(conn)
    conn.commit()
    row = conn.execute(
        "SELECT i.name FROM catalysts cat"
        "  JOIN asset_indications ai ON ai.id = cat.asset_indication_id"
        "  JOIN indications i ON i.id = ai.indication_id").fetchone()
    assert row and row["name"] == "Crohn Disease"
    conn.close()


def test_a_study_of_children_alone_is_still_diverted(tmp_path):
    """The narrowing above must not reach a study that names no adults."""
    path = _mixed_age_db(
        tmp_path, "A Study of A in Pediatric Participants With Crohn's Disease")
    im.build(path)
    conn = db.get_connection(path)
    im.attach_catalyst_indications(conn)
    conn.commit()
    assert conn.execute("SELECT asset_indication_id FROM catalysts").fetchone()[0] is None
    conn.close()


def test_a_parent_descriptor_does_not_make_a_readout_ambiguous():
    """MeSH indexes an obesity study under "Obesity" and its own parent "Overweight",
    and both are real rows on the asset, so 38 readouts on the largest franchise in the
    book matched two indications and were left unlinked."""
    assert im._narrow({1: "overweight", 2: "obesity"}) == {2: "obesity"}
    assert im._narrow({1: "hidradenitis", 2: "hidradenitis suppurativa"}) == \
        {2: "hidradenitis suppurativa"}


def test_two_unrelated_diseases_stay_ambiguous():
    """Narrowing only drops a term that is the parent of another on the same study.
    Type 2 diabetes and obesity are two diseases and the readout is in one of them;
    choosing would be a guess about which, so it stays unlinked and says so."""
    names = {1: "diabetes mellitus, type 2", 2: "obesity"}
    assert im._narrow(names) == names


def test_a_study_the_registry_never_indexed_is_read_from_its_condition_text():
    """143 readouts carry conditions MeSH never classified. They are not obscure —
    "Metastatic Castration-Resistant Prostate Cancer" is one — so where MeSH yields
    nothing the condition text is read against the asset's own indication names."""
    cands = [(7, set(im.tokens("Prostatic Neoplasms"))),
             (8, set(im.tokens("Breast Neoplasms")))]
    got = im._by_condition_text('["Metastatic Castration-Resistant Prostate Cancer"]',
                                cands)
    assert got == {7}


def test_a_one_word_indication_does_not_swallow_a_readout():
    """"Pain" sits inside any phrase that mentions it, so an unguarded containment
    match sent three diabetic neuropathy readouts to a row called Pain."""
    cands = [(7, set(im.tokens("Pain")))]
    assert im._by_condition_text('["Diabetic Peripheral Neuropathic Pain"]', cands) == set()


def test_a_shared_qualifier_is_not_a_match():
    """The book's name must sit inside the condition whole, not merely overlap it, so
    two diseases sharing "metastatic" do not match each other."""
    cands = [(7, set(im.tokens("Colorectal Neoplasms")))]
    assert im._by_condition_text('["Metastatic Breast Cancer"]', cands) == set()
