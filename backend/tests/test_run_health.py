"""A source that parses nothing it used to parse has failed, whatever it reports.

A run is marked partial by errors alone, so a source answering HTTP 200 and parsing zero
rows finished complete and said nothing. That is how the Purple Book fetcher ran blind
for weeks. The check is against the source's own last productive run, not against zero,
because most sources have quiet days and a status that cries wolf is one nobody reads.
"""

import json

import db
import refresh
import run_health


def _book(tmp_path, history):
    """``history`` is a list of {source: rows} dicts, oldest run first."""
    path = str(tmp_path / "r.db")
    db.init(path)
    conn = db.get_connection(path)
    for run in history:
        detail = {"sources": [{"source": name, "rows_fetched": rows}
                              for name, rows in run.items()]}
        conn.execute("INSERT INTO refresh_runs (started_at, status, detail)"
                     " VALUES ('2026-10-20 06:00:00', 'complete', ?)",
                     (json.dumps(detail),))
    conn.commit()
    conn.close()
    return path


def _agg(rows, ran=1, skipped=0, errors=None):
    return {"rows_fetched": rows, "ran": ran, "skipped_ttl": skipped,
            "errors": errors or [], "notes": []}


def test_a_source_that_stopped_parsing_is_caught(tmp_path):
    path = _book(tmp_path, [{"purple_book": 412}])
    quiet = refresh.went_quiet(path, {"purple_book": _agg(0)})
    assert [q["source"] for q in quiet] == ["purple_book"]
    assert quiet[0]["last_rows"] == 412


def test_a_source_that_has_never_returned_rows_is_not_accused(tmp_path):
    """No baseline is not the same as a regression."""
    path = _book(tmp_path, [{"purple_book": 0}])
    assert refresh.went_quiet(path, {"purple_book": _agg(0)}) == []


def test_a_quiet_day_on_a_working_source_is_not_a_failure(tmp_path):
    path = _book(tmp_path, [{"filings": 9}])
    assert refresh.went_quiet(path, {"filings": _agg(3)}) == [], (
        "it returned rows; there is nothing to report")


def test_a_source_skipped_on_its_ttl_is_not_a_failure(tmp_path):
    path = _book(tmp_path, [{"prices": 70}])
    assert refresh.went_quiet(path, {"prices": _agg(0, ran=1, skipped=1)}) == [], (
        "it was not asked, so it cannot have failed")


def test_a_source_that_already_raised_is_left_to_its_own_error(tmp_path):
    path = _book(tmp_path, [{"trials": 500}])
    assert refresh.went_quiet(path, {"trials": _agg(0, errors=["DNS"])}) == [], (
        "it already reports a failure; two for one event reads as two")


def test_the_baseline_is_the_last_productive_run_not_the_last_run(tmp_path):
    """A source silent for three days is measured against the day it last worked, so the
    first silent run does not become the baseline that excuses the rest."""
    path = _book(tmp_path, [{"purple_book": 412}, {"purple_book": 0}, {"purple_book": 0}])
    quiet = refresh.went_quiet(path, {"purple_book": _agg(0)})
    assert quiet and quiet[0]["last_rows"] == 412


def test_the_run_being_scored_is_not_its_own_baseline(tmp_path):
    path = _book(tmp_path, [{"purple_book": 412}])
    conn = db.get_connection(path)
    detail = json.dumps({"sources": [{"source": "purple_book", "rows_fetched": 99}]})
    conn.execute("INSERT INTO refresh_runs (started_at, status, detail)"
                 " VALUES ('2026-10-26 06:00:00', 'running', ?)", (detail,))
    mine = conn.execute("SELECT MAX(id) m FROM refresh_runs").fetchone()["m"]
    conn.commit(); conn.close()
    quiet = refresh.went_quiet(path, {"purple_book": _agg(0)}, run_id=mine)
    assert quiet and quiet[0]["last_rows"] == 412


# --- what the book leaves unvalued rides beside the run's health -----------------------

def test_the_gaps_block_rides_in_the_detail_and_on_the_line():
    source = {"source": "prices", "rows_fetched": 75, "ran": 75, "skipped_ttl": 0,
              "errors": [], "notes": []}
    health = run_health.summarise("2026-11-23 06:05:00", [source], [], {}, "groq")
    gaps = {"line": "bought and unvalued: LLY 1; acquisitions with no terms: none; "
                    "late-stage and unmodelled: LLY 1; stale anchors: none",
            "bought_unvalued": [{"ticker": "LLY"}], "deals_without_terms": [],
            "late_stage_unmodelled": [{"ticker": "LLY"}], "stale_anchors": []}
    out = run_health.with_gaps(health, gaps)
    assert out["gaps"] is gaps
    assert out["line"] == health["line"]       # the health line says what the run did
    assert out["abnormal"] is False            # a gap in the book is not a fault in the run
    assert run_health.with_gaps(health, None) == health
