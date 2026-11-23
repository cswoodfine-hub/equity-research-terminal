"""Backtest: span returns before and after an event over a deterministic price series,
and the aggregation of a resolved change. No network."""

import backtest
import db
import seed

_DATES = [f"2026-03-{d:02d}" for d in range(2, 27)]   # 25 bars, 03-02..03-26

# Flat, then a run-up of 100 -> 110 into the event at index 12, then 110 -> 120 after it.
_LLY = [100] * 8 + [102, 104, 106, 108, 110, 112, 114, 116, 118, 120] + [120] * 7
_EVENT = _DATES[12]                                    # 2026-03-14


def _seed(db_file):
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    cid = {tk: conn.execute("SELECT id FROM companies WHERE ticker = ?",
                            (tk,)).fetchone()[0] for tk in ("LLY", "MRK", "PFE")}

    def prices(company_id, closes):
        for day, close in zip(_DATES, closes):
            conn.execute("INSERT INTO prices (company_id, as_of, close, interval, source)"
                         " VALUES (?, ?, ?, '1d', 'test')", (company_id, day, close))

    prices(cid["LLY"], _LLY)
    prices(cid["MRK"], [50] * 25)                      # flat, so the benchmark is zero
    prices(cid["PFE"], [50] * 25)

    asset = conn.execute("INSERT INTO assets (owner_company_id, brand_name, internal_code)"
                         " VALUES (?, 'Zepbound', 'NDA1')", (cid["LLY"],)).lastrowid
    conn.execute("INSERT INTO approvals (asset_id, application_number, approval_date)"
                 " VALUES (?, 'NDA1', ?)", (asset, _EVENT))
    conn.execute("INSERT INTO changes (entity_type, entity_key, field, change_type,"
                 " significance) VALUES ('approval', 'NDA1', 'x', 'new_approval', 'high')")
    # A trial change has no event date and must be excluded, not measured.
    conn.execute("INSERT INTO changes (entity_type, entity_key, field, change_type,"
                 " significance) VALUES ('trial', 'NCT9', 'status', 'status_change', 'low')")
    conn.commit()
    conn.close()
    return cid


def test_span_return_reads_before_and_after_the_event(tmp_path):
    db_file = tmp_path / "t.db"
    cid = _seed(db_file)
    conn = db.get_connection(db_file)
    try:
        series = backtest._series(conn)
    finally:
        conn.close()
    # run-up over the five bars into the event: 100 -> 110.
    assert round(backtest.span_return(series, cid["LLY"], _EVENT, -5, 0), 4) == 0.10
    # reaction over the five bars after: 110 -> 120.
    assert round(backtest.span_return(series, cid["LLY"], _EVENT, 0, 5), 4) == 0.0909
    # the rest of the universe is flat, so the benchmark is zero.
    assert backtest.universe_span(series, _EVENT, -5, 0, exclude=cid["LLY"]) == 0.0
    # a window running off the series is None, never guessed.
    assert backtest.span_return(series, cid["LLY"], _EVENT, -21, 0) is None


def test_build_reports_runup_and_reaction_and_skips_the_trial(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    result = backtest.build(db_file)

    assert result["total_changes"] == 2 and result["measured_events"] == 1
    assert [r["change_type"] for r in result["rows"]] == ["new_approval"]
    windows = result["rows"][0]["windows"]
    # An approval carries a date and no time, so the last close before it is the day
    # before's (108) and the reaction is given two sessions (to 112).
    assert round(windows["runup_1w"]["mean_abnormal"], 4) == 0.08         # 100 -> 108
    assert round(windows["after_1d"]["mean_abnormal"], 4) == 0.037        # 108 -> 112
    assert round(windows["after_1w"]["mean_abnormal"], 4) == 0.0714       # 112 -> 120
    assert windows["after_1w"]["hit_rate"] == 1.0
    assert "runup_1m" not in windows          # off the start of the series, so unmeasured
    assert result["rows"][0]["timing"] == {"timed": 0, "date only": 1}


def test_trial_readouts_enter_the_study_by_phase_and_sign(tmp_path):
    db_file = tmp_path / "t.db"
    cid = _seed(db_file)
    conn = db.get_connection(db_file)
    # A Phase 3 positive readout on the same event date rides the same +10% run-up.
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase,"
                 " outcome, event_date) VALUES ('r1', ?, 'Zepbound', 3, 'positive', ?)",
                 (cid["LLY"], _EVENT))
    conn.commit()
    conn.close()
    result = backtest.build(db_file)
    types = {r["change_type"] for r in result["rows"]}
    assert "phase3_positive" in types
    row = next(r for r in result["rows"] if r["change_type"] == "phase3_positive")
    assert round(row["windows"]["after_1w"]["mean_abnormal"], 4) == 0.0714


def _readout_with_filing(db_file, cid, accepted_at, filed):
    conn = db.get_connection(db_file)
    conn.execute("INSERT INTO filings (company_id, form_type, filed_date, accession,"
                 " accepted_at) VALUES (?, '8-K', ?, 'r9', ?)", (cid, filed, accepted_at))
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase,"
                 " outcome, event_date) VALUES ('r9', ?, 'Zepbound', 3, 'negative', ?)",
                 (cid, filed))
    conn.commit()
    conn.close()


def test_a_result_filed_before_the_open_has_its_reaction_counted_as_the_reaction(tmp_path):
    """Filed at 07:30 in New York on the event day: the day's own move is the reaction.
    Measured from that day's close, as it used to be, the move sat in the run-up."""
    db_file = tmp_path / "t.db"
    cid = _seed(db_file)
    _readout_with_filing(db_file, cid["LLY"], f"{_EVENT}T11:30:00.000Z", _EVENT)
    row = next(r for r in backtest.build(db_file)["rows"]
               if r["change_type"] == "phase3_negative")
    assert row["timing"] == {"timed": 1, "date only": 0}
    assert round(row["windows"]["after_1d"]["mean_abnormal"], 4) == 0.0185   # 108 -> 110
    assert round(row["windows"]["runup_1w"]["mean_abnormal"], 4) == 0.08     # 100 -> 108
    assert round(row["windows"]["after_1w"]["mean_abnormal"], 4) == 0.0909   # 110 -> 120


def test_a_result_filed_after_the_close_is_given_two_sessions(tmp_path):
    """Filed at 17:00 in New York: the release may have gone out that day or after the
    bell, so the reaction runs from the close before to the close after."""
    db_file = tmp_path / "t.db"
    cid = _seed(db_file)
    _readout_with_filing(db_file, cid["LLY"], f"{_EVENT}T21:00:00.000Z", _EVENT)
    row = next(r for r in backtest.build(db_file)["rows"]
               if r["change_type"] == "phase3_negative")
    assert round(row["windows"]["after_1d"]["mean_abnormal"], 4) == 0.037    # 108 -> 112
    assert round(row["windows"]["after_1w"]["mean_abnormal"], 4) == 0.0714   # 112 -> 120
