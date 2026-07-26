"""Backtest: forward and abnormal returns over a deterministic price series, and the
aggregation of a resolved change event. No network."""

import backtest
import db
import seed

_DATES = [f"2026-03-{d:02d}" for d in range(2, 12)]   # 10 trading days, 03-02..03-11


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

    # Event dated 03-03 (index 1). LLY rises to +10% five bars later; the rest are flat,
    # so LLY's abnormal five-day return is a clean +10%.
    prices(cid["LLY"], [100, 100, 102, 104, 106, 108, 110, 110, 110, 110])
    prices(cid["MRK"], [50] * 10)
    prices(cid["PFE"], [50] * 10)

    asset = conn.execute("INSERT INTO assets (owner_company_id, brand_name, internal_code)"
                         " VALUES (?, 'Zepbound', 'NDA1')", (cid["LLY"],)).lastrowid
    conn.execute("INSERT INTO approvals (asset_id, application_number, approval_date)"
                 " VALUES (?, 'NDA1', '2026-03-03')", (asset,))
    conn.execute("INSERT INTO changes (entity_type, entity_key, field, change_type,"
                 " significance) VALUES ('approval', 'NDA1', 'x', 'new_approval', 'high')")
    # A trial change has no event date and must be excluded, not measured.
    conn.execute("INSERT INTO changes (entity_type, entity_key, field, change_type,"
                 " significance) VALUES ('trial', 'NCT9', 'status', 'status_change', 'low')")
    conn.commit()
    conn.close()
    return cid


def test_forward_and_universe_returns(tmp_path):
    db_file = tmp_path / "t.db"
    cid = _seed(db_file)
    conn = db.get_connection(db_file)
    try:
        series = backtest._series(conn)
    finally:
        conn.close()
    assert round(backtest.forward_return(series, cid["LLY"], "2026-03-03", 5), 4) == 0.10
    assert round(backtest.forward_return(series, cid["LLY"], "2026-03-03", 1), 4) == 0.02
    # The rest of the universe is flat, so the benchmark is zero.
    assert backtest.universe_return(series, "2026-03-03", 5, exclude=cid["LLY"]) == 0.0
    # A window that runs off the end of the series is None, never guessed.
    assert backtest.forward_return(series, cid["LLY"], "2026-03-11", 5) is None


def test_build_measures_the_approval_and_skips_the_trial(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    result = backtest.build(db_file)

    assert result["total_changes"] == 2 and result["measured_events"] == 1
    assert [r["change_type"] for r in result["rows"]] == ["new_approval"]
    five = result["rows"][0]["horizons"][5]
    assert five["n"] == 1 and round(five["mean_abnormal"], 4) == 0.10
    assert five["hit_rate"] == 1.0
