"""Discovery's shared rules: the scorer against scikit-learn's own numbers, the lab
matcher, and the seed loader."""

import json
import pathlib

import pytest

import db
import discovery as D
import seed

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "discovery"


@pytest.fixture(scope="module")
def scorer():
    made = D.scorer()
    if made is None:
        pytest.skip("no model file")
    return made


def test_the_numpy_scorer_gives_scikit_learns_scores(scorer):
    """The fixture holds what scikit-learn scored each text at when the model file was
    written (export_models.py). The app's arithmetic has to land on the same numbers."""
    parity = json.loads((FIXTURES / "parity.json").read_text())
    assert parity["version"] == scorer.version, "model file and fixture were not exported together"
    assert len(parity["cases"]) >= 20
    for case in parity["cases"]:
        got = scorer.score(case["title"], case["abstract"], case["preprint"])
        assert got["feas"]["score"] == pytest.approx(case["feas"], abs=1e-9), case["title"]
        assert got["comm"]["score"] == pytest.approx(case["comm"], abs=1e-9), case["title"]


def test_the_fixture_covers_the_awkward_texts():
    cases = json.loads((FIXTURES / "parity.json").read_text())["cases"]
    assert any(not c["abstract"] for c in cases)
    assert any("<" in c["title"] + c["abstract"] for c in cases)
    assert any(c["preprint"] for c in cases)
    assert any(any(ord(ch) > 127 for ch in c["title"]) for c in cases)


def test_a_score_reads_as_a_rank_and_says_what_raised_it(scorer):
    got = scorer.score(
        "In vivo base editing in non-human primates",
        "Lipid nanoparticles delivered a base editor to the liver of cynomolgus macaques."
        " Editing was dose-dependent and durable, with no off-target editing detected.")
    for name in ("feas", "comm"):
        assert 0.0 <= got[name]["pct"] <= 1.0
        assert set(got[name]["reasons"]) == {"flags", "phrases"}
    assert D.top_share(0.97) == "top 3%"
    assert D.top_share(0.9999) == "top 1%"
    assert D.top_share(None) is None


def test_no_model_file_means_no_scorer(tmp_path):
    assert D.scorer(tmp_path / "missing.json.gz") is None


def test_what_a_paper_is_filed_under():
    text = D.text_of("AAV9 gene therapy in mice",
                     "Biodistribution was measured in non-human primates.")
    found = D.flags(text)
    assert found["mouse"] and found["primate"] and not found["patients"]
    assert D.furthest(found) == "primate"
    assert D.furthest(D.flags("a method paper")) is None
    assert "AAV" in " ".join(D.modalities(text) + D.areas(text))


def test_a_company_address_is_told_from_a_university():
    assert D.company_among(["Beam Therapeutics, Cambridge, MA, USA"])
    assert not D.company_among(["Institute of Biotechnology, University of Cambridge"])
    assert not D.company_among([])


def test_the_institution_is_read_out_of_an_address():
    assert D.institution_of("Department of Genetics, Stanford University, Stanford, CA"
                            ) == "Stanford University"
    assert D.institution_of("Beam Therapeutics, Cambridge, MA, USA.") == "Beam Therapeutics"
    assert D.institution_of("12 High Street, Leeds") is None
    assert D.institution_of(None) is None


def test_an_initial_is_not_a_name():
    assert D.name_key("Carl H", "June") == "carl|june"
    assert D.name_key("C", "June") is None
    assert D.name_key("José", "Muñoz") == "jose|munoz"


def _labs():
    return D.LabIndex([
        {"id": "A1", "name": "Jane Doe", "name_keys": '["jane|doe"]',
         "institutions": '["Stanford University"]', "modalities": "[]"},
        {"id": "A2", "name": "Jane Doe", "name_keys": '["jane|doe"]',
         "institutions": '["University of Oxford"]', "modalities": "[]"},
        {"id": "A3", "name": "Sam Roe", "name_keys": '["sam|roe"]',
         "institutions": '["Broad Institute"]', "modalities": "[]"}])


def test_a_lab_is_matched_by_name_and_institution():
    labs = _labs()
    assert labs.match("Jane A", "Doe", ["Dept of Genetics, Stanford University, CA"]) == (
        "A1", D.LabIndex.BY_INSTITUTION)
    assert labs.match("Sam", "Roe", ["Broad Institute of MIT and Harvard, Cambridge"]) == (
        "A3", D.LabIndex.BY_INSTITUTION)


def test_a_shared_name_with_no_address_is_left_unmatched():
    labs = _labs()
    assert labs.match("Jane", "Doe", []) == (None, None)
    assert labs.match("Jane", "Doe", ["Massachusetts Institute of Technology"]) == (None, None)


def test_a_name_at_another_institution_is_not_the_lab():
    assert _labs().match("Sam", "Roe", ["University of Tokyo"]) == (None, None)


def test_a_preprint_with_no_address_matches_only_a_name_held_by_one_lab():
    assert _labs().match("Sam", "Roe", []) == ("A3", D.LabIndex.BY_NAME)
    assert _labs().match("S", "Roe", []) == (None, None)


def _seed_file(tmp_path, rank=7):
    path = tmp_path / "labs.ndjson"
    path.write_text(json.dumps({
        "id": "A9", "name": "Test Head", "name_keys": ["test|head"],
        "institutions": ["Test University"], "country": "GB", "rank": rank, "pct": 0.99,
        "ranked_as_of": "2026-11-14", "modalities": ["AAV"], "papers": 3,
        "furthest_stage": "mouse", "company_coauthor": False}) + "\n")
    return path


def test_the_lab_seed_is_insert_only(tmp_path):
    path = db.init(tmp_path / "d.db")
    conn = db.get_connection(path)
    try:
        assert D.load_labs(conn, _seed_file(tmp_path)) == 1
        assert D.load_labs(conn, _seed_file(tmp_path, rank=1)) == 0
        row = conn.execute("SELECT * FROM discovery_labs").fetchone()
        assert (row["rank"], row["furthest_stage"], row["company_coauthor"]) == (7, "mouse", 0)
        assert D.lab_index(conn).match("Test", "Head", ["Test University, Leeds"])[0] == "A9"
    finally:
        conn.close()


def test_the_committed_seed_loads_and_carries_no_company_record(tmp_path):
    if not D.LABS_SEED.exists():
        pytest.skip("no lab seed")
    path = db.init(tmp_path / "d.db")
    added = seed.load_discovery_labs(path)
    assert added > 1000 and seed.load_discovery_labs(path) == 0
    first = json.loads(D.LABS_SEED.read_text().splitlines()[0])
    assert set(first) == {"id", "name", "name_keys", "institutions", "country", "rank", "pct",
                          "ranked_as_of", "modalities", "papers", "furthest_stage",
                          "company_coauthor"}


def test_an_alert_about_a_paper_cannot_be_written_twice(tmp_path):
    import sqlite3

    path = db.init(tmp_path / "d.db")
    conn = db.get_connection(path)
    try:
        insert = ("INSERT INTO changes (entity_type, entity_key, field, new_value,"
                  " change_type, significance) VALUES (?, 'MED:1', 'discovery', 'x',"
                  " 'discovery_paper_top', 'medium')")
        conn.execute(insert, ("paper",))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, ("paper",))
        conn.execute(insert, ("company",))
        conn.execute(insert, ("company",))          # every other entity is unaffected
    finally:
        conn.close()
