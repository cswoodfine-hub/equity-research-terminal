"""The earliest approval a pipeline asset can have, beside the year the model starts it.

A flag and nothing more: every test here is about what the floor reads, which evidence
wins, and that the status only ever says what the evidence allows. None of it may reach a
value, which test_forecast_view's purity test and the book's invariance check hold.
"""

import datetime as dt
import json

import pytest

import db
import launch_timing as L

TODAY = dt.date(2026, 10, 5)


def _seed(tmp_path):
    path = str(tmp_path / "launch.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name, reporting_currency)"
                 " VALUES (1, 'LLY', 'Lilly', 'USD')")
    conn.execute("INSERT INTO indications (id, name, mesh_id) VALUES"
                 " (10, 'Obesity', 'D009765'), (11, 'Heart Failure', 'D006333')")
    conn.commit()
    return conn


def _asset(conn, asset_id, generic, *, marketed=0, seed=2027,
           source="convention: first full year after the current one", code=None):
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, internal_code,"
                 " is_marketed) VALUES (?, 1, ?, ?, ?)", (asset_id, generic, code, marketed))
    conn.execute("INSERT INTO asset_indications (asset_id, indication_id, phase, is_lead,"
                 " region) VALUES (?, 10, 'Phase 3', 1, 'US')", (asset_id,))
    if seed is not None:
        conn.execute("INSERT INTO assumptions (asset_id, key, value, unit, source)"
                     " VALUES (?, 'forecast_start_year', ?, 'year', ?)",
                     (asset_id, seed, source))
    conn.commit()


def _trial(conn, nct, asset_id, pcd, *, phase="Phase 3", status="Recruiting",
           kind="estimated", condition="Obesity", mesh=("D009765", "Obesity"),
           fetched="2026-10-05 05:00:00", enrollment=1000):
    browse = json.dumps({"meshes": [{"id": mesh[0], "term": mesh[1]}], "ancestors": []}
                        ) if mesh else None
    conn.execute("INSERT INTO trials (nct_id, asset_id, phase, overall_status,"
                 " primary_completion_date, primary_completion_type, enrollment,"
                 " conditions, mesh_terms, title, fetched_at)"
                 " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (nct, asset_id, phase, status, pcd, kind, enrollment,
                  json.dumps([condition]), browse, f"A study {nct}", fetched))
    conn.commit()


def _floor(conn, asset_id, **kwargs):
    kwargs.setdefault("legs", None)
    return L.for_asset(conn, asset_id, TODAY, **kwargs)


# --- the curated files ---------------------------------------------------------------

def test_every_clock_row_is_sourced_and_the_program_arithmetic_is_pinned():
    """A new molecule's priority clock is 6 months from a filing date 60 days after
    receipt, and every other clock starts at receipt. Every row carries the letter's
    section and its source, and the shipped file has no biosimilar or voucher row until
    those are read."""
    clock = L.review_clock()
    assert clock, "data/fda_review_clock.csv is missing"
    for key, row in clock.items():
        assert row["source"] and row["basis"] and row["as_of"], key
        assert "151712" in row["source"], key
        assert "193977" in row["carries_to"], key
    assert clock[("nme_nda_or_original_bla", "priority")]["months"] == 6
    assert clock[("nme_nda_or_original_bla", "standard")]["months"] == 10
    assert clock[("nme_nda_or_original_bla", "priority")]["filing_period_days"] == 60
    assert clock[("nme_nda_or_original_bla", "standard")]["filing_period_days"] == 60
    assert clock[("efficacy_supplement", "priority")]["months"] == 6
    assert clock[("efficacy_supplement", "standard")]["months"] == 10
    assert all(row["filing_period_days"] == 0 for (pathway, _), row in clock.items()
               if pathway != "nme_nda_or_original_bla")
    assert "8.0 months" in clock[("nme_nda_or_original_bla", "priority")]["cross_check"]
    assert "12.0 months" in clock[("nme_nda_or_original_bla", "standard")]["cross_check"]
    assert not any(p == "biosimilar_351k" or p == "cnpv" for p, _ in clock)


def test_the_voucher_register_ships_empty_until_it_is_transcribed():
    assert L.vouchers() == []
    with L.VOUCHERS.open(encoding="utf-8") as handle:
        header = [line for line in handle if not line.startswith("#")][0].strip()
    assert header == "product,sponsor,asset_name_match,awarded,source_url"


def test_a_missing_clock_file_reads_no_clock_and_never_flags(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran")
    _trial(conn, "NCT00000001", 1, "2028-03-31")
    got = _floor(conn, 1, clock=L.review_clock(tmp_path / "missing.csv"))
    conn.close()
    assert L.review_clock(tmp_path / "missing.csv") == {}
    assert got["status"] == "no_clock" and got["flag"] is None


# --- dates ---------------------------------------------------------------------------

def test_a_month_only_date_is_the_first_and_months_are_calendar_months():
    assert L.parse_date("2028-03") == dt.date(2028, 3, 1)
    assert L.parse_date("2028-03-31") == dt.date(2028, 3, 31)
    assert L.parse_date("2028") == dt.date(2028, 1, 1)
    assert L.parse_date("Q1 2027") is None and L.parse_date(None) is None
    assert L.add_months(dt.date(2028, 3, 31), 8) == dt.date(2028, 11, 30)
    assert L.add_months(dt.date(2027, 6, 30), 8) == dt.date(2028, 2, 29)
    assert L.add_months(dt.date(2027, 11, 15), 2) == dt.date(2028, 1, 15)


def test_the_filing_period_is_sixty_days_and_not_two_calendar_months(tmp_path):
    """21 CFR 314.101(a)(2): the filing date is 60 days after receipt, and the Program
    clock runs from it. Two calendar months from 1 May is 1 July, 61 days, which put the
    priority goal on 1 January 2029 and a seed of 2028 in the red; 60 days files on 30
    June and the goal is 30 December 2028, the approval year itself."""
    clock = L.review_clock()
    nme = clock[("nme_nda_or_original_bla", "priority")]
    assert L.review_ends(dt.date(2028, 5, 1), nme) == dt.date(2028, 12, 30)
    assert L.review_ends(dt.date(2029, 5, 1), nme) == dt.date(2029, 12, 30)
    assert L.review_ends(dt.date(2028, 5, 1),
                         clock[("efficacy_supplement", "priority")]) == dt.date(2028, 11, 1)
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran", seed=2028)
    _trial(conn, "NCT05581303", 1, "2028-05")
    got = _floor(conn, 1)
    conn.close()
    assert got["decision_date"] == "2028-12-30"
    assert got["status"] == "part_year" and got["flag"] is None
    assert got["standard"]["decision_date"] == "2029-04-30"
    assert "6 months from a filing date 60 days after receipt" in got["message"]


# --- the floor and its status --------------------------------------------------------

def test_a_seed_before_the_registry_allows_is_red_with_both_years(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran")
    _trial(conn, "NCT05581303", 1, "2028-03-31")
    got = _floor(conn, 1)
    conn.close()
    assert got["status"] == "before_floor" and got["flag"] == "red"
    assert got["decision_date"] == "2028-11-30"
    assert (got["first_possible_year"], got["first_full_year"]) == (2028, 2029)
    assert got["standard"]["decision_date"] == "2029-03-30"
    assert got["standard"]["first_full_year"] == 2030
    assert got["evidence"]["kind"] == "registry"
    assert got["evidence"]["nct_id"] == "NCT05581303"
    assert got["clock"]["pathway"] == "nme_nda_or_original_bla"
    assert got["clock"]["months"] == 6 and got["clock"]["filing_period_days"] == 60
    assert got["clock"]["applied"] is True
    assert got["message"].startswith("2027 in the model")
    assert "NCT05581303" in got["message"] and "Nov 2028" in got["message"]


def test_the_seed_year_equal_to_the_decision_year_is_a_part_year(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran", seed=2028)
    _trial(conn, "NCT05581303", 1, "2028-03-31")
    part = _floor(conn, 1)
    conn.execute("UPDATE assumptions SET value = 2029 WHERE asset_id = 1")
    conn.commit()
    clear = _floor(conn, 1)
    conn.close()
    assert part["status"] == "part_year" and part["flag"] is None
    assert clear["status"] == "clear" and clear["flag"] is None


def test_the_earliest_live_phase_3_governs_and_dead_ones_are_ignored(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran")
    for nct, status in (("NCT00000001", "Withdrawn"), ("NCT00000002", "Terminated"),
                        ("NCT00000003", "Suspended")):
        _trial(conn, nct, 1, "2026-01-01", status=status)
    _trial(conn, "NCT00000004", 1, "2026-01-01", phase="Phase 2")
    _trial(conn, "NCT00000005", 1, "2029-01-01")
    _trial(conn, "NCT00000006", 1, "2028-06-01", phase="Phase 2/3")
    got = _floor(conn, 1)
    conn.close()
    assert got["evidence"]["nct_id"] == "NCT00000006"
    assert got["trials_considered"] == 2


def test_a_positive_phase_3_readout_outranks_the_registry(tmp_path):
    """Data in hand. The readout is read through pos_granular.stage_of, the same reading
    that places the asset, so the floor and the probability never disagree on it."""
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran")
    _trial(conn, "NCT05581303", 1, "2028-03-31")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome,"
                 " event_date) VALUES ('0000-26-1', 1, 'olpasiran', 3, 'positive',"
                 " '2026-08-19')")
    conn.commit()
    got = _floor(conn, 1)
    conn.close()
    assert got["evidence"]["kind"] == "readout"
    assert got["evidence"]["date"] == "2026-08-19"
    assert got["decision_date"] == "2027-04-18"
    assert got["status"] == "part_year"
    assert got["if_filed_today"] == "2027-06-04"
    assert "read out positive 19 Aug 2026" in got["message"]


def test_good_news_never_makes_the_floor_later(tmp_path):
    """A Phase 3 completed 15 Jan 2026 and the seed of 2027 reads clear. Resolving its
    readout met on 10 May 2027 names the readout as the evidence, but the floor stays
    where the completion put it: a readout recorded later must not push the earliest
    approval into 2028 and turn a clear asset red."""
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran", seed=2027)
    _trial(conn, "NCT05581303", 1, "2026-01-15", status="Completed", kind="actual")
    before = L.for_asset(conn, 1, dt.date(2027, 5, 10), legs=None)
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type,"
                 " expected_date, title, description, is_curated, source_url, status,"
                 " updated_at) VALUES (9, 1, 1, 'data readout', '2026-03-01',"
                 " 'Phase 3, a study', 'NCT05581303', 0,"
                 " 'https://clinicaltrials.gov/study/NCT05581303', 'met',"
                 " '2027-05-10 09:00:00')")
    conn.commit()
    after = L.for_asset(conn, 1, dt.date(2027, 5, 10), legs=None)
    conn.close()
    assert before["evidence"]["kind"] == "registry" and before["status"] == "clear"
    assert before["decision_date"] == "2026-09-16"
    assert after["evidence"]["kind"] == "readout"
    assert after["evidence"]["date"] == "2027-05-10"
    assert after["decision_date"] == "2026-09-16" and after["status"] == "clear"
    assert after["evidence"]["floor_from"] == {"kind": "readout", "nct_id": "NCT05581303",
                                               "date": "2026-01-15"}
    assert "read out positive 10 May 2027" in after["message"]
    assert "NCT05581303's primary completion, 15 Jan 2026" in after["message"]


def test_the_earliest_positive_readout_dates_the_floor(tmp_path):
    """Two positive readouts on file: the floor runs from January's, not June's."""
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran", seed=2027)
    _trial(conn, "NCT05581303", 1, "2028-03-31")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome,"
                 " event_date) VALUES ('0000-26-1', 1, 'olpasiran', 3, 'positive',"
                 " '2026-01-20'), ('0000-26-2', 1, 'olpasiran', 3, 'positive',"
                 " '2026-06-01')")
    conn.commit()
    got = _floor(conn, 1)
    conn.close()
    assert got["evidence"]["kind"] == "readout" and got["evidence"]["date"] == "2026-06-01"
    assert got["evidence"]["floor_from"]["date"] == "2026-01-20"
    assert got["decision_date"] == "2026-09-21" and got["status"] == "clear"
    assert "an earlier Phase 3 readout, 20 Jan 2026" in got["message"]


def test_a_registry_completion_before_the_readout_dates_the_floor(tmp_path):
    """The readout names the evidence; a live Phase 3 that completed before it was
    announced still dates the floor, as it would with no readout at all."""
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran", seed=2027)
    _trial(conn, "NCT05581303", 1, "2026-01-10", status="Active, not recruiting",
           kind="actual")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome,"
                 " event_date) VALUES ('0000-26-1', 1, 'olpasiran', 3, 'positive',"
                 " '2026-04-20')")
    conn.commit()
    got = _floor(conn, 1)
    conn.close()
    assert got["evidence"]["kind"] == "readout"
    assert got["evidence"]["floor_from"] == {"kind": "registry", "nct_id": "NCT05581303",
                                             "date": "2026-01-10"}
    assert got["decision_date"] == "2026-09-11"


def test_an_accepted_application_sets_the_decision_date_itself(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran")
    _trial(conn, "NCT05581303", 1, "2028-03-31")
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type,"
                 " expected_date, title, description, status) VALUES (5, 1, 1, 'PDUFA',"
                 " '2026-11-30', 'Olpasiran PDUFA, obesity', 'FDA accepted it.', 'pending')")
    conn.commit()
    got = _floor(conn, 1)
    conn.close()
    assert got["status"] == "clear"
    assert got["evidence"]["kind"] == "accepted" and got["evidence"]["catalyst_id"] == 5
    assert got["decision_date"] == "2026-11-30" and got["first_possible_year"] == 2026
    assert got["clock"]["applied"] is False
    assert "due 30 Nov 2026" in got["message"]


def test_a_supplemental_application_is_left_out_and_named(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran")
    _trial(conn, "NCT05581303", 1, "2028-03-31")
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type,"
                 " expected_date, title, description, status) VALUES (5, 1, 1, 'PDUFA',"
                 " '2026-11-30', 'Olpasiran PDUFA, obesity', 'FDA accepts the sBLA.',"
                 " 'pending')")
    conn.commit()
    filings = L._filings(conn, 1, TODAY.isoformat())
    got = _floor(conn, 1)
    conn.close()
    assert filings["ahead"] is None and filings["supplements"][0]["catalyst_id"] == 5
    assert got["evidence"]["kind"] == "registry" and got["status"] == "before_floor"


def test_a_passed_decision_on_an_unmarketed_asset_is_reported_and_never_flagged(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran", seed=2026)
    _trial(conn, "NCT05581303", 1, "2028-03-31")
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type,"
                 " expected_date, title, description, status) VALUES (5, 1, 1, 'PDUFA',"
                 " '2026-08-22', 'Olpasiran PDUFA, obesity', 'FDA accepted it.', 'pending')")
    conn.commit()
    got = _floor(conn, 1)
    conn.close()
    assert got["status"] == "decision_passed" and got["flag"] is None
    assert "22 Aug 2026" in got["message"]


def test_a_seed_that_cites_a_filing_is_amber_and_a_negated_one_is_not(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran",
           source="the first full year after a PDUFA target action date of November 30, "
                  "2026 (6-K 0001-26-1)")
    _asset(conn, 2, "Lepodisiran",
           source="judgement. No filing, acceptance or PDUFA date is stated")
    _trial(conn, "NCT00000001", 1, "2028-03-31")
    _trial(conn, "NCT00000002", 2, "2028-03-31")
    cited, plain = _floor(conn, 1), _floor(conn, 2)
    conn.close()
    assert cited["status"] == "before_floor_cited" and cited["flag"] == "amber"
    assert cited["seed_basis"] == {"cites": "filing", "match": "PDUFA"}
    assert "record it" in cited["message"]
    assert plain["status"] == "before_floor" and plain["seed_basis"]["cites"] is None


def test_a_readout_cited_in_the_seed_also_softens_the_flag():
    assert L.seed_basis("INTerpath-001 met its primary endpoint at an interim analysis"
                        )["cites"] == "readout"
    assert L.seed_basis("convention: first full year after the current one")["cites"] is None


def test_the_pathway_is_read_from_the_asset_and_says_how(tmp_path):
    """A molecule the company already sells files a supplement, on a 6-month priority
    clock from receipt with no filing period; an ABP code is a biosimilar, for which no
    clock is on file until the BsUFA letter is read."""
    conn = _seed(tmp_path)
    _asset(conn, 1, "Tirzepatide", seed=2027)
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, brand_name,"
                 " is_marketed) VALUES (2, 1, 'Tirzepatide', 'Zepbound', 1)")
    _asset(conn, 3, "ABP 206", seed=2027)
    conn.commit()
    _trial(conn, "NCT00000001", 1, "2027-03-31")
    _trial(conn, "NCT00000003", 3, "2027-03-31")
    supplement, biosimilar = _floor(conn, 1), _floor(conn, 3)
    conn.close()
    assert supplement["clock"]["pathway"] == "efficacy_supplement"
    assert "Zepbound" in supplement["clock"]["pathway_how"]
    assert supplement["decision_date"] == "2027-09-30"
    assert supplement["standard"]["months"] == 10
    assert biosimilar["status"] == "no_clock" and biosimilar["flag"] is None
    assert "BsUFA" in biosimilar["message"]


def test_a_voucher_holder_keeps_the_priority_clock_until_the_programme_has_a_row(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran")
    _trial(conn, "NCT05581303", 1, "2028-03-31")
    held = [{"product": "Olpasiran", "sponsor": "Lilly", "asset_name_match": "olpasiran",
             "awarded": "2026-04-24", "source_url": "https://www.fda.gov/x"}]
    without = _floor(conn, 1, voucher_rows=held)
    clock = {**L.review_clock(), ("cnpv", "any"): {
        "pathway": "cnpv", "review": "any", "months": 1, "basis": "a test row",
        "source": "a test", "carries_to": "", "cross_check": "", "as_of": "2026-10-05"}}
    applied = _floor(conn, 1, voucher_rows=held, clock=clock)
    conn.close()
    assert without["voucher"]["applied"] is False and without["clock"]["months"] == 6
    assert applied["voucher"]["applied"] is True
    assert applied["decision_date"] == "2028-04-30"


def test_the_last_slip_shows_the_floor_before_and_after(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran")
    _trial(conn, "NCT05581303", 1, "2028-03-31")
    conn.execute("INSERT INTO changes (entity_type, entity_key, field, old_value,"
                 " new_value, change_type, significance, detected_at) VALUES ('trial',"
                 " 'NCT05581303', 'primary_completion_date', '2027-01-31', '2028-03-31',"
                 " 'date_slip', 'medium', '2026-09-30 05:00:00')")
    conn.commit()
    got = _floor(conn, 1)
    conn.close()
    assert got["slip"]["old"] == "2027-01-31" and got["slip"]["new"] == "2028-03-31"
    assert (got["slip"]["floor_before"], got["slip"]["floor_after"]) == (2027, 2028)


def test_a_later_floor_in_the_modelled_disease_is_shown_and_does_not_decide(tmp_path):
    """The asset-wide floor is the lenient one, so a study missing from the modelled
    disease can never create a flag; the modelled disease's own floor sits beside it."""
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran", seed=2028)
    conn.execute("INSERT INTO assumptions (asset_id, indication_id, key, value, source)"
                 " VALUES (1, 10, 'prevalence', 1000000, 'x')")
    conn.commit()
    _trial(conn, "NCT00000001", 1, "2027-01-31", condition="Heart Failure",
           mesh=("D006333", "Heart Failure"))
    _trial(conn, "NCT00000002", 1, "2028-06-30")
    got = _floor(conn, 1)
    conn.close()
    assert got["evidence"]["nct_id"] == "NCT00000001"
    assert got["status"] == "clear"
    assert got["modelled_floor"]["nct_id"] == "NCT00000002"
    assert got["modelled_floor"]["first_possible_year"] == 2029


def test_a_study_not_seen_on_the_active_list_is_marked_stale(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran")
    _trial(conn, "NCT05581303", 1, "2028-03-31", fetched="2026-09-01 05:00:00")
    got = _floor(conn, 1)
    conn.close()
    assert got["evidence"]["stale"] is True


def test_nil_probability_or_a_failed_phase_3_is_not_assessed(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran")
    conn.execute("INSERT INTO assumptions (asset_id, key, value, source)"
                 " VALUES (1, 'pos', 0, 'stopped')")
    _asset(conn, 2, "Lepodisiran")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome,"
                 " event_date) VALUES ('0000-26-2', 1, 'lepodisiran', 3, 'negative',"
                 " '2026-08-19')")
    conn.commit()
    nil, failed = _floor(conn, 1), _floor(conn, 2)
    conn.close()
    assert nil["status"] == failed["status"] == "not_assessed"
    assert nil["flag"] is None and failed["flag"] is None


def test_nothing_to_date_from_draws_no_floor(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran")
    _trial(conn, "NCT00000001", 1, "2027-01-31", phase="Phase 2")
    got = _floor(conn, 1)
    conn.close()
    assert got["status"] == "no_registry_basis" and got["flag"] is None


def test_a_marketed_asset_or_one_with_no_seed_has_no_floor(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Tirzepatide", marketed=1)
    _asset(conn, 2, "Olpasiran", seed=None)
    assert _floor(conn, 1) is None and _floor(conn, 2) is None
    conn.close()


def test_a_scenario_start_year_is_read_before_base(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran")
    conn.execute("INSERT INTO assumptions (asset_id, scenario, key, value, source)"
                 " VALUES (1, 'bull', 'forecast_start_year', 2030, 'bull case')")
    conn.commit()
    _trial(conn, "NCT05581303", 1, "2028-03-31")
    bull, bear = _floor(conn, 1, scenario="bull"), _floor(conn, 1, scenario="bear")
    conn.close()
    assert (bull["seed_year"], bull["seed_scenario"], bull["status"]) == (2030, "bull", "clear")
    assert (bear["seed_year"], bear["seed_scenario"]) == (2027, "base")


# --- the next gate -------------------------------------------------------------------

def _legs(gate, nct=None, date=None, due=False, why=None):
    return {"gate": gate, "label": {"p2_to_p3": "Phase 2 readout",
                                    "p3_to_nda": "Phase 3 readout",
                                    "nda_to_approval": "FDA decision"}[gate],
            "trial": {"nct_id": nct} if nct else None, "date": date, "due": due,
            "why": why}


def test_the_gate_study_is_named_where_it_is_not_the_one_that_sets_the_floor(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran")
    _trial(conn, "NCT05581303", 1, "2028-03-31")
    _trial(conn, "NCT07293260", 1, "2028-06-15")
    other = _floor(conn, 1, legs=_legs("p3_to_nda", "NCT07293260", "2028-06-15"))
    same = _floor(conn, 1, legs=_legs("p3_to_nda", "NCT05581303", "2028-03-31"))
    conn.close()
    assert other["gate"]["decision_date"] == "2029-02-14"
    assert other["gate"]["first_full_year"] == 2030
    assert "The gate study is NCT07293260, completing 15 Jun 2028" in other["message"]
    assert "Feb 2029" in other["message"]
    assert same["gate"]["same_as_governing"] is True
    assert "gate study" not in same["message"]


def test_a_phase_2_gate_or_an_undated_fda_gate_gives_no_approval_date(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran")
    _trial(conn, "NCT05581303", 1, "2028-03-31")
    p2 = _floor(conn, 1, legs=_legs("p2_to_p3", "NCT00000009", "2027-05-01"))
    fda = _floor(conn, 1, legs=_legs("nda_to_approval", why="no accepted application"))
    dated = _floor(conn, 1, legs=_legs("nda_to_approval", date="2026-11-30"))
    conn.close()
    assert p2["gate"]["decision_date"] is None and "Phase 2" in p2["gate"]["why"]
    assert "The next gate is a Phase 2 readout, NCT00000009" in p2["message"]
    assert fda["gate"]["decision_date"] is None and fda["gate"]["why"]
    assert dated["gate"]["decision_date"] == "2026-11-30"


# --- reads only, and house style -----------------------------------------------------

def test_the_floor_writes_nothing(tmp_path):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran")
    _trial(conn, "NCT05581303", 1, "2028-03-31")
    before = conn.total_changes
    _floor(conn, 1)
    L.for_company(conn, 1, TODAY)
    assert conn.total_changes == before
    conn.close()


@pytest.mark.parametrize("seed, pcd", [(2027, "2028-03-31"), (2028, "2028-03-31"),
                                       (2030, "2028-03-31")])
def test_every_message_is_in_house_style(tmp_path, seed, pcd):
    conn = _seed(tmp_path)
    _asset(conn, 1, "Olpasiran", seed=seed)
    _trial(conn, "NCT05581303", 1, pcd)
    _trial(conn, "NCT07293260", 1, "2028-06-15")
    got = _floor(conn, 1, legs=_legs("p3_to_nda", "NCT07293260", "2028-06-15", due=True))
    conn.close()
    text = got["message"]
    assert "—" not in text and "–" not in text
    for word in ("additionally", "highlight", "underscore", "pivotal", "showcase",
                 "testament"):
        assert word not in text.lower()
    assert text[0].isdigit() or text[0].isupper()


def test_the_summary_carries_what_a_rollup_line_needs():
    full = {"status": "before_floor", "flag": "red", "seed_year": 2027,
            "first_possible_year": 2028, "first_full_year": 2029,
            "decision_date": "2028-11-30", "message": "m",
            "evidence": {"kind": "registry", "nct_id": "NCT1", "date": "2028-03-31"}}
    assert L.summary(full) == {"status": "before_floor", "flag": "red", "seed_year": 2027,
                               "first_possible_year": 2028, "first_full_year": 2029,
                               "decision_date": "2028-11-30", "message": "m",
                               "evidence_kind": "registry", "nct_id": "NCT1",
                               "evidence_date": "2028-03-31"}
    assert L.summary(None) is None
