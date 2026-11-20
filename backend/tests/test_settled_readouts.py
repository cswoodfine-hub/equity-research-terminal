"""A readout research has read and found to decide nothing, told apart from one nobody
has looked at.

Both are worth nil and only one of them is work. The book used to say the same sentence
for both, so 60 rows sat in a queue of which 28 were already finished.
"""

import pytest

import catalyst_scenarios as CS
import db
import forecast_view as V
import settled_readouts as S

_HEADER = "ticker,asset,nct_id,kind,basis\n"
_BASE = (("therapy_mode", None, "marketed"), ("base_revenue", 1198.0, None),
         ("revenue_growth_pct", 0.10, None), ("terminal_growth_pct", 0.0, None),
         ("growth_fade_years", 5, None), ("cogs_pct", 0.25, None),
         ("sga_pct", 0.23, None), ("rd_pct", 0.20, None), ("tax_rate", 0.11, None),
         ("wacc", 0.08, None), ("pos", 1.0, None),
         ("forecast_start_year", 2026, None), ("forecast_years", 10, None))


def _db(tmp_path):
    path = str(tmp_path / "settled.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AZN', 'AstraZeneca')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Tezspire', 1)")
    conn.execute("INSERT INTO indications (id, name) VALUES (1, 'Asthma')")
    conn.execute("INSERT INTO asset_indications (id, asset_id, indication_id, phase,"
                 " region) VALUES (5, 1, 1, 'Phase 3', 'US')")
    for key, value, text in _BASE:
        conn.execute("INSERT INTO assumptions (asset_id, region, scenario, key, value,"
                     " text_value, source) VALUES (1, 'US', 'base', ?, ?, ?, 'test')",
                     (key, value, text))
    conn.execute("INSERT INTO assumptions (asset_id, indication_id, region, scenario,"
                 " key, value, source) VALUES (1, 1, 'US', 'base',"
                 " 'base_pool_overlap_pct', 1.0, 'test')")
    conn.execute("INSERT INTO trials (nct_id, sponsor_company_id, asset_id, title, phase,"
                 " overall_status, primary_completion_date) VALUES ('NCT07363642', 1, 1,"
                 " 'Phase 3b Study in Patients With Severe Asthma', 'Phase 3',"
                 " 'Recruiting', date('now', '+90 days'))")
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, asset_indication_id,"
                 " catalyst_type, expected_date, title, description, source_url, status)"
                 " VALUES (10, 1, 1, 5, 'data readout', date('now', '+90 days'),"
                 " 'Phase 3, Tezspire', 'TAPER',"
                 " 'https://clinicaltrials.gov/study/NCT07363642', 'pending')")
    conn.commit(); conn.close()
    return path


def _file(tmp_path, body, monkeypatch, name="settled_readouts.csv", mod=S):
    path = tmp_path / name
    path.write_text(_HEADER + body if mod is S else body, encoding="utf-8")
    monkeypatch.setattr(mod, "CURATED", path)
    return path


_ROW = ("AZN,Tezspire,NCT07363642,evidence_generation,"
        "\"TAPER is single-arm descriptive step-down, with no control arm\"\n")


def test_a_readout_nobody_has_read_still_reads_as_work(tmp_path, monkeypatch):
    path = _db(tmp_path)
    # The fixture reuses a real study id, so the shipped file has to be out of the way:
    # without this the test reads the book's own row for it and proves nothing.
    _file(tmp_path, "", monkeypatch)
    rows = V.catalyst_stakes(path, "AZN")["unpriced"]
    assert [r["reason"] for r in rows] == ["in_the_base"]
    assert "none is on file" in rows[0]["why"]


def test_a_readout_research_has_read_says_so_instead(tmp_path, monkeypatch):
    path = _db(tmp_path)
    _file(tmp_path, _ROW, monkeypatch)
    rows = V.catalyst_stakes(path, "AZN")["unpriced"]
    assert [r["reason"] for r in rows] == ["settled_nil"]
    why = rows[0]["why"]
    assert "has read this study" in why
    assert "single-arm evidence generation" in why    # the kind
    assert "no control arm" in why                    # the filed basis
    assert why.endswith(".")


def test_the_basis_is_closed_into_a_sentence_once(tmp_path, monkeypatch):
    """None of the filed bases ends in a full stop, and the book guard reads every
    reason as prose."""
    path = _db(tmp_path)
    _file(tmp_path, "AZN,Tezspire,NCT07363642,in_label,\"the label covers it\"\n",
          monkeypatch)
    assert V.catalyst_stakes(path, "AZN")["unpriced"][0]["why"].endswith("it.")


def test_an_unknown_kind_is_named_rather_than_swallowed(tmp_path, monkeypatch):
    path = _db(tmp_path)
    _file(tmp_path, "AZN,Tezspire,NCT07363642,a_kind_nobody_defined,\"x y z\"\n",
          monkeypatch)
    conn = db.get_connection(path)
    assert S.unresolved(conn) == [
        "AZN Tezspire: unknown kind 'a_kind_nobody_defined'"]
    conn.close()


def test_an_asset_the_book_does_not_hold_is_named(tmp_path, monkeypatch):
    path = _db(tmp_path)
    _file(tmp_path, "AZN,Fasenra,NCT07363642,in_label,\"x y z\"\n", monkeypatch)
    conn = db.get_connection(path)
    assert S.unresolved(conn) == ["AZN Fasenra: no single asset of that name"]
    conn.close()


def test_settling_a_readout_is_reversible(tmp_path, monkeypatch):
    """The judgement is a row, so removing the row returns the readout to the queue."""
    path = _db(tmp_path)
    f = _file(tmp_path, _ROW, monkeypatch)
    assert V.catalyst_stakes(path, "AZN")["unpriced"][0]["reason"] == "settled_nil"
    f.write_text(_HEADER, encoding="utf-8")
    assert V.catalyst_stakes(path, "AZN")["unpriced"][0]["reason"] == "in_the_base"


def test_a_readout_no_free_source_prices_does_not_read_as_nil(tmp_path, monkeypatch):
    """Worth something and unpriced is not the same as worth nothing, so it takes its own
    reason and says the value would move."""
    path = _db(tmp_path)
    _file(tmp_path, "AZN,Tezspire,NCT07363642,no_citable_figure,"
          "\"AstraZeneca states no figure for the trial in any filing\"\n", monkeypatch)
    row = V.catalyst_stakes(path, "AZN")["unpriced"][0]
    assert row["reason"] == "no_free_data"
    assert "would move the value" in row["why"]
    assert "decides nothing" not in row["why"]
    assert "in any filing." in row["why"]


def test_the_two_verdicts_share_no_kind():
    assert not set(S.KINDS) & set(S.NO_FREE_DATA)


# --- the two judgements cannot both be made ---------------------------------

def test_no_study_is_both_settled_at_nil_and_priced_from_a_case():
    """One of the two is wrong. The shipped files must not disagree."""
    nil = {r["nct_id"].upper() for r in S.rows()}
    cased = {r["nct_id"].upper() for r in CS.rows()}
    assert nil & cased == set(), sorted(nil & cased)


def test_no_row_of_the_shipped_file_is_silently_ignored():
    conn = db.get_connection()
    try:
        assert S.unresolved(conn) == []
    finally:
        conn.close()


def test_every_shipped_row_names_a_kind_and_a_basis_worth_reading():
    for row in S.rows():
        assert row["kind"] in S.KINDS or row["kind"] in S.NO_FREE_DATA, row["nct_id"]
        assert len(row["basis"]) > 30, row["nct_id"]
