"""The latest report as one reading: the rules, and the parts built from stored rows."""

import db
import earnings_report as ER


def _g(direction, metric="Revenue"):
    return {"direction": direction, "metric": metric}


def test_a_quarter_inside_the_band_is_in_line_and_outside_it_a_beat_or_a_miss():
    assert ER.result_of(None) is None
    assert ER.result_of(2.0) == "in line" and ER.result_of(-2.0) == "in line"
    assert ER.result_of(2.01) == "beat" and ER.result_of(-9.4) == "miss"


def test_guidance_counts_only_what_was_re_read():
    assert ER.guidance_of([]) is None
    # A figure the scan did not re-read is silence, and silence is not "held".
    assert ER.guidance_of([_g("not re-read"), _g("first reading")]) is None
    assert ER.guidance_of([_g("held"), _g("not re-read")]) == "held"
    assert ER.guidance_of([_g("raised"), _g("held")]) == "raised"
    assert ER.guidance_of([_g("raised"), _g("cut", "EPS")]) == "mixed"


def test_the_verdict_names_both_halves_and_refuses_to_pick_when_they_disagree():
    word = lambda s, g: (ER.verdict(s, [_g(d) for d in g]) or {}).get("word")
    assert word(39.0, ["raised"]) == "Beat and raise"
    assert word(39.0, ["not re-read"]) == "Beat"
    assert word(39.0, ["cut"]) == "Mixed" and word(-9.0, ["raised"]) == "Mixed"
    assert word(-9.0, ["cut"]) == "Miss and cut" and word(-9.0, []) == "Miss"
    assert word(0.5, ["raised"]) == "In line, raised" and word(0.5, []) == "In line"
    assert word(None, ["cut"]) == "Guidance cut" and word(None, ["held"]) == "Guidance held"
    assert ER.verdict(None, []) is None and ER.verdict(None, [_g("not re-read")]) is None
    assert ER.verdict(39.0, [_g("cut")])["tone"] == "mixed"
    assert ER.verdict(-9.0, [])["tone"] == "down" and ER.verdict(0.5, [])["tone"] == "flat"


def test_a_filing_after_the_close_moves_the_next_session_and_one_before_it_the_same():
    # 11:03 UTC on 29 October is 07:03 in New York, before the open.
    assert ER._timing("2026-10-29T11:03:30.000Z", "2026-10-29") == (
        "2026-10-29", "before the open")
    assert ER._timing("2026-10-29T15:00:00.000Z", "2026-10-29")[1] == "during the session"
    # 20:05 UTC is 16:05 in New York while daylight time holds: after the close.
    assert ER._timing("2026-10-29T20:05:00.000Z", "2026-10-29") == (
        "2026-10-30", "after the close")
    # In winter the close is 21:00 UTC, so 20:05 is still inside the session.
    assert ER._timing("2026-11-03T20:05:00.000Z", "2026-11-03")[1] == "during the session"
    assert ER._timing(None, "2026-10-29") == ("2026-10-29", "time of day not known")
    # A stamp from another day's filing says nothing about this announcement.
    assert ER._timing("2026-10-30T11:00:00.000Z", "2026-10-29")[1] == "time of day not known"


def _seed(path):
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'TST', 'Test Co')")
    for day, close in (("2026-10-27", 99.0), ("2026-10-28", 100.0), ("2026-10-29", 110.0),
                       ("2026-10-30", 121.0)):
        conn.execute("INSERT INTO prices (company_id, as_of, close, interval)"
                     " VALUES (1, ?, ?, '1d')", (day, close))
    for day, close in (("2026-10-28", 50.0), ("2026-10-29", 51.0), ("2026-10-30", 51.0)):
        conn.execute("INSERT INTO benchmark_prices (symbol, as_of, close)"
                     " VALUES ('XBI', ?, ?)", (day, close))
    for as_of, value in (("2026-08-05", 86e9), ("2026-10-29", 91.5e9)):
        conn.execute(
            "INSERT INTO consensus_estimates (company_id, metric, period, value, currency,"
            " source, as_of) VALUES (1, 'Revenue', 'FY2026', ?, 'USD', 'guidance', ?)",
            (value, as_of))
    conn.execute(
        "INSERT INTO consensus_estimates (company_id, metric, period, value, currency,"
        " source, as_of) VALUES (1, 'EPS', 'FY2026', 36.0, 'USD', 'guidance', '2026-08-05')")
    conn.execute(
        "INSERT INTO consensus_estimates (company_id, metric, period, value, currency,"
        " source, as_of) VALUES (1, 'EPS', 'FY2025', 20.0, 'USD', 'guidance', '2025-10-30')")
    conn.commit()
    return conn


def test_the_day_is_the_first_close_that_could_react_against_the_one_before(tmp_path):
    conn = _seed(str(tmp_path / "r.db"))
    before_open = ER.day_move(conn, 1, "2026-10-29", "2026-10-29T11:03:30.000Z")
    assert (before_open["previous_session"], before_open["session"]) == (
        "2026-10-28", "2026-10-29")
    assert round(before_open["move"], 4) == 0.10
    assert round(before_open["benchmark_move"], 4) == 0.02
    assert round(before_open["abnormal"], 4) == 0.08
    # The same report filed after the close is measured a session later, from the close
    # it could not have moved.
    after_close = ER.day_move(conn, 1, "2026-10-29", "2026-10-29T20:05:00.000Z")
    assert (after_close["previous_session"], after_close["session"]) == (
        "2026-10-29", "2026-10-30")
    assert round(after_close["move"], 4) == 0.10
    # No close near the report is no reaction, not a move of nothing.
    assert ER.day_move(conn, 1, "2027-03-01", None) is None
    conn.close()


def test_guidance_is_read_against_the_reading_before_and_silence_is_not_a_hold(tmp_path):
    conn = _seed(str(tmp_path / "g.db"))
    changes = {g["label"]: g for g in ER.guidance_changes(conn, 1, "2026-10-29")}
    revenue = changes["FY2026 revenue"]
    assert revenue["direction"] == "raised" and round(revenue["change"], 4) == 0.064
    assert (revenue["prior"], revenue["value"]) == (86e9, 91.5e9)
    # EPS was guided in August and not re-read at this report.
    assert changes["FY2026 EPS"]["direction"] == "not re-read"
    assert changes["FY2026 EPS"]["value"] is None
    # A year that closed before this report is not one left unread.
    assert "FY2025 EPS" not in changes
    assert ER.guidance_of(list(changes.values())) == "raised"
    conn.close()


def test_a_company_with_no_announcement_on_file_says_so_and_builds_nothing(tmp_path):
    path = str(tmp_path / "n.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'TST', 'Test Co')")
    conn.commit()
    conn.close()
    assert ER.build(path, "NOPE") is None
    built = ER.build(path, "TST")
    assert built["report"] is None and "no results announcement" in built["reason"]


def test_the_book_before_and_after_needs_both_readings(tmp_path):
    conn = _seed(str(tmp_path / "b.db"))
    assert ER.book_change(conn, 1, "2026-10-29")["reason"] == (
        "no valuation was stored before this report")
    conn.execute("INSERT INTO valuation_snapshots (company_id, as_of, captured_at,"
                 " equity_per_share) VALUES (1, '2026-10-28', '2026-10-28T06:00', 400.0)")
    assert "since this report" in ER.book_change(conn, 1, "2026-10-29")["reason"]
    conn.execute("INSERT INTO valuation_snapshots (company_id, as_of, captured_at,"
                 " equity_per_share) VALUES (1, '2026-10-30', '2026-10-30T06:00', 440.0)")
    book = ER.book_change(conn, 1, "2026-10-29")
    assert round(book["change"], 4) == 0.10 and book["reason"] is None
    conn.close()
