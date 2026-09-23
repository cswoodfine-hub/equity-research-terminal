"""An accepted application, joined to the asset and the disease it is actually for.

The guards matter more than the join. A filed stage replaces the two-gate Phase 3 chain
with the approval gate alone, which in oncology is 0.439 becoming 0.920, so every test
below is about refusing rather than finding.
"""

import datetime as dt

import pytest

import db
import applications as R

TODAY = dt.date(2026, 9, 23)


def _seed(tmp_path):
    path = str(tmp_path / "reg.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name, reporting_currency)"
                 " VALUES (1, 'VRTX', 'Vertex', 'USD')")
    conn.execute("INSERT INTO indications (id, name) VALUES (10, 'Myasthenia Gravis'),"
                 " (11, 'Glomerulonephritis, IGA'), (12, 'Colorectal Neoplasms')")
    conn.commit()
    return conn


def _asset(conn, asset_id, generic, marketed=0, brand=None, code=None):
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, brand_name,"
                 " internal_code, is_marketed) VALUES (?, 1, ?, ?, ?, ?)",
                 (asset_id, generic, brand, code, marketed))
    conn.commit()


def _indication(conn, ai_id, asset_id, indication_id, phase="Phase 3", lead=1):
    conn.execute("INSERT INTO asset_indications (id, asset_id, indication_id, phase,"
                 " is_lead, region) VALUES (?, ?, ?, ?, ?, 'US')",
                 (ai_id, asset_id, indication_id, phase, lead))
    conn.commit()


def _catalyst(conn, cat_id, title, date, kind="PDUFA", description="FDA accepted it."):
    conn.execute("INSERT INTO catalysts (id, company_id, catalyst_type, expected_date,"
                 " title, description, is_curated, source_url, status) VALUES"
                 " (?, 1, ?, ?, ?, ?, 0, 'https://sec.gov/x', 'pending')",
                 (cat_id, kind, date, title, description))
    conn.commit()


def test_the_title_the_extractor_writes_splits_back_into_product_and_disease():
    """pdufa.py writes "<product> PDUFA, <indication>". This is the only place the
    disease is recorded, so reading it back is what makes the indication guard possible."""
    assert R.parse_title("zanzalintinib PDUFA, treatment of patients with metastatic "
                         "colorectal cancer") == (
        "zanzalintinib", "treatment of patients with metastatic colorectal cancer")
    assert R.parse_title("Deramiocel PDUFA, Duchenne muscular dystrophy") == (
        "Deramiocel", "Duchenne muscular dystrophy")
    assert R.parse_title("Jemperli PDUFA") == ("Jemperli", None)
    assert R.parse_title("") == (None, None)


def test_a_name_reaching_two_assets_is_refused_rather_than_assigned_to_the_first(tmp_path):
    """The failure this prevents put another product's decision date on an asset that
    had just dosed its first Phase 3 subject."""
    conn = _seed(tmp_path)
    _asset(conn, 1, "Zanzalintinib")
    _asset(conn, 2, "Zanzalintinib Malate")
    got, why = R.match_asset(conn, 1, "Zanzalintinib")
    conn.close()
    assert got is None and "ambiguous" in why


def test_a_name_that_matches_nothing_is_refused_and_says_so(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Povetacicept")
    got, why = R.match_asset(conn, 1, 'lonvoguran ziclumeran ("lonvo-z")')
    short, _ = R.match_asset(conn, 1, "abc")
    conn.close()
    assert got is None and "no asset of this company" in why
    assert short is None


def test_an_asset_is_matched_on_generic_brand_or_code(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Zeleciment Rostudirsen (DYNE-251)", brand=None, code="DYNE-251")
    got, _ = R.match_asset(conn, 1, "zeleciment rostudirsen (z-rostudirsen, also known "
                                    "as DYNE-251)")
    conn.close()
    assert got == 1


def test_an_already_marketed_molecule_is_a_label_expansion_not_a_first_approval(tmp_path):
    """Jemperli and zilganersen are both approved. Their acceptances are supplements and
    say nothing about an unapproved asset."""
    conn = _seed(tmp_path)
    _asset(conn, 1, "Dostarlimab-Gxly", marketed=1, brand="Jemperli")
    supplemental, why = R.is_supplemental(conn, 1, "Jemperli PDUFA, rectal cancer", "")
    conn.close()
    assert supplemental and "already marketed" in why


def test_the_same_molecule_held_as_a_separate_marketed_row_is_caught_by_the_join(tmp_path):
    """The filers that matter announce a supplemental application without ever writing
    the word, so the test has to be a join rather than a regular expression."""
    conn = _seed(tmp_path)
    _asset(conn, 1, "Trastuzumab Deruxtecan", marketed=0)
    _asset(conn, 2, "Trastuzumab Deruxtecan", marketed=1, brand="Enhertu")
    supplemental, why = R.is_supplemental(conn, 1, "Enhertu granted Priority Review", "")
    conn.close()
    assert supplemental and "same molecule already marketed" in why


def test_the_word_supplemental_is_caught_when_the_text_does_say_it(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Clesrovimab")
    got, why = R.is_supplemental(conn, 1, "Clesrovimab PDUFA, RSV", "FDA accepts sBLA.")
    conn.close()
    assert got and "supplemental" in why


def test_a_first_approval_for_an_unmarketed_molecule_passes(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Zanzalintinib")
    got, why = R.is_supplemental(conn, 1, "Zanzalintinib PDUFA, colorectal", "accepted")
    conn.close()
    assert got is False and "no marketed row" in why


def test_the_indication_is_matched_to_one_the_asset_actually_carries(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Zanzalintinib")
    _indication(conn, 100, 1, 12)
    got, why = R.match_indication(conn, 1, "treatment of patients with metastatic "
                                           "colorectal cancer")
    conn.close()
    assert got == 100 and "Colorectal Neoplasms" in why


def test_an_indication_the_asset_does_not_carry_matches_nothing(tmp_path):
    """The live case. Povetacicept's accepted application is for IgA nephropathy and the
    only indication row it carries is myasthenia gravis, so nothing may lift."""
    conn = _seed(tmp_path)
    _asset(conn, 1, "Povetacicept")
    _indication(conn, 100, 1, 10, phase="Phase 2")
    got, why = R.match_indication(conn, 1, "IgA Nephropathy")
    none, _ = R.match_indication(conn, 1, None)
    conn.close()
    assert got is None and "no indication matching" in why
    assert none is None


def test_resolve_attaches_what_it_can_and_reports_what_it_refuses(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Zanzalintinib")
    _indication(conn, 100, 1, 12)
    _catalyst(conn, 500, "zanzalintinib PDUFA, metastatic colorectal cancer", "2027-03-03")
    _catalyst(conn, 501, 'lonvoguran ziclumeran ("lonvo-z") PDUFA, angioedema', "2027-03-10")
    got = R.resolve(conn, today=TODAY)
    rows = {r["id"]: (r["asset_id"], r["asset_indication_id"]) for r in
            conn.execute("SELECT id, asset_id, asset_indication_id FROM catalysts")}
    conn.close()
    assert got["seen"] == 2 and got["asset"] == 1 and got["indication"] == 1
    assert rows[500] == (1, 100)
    assert rows[501] == (None, None)
    assert len(got["refused"]) == 1


def test_resolve_is_idempotent_and_leaves_a_resolved_row_alone(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Zanzalintinib")
    _indication(conn, 100, 1, 12)
    _catalyst(conn, 500, "zanzalintinib PDUFA, metastatic colorectal cancer", "2027-03-03")
    R.resolve(conn, today=TODAY)
    again = R.resolve(conn, today=TODAY)
    conn.close()
    assert again["seen"] == 0 and again["asset"] == 0


def test_a_filing_lifts_only_when_every_guard_passes(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Zanzalintinib")
    _indication(conn, 100, 1, 12)
    _catalyst(conn, 500, "zanzalintinib PDUFA, metastatic colorectal cancer", "2027-03-03")
    R.resolve(conn, today=TODAY)
    got = R.filed_for(conn, 1, 100, today=TODAY)
    conn.close()
    assert got["lifts"] is True
    assert got["date"] == "2027-03-03" and got["quote"] == "FDA accepted it."


def test_a_filing_for_another_disease_is_reported_and_lifts_nothing(tmp_path):
    """Povetacicept. The filing exists, the reader should see it, and the number stays."""
    conn = _seed(tmp_path)
    _asset(conn, 1, "Povetacicept")
    _indication(conn, 100, 1, 10, phase="Phase 2")
    _catalyst(conn, 500, "Povetacicept PDUFA, IgA Nephropathy", "2026-11-30")
    R.resolve(conn, today=TODAY)
    got = R.filed_for(conn, 1, 100, today=TODAY)
    conn.close()
    assert got["lifts"] is False
    assert "not an indication this asset carries" in got["why"]
    assert got["date"] == "2026-11-30"


def test_a_filing_for_an_indication_other_than_the_one_modelled_lifts_nothing(tmp_path):
    """Fifty of the sixty modelled assets carry more than one indication, several
    spanning Phase 1 to Phase 3, so an asset-level lift would price a Phase 1 line at the
    approval gate on another disease's evidence."""
    conn = _seed(tmp_path)
    _asset(conn, 1, "Zanzalintinib")
    _indication(conn, 100, 1, 12, phase="Phase 3", lead=1)
    _indication(conn, 101, 1, 10, phase="Phase 1", lead=0)
    _catalyst(conn, 500, "zanzalintinib PDUFA, metastatic colorectal cancer", "2027-03-03")
    R.resolve(conn, today=TODAY)
    lifts = R.filed_for(conn, 1, 100, today=TODAY)
    other = R.filed_for(conn, 1, 101, today=TODAY)
    conn.close()
    assert lifts["lifts"] is True
    assert other["lifts"] is False
    assert "not the indication this forecast is built on" in other["why"]


def test_a_passed_decision_date_lifts_nothing(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Zanzalintinib")
    _indication(conn, 100, 1, 12)
    _catalyst(conn, 500, "zanzalintinib PDUFA, colorectal cancer", "2026-01-05")
    R.resolve(conn, today=TODAY)
    got = R.filed_for(conn, 1, 100, today=TODAY)
    conn.close()
    assert got["lifts"] is False and "has passed" in got["why"]


def test_an_asset_with_no_filing_returns_none(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Zanzalintinib")
    got = R.filed_for(conn, 1, None, today=TODAY)
    conn.close()
    assert got is None


def test_an_advisory_committee_row_is_not_a_filing(tmp_path):
    """An AdCom is scheduled during a review and says nothing the acceptance did not."""
    conn = _seed(tmp_path)
    _asset(conn, 1, "Zanzalintinib")
    _indication(conn, 100, 1, 12)
    _catalyst(conn, 500, "Zanzalintinib AdCom, colorectal", "2027-01-05", kind="AdCom")
    got = R.resolve(conn, today=TODAY)
    filed = R.filed_for(conn, 1, 100, today=TODAY)
    conn.close()
    assert got["seen"] == 0 and filed is None


def test_the_lead_line_wins_when_the_asset_carries_the_disease_twice(tmp_path):
    """Bepirovirsen carries "Hepatitis B" as its lead line and "Hepatitis B, Chronic"
    beside it. Matching a chronic hepatitis B filing to the more specific row and then
    refusing it for not being the lead would be a refusal on a technicality."""
    conn = _seed(tmp_path)
    conn.execute("INSERT INTO indications (id, name) VALUES (20, 'Hepatitis B'),"
                 " (21, 'Hepatitis B, Chronic')")
    _asset(conn, 1, "Bepirovirsen")
    _indication(conn, 100, 1, 20, phase="Phase 2", lead=1)
    _indication(conn, 101, 1, 21, phase="Phase 2", lead=0)
    got, why = R.match_indication(conn, 1, "treatment of adults with chronic hepatitis B")
    conn.close()
    assert got == 100 and "the lead line" in why


def test_generic_clinical_words_cannot_manufacture_a_match(tmp_path):
    """"Treatment of patients with metastatic colorectal cancer" and the same phrase
    about gastric cancer share five long words. Without the stop list an overlap count
    matches almost any oncology filing to almost any oncology line."""
    conn = _seed(tmp_path)
    conn.execute("INSERT INTO indications (id, name) VALUES (30, 'Stomach Neoplasms')")
    _asset(conn, 1, "Zanzalintinib")
    _indication(conn, 100, 1, 30)
    got, why = R.match_indication(
        conn, 1, "treatment of patients with metastatic colorectal cancer")
    conn.close()
    assert got is None and "no indication matching" in why


def test_the_stop_list_does_not_swallow_a_real_disease_word():
    assert "colorectal" in R._words("metastatic colorectal cancer")
    assert "hepatitis" in R._words("chronic hepatitis B")
    assert R._words("treatment of adult patients with severe disease") == set()
