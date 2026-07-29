"""The modality classifier, and the leaks it is built to refuse.

Most of these tests are negative. The classifier's failure mode is not missing a theme,
it is confidently attaching the wrong one: a trial of Darzalex against a CAR-T tagged
Darzalex as a CAR-T, which reads as a fact about the drug and is not one. So the cases
that matter are the ones asserting a theme is absent.
"""

import sqlite3

import pytest

import db
import themes


# --- what the keywords do, on text ---------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    # The conjugate stem is a separate word in an INN, which an attached pattern missed.
    ("Trastuzumab deruxtecan", "Antibody-drug conjugate"),
    ("Enfortumab vedotin-ejfv", "Antibody-drug conjugate"),
    ("Sacituzumab govitecan-hziy", "Antibody-drug conjugate"),
    ("Ado-trastuzumab emtansine", "Antibody-drug conjugate"),
    # How a label words the same thing.
    ("HER2-directed antibody and topoisomerase inhibitor conjugate",
     "Antibody-drug conjugate"),
    ("Ciltacabtagene autoleucel", "CAR-T"),
    ("Exagamglogene autotemcel", "Gene editing"),
    ("Onasemnogene abeparvovec", "Gene therapy"),
    ("Inclisiran", "RNA"),
    ("Nusinersen", "RNA"),
    ("Tirzepatide", "Incretin"),
    ("programmed death receptor-1 (PD-1)-blocking antibody", "Checkpoint"),
    ("bispecific CD19-directed CD3 T-cell engager", "T-cell engager"),
    ("lutetium Lu 177 vipivotide tetraxetan", "Radioligand"),
])
def test_classify_finds_the_modality(text, expected):
    assert expected in themes.classify(text)


@pytest.mark.parametrize("text", [
    "Abemaciclib, a CDK4/6 inhibitor",
    "OLUMIANT is a Janus kinase (JAK) inhibitor",
    "CD38-directed cytolytic antibody",          # Darzalex: an antibody, no theme
    "",
    None,
])
def test_classify_says_nothing_when_there_is_nothing_to_say(text):
    """A kinase inhibitor is not a modality story. Empty is the honest answer, and the
    alternative is filing every drug under something."""
    assert themes.classify(text) == {}


def test_parent_is_implied_not_repeated():
    found = themes.classify("Ciltacabtagene autoleucel")
    assert found["Cell therapy"]                 # a CAR-T is a cell therapy
    assert "CAR-T" in found


def test_leucel_alone_is_not_a_tcr_or_til():
    """-leucel means autologous leukocytes and is carried by CAR-Ts too. Reading it as
    TIL put every CAR-T in the TIL bucket."""
    found = themes.classify("Ciltacabtagene autoleucel")
    assert "TCR and TIL" not in found


def test_evidence_is_the_phrase_that_matched():
    """Every tag has to be answerable without rerunning the classifier."""
    assert themes.classify("Tirzepatide")["Incretin"].lower() == "tirzepatide"


# --- the label's class clause --------------------------------------------------------

def test_class_clause_stops_at_indicated():
    clause = themes.class_clause(
        "1 INDICATIONS AND USAGE ENHERTU is a HER2-directed antibody and topoisomerase "
        "inhibitor conjugate indicated for the treatment of adult patients with "
        "unresectable HER2-positive breast cancer who have received a prior anti-HER2 "
        "regimen.")
    assert "conjugate" in clause
    assert "breast cancer" not in clause


def test_class_clause_refuses_indication_prose():
    """Padcev's label makes no class claim and goes straight to the indication. Reading
    that clause would describe the disease and call it the drug."""
    assert themes.class_clause(
        "1 INDICATIONS AND USAGE PADCEV, in combination with pembrolizumab, is "
        "indicated for the treatment of adult patients with bladder cancer.") is None


def test_class_clause_none_when_absent():
    assert themes.class_clause("CARVYKTI is indicated for the treatment of adults") is None
    assert themes.class_clause("") is None


# --- what derive() reads, which is the part that leaked ------------------------------

@pytest.fixture()
def conn(tmp_path):
    path = str(tmp_path / "t.db")
    db.init(path)
    c = db.get_connection(path)
    c.execute("INSERT INTO companies (ticker, name) VALUES ('XYZ', 'Test Co')")
    company = c.execute("SELECT id FROM companies WHERE ticker='XYZ'").fetchone()[0]
    c.execute("INSERT INTO assets (owner_company_id, brand_name, generic_name,"
              " is_marketed) VALUES (?, 'Darzalex', 'Daratumumab', 1)", (company,))
    c.commit()
    yield c, company, path
    c.close()


def test_a_comparator_arm_does_not_tag_the_asset(conn):
    """The leak this design exists to stop. A study of daratumumab against a CAR-T
    lists both drugs as interventions; only one of them is daratumumab."""
    c, company, path = conn
    asset = c.execute("SELECT id FROM assets WHERE brand_name='Darzalex'").fetchone()[0]
    c.execute("INSERT INTO trials (nct_id, sponsor_company_id, asset_id, title)"
              " VALUES ('NCT1', ?, ?, 'Daratumumab versus CAR-T in myeloma')",
              (company, asset))
    for name in ("Daratumumab", "Ciltacabtagene autoleucel"):
        c.execute("INSERT INTO trial_interventions (nct_id, name, norm, kind)"
                  " VALUES ('NCT1', ?, ?, 'DRUG')", (name, name.lower()))
    c.commit()
    c.close()

    themes.derive(path)

    check = sqlite3.connect(path)
    tagged = [r[0] for r in check.execute(
        "SELECT theme FROM asset_themes WHERE asset_id = ?", (asset,))]
    check.close()
    assert tagged == [], f"daratumumab was tagged from another arm: {tagged}"


def test_an_intervention_naming_the_asset_is_read(conn):
    """The recall this buys: the registry often describes the drug more fully than the
    asset row does, and that description is about this drug."""
    c, company, path = conn
    c.execute("INSERT INTO assets (owner_company_id, internal_code, is_marketed)"
              " VALUES (?, 'DJI136', 0)", (company,))
    asset = c.execute("SELECT id FROM assets WHERE internal_code='DJI136'").fetchone()[0]
    c.execute("INSERT INTO trials (nct_id, sponsor_company_id, asset_id, title)"
              " VALUES ('NCT2', ?, ?, 'A study')", (company, asset))
    c.execute("INSERT INTO trial_interventions (nct_id, name, norm, kind)"
              " VALUES ('NCT2', 'DJI136 CAR-T cells', 'dji136 car t cells', 'DRUG')")
    c.commit()
    c.close()

    themes.derive(path)

    check = sqlite3.connect(path)
    tagged = {r[0] for r in check.execute(
        "SELECT theme FROM asset_themes WHERE asset_id = ?", (asset,))}
    check.close()
    assert "CAR-T" in tagged and "Cell therapy" in tagged


def test_derive_is_idempotent(conn):
    """It rebuilds, so running twice must not double the rows or keep a stale tag."""
    c, company, path = conn
    c.close()
    first = themes.derive(path)
    second = themes.derive(path)
    assert first == second

    check = sqlite3.connect(path)
    rows = check.execute("SELECT COUNT(*) FROM asset_themes").fetchone()[0]
    check.close()
    assert rows == second["tagged"]


# --- what a company says it does, read from its own filing ---------------------------

def test_a_competitor_paragraph_is_not_this_company_s_platform():
    """The leak this axis is built to refuse.

    A risk factors section has to describe the competition, so Beam's filing names
    CAR-T, CRISPR, gene therapy and cell therapy. Counting terms tags every company with
    every modality in its sector, which is the comparator-arm problem in a longer
    document. Only first-person sentences count.
    """
    text = ("Our competitors are developing base editing therapies. Other companies "
            "have advanced CAR-T products into registrational trials.")
    assert themes.self_descriptions(text) == []


def test_a_first_person_platform_sentence_is_read():
    windows = themes.self_descriptions(
        "We have assembled a platform that includes a suite of gene editing and "
        "delivery technologies.")
    assert windows
    assert "Gene editing" in themes.classify(windows[0])


def test_a_denied_platform_is_not_a_platform():
    """Atara. Its filing says the T-cell platform "does not require TCR or HLA gene
    editing", and reading that tagged Atara as a gene editing company on the strength of
    a sentence denying it."""
    assert themes.self_descriptions(
        "Our 1XX CAR co-stimulatory domain and EBV T-cell platform does not require "
        "TCR or HLA gene editing.") == []


def test_a_patent_or_licence_sentence_is_not_a_platform():
    """First person, and still about someone else's technology."""
    assert themes.self_descriptions(
        "With respect to the KYV-201 product candidate, we own a patent family "
        "directed to allogeneic CD19 CAR T cells.") == []


def test_a_window_stops_at_the_sentence_end():
    """A window that runs past the full stop reaches into the next sentence, which is
    where the competitive landscape lives."""
    windows = themes.self_descriptions(
        "Our platform is small molecule. Competitors are developing CRISPR therapies.")
    assert all("CRISPR" not in w for w in windows)


def test_derive_companies_is_idempotent(tmp_path):
    import db

    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('EDT', 'Editor Bio')")
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    conn.execute(
        "INSERT INTO filing_sections (company_id, accession, form_type, filed_date,"
        "  section, char_count, text) VALUES (?, '0001', '10-K', '2026-02-01',"
        "  'risk_factors', 60, ?)",
        (cid, "We are a pioneering gene editing company developing therapies."))
    conn.commit()
    conn.close()

    first = themes.derive_companies(path)
    second = themes.derive_companies(path)
    assert first == second

    check = db.get_connection(path)
    tagged = {r[0] for r in check.execute("SELECT theme FROM company_themes")}
    rows = check.execute("SELECT COUNT(*) FROM company_themes").fetchone()[0]
    check.close()
    assert "Gene editing" in tagged
    assert rows == second["tagged"]


def test_company_evidence_is_the_sentence_not_the_keyword(tmp_path):
    """A reader has to be able to see whose platform the sentence described."""
    import db

    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('EDT', 'Editor Bio')")
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    conn.execute(
        "INSERT INTO filing_sections (company_id, accession, form_type, filed_date,"
        "  section, char_count, text) VALUES (?, '0001', '10-K', '2026-02-01',"
        "  'risk_factors', 60, ?)",
        (cid, "Our proprietary base editing platform is the core of our pipeline."))
    conn.commit()
    conn.close()

    themes.derive_companies(path)
    check = db.get_connection(path)
    evidence = check.execute(
        "SELECT evidence FROM company_themes WHERE theme = 'Gene editing'").fetchone()[0]
    check.close()
    assert "base editing" in evidence.lower()
    assert len(evidence.split()) > 3, "evidence should be the phrase, not the keyword"
