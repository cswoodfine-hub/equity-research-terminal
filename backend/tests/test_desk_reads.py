"""The three reads built for the desk tools: comparable readouts, base rates, the calendar.

Each joins things the book already holds and adds no figure of its own, so the tests pin
the joins: which rows are in, which are kept apart, and that a gap stays a gap.
"""

import datetime as dt

import base_rates
import comparable_readouts as CR
import db
import event_calendar as EC


def _days(start: str, n: int) -> list:
    first = dt.date.fromisoformat(start)
    return [(first + dt.timedelta(days=i)).isoformat() for i in range(n)]


def _book(tmp_path):
    """Two companies with a hundred daily closes each and a flat XBI. AAA doubles on the
    day after day 80; BBB is flat throughout."""
    path = str(tmp_path / "book.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AAA', 'Aaa Bio')")
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (2, 'BBB', 'Bbb Bio')")
    days = _days("2026-01-01", 100)
    for i, day in enumerate(days):
        conn.execute("INSERT INTO prices (company_id, as_of, close, interval)"
                     " VALUES (1, ?, ?, '1d')", (day, 10.0 if i <= 80 else 20.0))
        conn.execute("INSERT INTO prices (company_id, as_of, close, interval)"
                     " VALUES (2, ?, 5.0, '1d')", (day,))
        conn.execute("INSERT INTO benchmark_prices (symbol, as_of, close)"
                     " VALUES ('XBI', ?, 100.0)", (day,))
    conn.commit()
    return path, conn, days


def _readout(conn, company_id, day, outcome, phase=3, drug="drug", accession=None):
    conn.execute(
        "INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome,"
        " event_date, quote, source_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (accession or f"{company_id}-{day}-{outcome}", company_id, drug, phase, outcome,
         day, "The study met its primary endpoint.", "https://example.test/r"))
    conn.commit()


# --- comparable readouts --------------------------------------------------------------
def test_a_readout_carries_its_own_windows_against_the_benchmark(tmp_path):
    path, conn, days = _book(tmp_path)
    _readout(conn, 1, days[80], "positive")
    conn.close()
    row = CR.build(path)["comparables"][0]
    assert row["ticker"] == "AAA" and row["quote"] == "The study met its primary endpoint."
    assert row["abnormal"]["after_1d"] == 1.0              # doubled, XBI flat
    assert row["abnormal"]["runup_1m"] == 0.0
    # Day 80 plus 21 trading days runs off a hundred-day series: empty, not estimated.
    assert row["abnormal"]["after_1m"] is None


def test_a_companys_own_readouts_are_kept_apart_from_its_comparables(tmp_path):
    path, conn, days = _book(tmp_path)
    _readout(conn, 1, days[80], "positive")
    _readout(conn, 2, days[70], "negative")
    conn.close()
    out = CR.build(path, ticker="aaa")
    assert [r["ticker"] for r in out["own"]] == ["AAA"]
    assert "AAA" not in [r["ticker"] for r in out["comparables"]]
    assert out["filters"]["ticker"] == "AAA"


def test_only_signed_readouts_count_and_filters_narrow_them(tmp_path):
    path, conn, days = _book(tmp_path)
    _readout(conn, 1, days[80], "positive", phase=3)
    _readout(conn, 2, days[70], "negative", phase=2)
    _readout(conn, 2, days[60], "none", phase=3)           # read, no result in it
    conn.close()
    assert CR.build(path)["comparables_on_file"] == 2
    assert [r["phase"] for r in CR.build(path, phase=2)["comparables"]] == [2]
    assert [r["outcome"] for r in CR.build(path, outcome="positive")["comparables"]] == ["positive"]
    # A filter value the book does not use is ignored, not matched to nothing.
    assert CR.build(path, phase=7)["filters"]["phase"] is None


def test_the_summary_is_a_median_and_a_count_by_outcome(tmp_path):
    path, conn, days = _book(tmp_path)
    _readout(conn, 1, days[80], "positive")
    _readout(conn, 2, days[50], "positive")
    _readout(conn, 2, days[40], "positive")
    conn.close()
    out = CR.build(path)
    (line,) = out["summary"]
    assert line["outcome"] == "positive" and line["readouts"] == 3 and line["companies"] == 2
    assert line["windows"]["after_1d"] == {"n": 3, "median": 0.0, "worst": 0.0, "best": 1.0}
    assert any("leans positive" in c for c in out["caveats"])


def test_the_limit_cuts_the_list_but_not_the_count_or_the_summary(tmp_path):
    path, conn, days = _book(tmp_path)
    for i in range(6):
        _readout(conn, 2, days[20 + i], "positive", accession=f"a{i}")
    conn.close()
    out = CR.build(path, limit=2)
    assert len(out["comparables"]) == 2 and out["comparables_on_file"] == 6
    assert out["summary"][0]["readouts"] == 6


# --- base rates -----------------------------------------------------------------------
def _table(tmp_path):
    path = tmp_path / "rates.csv"
    path.write_text("# a comment line\n"
                    "cut,group,transition,pos,n,source\n"
                    "area,Oncology,p3_to_nda,0.477,180,Figure 2\n"
                    "area,Metabolic,p3_to_nda,0.636,66,Figure 2\n"
                    "modality,Peptide,p3_to_nda,0.600,25,Figure 9\n"
                    "area,Oncology,p2_to_p3,0.248,400,Figure 2\n")
    return path


def test_the_published_rates_come_with_their_sample_and_a_thin_one_is_marked(tmp_path):
    out = base_rates.table(path=_table(tmp_path))
    assert len(out["rows"]) == 4 and out["cuts"] == ["area", "modality"]
    peptide = [r for r in out["rows"] if r["group"] == "Peptide"][0]
    assert peptide["n"] == 25 and peptide["thin"] is True and peptide["figure"] == "Figure 9"
    assert all(not r["thin"] for r in out["rows"] if r["group"] != "Peptide")


def test_the_rates_narrow_by_transition_cut_and_part_of_a_group_name(tmp_path):
    path = _table(tmp_path)
    assert len(base_rates.table("p3_to_nda", path=path)["rows"]) == 3
    assert len(base_rates.table("p3_to_nda", "area", path=path)["rows"]) == 2
    (row,) = base_rates.table("p3_to_nda", group="onco", path=path)["rows"]
    assert row["pos"] == 0.477 and row["transition_label"] == "Phase 3 to filing"


def test_the_books_own_record_is_counts_and_says_it_is_not_a_rate(tmp_path):
    path, conn, days = _book(tmp_path)
    _readout(conn, 1, days[80], "positive")
    _readout(conn, 2, days[70], "none")
    for ident, outcome in ((1, "met"), (2, "unknown")):
        conn.execute("INSERT INTO catalysts (id, company_id, catalyst_type, title, status)"
                     " VALUES (?, 1, 'data readout', 't', ?)", (ident, outcome))
        conn.execute("INSERT INTO catalyst_resolutions (catalyst_id, outcome, source)"
                     " VALUES (?, ?, 'hand')", (ident, outcome))
    conn.commit()
    conn.close()
    out = base_rates.record(path)
    assert {(r["outcome"], r["n"]) for r in out["catalysts_resolved"]} == {("met", 1), ("unknown", 1)}
    assert out["readouts_read"] == [{"phase": 3, "outcome": "positive", "n": 1}]
    assert "Counts, not rates" in out["note"]


def test_an_asset_the_book_does_not_hold_has_no_placement(tmp_path):
    path, conn, _days_ = _book(tmp_path)
    conn.close()
    assert base_rates.for_asset(path, 999) is None


# --- the calendar ---------------------------------------------------------------------
TODAY = dt.date(2026, 11, 23)


def _catalyst(conn, ident, kind, date, status="pending", guided=None, confidence="month"):
    conn.execute(
        "INSERT INTO catalysts (id, company_id, catalyst_type, expected_date,"
        " date_confidence, title, status, is_curated, guided_date, guided_confidence)"
        " VALUES (?, 1, ?, ?, ?, ?, ?, 0, ?, ?)",
        (ident, kind, date, confidence, f"{kind} {ident}", status, guided,
         "company guidance" if guided else None))
    conn.commit()


def test_the_calendar_is_every_dated_thing_ahead_in_date_order(tmp_path):
    path, conn, _d = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2027-06")
    _catalyst(conn, 2, "PDUFA", "2027-01-21", confidence="confirmed")
    _catalyst(conn, 3, "data readout", "2029-01-01")         # outside a year
    _catalyst(conn, 4, "data readout", "2027-02-01", status="met")
    conn.execute("INSERT INTO adcomm_meetings (meeting_key, committee, meeting_date,"
                 " product, company_id, url) VALUES ('k', 'ODAC', '2027-03-10', 'drug', 1,"
                 " 'https://example.test/fr')")
    conn.commit()
    conn.close()
    out = EC.for_company(path, "aaa", today=TODAY)
    assert [(e["kind"], e["date"]) for e in out["events"]] == [
        ("PDUFA", "2027-01-21"), ("advisory committee", "2027-03-10"),
        ("data readout", "2027-06")]
    assert out["events"][2]["precision"] == "month" and out["events"][0]["firmness"] == "confirmed"
    assert out["from"] == "2026-11-23" and out["to"] == "2027-11-23"


def test_a_readout_the_registry_dates_in_the_past_stays_ahead_where_the_company_guides_later(tmp_path):
    """The registry's primary completion date and the company's guided date are two
    claims; a row past due on the first and ahead on the second is still ahead, and
    both dates are shown."""
    path, conn, _d = _book(tmp_path)
    _catalyst(conn, 1, "data readout", "2026-10-15", guided="2027-03")
    _catalyst(conn, 2, "data readout", "2026-09-30", confidence="day")
    conn.close()
    out = EC.for_company(path, "AAA", today=TODAY)
    (row,) = out["events"]
    assert row["date"] == "2026-10-15" and row["guided_date"] == "2027-03"
    assert row["guided_firmness"] == "company guidance"
    assert out["pending_past_due"] == 2                    # both are past the registry date


def test_the_calendar_says_what_it_does_not_hold(tmp_path):
    path, conn, _d = _book(tmp_path)
    conn.execute("INSERT INTO earnings_surprises (company_id, quarter_end, reported_on)"
                 " VALUES (1, '2026-09', '2026-11-05')")
    conn.commit()
    conn.close()
    out = EC.for_company(path, "AAA", today=TODAY)
    assert out["events"] == [] and out["last_results_reported"] == "2026-11-05"
    assert any("projection" in line for line in out["absent"])


def test_an_unknown_ticker_has_no_calendar(tmp_path):
    path, conn, _d = _book(tmp_path)
    conn.close()
    assert EC.for_company(path, "ZZZ", today=TODAY) is None


def test_a_month_or_a_year_sorts_at_its_first_day():
    assert EC._sort_key("2027-03") == "2027-03-01"
    assert EC._sort_key("2027") == "2027-01-01"
    assert EC._sort_key("2027-03-15") == "2027-03-15"


# --- positioning ----------------------------------------------------------------------
def test_positioning_puts_the_reads_side_by_side_and_one_failing_does_not_take_the_rest(
        tmp_path, monkeypatch):
    import event_moves
    import market_reads
    import positioning

    path, conn, _d = _book(tmp_path)
    conn.close()
    rows = [{"settlement": "2026-10-30", "shares": 110.0, "avg_volume": 10.0, "days_to_cover": 11.0},
            {"settlement": "2026-10-15", "shares": 100.0, "avg_volume": 20.0, "days_to_cover": 5.0}]
    monkeypatch.setattr(market_reads, "short_interest", lambda symbols: {symbols[0]: rows})

    def refused(db_path, ticker):
        raise OSError("the host refused")
    monkeypatch.setattr(event_moves, "company", refused)
    out = positioning.for_company(path, "aaa", ("short", "options"))
    assert out["short_interest"]["latest"]["shares"] == 110.0
    assert out["short_interest"]["change_from_previous"] == 0.1
    assert out["options"]["ok"] is False and "refused" in out["options"]["reason"]
    assert "insiders" not in out and "holders" not in out
    assert "not a score" in out["note"]


def test_a_missing_chain_is_not_reported_as_a_stock_with_no_options(tmp_path, monkeypatch):
    """Cboe answers 403 for a symbol it lists nothing for and for a request it refuses.
    The reader cannot tell which, so the answer must not claim the first."""
    import event_moves
    import positioning

    path, conn, _d = _book(tmp_path)
    conn.close()
    monkeypatch.setattr(event_moves, "company", lambda db_path, ticker: {
        "ticker": ticker, "ok": False,
        "reason": "no listed options on Cboe for the US listing"})
    got = positioning.for_company(path, "AAA", ("options",))["options"]
    assert got["ok"] is False and "not evidence that none" in got["reason"]


def test_a_stored_read_comes_back_as_its_summary_and_an_absent_one_says_why(
        tmp_path, monkeypatch):
    import sys
    import types

    import positioning

    path, conn, _d = _book(tmp_path)
    conn.close()
    fake = types.ModuleType("insiders")
    fake.for_company = lambda db_path, ticker: {"summary": {"net_shares": -5},
                                               "transactions": [{"shares": 5}] * 300}
    monkeypatch.setitem(sys.modules, "insiders", fake)
    gone = types.ModuleType("holders")
    gone.for_company = lambda db_path, ticker: None
    monkeypatch.setitem(sys.modules, "holders", gone)
    out = positioning.for_company(path, "AAA", ("insiders", "holders"))
    assert out["insiders"] == {"summary": {"net_shares": -5}}
    assert out["holders"]["ok"] is False
    assert positioning.for_company(path, "ZZZ") is None
