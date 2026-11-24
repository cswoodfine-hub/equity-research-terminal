"""A completed study read from what its sponsor posted: the scorecard, the summary in
words and the points to weigh (``trial_report``), and the page's builders for it
(``portfolio_cards``). Figures synthetic."""

import re
import sys
from pathlib import Path

import pytest

import db
import trial_report as TR

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "frontend"))
import portfolio_cards as PC  # noqa: E402

BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")
NCT = "NCT01234567"


def _db(tmp_path, *, p_value="<0.001", control="Placebo", drug_serious=12,
        results=True, analyses=None):
    path = str(tmp_path / "t.db")
    db.init(path)
    c = db.get_connection(path)
    c.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'EX', 'Example')")
    c.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name, is_marketed)"
              " VALUES (5, 1, 'Exampla', 'examplatide', 1)")
    c.execute("INSERT INTO completed_trials (nct_id, sponsor_company_id, asset_id, title, phase,"
              " completion_date, enrollment) VALUES (?, 1, 5, 'A <b>study</b> of examplatide',"
              " 'Phase 3', '2025-03-01', 400)", (NCT,))
    if results is not None:                     # None: the fetcher never asked
        c.execute("INSERT INTO trial_result_fetches (nct_id, has_results, results_date,"
                  " fetched_at) VALUES (?, ?, '2025-09-01', '2025-10-01')",
                  (NCT, int(results)))
    arms = (("OG000", control, 10.0), ("OG001", "Examplatide 10 mg", 25.0))
    for gid, title, value in arms:
        c.execute("INSERT INTO trial_result_outcomes (nct_id, outcome_index, outcome_type, title,"
                  " time_frame, unit, param_type, group_id, group_title, value, n_analysed)"
                  " VALUES (?, 0, 'PRIMARY', 'Change in score', 'Week 24', 'points', 'MEAN',"
                  " ?, ?, ?, 200)", (NCT, gid, title, value))
    for gids, est, lo, hi, p in (analyses or [('["OG000", "OG001"]', 15.0, 9.0, 21.0, p_value)]):
        c.execute("INSERT INTO trial_result_analyses (nct_id, outcome_index, group_ids,"
                  " param_type, param_value, ci_pct, ci_lower, ci_upper, p_value)"
                  " VALUES (?, 0, ?, 'Mean Difference (Final Values)', ?, 95, ?, ?, ?)",
                  (NCT, gids, est, lo, hi, p))
    for gid, title, serious, wd in (("EG000", control, 5, 2), ("EG001", "Examplatide 10 mg",
                                                               drug_serious, 6)):
        c.execute("INSERT INTO trial_result_safety (nct_id, group_id, group_title,"
                  " deaths_affected, deaths_at_risk, serious_affected, serious_at_risk,"
                  " other_affected, other_at_risk, withdrawn_ae) VALUES (?, ?, ?, 0, 100, ?,"
                  " 100, 30, 100, ?)", (NCT, gid, title, serious, wd))
        c.execute("INSERT INTO trial_result_events (nct_id, term, serious, group_id, affected,"
                  " at_risk) VALUES (?, 'Nausea', 0, ?, ?, 100)",
                  (NCT, gid, 4 if gid == "EG000" else 20))
    c.commit()
    c.close()
    return path


def _card(r):
    return {row["k"]: row for row in r["scorecard"]}


def test_a_controlled_study_that_met_reads_green_and_its_safety_against_placebo(tmp_path):
    r = TR.report(_db(tmp_path), NCT)
    assert {a["group_title"]: a["role"] for a in r["arms"]} == {
        "Placebo": "placebo", "Examplatide 10 mg": "drug"}
    card = _card(r)
    assert card["Primary endpoint"]["verdict"] == "significant"
    assert card["Primary endpoint"]["tone"] == "good"
    assert card["Size of effect"]["tone"] == "good"
    # The safety arms carry their own ids and are read on their own.
    assert card["Serious adverse events"]["verdict"] == "+7.0 points against placebo"
    assert card["Serious adverse events"]["tone"] == "bad"
    assert card["Stopped for adverse events"]["verdict"] == "6.0% against 2.0%"
    assert card["Evidence"]["tone"] == "good"
    (tmp_path / "fewer").mkdir()
    fewer = _card(TR.report(_db(tmp_path / "fewer", drug_serious=2), NCT))
    assert fewer["Serious adverse events"]["verdict"] == "−3.0 points against placebo"
    assert fewer["Serious adverse events"]["tone"] == "good"
    assert "Placebo 10 points; Examplatide 10 mg 25 points" in r["summary"]
    assert "p <0.001" in r["summary"]
    assert r["events"][0]["term"] == "Nausea"
    assert [a["pct"] for a in r["events"][0]["arms"]] == [4.0, 20.0]


def test_a_miss_reads_red_and_its_interval_is_a_point_to_weigh(tmp_path):
    r = TR.report(_db(tmp_path, analyses=[('["OG000", "OG001"]', 2.0, -1.0, 5.0, "0.21")]), NCT)
    card = _card(r)
    assert card["Primary endpoint"]["verdict"] == "not significant"
    assert card["Size of effect"]["verdict"] == "interval spans no effect"
    assert "The interval around the effect includes no effect." in r["factors"]


def test_with_no_p_value_the_endpoint_is_read_by_its_interval(tmp_path):
    r = TR.report(_db(tmp_path, analyses=[('["OG000", "OG001"]', 15.0, 9.0, 21.0, None)]), NCT)
    assert _card(r)["Primary endpoint"]["verdict"] == "interval clear of no effect"


def test_no_comparator_is_said_and_no_posted_results_are_said(tmp_path):
    r = TR.report(_db(tmp_path, control="Examplatide 5 mg"), NCT)
    assert "No placebo or control arm" in " ".join(r["factors"])
    assert _card(r)["Evidence"]["tone"] == "bad"
    (tmp_path / "unposted").mkdir()
    none = TR.report(_db(tmp_path / "unposted", results=False), NCT)
    assert _card(none)["Primary endpoint"]["verdict"] == "no results posted"
    assert TR.report(str(tmp_path / "unposted" / "t.db"), "NCT00000000") is None


def test_the_company_list_says_which_studies_have_results(tmp_path):
    path = _db(tmp_path)
    rows = TR.completed(path, "ex")
    assert [(r["nct_id"], r["asset_id"], r["has_results"]) for r in rows] == [(NCT, 5, True)]
    assert TR.completed(path, "NOPE") is None


def test_the_page_draws_the_scorecard_the_summary_and_escapes_the_registry(tmp_path):
    r = TR.report(_db(tmp_path), NCT)
    markup = PC.trial_report_html(r)
    assert "Clinical scorecard" in markup and "Summary of the results" in markup
    assert "Points to weigh" in markup and 'class="tr-row good"' in markup
    assert "A &lt;b&gt;study&lt;/b&gt; of examplatide" in markup
    assert f'https://clinicaltrials.gov/study/{NCT}?tab=results' in markup
    text = re.sub(r"<[^>]+>", " ", markup)
    assert "—" not in text and not any(re.search(rf"\b{w}\b", text.lower()) for w in BANNED)


def test_a_past_study_is_listed_with_its_date_phase_size_and_whether_results_are_posted():
    label = PC.completed_label({"nct_id": NCT, "title": "T", "phase": "Phase 3",
                                "completion_date": "2025-03-01", "enrollment": 400,
                                "has_results": True})
    assert label == "Mar 2025 · Phase 3 · 400 participants · T · results posted"
    assert PC.completed_label({"nct_id": NCT, "has_results": False}).endswith(
        "no results posted")
    assert PC.nct_id_number("nct01234567") == 1234567 and PC.nct_id_number("x") is None


def test_a_compounds_completed_studies_join_the_registrys_finished_ones_newest_first():
    prog = {"studies": [{"nct_id": "NCT00000009", "status": "Completed", "due": "2026-01"},
                        {"nct_id": "NCT00000008", "status": "Recruiting", "due": "2027-01"}]}
    got = PC.completed_studies([{"nct_id": NCT, "completion_date": "2025-03-01"}], prog)
    assert [t["nct_id"] for t in got] == ["NCT00000009", NCT]


@pytest.mark.parametrize("words", [TR._factors.__doc__ or "", TR.__doc__])
def test_the_modules_own_words_keep_house_style(words):
    assert "—" not in words and not any(re.search(rf"\b{w}\b", words.lower()) for w in BANNED)


def test_a_study_the_fetcher_never_asked_is_unread_not_unposted(tmp_path):
    path = _db(tmp_path, results=None)
    r = TR.report(path, NCT)
    assert r["fetched"] is False
    assert _card(r)["Primary endpoint"]["verdict"] == "results not fetched"
    assert "Not fetched yet" in r["summary"] and "no results are posted" not in r["summary"]
    assert not any("no results are posted" in f for f in r["factors"])
    assert TR.completed(path, "EX")[0]["has_results"] is None
    assert PC.completed_label({"nct_id": NCT, "has_results": None}).endswith(
        "results not fetched")
    assert "results not fetched" in PC.trial_report_html(r)
