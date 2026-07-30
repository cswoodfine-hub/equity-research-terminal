"""Programmes read out of a filing, and the four things that must never become one.

The extraction tests run against Dyne's own sentences, taken verbatim from the 10-Q filed
2026-07-29, because a parser written against invented prose passes on invented prose.
"""

import db
import pipeline_filing as pf


# Verbatim from Dyne's 10-Q, item 2.
DYNE = """
We are developing DYNE-302 for the treatment of FSHD.
DYNE-302 is designed to deliver functional improvement in individuals living with FSHD by
reducing aberrant DUX4 expression.
In June 2024 and June 2025, we announced preclinical data for DYNE-302, our product
candidate for FSHD, that demonstrated robust and durable DUX4 suppression.
In July 2026, we announced that we received clearance from the FDA for our investigational
new drug, or IND, application to initiate a Phase 1 clinical trial for DYNE-302 in FSHD.
We plan to evaluate DYNE-302 in a Phase 1 randomized, placebo-controlled, double-blind,
multiple ascending dose clinical trial in ambulatory adult individuals with FSHD.
Additionally, we are advancing four development candidates (DYNE-253, DYNE-245, DYNE-244
and DYNE-255) for the treatment of DMD amenable to skipping of exons 53, 45, 44, 55,
respectively, into IND-enabling studies.
We are developing DYNE-401 for the treatment of Pompe disease.
We engineered DYNE-401 by leveraging the FORCE platform to deliver GAA.
"""


# What the risk factors of the same filing say. The MD&A names the four DMD candidates
# once each, and a code needs a second sighting before it counts as a programme.
DYNE_RISKS = ("Risks to DYNE-253, DYNE-245, DYNE-244, DYNE-255, DYNE-302 and DYNE-401 "
              "include delay, and the FORCE platform may not work.")


def _by_code(text, name="Dyne Therapeutics, Inc.", corroboration=DYNE_RISKS):
    return {row["code"]: row for row in pf.programmes(text, name, corroboration)}


def test_an_ind_clearance_is_read_as_a_stage():
    """The fact the user was missing: DYNE-302 has FDA clearance and no registered
    study, so no other route into the model can see it."""
    row = _by_code(DYNE)["DYNE-302"]
    assert row["stage"] == "IND cleared"
    assert row["indication"] == "FSHD"


def test_a_planned_phase_is_never_recorded_as_a_phase():
    """"We plan to evaluate DYNE-302 in a Phase 1" is a plan. Recording it as Phase 1
    would be inventing a study, and a phase is what a registered study means."""
    assert _by_code(DYNE)["DYNE-302"]["stage"] not in ("Phase 1", "Phase 1/2")
    assert all(row["stage"] in pf.STAGES or row["stage"] is None
               for row in pf.programmes(DYNE))


def test_the_furthest_stage_wins():
    """DYNE-302 is called preclinical in one sentence and IND-cleared in another. The
    filing is describing the same programme at two points in time."""
    assert _by_code(DYNE)["DYNE-302"]["stage"] == "IND cleared"


def test_four_candidates_in_one_sentence_are_four_programmes():
    codes = _by_code(DYNE)
    assert {"DYNE-244", "DYNE-245", "DYNE-253", "DYNE-255"} <= set(codes)
    assert codes["DYNE-255"]["stage"] == "IND-enabling"


def test_a_subpopulation_is_cut_off_the_indication():
    """One sentence, four codes, one disease and four different exons. "DMD amenable to
    skipping of exons 53" would be right for one of them and wrong for three."""
    assert _by_code(DYNE)["DYNE-244"]["indication"] == "DMD"


def test_the_evidence_sentence_is_kept():
    assert "clearance from the FDA" in _by_code(DYNE)["DYNE-302"]["evidence"]


def test_another_company_s_compound_is_not_a_programme():
    """Merck's discussion names TERN-701 and Solid's names Entrada's compound. A sentence
    naming another party is not evidence of ownership, whatever else it says."""
    text = ("We licensed rights from Terns Pharmaceuticals, Inc. to TERN-701 for the "
            "treatment of chronic myeloid leukemia. "
            "TERN-701 is being developed for CML. "
            "We are developing MRK-101 for the treatment of asthma. "
            "We have moved MRK-101 into IND-enabling studies.")
    codes = _by_code(text, "Merck & Co Inc")
    assert "TERN-701" not in codes
    assert "MRK-101" in codes


def test_a_trial_name_is_not_a_compound():
    """STELLAR-303 is a study. It has the shape of a development code and is introduced
    once as a trial, so one sighting settles it for the whole document."""
    text = ("Our first such trial, STELLAR-303, was initiated in June 2022. "
            "Beyond STELLAR-303 and STELLAR-304, we intend to start more. "
            "We are developing XB-628 for the treatment of lung cancer. "
            "We have moved XB-628 into IND-enabling studies.")
    codes = _by_code(text, "Exelixis, Inc.")
    assert "STELLAR-303" not in codes
    assert "STELLAR-304" not in codes
    assert "XB-628" in codes


def test_a_capsid_is_not_a_compound():
    text = ("In March of 2026, we began using the mark POLARIS-101 to represent our "
            "AAV capsid. We license POLARIS-101 broadly to institutions. "
            "We are developing SGT-601, our preclinical candidate, for the treatment "
            "of dilated cardiomyopathy. We expect SGT-601 to enter the clinic.")
    codes = _by_code(text, "Solid Biosciences Inc.")
    assert "POLARIS-101" not in codes
    assert codes["SGT-601"]["stage"] == "Preclinical"


def test_a_prefix_that_is_an_ordinary_word_is_not_a_family():
    """Wave's FORWARD-53 is a trial, and the same filing writes "forward-looking"."""
    text = ("These are forward-looking statements. "
            "We expanded FORWARD-53 to include additional participants. "
            "We are developing WVE-008 for the treatment of AATD. "
            "We announced preclinical data for WVE-008.")
    codes = _by_code(text, "Wave Life Sciences Ltd.")
    assert "FORWARD-53" not in codes
    assert "WVE-008" in codes


def test_a_date_is_not_a_code():
    text = ("We expect data in mid-2027. We expect a filing in mid-2027. "
            "We are developing ABC-101 for the treatment of anaemia. "
            "We announced preclinical data for ABC-101.")
    assert set(_by_code(text)) == {"ABC-101"}


def test_a_single_mention_needs_corroboration():
    """One appearance could be a typo. Dyne names its four DMD candidates once each in
    the MD&A and again in the risk factors, which is what makes them real."""
    text = "We are developing SOLO-101 for the treatment of anaemia."
    assert "SOLO-101" not in _by_code(text)
    assert "SOLO-101" in _by_code(text, corroboration="risks to SOLO-101 include delay")


def test_a_stage_word_alone_is_not_a_programme():
    assert pf.programmes("Our preclinical work continues.") == []


# --- writing it down -------------------------------------------------------------------

def _company(tmp_path, text, ticker="DYN"):
    path = str(tmp_path / "p.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES (?, 'Dyne Therapeutics')",
                 (ticker,))
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    conn.execute(
        "INSERT INTO filing_sections (company_id, accession, form_type, filed_date,"
        "  section, char_count, text) VALUES (?, '0001-26-1', '10-Q', '2026-07-29',"
        "  'mdna', ?, ?)", (cid, len(text), text))
    conn.execute(
        "INSERT INTO filing_sections (company_id, accession, form_type, filed_date,"
        "  section, char_count, text) VALUES (?, '0001-26-1', '10-Q', '2026-07-29',"
        "  'risk_factors', ?, ?)", (cid, len(DYNE_RISKS), DYNE_RISKS))
    conn.commit()
    return path, conn, cid


def test_build_writes_an_asset_and_its_provenance(tmp_path):
    path, conn, cid = _company(tmp_path, DYNE)
    conn.close()

    assert pf.build(path)["created"] == 6

    conn = db.get_connection(path)
    row = conn.execute(
        "SELECT p.code, p.stage, p.indication, p.form_type, p.filed_date, a.generic_name,"
        "       a.internal_code, a.is_marketed, a.notes"
        "  FROM filing_programmes p JOIN assets a ON a.id = p.asset_id"
        " WHERE p.code = 'DYNE-302'").fetchone()
    conn.close()
    assert row["stage"] == "IND cleared" and row["indication"] == "FSHD"
    assert row["internal_code"] == "DYNE-302" and row["is_marketed"] == 0
    assert "10-Q filed 2026-07-29" in row["notes"]


def test_build_is_idempotent(tmp_path):
    path, conn, cid = _company(tmp_path, DYNE)
    conn.close()
    pf.build(path)
    again = pf.build(path)
    assert again["created"] == 0 and again["updated"] == 6

    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 6
    conn.close()


def test_a_programme_the_registry_already_has_is_skipped(tmp_path):
    """The trial mapper owns anything with a study, and it has a phase. This must only
    ever add what the registry does not have."""
    path, conn, cid = _company(tmp_path, DYNE)
    conn.execute("INSERT INTO assets (owner_company_id, generic_name, is_marketed)"
                 " VALUES (?, 'zeleciment basivarsen (DYNE-302)', 0)", (cid,))
    conn.commit()
    conn.close()

    pf.build(path)
    conn = db.get_connection(path)
    codes = {r["code"] for r in conn.execute("SELECT code FROM filing_programmes")}
    conn.close()
    assert "DYNE-302" not in codes


def test_prune_drops_a_programme_that_has_since_acquired_a_trial(tmp_path):
    path, conn, cid = _company(tmp_path, DYNE)
    conn.close()
    pf.build(path)

    conn = db.get_connection(path)
    asset_id = conn.execute("SELECT asset_id FROM filing_programmes"
                            "  WHERE code = 'DYNE-302'").fetchone()[0]
    conn.execute("INSERT INTO trials (nct_id, asset_id, title, phase)"
                 " VALUES ('NCT9', ?, 'A study', 'Phase 1')", (asset_id,))
    conn.commit()
    conn.close()

    assert pf.prune(path)["dropped"] == 1
    conn = db.get_connection(path)
    codes = {r["code"] for r in conn.execute("SELECT code FROM filing_programmes")}
    conn.close()
    assert "DYNE-302" not in codes


def test_no_filing_text_is_no_programmes(tmp_path):
    path = str(tmp_path / "empty.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('X', 'X Inc')")
    conn.commit()
    conn.close()
    assert pf.build(path) == {"created": 0, "updated": 0}
