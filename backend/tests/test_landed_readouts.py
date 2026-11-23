"""A posted readout is tied to its study and recorded, or held and said why.

The four cases the proposals block held on 2026-11-22 are the regression: 17 proposals
from four headlines, each matched by the asset's name, none deciding the gate it was
shown against. They are rebuilt here from the headlines and the book rows as saved in
``fixtures/landed_readouts/four_cases.json``; the registry's acronyms are its own answer,
saved as ``ctgov_acronyms.json``.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import pathlib

import pytest

import announced_readouts
import catalyst_outcomes as CO
import db
import landed_readouts as L

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "landed_readouts"
TODAY = dt.date(2026, 11, 22)
NONE = "/nonexistent/file.csv"


def _book(tmp_path, cases=None):
    path = str(tmp_path / "book.db")
    db.init(path)
    conn = db.get_connection(path)
    f = cases or json.loads((FIX / "four_cases.json").read_text())
    conn.executemany("INSERT INTO companies (id, ticker, name) VALUES (?, ?, ?)", f["companies"])
    conn.executemany("INSERT INTO assets (id, owner_company_id, generic_name, brand_name,"
                     " internal_code, is_marketed) VALUES (?, ?, ?, ?, ?, ?)", f["assets"])
    conn.executemany("INSERT INTO trials (nct_id, asset_id, sponsor_company_id, phase,"
                     " overall_status, primary_completion_date, title)"
                     " VALUES (?, ?, ?, ?, ?, ?, ?)", f["trials"])
    for cid, company, asset, due, status, nct in f["catalysts"]:
        conn.execute(
            "INSERT INTO catalysts (id, company_id, asset_id, catalyst_type, expected_date,"
            " date_confidence, title, description, is_curated, source_url, status)"
            " VALUES (?, ?, ?, 'data readout', ?, 'estimated', 'Phase 3, a study', ?, 0, ?, ?)",
            (cid, company, asset, due, nct, f"https://clinicaltrials.gov/study/{nct}", status))
    conn.executemany("INSERT INTO approvals (asset_id, region, agency, approval_date,"
                     " application_number) VALUES (?, ?, ?, ?, ?)", f.get("approvals") or [])
    conn.executemany("INSERT INTO supplements (asset_id, application_number, submission_number,"
                     " submission_class_code, approval_date) VALUES (?, ?, ?, ?, ?)",
                     f.get("supplements") or [])
    for ticker, url, headline, kind, published, days in f.get("press") or []:
        if published:
            conn.execute("INSERT INTO news (company_id, source, title, url, published_at)"
                         " SELECT id, 'press_ir', ?, ?, ? FROM companies WHERE ticker = ?",
                         (headline, url, published, ticker))
        for day in days:          # the same release, a change row on several days
            conn.execute(
                "INSERT INTO changes (entity_type, entity_key, field, new_value, change_type,"
                " significance, detected_at) VALUES ('company', ?, 'press release', ?, ?,"
                " 'high', ?)", (f"{ticker}|{url}", headline, kind, f"{day} 09:00:00"))
    conn.commit()
    L.fill_names(path, get=lambda url, params: json.loads((FIX / "ctgov_acronyms.json").read_text()),
                 pause=0)
    return path, conn


def _status(conn):
    return {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM catalysts")}


def _reports(conn):
    return {r["ticker"]: dict(r) for r in conn.execute(
        "SELECT co.ticker, rep.* FROM readout_reports rep JOIN companies co"
        " ON co.id = rep.company_id")}


# ------------------------------------------------------------------- the study's own name
def test_the_registrys_acronym_is_asked_once_and_stored(tmp_path):
    path, conn = _book(tmp_path)
    got = dict(conn.execute("SELECT nct_id, acronym FROM trials").fetchall())
    assert got["NCT06356311"] == "TroFuse-015" and got["NCT04960709"] == "VOLGA"
    assert got["NCT06074588"] == "" and got["NCT06960577"] == ""      # asked, none given
    called = []
    again = L.fill_names(path, get=lambda u, p: called.append(p) or {"studies": []}, pause=0)
    assert again["asked"] == 0 and called == []


def test_a_name_ties_a_sentence_only_where_it_cannot_be_a_word_of_it():
    assert [L.usable(n) for n in ("TroFuse-015", "VOLGA", "lidERA", "TOPAZ-1", "B-Well 1")] == [True] * 5
    # A capitalised word, and a name too short to stand out.
    assert [L.usable(n) for n in ("Cosmic", "Orbit", "FENhance", "APEX", "")] == [False] * 5
    assert L._pattern("TOPAZ-1").search("data from TOPAZ-1 and TOPAZ-2")
    assert not L._pattern("TOPAZ-1").search("the TOPAZ-10 study")
    assert not L._pattern("VOLGA").search("the VOLGA 2 study") and L._pattern("VOLGA").search("the VOLGA trial")
    assert not L._pattern("VOLGA").search("volga") and L._pattern("TroFuse-015").search("TROFUSE-015")
    assert not L._pattern("ADVANCE").search("ICONIC-ADVANCE 2")


def test_a_study_goes_by_its_acronym_its_titles_bracket_and_the_names_on_file():
    names = L.names_of({"nct_id": "NCT04586010", "acronym": "FENhance",
                        "title": "A Study of Fenebrutinib (FENhance)"},
                       {"NCT04586010": ["FENhance 1"]})
    assert names == ["FENhance 1"]
    assert L.names_of({"nct_id": "N", "acronym": None,
                       "title": "Perioperative Durvalumab With Neoadjuvant ddMVAC (NIAGARA-2)"}) == ["NIAGARA-2"]
    assert L.names_of({"nct_id": "N", "acronym": "", "title": "A Study in Adults (Part B)"}) == []


def test_a_headline_set_in_capitals_ties_only_by_a_name_with_a_number(tmp_path):
    path, conn = _book(tmp_path)
    index = L.studies(conn)
    loud = "ASTRAZENECA REPORTS VOLGA PHASE III TRIAL MET ITS PRIMARY ENDPOINT"
    assert L.named(loud, 2, index) == []
    assert [s["nct_id"] for s, _ in L.named(loud.title().replace("Volga", "VOLGA"), 2, index)] == ["NCT04960709"]
    assert [s["nct_id"] for s, _ in L.named("MERCK'S TROFUSE-015 MET ITS PRIMARY ENDPOINT", 1, index)] == ["NCT06356311"]
    # Another company's study is not this company's to report.
    assert L.named("TroFuse-015 met its primary endpoint", 2, index) == []
    assert L.named("results from NCT04550260", 2, index)[0][1] == "registry number"


# ------------------------------------------------------------------------ the outcome
@pytest.mark.parametrize("text,want", [
    ("TroFuse-015 Trial Met Primary Endpoint of Overall Survival", "met"),
    ("the study met both co-primary endpoints", "met"),
    ("The primary endpoint was met at week 24", "met"),
    ("the trial did not meet its primary endpoint", "missed"),
    ("failed to achieve the primary objective", "missed"),
    ("The primary endpoint was not met", "missed"),
    ("Announces Positive Topline Results from Maintenance Study", None),
    ("significantly improved progression-free survival", None),
    ("discontinues the Phase 3 trial", None),
    ("to present data showing the study met its primary endpoint", None),
    ("", None)])
def test_only_the_primary_endpoint_in_so_many_words_is_an_outcome(text, want):
    assert L.outcome_of(text)[0] == want


# ----------------------------------------------------------- the four cases, by rule alone
def test_the_four_cases_settle_and_none_lands_on_the_gate_it_was_shown_against(tmp_path):
    path, conn = _book(tmp_path)
    before = _status(conn)
    got = L.run(path, today=TODAY, step=False, set_aside_path=NONE)
    after, reps = _status(conn), _reports(conn)
    # 1. TroFuse-015 is the gastroesophageal study, and that is the one it closes.
    assert after[1462] == "met" and after[434] == "pending"
    assert (reps["MRK"]["state"], reps["MRK"]["nct_id"], reps["MRK"]["tied_by"]) == (
        "landed", "NCT06356311", "study name")
    led = conn.execute("SELECT * FROM catalyst_resolutions WHERE catalyst_id = 1462").fetchone()
    assert (led["outcome"], led["event_date"], led["source"], led["automated"]) == (
        "met", "2026-11-20", "posted:press", 1)
    assert "merck.com" in led["evidence"] and "Met Primary Endpoint" in led["evidence"]
    assert conn.execute("SELECT updated_at FROM catalysts WHERE id = 1462").fetchone()[0] == "2026-11-20"
    # 2. The Imfinzi approval is the efficacy supplement on file, and decides no study.
    assert reps["AZN"]["state"] == "on_file" and "BLA761069/59" in reps["AZN"]["reason"]
    # 3. The Hibsago approval is the approval on file, read once from nine change rows.
    assert reps["GSK"]["state"] == "on_file" and "NDA221276" in reps["GSK"]["reason"]
    assert conn.execute("SELECT COUNT(*) FROM readout_reports").fetchone()[0] == 4
    # 4. The maintenance study names no study the book holds.
    assert reps["VKTX"]["state"] == "not_tied" and reps["VKTX"]["nct_id"] is None
    # Nothing but TroFuse-015's own study moved.
    assert {k: v for k, v in after.items() if before[k] != v} == {1462: "met"}
    assert got["landed"] == 1 and got["held"] == 1 and got["on_file"] == 2


def test_a_person_s_ruling_sets_a_held_report_aside_and_keeps_the_reason(tmp_path):
    path, conn = _book(tmp_path)
    L.run(path, today=TODAY, step=False)                       # with the committed rulings
    reps = _reports(conn)
    assert reps["VKTX"]["state"] == "set_aside" and reps["VKTX"]["nct_id"] == "NCT07838740"
    assert "VK2735-102" in reps["VKTX"]["reason"] and "vikingtherapeutics.com" in reps["VKTX"]["reason"]
    assert reps["AZN"]["state"] == "set_aside" and "VOLGA" in reps["AZN"]["reason"]
    assert reps["MRK"]["state"] == "landed"                    # a ruling never unlands one
    shown = L.block(path, None, today=TODAY)
    assert shown["reported"] == []
    assert [(x["ticker"], x["study"], x["nct_id"], x["outcome"]) for x in shown["landed"]] == [
        ("MRK", "TroFuse-015", "NCT06356311", "met")]
    one = shown["landed"][0]
    assert one["url"].startswith("https://www.merck.com/") and one["automated"] is True
    assert "Met Primary Endpoint" in one["sentence"] and one["tied_by"] == "study name"


def test_a_second_run_lands_nothing_and_says_it_once_in_the_feed(tmp_path):
    path, conn = _book(tmp_path)
    L.run(path, today=TODAY, step=False)
    again = L.run(path, today=TODAY, step=False)
    assert again["landed"] == 0
    feed = conn.execute("SELECT entity_key, new_value, significance FROM changes"
                        " WHERE change_type = 'readout_landed'").fetchall()
    assert len(feed) == 1 and feed[0]["entity_key"] == "MRK|landed:NCT06356311"
    assert feed[0]["new_value"].startswith(
        "Sacituzumab Tirumotecan: TroFuse-015 (NCT06356311) met its primary endpoint, "
        "announced 2026-11-20")
    assert conn.execute("SELECT COUNT(*) FROM catalyst_resolutions").fetchone()[0] == 1
    assert CO.resolve(path, today=TODAY, fetch=False)["met"] == 0
    assert _status(conn)[1462] == "met"


def test_a_result_already_entered_by_hand_is_acknowledged_not_recorded_twice(tmp_path):
    path, conn = _book(tmp_path)
    announced_readouts.record(conn, 1462, "met", "2026-11-20", "https://x/y: met.", today=TODAY)
    conn.commit()
    got = L.run(path, today=TODAY, step=False)
    assert got["landed"] == 0 and _reports(conn)["MRK"]["effect"] == "already on file with this outcome"
    assert conn.execute("SELECT COUNT(*) FROM catalyst_resolutions").fetchone()[0] == 1


def test_a_resolution_on_file_is_not_overturned_by_a_rule(tmp_path):
    path, conn = _book(tmp_path)
    conn.execute("UPDATE catalysts SET status = 'missed' WHERE id = 1462")
    conn.commit()
    L.run(path, today=TODAY, step=False)
    rep = _reports(conn)["MRK"]
    assert rep["state"] == "outcome_not_read" and "holds NCT06356311 as missed" in rep["reason"]
    assert _status(conn)[1462] == "missed"


# ------------------------------------------------------------- held, and what a person does
def _one(tmp_path, headline, kind="press_data_readout", ticker="MRK", published="2026-11-18"):
    f = json.loads((FIX / "four_cases.json").read_text())
    f["press"] = [[ticker, "https://example.org/r", headline, kind, published, ["2026-11-19"]]]
    return _book(tmp_path, f)


def test_a_study_named_with_no_outcome_in_words_is_held_until_a_person_reads_it(tmp_path):
    path, conn = _one(tmp_path, "Merck Announces Positive Topline Results From TroFuse-015")
    L.run(path, today=TODAY, step=False, set_aside_path=NONE)
    rep = _reports(conn)["MRK"]
    assert (rep["state"], rep["nct_id"], rep["outcome"]) == ("outcome_not_read", "NCT06356311", None)
    assert "does not say in so many words" in rep["reason"] and _status(conn)[1462] == "pending"
    shown = L.block(path, "MRK", today=TODAY)
    assert shown["landed"] == [] and [x["state"] for x in shown["reported"]] == ["outcome_not_read"]
    got = L.record_report(path, rep["id"], "met", today=TODAY, step=False)
    assert got["state"] == "landed" and _status(conn)[1462] == "met"
    led = conn.execute("SELECT source, automated, event_date FROM catalyst_resolutions").fetchone()
    assert (led["source"], led["automated"], led["event_date"]) == ("hand", 0, "2026-11-18")
    L.run(path, today=TODAY, step=False, set_aside_path=NONE)       # the sources read as before
    assert _reports(conn)["MRK"]["state"] == "landed"
    assert L.block(path, "MRK", today=TODAY)["reported"] == []
    with pytest.raises(ValueError):
        L.record_report(path, rep["id"], "met", today=TODAY, step=False)


def test_a_result_naming_only_the_asset_is_reported_and_never_landed(tmp_path):
    path, conn = _one(tmp_path, "Sacituzumab Tirumotecan Met Primary Endpoint in a Phase 3 Study")
    before = _status(conn)
    L.run(path, today=TODAY, step=False, set_aside_path=NONE)
    rep = _reports(conn)["MRK"]
    assert rep["state"] == "not_tied" and "no study the book holds" in rep["reason"]
    assert _status(conn) == before
    with pytest.raises(ValueError):
        L.record_report(path, rep["id"], "met", today=TODAY, step=False)


@pytest.mark.parametrize("headline", [
    "Merck to Present TroFuse-015 Data at ESMO",
    "Merck Presents Five-Year Phase 3 Data for Sacituzumab Tirumotecan",
    "Merck Begins Treating Patients in TroFuse-015",
    "Merck Announces Quarterly Dividend"])
def test_a_headline_that_reports_no_new_result_is_not_a_report(tmp_path, headline):
    path, conn = _one(tmp_path, headline)
    L.run(path, today=TODAY, step=False, set_aside_path=NONE)
    assert _reports(conn) == {} and _status(conn)[1462] == "pending"


def test_an_approval_sought_or_recommended_is_not_one_that_happened(tmp_path):
    path, conn = _one(tmp_path, "CHMP recommends EU approval of Imfinzi in bladder cancer",
                      kind="press_approval", ticker="AZN", published="2026-11-13")
    L.run(path, today=TODAY, step=False, set_aside_path=NONE)
    rep = _reports(conn)["AZN"]
    assert rep["state"] == "no_gate" and L.block(path, "AZN", today=TODAY)["reported"] == []


def test_an_approval_in_the_use_a_decision_waits_on_is_held_for_the_register(tmp_path):
    path, conn = _one(tmp_path, "Imfinzi approved in the US for limited-stage small cell lung cancer",
                      kind="press_approval", ticker="AZN", published="2026-08-01")
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type, expected_date,"
                 " title, is_curated, status) VALUES (9, 2, 20, 'PDUFA', '2026-12-01',"
                 " 'Imfinzi PDUFA, limited-stage small cell lung cancer', 1, 'pending')")
    conn.commit()
    L.run(path, today=TODAY, step=False, set_aside_path=NONE)
    rep = _reports(conn)["AZN"]
    assert rep["state"] == "awaiting_register" and rep["catalyst_id"] == 9
    assert _status(conn)[9] == "pending" and "openFDA" in rep["reason"]


def test_result_tables_on_the_registry_are_a_study_certain_and_an_outcome_not_read(tmp_path):
    path, conn = _one(tmp_path, "Merck Announces Quarterly Dividend")
    conn.execute("INSERT INTO trial_result_fetches (nct_id, has_results, results_date)"
                 " VALUES ('NCT06074588', 1, '2026-11-13')")
    conn.commit()
    L.run(path, today=TODAY, step=False, set_aside_path=NONE)
    rep = _reports(conn)["MRK"]
    assert (rep["state"], rep["source"], rep["nct_id"]) == ("outcome_not_read", "registry", "NCT06074588")
    assert "state no outcome in words" in rep["reason"] and _status(conn)[434] == "pending"


def test_a_held_report_is_settled_once_its_study_is_closed_from_elsewhere(tmp_path):
    """Held on Monday, entered in announced_readouts.csv on Tuesday: the report stayed on
    the tab as unsettled beside the landed readout it was about."""
    path, conn = _one(tmp_path, "Merck Announces Quarterly Dividend")
    conn.execute("INSERT INTO trial_result_fetches (nct_id, has_results, results_date)"
                 " VALUES ('NCT06074588', 1, '2026-11-13')")
    conn.commit()
    first = L.run(path, today=TODAY, step=False, set_aside_path=NONE)
    assert first["held"] == 1 and first["settled"] == 0
    announced_readouts.record(conn, 434, "missed", "2026-11-20", "https://x/y: missed.", today=TODAY)
    conn.commit()
    again = L.run(path, today=TODAY, step=False, set_aside_path=NONE)
    rep = _reports(conn)["MRK"]
    assert again["settled"] == 1 and again["held"] == 0
    assert (rep["state"], rep["outcome"], rep["catalyst_id"]) == ("landed", "missed", 434)
    assert "closed from another source" in rep["reason"]
    assert L.run(path, today=TODAY, step=False, set_aside_path=NONE)["settled"] == 0


def test_a_posting_carries_the_primary_endpoint_as_posted_and_still_reads_no_outcome(tmp_path):
    """Roche's IMvigor011: the registry posts disease-free survival at a hazard ratio of
    0.64, 0.47 to 0.87, p = 0.0047. The report says so, in the registry's own figures,
    and the outcome stays unread: whether a p-value met an endpoint depends on the alpha
    the protocol spent on it, which no table carries."""
    path, conn = _one(tmp_path, "Merck Announces Quarterly Dividend")
    conn.execute("INSERT INTO trial_result_fetches (nct_id, has_results, results_date)"
                 " VALUES ('NCT06074588', 1, '2026-11-13')")
    for index, kind, title in ((0, "PRIMARY", "INV-assessed Disease-free  Survival (DFS)"),
                               (1, "SECONDARY", "Overall Survival (OS)")):
        conn.execute("INSERT INTO trial_result_outcomes (nct_id, outcome_index, outcome_type,"
                     " title, group_id, value) VALUES ('NCT06074588', ?, ?, ?, 'OG000', '1')",
                     (index, kind, title))
    conn.execute("INSERT INTO trial_result_analyses (nct_id, outcome_index, method, param_type,"
                 " param_value, ci_lower, ci_upper, p_value) VALUES ('NCT06074588', 0,"
                 " 'Log Rank', 'Hazard Ratio (HR)', 0.64, 0.47, 0.87, 0.0047)")
    conn.execute("INSERT INTO trial_result_analyses (nct_id, outcome_index, method, param_type,"
                 " param_value, ci_lower, ci_upper, p_value) VALUES ('NCT06074588', 1,"
                 " 'Log Rank', 'Hazard Ratio (HR)', 0.59, 0.39, 0.9, 0.0131)")
    conn.commit()
    L.run(path, today=TODAY, step=False, set_aside_path=NONE)
    rep = _reports(conn)["MRK"]
    assert rep["sentence"].endswith(
        "Primary endpoint as posted. INV-assessed Disease-free Survival (DFS): "
        "Hazard Ratio (HR) 0.64 (0.47 to 0.87), p = 0.0047 by Log Rank")
    assert "Overall Survival" not in rep["sentence"]
    assert rep["state"] == "outcome_not_read" and rep["outcome"] is None


def test_a_primary_endpoint_with_no_analysis_posted_says_so(tmp_path):
    path, conn = _one(tmp_path, "Merck Announces Quarterly Dividend")
    conn.execute("INSERT INTO trial_result_outcomes (nct_id, outcome_index, outcome_type,"
                 " title, group_id, value) VALUES ('NCT06074588', 0, 'PRIMARY',"
                 " 'Number of participants with adverse events', 'OG000', '12')")
    conn.commit()
    assert L.posted_primary(conn, "NCT06074588") == (
        "Primary endpoint as posted. Number of participants with adverse events: "
        "no statistical analysis posted")
    assert L.posted_primary(conn, "NCT00000000") is None


# ----------------------------------------------- results the extractors read from a body
def _labelled(conn, accession, quote, outcome="positive", title="8-K: RESULTS", company=1,
              day="2026-11-10"):
    conn.execute("INSERT INTO filings (company_id, form_type, filed_date, accession, title, url)"
                 " VALUES (?, '8-K', ?, ?, ?, 'https://sec.gov/f')", (company, day, accession, title))
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome,"
                 " event_date, quote, source_url) VALUES (?, ?, 'sac-TMT', 3, ?, ?, ?,"
                 " 'https://sec.gov/f')", (accession, company, outcome, day, quote))
    conn.commit()


def test_a_labelled_result_lands_on_the_study_its_sentence_names(tmp_path):
    path, conn = _one(tmp_path, "Merck Announces Quarterly Dividend")
    _labelled(conn, "A-1", "The TroFuse-015 trial did not meet its primary endpoint.", "negative")
    L.run(path, today=TODAY, step=False, set_aside_path=NONE)
    assert _status(conn)[1462] == "missed" and _status(conn)[434] == "pending"
    led = conn.execute("SELECT source, evidence FROM catalyst_resolutions").fetchone()
    assert led["source"] == "posted:filing" and "did not meet its primary endpoint" in led["evidence"]
    # The same filing is spent: the resolver's own tier does not offer it to the sibling.
    CO.resolve(path, today=dt.date(2027, 8, 1), fetch=False)
    assert _status(conn)[434] in ("pending", "unknown")


def test_a_labelled_result_that_names_no_study_lands_nowhere(tmp_path):
    """The stored body lists the programme's other studies; a name down there says only
    that the study exists."""
    path, conn = _one(tmp_path, "Merck Announces Quarterly Dividend")
    _labelled(conn, "A-2", "The trial met its primary endpoint.")
    conn.execute("INSERT INTO filing_sections (company_id, accession, section, text) VALUES"
                 " (1, 'A-2', 'exhibit', 'Other studies, including TroFuse-015, continue.')")
    conn.commit()
    got = L.run(path, today=TODAY, step=False, set_aside_path=NONE)
    assert got["landed"] == 0 and _status(conn)[1462] == "pending"


def test_a_filings_title_names_the_study_its_result_sentence_is_about(tmp_path):
    path, conn = _one(tmp_path, "Merck Announces Quarterly Dividend")
    _labelled(conn, "A-3", "The study met its primary endpoint of overall survival.",
              title="8-K: TROFUSE-015 MET PRIMARY ENDPOINT")
    L.run(path, today=TODAY, step=False, set_aside_path=NONE)
    assert _status(conn)[1462] == "met"


# ------------------------------------------------------------------- stepping the model
def test_the_priced_gate_is_stepped_by_the_resolve_and_the_feed_says_what_it_did(tmp_path, monkeypatch):
    import forecast_view
    path, conn = _book(tmp_path)
    seen = []

    def resolve(db_path, ticker, catalyst_id, outcome):
        seen.append((ticker, catalyst_id, outcome,
                     db.get_connection(db_path).execute(
                         "SELECT status FROM catalysts WHERE id = ?", (catalyst_id,)).fetchone()[0]))
        return {"route": "gate evidence", "pos_before": 0.46, "pos_applied": 0.91, "held": None}
    monkeypatch.setattr(forecast_view, "resolve_catalyst", resolve)
    L.run(path, today=TODAY, set_aside_path=NONE)
    assert seen == [("MRK", 1462, "met", "pending")]            # stepped before it was closed
    rep = _reports(conn)["MRK"]
    assert rep["effect"] == "the gate's odds moved from 46% to 91%"
    assert _status(conn)[1462] == "met"
    assert conn.execute("SELECT updated_at FROM catalysts WHERE id = 1462").fetchone()[0] == "2026-11-20"
    feed = conn.execute("SELECT new_value FROM changes WHERE change_type = 'readout_landed'").fetchone()[0]
    assert feed.endswith("the gate's odds moved from 46% to 91%.")


def test_a_readout_that_is_not_the_priced_gate_is_recorded_and_the_reason_kept(tmp_path, monkeypatch):
    import forecast_view
    path, conn = _book(tmp_path)

    def refuse(db_path, ticker, catalyst_id, outcome):
        raise ValueError("this catalyst is not the gate the model prices")
    monkeypatch.setattr(forecast_view, "resolve_catalyst", refuse)
    L.run(path, today=TODAY, set_aside_path=NONE)
    assert _status(conn)[1462] == "met"
    assert _reports(conn)["MRK"]["effect"] == (
        "recorded against the study; no priced gate moved: this catalyst is not the gate "
        "the model prices")


def test_a_readout_closed_unknown_is_reopened_for_the_step(tmp_path, monkeypatch):
    import forecast_view
    f = json.loads((FIX / "four_cases.json").read_text())
    f["catalysts"][0][4] = "unknown"
    path, conn = _book(tmp_path, f)
    states = []
    monkeypatch.setattr(forecast_view, "resolve_catalyst", lambda p, t, c, o: states.append(
        db.get_connection(p).execute("SELECT status FROM catalysts WHERE id = ?", (c,)).fetchone()[0])
        or {"route": "stated legs", "pos_before": 0.5, "pos_applied": 0.9})
    L.run(path, today=TODAY, set_aside_path=NONE)
    assert states == ["pending"] and _status(conn)[1462] == "met"
    assert _reports(conn)["MRK"]["effect"] == "the stated odds were stepped from 50% to 90%"


# ------------------------------------------------------------------------- the hand files
def test_every_committed_name_and_ruling_carries_its_source():
    with open(L.NAMES_CSV, newline="", encoding="utf-8") as handle:
        names = list(csv.DictReader(line for line in handle if not line.startswith("#")))
    assert names
    for row in names:
        assert L._NCT.fullmatch(row["nct_id"]) and L.usable(row["name"]), row
        assert row["source_url"].startswith("https://"), row
    rulings = L.set_aside()
    with open(L.SET_ASIDE_CSV, newline="", encoding="utf-8") as handle:
        raw = list(csv.DictReader(line for line in handle if not line.startswith("#")))
    assert len(rulings) == len(raw) >= 2
    for row in raw:
        assert row["ruling"] in L.RULINGS and row["url"].startswith("https://"), row
        assert row["source_url"].startswith("https://") and len(row["reason"]) > 40, row
        assert "—" not in row["reason"], row
