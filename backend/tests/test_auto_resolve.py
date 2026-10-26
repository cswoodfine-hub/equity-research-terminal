"""A readout in the news, matched to the gate it decides.

The rule under test is abstention. The feed that carries "meets primary endpoint" also
carries "Begins Treating Patients" and "to Present New Data", both filed as data
readouts, so a classifier confident enough to act on it would be wrong about the model's
biggest numbers.
"""

import datetime as dt
import pathlib

import auto_resolve as A
import db


def _book(tmp_path, press):
    tmp_path = pathlib.Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = str(tmp_path / "a.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1,'LLY','Lilly')")
    today = dt.date.today().isoformat()
    for ticker, url, headline, kind in press:
        conn.execute(
            """INSERT INTO changes (entity_type, entity_key, field, new_value,
                                    change_type, significance, detected_at)
               VALUES ('company', ?, 'press release', ?, ?, 'high', ?)""",
            (f"{ticker}|{url}", headline, kind, f"{today} 09:00:00"))
    conn.commit(); conn.close()
    return path


def _gate(**over):
    base = {"id": 7, "asset_id": 12, "asset_name": "Omvoh", "gate": "p3_to_nda",
            "gate_label": "Phase 3 readout", "gate_trial": "NCT06661383",
            "expected_date": "2027-03-01", "pos_now": 0.5, "pos_success": 0.9,
            "pos_failure": 0.0, "per_share": 4.0, "rnpv_now": 500.0,
            "rnpv_success": 900.0, "rnpv_failure": 0.0, "resolvable": True,
            "resolve_note": None, "priced": True}
    return {**base, **over}


def _stakes(*gates):
    return lambda t: {"priced": list(gates), "unpriced": []}


# --- what the words say --------------------------------------------------------------

def test_a_headline_that_announces_a_future_event_is_not_a_result():
    for line in ("Biogen to Present New Data Across Nephrology Portfolio",
                 "Revolution Medicines Begins Treating Patients in Phase 3 RASolve 308",
                 "Wave Life Sciences Third Quarter Results Scheduled for October 27",
                 "Acme doses first patient in the Phase 3 study"):
        assert A.classify(line) == (None, None), line


def test_a_miss_is_read_before_a_hit():
    """'did not meet its primary endpoint' contains the word meet, and the cheerful
    reading of that sentence is the expensive one."""
    outcome, words = A.classify("Acme announces TRIAL did not meet its primary endpoint")
    assert outcome == "missed" and "did not meet" in words.lower()


def test_a_hit_is_read_where_the_words_are_the_industry_s():
    assert A.classify("Lilly's Omvoh meets primary endpoint of clinical remission")[0] == "met"
    assert A.classify("Acme Announces Positive Topline Results from Study 3")[0] == "met"
    assert A.classify("Hibsago approved in the US for chronic hepatitis B")[0] == "met"


def test_a_discontinuation_is_a_miss():
    assert A.classify("Acme discontinues development of foobarmab")[0] == "missed"


def test_a_good_result_in_words_no_rule_can_defend_is_not_classified():
    """Significantly reduced proteinuria is a real result. The sentence the model would
    have to write to act on it is one no rule can defend, so it abstains."""
    assert A.classify(
        "Roche presents interim data showing sefaxersen significantly reduced "
        "proteinuria in people with IgA nephropathy") == (None, None)
    assert A.classify("Phase 3 RAINIER Results Supporting Best-in-Class Potential "
                      "Published") == (None, None)


def test_an_empty_headline_classifies_as_nothing():
    assert A.classify(None) == (None, None) and A.classify("   ") == (None, None)


# --- what reaches a gate -------------------------------------------------------------

def test_a_result_naming_an_asset_with_an_open_gate_is_proposed(tmp_path):
    path = _book(tmp_path, [("LLY", "u1", "Lilly's Omvoh meets primary endpoint",
                             "press_data_readout")])
    out = A.proposals(path, stakes_fn=_stakes(_gate()))
    assert len(out["proposals"]) == 1
    p = out["proposals"][0]
    assert (p["outcome"], p["asset_name"], p["catalyst_id"]) == ("met", "Omvoh", 7)
    assert p["pos_now"] == 0.5 and p["pos_after"] == 0.9
    assert p["rnpv_now"] == 500.0 and p["rnpv_after"] == 900.0


def test_a_miss_reads_the_failure_leg(tmp_path):
    path = _book(tmp_path, [("LLY", "u1", "Omvoh did not meet its primary endpoint",
                             "press_data_readout")])
    p = A.proposals(path, stakes_fn=_stakes(_gate()))["proposals"][0]
    assert p["outcome"] == "missed" and p["pos_after"] == 0.0 and p["rnpv_after"] == 0.0


def test_a_headline_naming_no_asset_on_the_book_proposes_nothing(tmp_path):
    path = _book(tmp_path, [("LLY", "u1", "Jaypirca meets primary endpoint",
                             "press_data_readout")])
    assert A.proposals(path, stakes_fn=_stakes(_gate()))["proposals"] == []


def test_naming_the_registry_number_is_a_stronger_match_than_naming_the_asset(tmp_path):
    """One company can run six studies on one molecule. A headline naming the trial
    decides that trial; one naming the asset says something happened near it."""
    path = _book(tmp_path, [("LLY", "u1", "Omvoh meets primary endpoint in NCT06661383",
                             "press_data_readout")])
    assert A.proposals(path, stakes_fn=_stakes(_gate()))["proposals"][0]["match"] == "trial"
    path2 = _book(tmp_path / "b", [("LLY", "u2", "Omvoh meets primary endpoint",
                                    "press_data_readout")])
    assert A.proposals(path2, stakes_fn=_stakes(_gate()))["proposals"][0]["match"] == "asset"


def test_a_gate_the_refresh_recomputes_is_shown_and_not_offered(tmp_path):
    """A resolution the next run overwrites is worse than none."""
    path = _book(tmp_path, [("LLY", "u1", "Omvoh meets primary endpoint",
                             "press_data_readout")])
    p = A.proposals(path, stakes_fn=_stakes(
        _gate(resolvable=False, resolve_note="switched off")))["proposals"][0]
    assert p["resolvable"] is False and p["resolve_note"] == "switched off"


def test_a_catalyst_already_resolved_is_not_proposed_again(tmp_path):
    path = _book(tmp_path, [("LLY", "u1", "Omvoh meets primary endpoint",
                             "press_data_readout")])
    conn = db.get_connection(path)
    conn.execute("INSERT INTO catalysts (id, company_id, catalyst_type, expected_date,"
                 " title, description) VALUES (7, 1, 'data readout', '2027-03-01',"
                 " 'Phase 3', 'NCT1 | resolved met, pos -> 0.9')")
    conn.commit(); conn.close()
    assert A.proposals(path, stakes_fn=_stakes(_gate()))["proposals"] == []


def test_a_deal_headline_is_never_read_for_an_outcome(tmp_path):
    path = _book(tmp_path, [("LLY", "u1", "Lilly to acquire Omvoh maker", "press_deal")])
    assert A.proposals(path, stakes_fn=_stakes(_gate()))["proposals"] == []


def test_how_far_the_gate_still_is_travels_with_the_proposal(tmp_path):
    path = _book(tmp_path, [("LLY", "u1", "Omvoh meets primary endpoint",
                             "press_data_readout")])
    future = (dt.date.today() + dt.timedelta(days=100)).isoformat()
    p = A.proposals(path, stakes_fn=_stakes(_gate(expected_date=future)))["proposals"][0]
    assert p["days_to_gate"] == 100
