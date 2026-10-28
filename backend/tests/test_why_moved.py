"""Why a value moved: the three histories read together.

The rule under test is restraint. It states what provably held still, names what changed,
and refuses to divide a move into shares the records cannot defend.
"""

import db
import why_moved as W

CALL = dict(cohort="pharma", price=100.0, price_date="2026-10-20", cost_of_equity=0.08,
            target_mid=120.0, pe_mid=90.0, ev_sales_mid=95.0, precedents_mid=88.0)


def _book(tmp_path, calls):
    path = str(tmp_path / "w.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1,'LLY','Lilly')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, modality,"
                 " is_marketed) VALUES (1, 1, 'Verzenio', 'small molecule', 1)")
    for day, fields in calls:
        row = {**CALL, **fields, "as_of": day, "ticker": "LLY"}
        conn.execute(f"INSERT INTO model_calls ({', '.join(row)}) VALUES "
                     f"({', '.join('?' * len(row))})", list(row.values()))
    conn.commit(); conn.close()
    return path


def test_a_market_that_did_not_move_is_said_to_have_not_moved(tmp_path):
    """The strongest thing these records can say, and the one that did the most work in
    the 25 October decomposition."""
    path = _book(tmp_path, [("2026-10-24", {"fair_value": 436.42}),
                            ("2026-10-25", {"fair_value": 474.50})])
    out = W.between(path, "LLY", "2026-10-24", "2026-10-25")
    assert out["ok"] and out["market_moved"] == {}
    assert out["move"] == 474.50 - 436.42
    assert any("market did not move it" in line for line in out["reading"])


def test_a_market_that_moved_is_named(tmp_path):
    path = _book(tmp_path, [("2026-10-24", {"fair_value": 436.42}),
                            ("2026-10-25", {"fair_value": 474.50, "price": 110.0})])
    out = W.between(path, "LLY", "2026-10-24", "2026-10-25")
    assert "price" in out["market_moved"]
    assert out["market_moved"]["price"] == {"from": 100.0, "to": 110.0}


def test_a_code_change_is_reported_and_not_attributed(tmp_path):
    path = _book(tmp_path, [("2026-10-24", {"fair_value": 436.0, "code_version": "aaa"}),
                            ("2026-10-25", {"fair_value": 474.0, "code_version": "bbb"})])
    out = W.between(path, "LLY", "2026-10-24", "2026-10-25")
    assert out["code"]["same"] is False
    assert any("cannot be attributed" in line for line in out["reading"])


def test_a_comparison_across_two_books_says_so(tmp_path):
    """One call made here and one brought in from an exported history price differently,
    and the seam between them is not the model changing its mind."""
    path = _book(tmp_path, [("2026-10-17", {"fair_value": 481.92, "source": "scheduled"}),
                            ("2026-10-18", {"fair_value": 463.34, "source": "backfill"})])
    out = W.between(path, "LLY", "2026-10-17", "2026-10-18")
    assert out["crosses_books"] is True
    assert any("different books" in line for line in out["reading"])


def test_an_analyst_change_is_grouped_by_save_and_carries_its_reason(tmp_path):
    import assumptions as A
    path = _book(tmp_path, [("2026-10-24", {"fair_value": 436.0}),
                            ("2026-10-25", {"fair_value": 474.0})])
    conn = db.get_connection(path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "source": "a judgement"}])
    A.save(conn, 1, [{"key": "pos", "value": 0.92, "source": "CYCLONE 3 read out"},
                     {"key": "penetration_peak_pct", "value": 0.2, "source": "with it"}],
           reason="readout", batch_id="b1", trigger_ref="NCT05288166")
    conn.execute("UPDATE assumption_edits SET changed_at='2026-10-25 09:00:00'"
                 " WHERE batch_id='b1'")
    conn.commit(); conn.close()
    out = W.between(path, "LLY", "2026-10-24", "2026-10-25")
    assert len(out["assumptions"]) == 1, "one save is one entry"
    entry = out["assumptions"][0]
    assert entry["reason"] == "readout" and entry["trigger"] == "NCT05288166"
    assert len(entry["rows"]) == 2
    assert any("readout" in line for line in out["reading"])


def test_the_seed_load_is_not_reported_as_an_analyst_change(tmp_path):
    import assumptions as A
    path = _book(tmp_path, [("2026-10-24", {"fair_value": 436.0}),
                            ("2026-10-25", {"fair_value": 474.0})])
    conn = db.get_connection(path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "source": "a judgement"}],
           reason="initial_seed")
    conn.execute("UPDATE assumption_edits SET changed_at='2026-10-25 09:00:00'")
    conn.commit(); conn.close()
    out = W.between(path, "LLY", "2026-10-24", "2026-10-25")
    assert out["assumptions"] == []


def test_two_dates_that_resolve_to_one_call_are_refused(tmp_path):
    path = _book(tmp_path, [("2026-10-24", {"fair_value": 436.0})])
    out = W.between(path, "LLY", "2026-10-25", "2026-10-26")
    assert out["ok"] is False and out["reason"] == "same_call"


def test_a_company_the_book_never_valued_is_refused(tmp_path):
    path = _book(tmp_path, [("2026-10-24", {"fair_value": 436.0})])
    out = W.between(path, "AAA", "2026-10-24", "2026-10-25")
    assert out["ok"] is False and out["reason"] == "no_calls"
