"""Posted results from ClinicalTrials.gov: outcomes, analyses, safety and events per arm."""

import json
from pathlib import Path

import db
from fetchers import trial_results as TR

FIXTURE = Path(__file__).parent / "fixtures" / "ctgov_results_mazdutide.json"


def _study():
    return json.loads(FIXTURE.read_text())["studies"][0]


def test_the_primary_endpoint_is_read_per_arm_as_posted():
    got = TR.parse_study(_study())
    assert got["nct_id"] == "NCT06124807" and got["has_results"]
    primary = [o for o in got["outcomes"] if o["outcome_type"] == "PRIMARY"]
    assert primary[0]["title"] == "Percent Change From Baseline in Body Weight at Week 32"
    by_arm = {o["group_title"]: o["value"] for o in primary}
    assert by_arm["Placebo"] == -0.85
    assert by_arm["16 mg Mazdutide"] is not None and by_arm["16 mg Mazdutide"] < -10
    assert all(o["unit"] == "percent change" for o in primary)
    assert all(o["n_analysed"] for o in primary)


def test_secondary_endpoints_are_capped():
    got = TR.parse_study(_study())
    kept = {o["outcome_index"] for o in got["outcomes"] if o["outcome_type"] == "SECONDARY"}
    assert 0 < len(kept) <= TR.SECONDARY_KEPT


def test_safety_carries_totals_and_withdrawals_for_adverse_events_per_arm():
    got = TR.parse_study(_study())
    arms = {s["group_title"]: s for s in got["safety"]}
    placebo = arms["Placebo"]
    assert placebo["serious_affected"] == 1 and placebo["serious_at_risk"] == 47
    assert placebo["deaths_affected"] == 0
    # The flow's FG groups are matched to the event groups by title.
    assert placebo["withdrawn_ae"] == 1
    assert arms["16 mg Mazdutide"]["withdrawn_ae"] == 5


def test_only_the_most_frequent_events_are_kept_with_every_arms_rate():
    got = TR.parse_study(_study())
    other = {e["term"] for e in got["events"] if not e["serious"]}
    assert len(other) == TR.OTHER_EVENTS_KEPT
    groups = {e["group_id"] for e in got["events"] if e["term"] == next(iter(other))}
    assert len(groups) == 4             # the placebo rate stays beside the drug's


def test_a_value_posted_as_text_is_kept_as_text_not_a_number():
    study = {"protocolSection": {"identificationModule": {"nctId": "NCT1"}},
             "hasResults": True, "resultsSection": {"outcomeMeasuresModule": {
                 "outcomeMeasures": [{"type": "PRIMARY", "title": "t",
                                      "groups": [{"id": "OG000", "title": "A"}],
                                      "classes": [{"categories": [{"measurements": [
                                          {"groupId": "OG000", "value": "NA"}]}]}],
                                      "analyses": [{"groupIds": ["OG000", "OG001"],
                                                    "pValue": "<0.001",
                                                    "paramValue": "-7.5",
                                                    "ciLowerLimit": "-9", "ciUpperLimit": "-6"}]}]}}}
    got = TR.parse_study(study)
    assert got["outcomes"][0]["value"] is None and got["outcomes"][0]["value_text"] == "NA"
    assert got["analyses"][0]["p_value"] == "<0.001"
    assert got["analyses"][0]["param_value"] == -7.5


def test_a_study_without_results_is_marked_asked_and_writes_nothing(tmp_path, monkeypatch):
    path = str(tmp_path / "tr.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Lilly')")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name) VALUES (1, 1, 'Mazdutide')")
    for nct in ("NCT06124807", "NCT00000001"):
        conn.execute("INSERT INTO completed_trials (nct_id, sponsor_company_id, asset_id,"
                     " phase, completion_date) VALUES (?, 1, 1, 'Phase 2', '2025-01-22')", (nct,))
    conn.commit()
    conn.close()
    calls = []

    def fake(url, params):
        calls.append(params["filter.ids"])
        return {"studies": [_study()]}      # the registry returns only the one with results
    monkeypatch.setattr(TR, "get_json", fake)
    monkeypatch.setattr(TR, "_POLITE_SLEEP_S", 0)
    result = TR.TrialResultsFetcher("LLY", path).run()
    assert not result.errors and result.rows_fetched == 1
    conn = db.get_connection(path)
    marks = dict(conn.execute("SELECT nct_id, has_results FROM trial_result_fetches"))
    assert marks == {"NCT06124807": 1, "NCT00000001": 0}
    assert conn.execute("SELECT COUNT(*) FROM trial_result_outcomes").fetchone()[0] > 0
    conn.close()
    # Asked once: a second run inside the refetch window asks for nothing.
    fetcher = TR.TrialResultsFetcher("LLY", path)
    fetcher.force = True
    fetcher.run()
    assert len(calls) == 1


def test_a_study_still_active_is_asked_however_its_status_is_spelled(tmp_path):
    """The pipeline stores the registry's status humanised, "Active not recruiting", and
    the list of statuses that can have posted was written as the API spells them. That
    half of the query matched nothing, so a Phase 3 past its primary completion and still
    following patients, which is when it posts, was never asked. Both spellings are due;
    a study still recruiting and one mapped to no asset are not, and a Phase 1 study is
    due after every late one."""
    path = str(tmp_path / "tr.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Lilly')")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name) VALUES (1, 1, 'Omvoh')")
    studies = [("NCT00000001", 1, "Phase 3", "Active not recruiting", "2025-03-01"),
               ("NCT00000002", 1, "Phase 3", "ACTIVE_NOT_RECRUITING", "2025-02-01"),
               ("NCT00000003", 1, "Phase 2", "Completed", "2025-01-01"),
               ("NCT00000004", 1, "Phase 3", "Terminated", "2024-12-01"),
               ("NCT00000005", 1, "Phase 3", "Recruiting", "2027-01-01"),
               ("NCT00000006", 1, "Phase 1", "Completed", "2024-01-01"),
               ("NCT00000007", None, "Phase 3", "Completed", "2024-01-01")]
    for nct, asset, phase, status, done in studies:
        conn.execute("INSERT INTO trials (nct_id, asset_id, sponsor_company_id, phase,"
                     " overall_status, primary_completion_date) VALUES (?, ?, 1, ?, ?, ?)",
                     (nct, asset, phase, status, done))
    conn.commit()
    due = TR.TrialResultsFetcher("LLY", path).due(conn)
    conn.close()
    assert due == ["NCT00000001", "NCT00000002", "NCT00000003", "NCT00000004",
                   "NCT00000006"]


def test_a_late_study_is_asked_before_an_early_one_however_recent(tmp_path):
    """Phase 1 and Phase 4 studies are asked too, but after every late one: the cap on a
    run must never leave a Phase 3 waiting behind a newer Phase 1."""
    path = str(tmp_path / "tr.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Lilly')")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name) VALUES (1, 1, 'Omvoh')")
    for nct, phase, done in (("NCT00000011", "Phase 1", "2026-06-01"),
                             ("NCT00000012", "Phase 4", "2026-05-01"),
                             ("NCT00000013", "Phase 3", "2020-01-01"),
                             ("NCT00000014", None, "2026-07-01")):
        conn.execute("INSERT INTO completed_trials (nct_id, sponsor_company_id, asset_id,"
                     " phase, completion_date) VALUES (?, 1, 1, ?, ?)", (nct, phase, done))
    conn.commit()
    due = TR.TrialResultsFetcher("LLY", path).due(conn)
    conn.close()
    # A study with no phase stated (observational, device) is not asked.
    assert due == ["NCT00000013", "NCT00000011", "NCT00000012"]
