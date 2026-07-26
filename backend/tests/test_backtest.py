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
    assert round(windows["runup_1w"]["mean_abnormal"], 4) == 0.10
    assert round(windows["after_1w"]["mean_abnormal"], 4) == 0.0909
    assert windows["after_1w"]["hit_rate"] == 1.0
    assert "runup_1m" not in windows          # off the start of the series, so unmeasured
