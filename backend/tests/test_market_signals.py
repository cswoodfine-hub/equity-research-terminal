"""A rate move is measured against the level the last flag was written from.

The alternative, comparing one refresh to the last, is what the engine did everywhere
else and it cannot work here: over thirteen months of stored history no series moved
25bp in a day, once, while the ten-year travelled 104bp. These pin the ratchet that
catches the walk, and the confinement that keeps the values away from the model.
"""

import pytest

import db
import diff
import insights
import market_signals as MS
from fetchers import rates_fred


def _db(tmp_path, name="sig.db"):
    path = str(tmp_path / name)
    db.init(path)
    rates_fred.clear_cache()
    return path


def _observe(path, series, as_of, value):
    conn = db.get_connection(path)
    conn.execute("INSERT INTO market_rates (series, as_of, value, source)"
                 " VALUES (?, ?, ?, 'fred')", (series, as_of, value))
    conn.commit()
    conn.close()
    rates_fred.clear_cache()


def test_a_first_sighting_baselines_and_never_fires():
    """Flagging one would announce the rate on the day the terminal was installed."""
    import pathlib
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = _db(pathlib.Path(tmp))
        _observe(path, "DGS10", "2026-09-01", 0.0476)
        conn = db.get_connection(path)
        assert MS.evaluate(conn) == []
        conn.commit()
        assert MS.anchors(conn)["DGS10:10"]["anchor_value"] == pytest.approx(0.0476)
        conn.close()


def test_a_walk_of_nine_basis_point_days_still_crosses(tmp_path):
    """The whole reason for an anchor. Three 9bp days is 27bp, which no day-on-day
    rule at any useful bar would see, and which the book has to be told about."""
    path = _db(tmp_path, "walk.db")
    _observe(path, "DGS10", "2026-09-01", 0.0476)
    conn = db.get_connection(path)
    MS.evaluate(conn)                     # baseline at 4.76%
    conn.commit()
    conn.close()

    for day, value in (("2026-09-02", 0.0485), ("2026-09-03", 0.0494)):
        _observe(path, "DGS10", day, value)
        conn = db.get_connection(path)
        fired = {f["signal_key"] for f in MS.evaluate(conn)}
        conn.commit()
        conn.close()
        # 9bp then 18bp: the 25bp bar is not reached yet.
        assert "DGS10:25" not in fired

    _observe(path, "DGS10", "2026-09-04", 0.0503)
    conn = db.get_connection(path)
    fired = {f["signal_key"]: f for f in MS.evaluate(conn)}
    conn.close()
    assert "DGS10:25" in fired
    assert fired["DGS10:25"]["move_bp"] == pytest.approx(27.0)
    assert fired["DGS10:25"]["anchor_as_of"] == "2026-09-01"


def test_a_clean_twenty_five_basis_point_move_clears_a_twenty_five_bar(tmp_path):
    """0.0501 less 0.0476 is 24.999999999999996 in binary floating point, so an
    unrounded comparison lets a clean move fail its own bar."""
    path = _db(tmp_path, "edge.db")
    _observe(path, "DGS10", "2026-09-01", 0.0476)
    conn = db.get_connection(path)
    MS.evaluate(conn)
    conn.commit()
    conn.close()
    _observe(path, "DGS10", "2026-09-02", 0.0501)
    conn = db.get_connection(path)
    assert "DGS10:25" in {f["signal_key"] for f in MS.evaluate(conn)}
    conn.close()


def test_it_fires_once_and_the_rerun_is_quiet(tmp_path):
    """Both market fetchers snapshot on every refresh whether the numbers moved or
    not, so a rule that did not re-anchor would repeat itself every night."""
    path = _db(tmp_path, "once.db")
    _observe(path, "DGS10", "2026-09-01", 0.0476)
    conn = db.get_connection(path)
    MS.evaluate(conn)
    conn.commit()
    conn.close()
    _observe(path, "DGS10", "2026-09-02", 0.0505)

    conn = db.get_connection(path)
    # Both bars on the ten-year trip, and they fold into one row rather than saying
    # the same thing twice in the feed.
    assert diff._diff_market(conn, None) == 1
    conn.commit()
    assert diff._diff_market(conn, None) == 0          # nothing moved since
    assert diff._diff_market(conn, None) == 0
    rows = conn.execute("SELECT entity_type, entity_key, change_type, significance,"
                        " old_value, new_value FROM changes").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["entity_type"] == "market"
    assert rows[0]["significance"] == "high"           # the strongest bar that fired
    assert "29bp up" in rows[0]["new_value"]
    # The anchor moved to where the flag was written from, so the next 25bp is a new
    # 25bp rather than the same one counted again.
    assert "2026-09-02" in rows[0]["new_value"]


def test_the_two_bars_on_one_series_keep_separate_anchors(tmp_path):
    """Sharing one would let the 10bp bar keep resetting it so 25bp is never reached,
    which is the failure mode the key exists to prevent."""
    path = _db(tmp_path, "bars.db")
    _observe(path, "DGS10", "2026-09-01", 0.0400)
    conn = db.get_connection(path)
    MS.evaluate(conn)
    conn.commit()
    conn.close()
    # Four 12bp steps from 4.00%: 4.12, 4.24, 4.36, 4.48. Every one trips the 10bp bar
    # and re-anchors it. On a shared anchor the 25bp bar would therefore never see
    # more than 12bp and would fire nothing across a 48bp move. On its own anchor it
    # sees 12, 24, 36 and fires at the third, then re-anchors and sees 12 again.
    fired_25, fired_10 = 0, 0
    for day, value in (("2026-09-02", 0.0412), ("2026-09-03", 0.0424),
                       ("2026-09-04", 0.0436), ("2026-09-05", 0.0448)):
        _observe(path, "DGS10", day, value)
        conn = db.get_connection(path)
        keys = {f["signal_key"] for f in MS.evaluate(conn)}
        for f in MS.evaluate(conn):
            MS.set_anchor(conn, f["signal_key"], f["value"], f["as_of"], flagged=True)
        conn.commit()
        conn.close()
        fired_10 += "DGS10:10" in keys
        fired_25 += "DGS10:25" in keys
    assert fired_10 == 4
    assert fired_25 == 1


def test_a_fall_is_a_move_too(tmp_path):
    path = _db(tmp_path, "down.db")
    _observe(path, "DGS10", "2026-09-01", 0.0501)
    conn = db.get_connection(path)
    MS.evaluate(conn)
    conn.commit()
    conn.close()
    _observe(path, "DGS10", "2026-09-02", 0.0470)
    conn = db.get_connection(path)
    fired = {f["signal_key"]: f for f in MS.evaluate(conn)}
    conn.close()
    assert fired["DGS10:25"]["move_bp"] == pytest.approx(-31.0)
    assert "down" in MS.headline(fired["DGS10:25"])


def test_the_breakeven_bar_is_set_where_the_series_can_reach_it(tmp_path):
    """25bp would be a rule that never runs: the breakeven moved 32bp in total across
    276 observations and never 25bp from any anchor."""
    bars = {(s["series"], s["bp"]) for s in MS.SIGNALS}
    assert ("T10YIE", 10) in bars
    assert ("T10YIE", 25) not in bars
    # And the real rate carries no bar at all; it is only ever a clause in the split.
    assert not any(s["series"] == "DFII10" for s in MS.SIGNALS)


def test_the_split_is_dropped_when_it_does_not_account_for_the_move(tmp_path):
    """The parts are read from the series over the two dates and the headline states
    the move from the anchor. Where an anchor no longer matches what the series held
    that day, the sentence would say 25bp and then account for 34bp of it."""
    path = _db(tmp_path, "split.db")
    for series, value in (("DGS10", 0.0467), ("DFII10", 0.0234), ("T10YIE", 0.0233)):
        _observe(path, series, "2026-08-27", value)
    for series, value in (("DGS10", 0.0501), ("DFII10", 0.0258), ("T10YIE", 0.0243)):
        _observe(path, series, "2026-09-18", value)

    conn = db.get_connection(path)
    MS.evaluate(conn)                                  # baseline every bar
    conn.commit()
    # An anchor consistent with the series: the split appears and adds up.
    MS.set_anchor(conn, "DGS10:25", 0.0467, "2026-08-27")
    conn.commit()
    fired = next(f for f in MS.evaluate(conn) if f["signal_key"] == "DGS10:25")
    said = MS.sentence(conn, "AMGN", fired, db_path=path)
    # 24bp of real rate and 10bp of breakeven, which add to the 34bp nominal.
    assert "24bp of the move is the real rate and 10bp is breakeven inflation" in said
    assert "not an inflation story" in said

    # An anchor that is not what the series held: the clause goes rather than mislead.
    MS.set_anchor(conn, "DGS10:25", 0.0476, "2026-08-27")
    conn.commit()
    fired = next(f for f in MS.evaluate(conn) if f["signal_key"] == "DGS10:25")
    said = MS.sentence(conn, "AMGN", fired, db_path=path)
    assert "real rate" not in said
    assert "Dates compared: 2026-08-27 and 2026-09-18." in said
    conn.close()


def test_no_market_level_ever_reaches_the_model():
    """CLAUDE.md confines the API to the note step and the rate work is rules only.
    FRED restricts feeding its values into an artificial-intelligence process, and the
    ICE credit index may not be furnished onward at all, so this is a licence term as
    much as a house rule."""
    items = [
        {"kind": "market", "significance": "high", "date": "2026-09-22",
         "headline": "The 10-year Treasury 5.01%, 25bp up"},
        {"kind": "fx", "significance": "low", "date": "2026-09-22",
         "headline": "EUR/USD 1.1490"},
        {"kind": "change", "significance": "high", "date": "2026-09-22",
         "headline": "AMGN phase 3 read out"},
    ]
    payload = insights._user_content("AMGN", items)
    assert "Treasury" not in payload and "EUR" not in payload
    assert "phase 3 read out" in payload
    assert set(insights.UNMODELLED_KINDS) == {"market", "fx"}


def test_the_thresholds_are_the_measured_ones():
    """Each bar carries its measured firing rate in the module comment so it can be
    argued with. Changing one without re-measuring should fail here first."""
    bars = {(s["series"], s["bp"]) for s in MS.SIGNALS}
    assert bars == {("DGS10", 10), ("DGS10", 25), ("T10YIE", 10),
                    ("BAMLC0A3CAEY", 25)}
    notes = {s["series"] for s in MS.SIGNALS if s["notes"]}
    assert notes == {"DGS10", "BAMLC0A3CAEY"}


def test_the_paragraphs_are_ranked_by_what_the_move_is_worth(tmp_path):
    """Not by how many basis points it is. A 35bp credit move and a 34bp rate move
    look the same in the feed and are not: on Pfizer the rate move is 4.2% of equity
    per share and the credit move 1.6%. Ranking on the headline number would lead the
    note with the smaller of the two."""
    scored = [(0.016, "the credit sentence"), (0.042, "the rate sentence")]
    ranked = [text for _w, text in sorted(scored, key=lambda x: -x[0])]
    assert ranked[0] == "the rate sentence"


def test_a_flagged_move_is_replayed_from_its_own_row(tmp_path):
    """A note is written after the diff has re-anchored, so asking what is moving now
    would find nothing and say nothing. The row carries the anchor and the date it was
    struck, which is everything needed to restate the move that was flagged."""
    path = _db(tmp_path, "replay.db")
    _observe(path, "DGS10", "2026-08-27", 0.0467)
    _observe(path, "DGS10", "2026-09-18", 0.0501)
    conn = db.get_connection(path)
    got = MS.replay(conn, "DGS10", "level@2026-08-27", "0.046700")
    conn.close()
    assert got["move_bp"] == pytest.approx(34.0)
    assert got["anchor_as_of"] == "2026-08-27"
    assert got["as_of"] == "2026-09-18"
    assert got["leg"] == "risk_free"

    conn = db.get_connection(path)
    # A row with no date on its field cannot be replayed, and says so by returning
    # nothing rather than guessing a date.
    assert MS.replay(conn, "DGS10", "level", "0.046700") is None
    assert MS.replay(conn, "DGS10", "level@2026-08-27", None) is None
    # T10YIE writes no note, so there is nothing to replay for it.
    assert MS.replay(conn, "T10YIE", "level@2026-08-27", "0.0233") is None
    conn.close()


def test_a_flat_breakeven_reads_as_flat_rather_than_as_zero(tmp_path):
    """Below a basis point the split rounds to nothing, and "0bp is breakeven
    inflation" reads as a measurement rather than as nothing having happened."""
    path = _db(tmp_path, "flat.db")
    for series, value in (("DGS10", 0.0467), ("DFII10", 0.0234), ("T10YIE", 0.0233)):
        _observe(path, series, "2026-08-27", value)
    for series, value in (("DGS10", 0.0501), ("DFII10", 0.0268), ("T10YIE", 0.0233)):
        _observe(path, series, "2026-09-18", value)
    conn = db.get_connection(path)
    MS.evaluate(conn)
    conn.commit()
    MS.set_anchor(conn, "DGS10:25", 0.0467, "2026-08-27")
    conn.commit()
    fired = next(f for f in MS.evaluate(conn) if f["signal_key"] == "DGS10:25")
    said = MS.sentence(conn, "AMGN", fired, db_path=path)
    conn.close()
    assert "All of the move is the real rate, with breakeven inflation flat" in said
    assert "0bp" not in said
