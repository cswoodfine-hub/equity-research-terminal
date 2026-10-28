"""The fair value line against the price line.

The rule under test is the one that separates the two: the price series is the market's
and the source hands its history back, so a missed day fills itself in. The fair value
series is the book's own and nothing can backfill it, so a missed day carries the last
stated view flat and says it is carrying.
"""

import db
import forecast_history as F


def _book(tmp_path, closes, calls):
    path = str(tmp_path / "h.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Lilly')")
    for day, close in closes:
        conn.execute("INSERT INTO prices (company_id, as_of, close) VALUES (1, ?, ?)",
                     (day, close))
    for day, fair in calls:
        conn.execute("INSERT INTO model_calls (as_of, ticker, fair_value, price, rating)"
                     " VALUES (?, 'LLY', ?, 100.0, 'Hold')", (day, fair))
    conn.commit()
    conn.close()
    return path


def _at(out, day):
    return next(p for p in out["points"] if p["as_of"] == day)


def test_a_day_that_did_not_run_carries_the_last_stated_value_flat(tmp_path):
    path = _book(tmp_path,
                 [("2026-10-08", 100.0), ("2026-10-09", 110.0), ("2026-10-10", 90.0)],
                 [("2026-10-08", 50.0)])
    out = F.series(path, "LLY")
    assert [p["fair_value"] for p in out["points"]] == [50.0, 50.0, 50.0]
    assert _at(out, "2026-10-08")["stated"] is True
    assert _at(out, "2026-10-09")["carried"] is True
    assert _at(out, "2026-10-10")["carried"] is True


def test_the_price_on_a_carried_day_is_the_real_close(tmp_path):
    path = _book(tmp_path,
                 [("2026-10-08", 100.0), ("2026-10-09", 110.0)],
                 [("2026-10-08", 50.0)])
    out = F.series(path, "LLY")
    carried = _at(out, "2026-10-09")
    assert carried["close"] == 110.0 and carried["close_stale"] is False


def test_nothing_is_carried_backwards(tmp_path):
    path = _book(tmp_path,
                 [("2026-10-07", 95.0), ("2026-10-08", 100.0)],
                 [("2026-10-08", 50.0)])
    out = F.series(path, "LLY")
    before = _at(out, "2026-10-07")
    assert before["fair_value"] is None
    assert before["close"] == 95.0, "the price line still runs before the first call"


def test_a_new_call_ends_the_carry(tmp_path):
    path = _book(tmp_path,
                 [("2026-10-08", 100.0), ("2026-10-09", 110.0), ("2026-10-10", 90.0)],
                 [("2026-10-08", 50.0), ("2026-10-10", 62.0)])
    out = F.series(path, "LLY")
    assert [p["fair_value"] for p in out["points"]] == [50.0, 50.0, 62.0]
    assert out["stated_days"] == 2 and out["carried_days"] == 1


def test_a_call_on_a_day_the_market_was_shut_still_reaches_the_line(tmp_path):
    path = _book(tmp_path, [("2026-10-16", 100.0), ("2026-10-19", 104.0)],
                 [("2026-10-17", 50.0)])
    out = F.series(path, "LLY")
    saturday = _at(out, "2026-10-17")
    assert saturday["stated"] is True and saturday["fair_value"] == 50.0
    assert saturday["close_stale"] is True, "the close is Friday's, and says so"


def test_the_line_stops_rather_than_carrying_for_ever(tmp_path):
    days = [(f"2026-{m:02d}-{d:02d}", 100.0)
            for m in (10, 11, 12) for d in range(1, 29)]
    path = _book(tmp_path, days, [("2026-10-01", 50.0)])
    out = F.series(path, "LLY")
    assert _at(out, "2026-11-10")["fair_value"] == 50.0
    assert _at(out, "2026-12-28")["fair_value"] is None, (
        "a line carried for three months has stopped being a view")


def test_a_company_with_no_call_says_so_rather_than_drawing_a_flat_zero(tmp_path):
    path = _book(tmp_path, [("2026-10-08", 100.0)], [])
    out = F.series(path, "LLY")
    assert out["ok"] is False and out["reason"] == "no_calls"
    assert out["points"] == []


def test_the_first_and_last_stated_days_are_named(tmp_path):
    path = _book(tmp_path,
                 [("2026-10-08", 100.0), ("2026-10-09", 110.0), ("2026-10-10", 90.0)],
                 [("2026-10-08", 50.0), ("2026-10-09", 55.0)])
    out = F.series(path, "LLY")
    assert out["begins"] == "2026-10-08" and out["last_stated"] == "2026-10-09"


# --- the events on the line --------------------------------------------------

def test_one_save_is_one_marker_however_many_numbers_it_moved(tmp_path):
    import assumptions as A
    path = _book(tmp_path, [("2026-10-08", 100.0)], [("2026-10-08", 50.0)])
    conn = db.get_connection(path)
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, modality,"
                 " is_marketed) VALUES (1, 1, 'Verzenio', 'small molecule', 1)")
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "source": "a judgement"},
                     {"key": "penetration_peak_pct", "value": 0.1,
                      "source": "a judgement"}])
    batch = __import__("assumption_log").new_batch()
    A.save(conn, 1, [{"key": "pos", "value": 0.92, "source": "CYCLONE 3 read out"},
                     {"key": "penetration_peak_pct", "value": 0.18,
                      "source": "CYCLONE 3 read out"}],
           reason="readout", batch_id=batch)
    conn.execute("UPDATE assumption_edits SET changed_at = '2026-10-08 09:00:00',"
                 " rnpv_before = 1000, rnpv_after = 1400 WHERE batch_id = ?", (batch,))
    conn.commit()
    conn.close()
    out = F.series(path, "LLY")
    moves = [e for e in out["events"] if e["kind"] == "model"]
    assert len(moves) == 1, "one save is one decision"
    assert moves[0]["rnpv_move"] == 400
    assert moves[0]["reason"] == "readout"
    assert "and 1 more" in moves[0]["headline"]


def test_the_seed_load_is_not_an_event(tmp_path):
    import assumptions as A
    path = _book(tmp_path, [("2026-10-08", 100.0)], [("2026-10-08", 50.0)])
    conn = db.get_connection(path)
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, modality,"
                 " is_marketed) VALUES (1, 1, 'Verzenio', 'small molecule', 1)")
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "source": "a judgement"}],
           reason="initial_seed")
    conn.execute("UPDATE assumption_edits SET changed_at = '2026-10-08 09:00:00'")
    conn.commit()
    conn.close()
    out = F.series(path, "LLY")
    assert [e for e in out["events"] if e["kind"] == "model"] == [], (
        "a row's first write is not a change of mind")


def test_a_day_before_the_first_call_is_blank_rather_than_carried(tmp_path):
    """Carried means the view was held. A day before the book had a view was not held,
    and counting it as carried would claim a line the chart never draws."""
    path = _book(tmp_path,
                 [("2026-10-06", 90.0), ("2026-10-07", 95.0), ("2026-10-08", 100.0),
                  ("2026-10-09", 110.0)],
                 [("2026-10-08", 50.0)])
    out = F.series(path, "LLY")
    assert (out["stated_days"], out["carried_days"], out["blank_days"]) == (1, 1, 2)
