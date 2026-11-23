"""Every run says in one place whether it was normal (run_health.py).

106 of the first 143 committed runs finished "partial", so the word told nobody anything,
and under it the readers that pull PDUFA dates, guidance and readouts out of filings had
not read one filing in a scheduled run: no key until 2026-11-09, then a retired model
answering 404 on every call while each reader reported ``"status": "ok"``. These tests
break a reader and a source on purpose and read the health summary the run writes.

Nothing here touches the network: the model seam's HTTP call is replaced in every test
that runs a refresh.
"""

from __future__ import annotations

import json

import pytest

import db
import llm
import pdufa
import refresh
import run_health
from fetchers.base import BaseFetcher, RefreshResult
from fetchers.deals_news import DealsNewsFetcher

RETIRED = ("groq HTTP 404: The model `llama-3.3-70b-versatile` does not exist or you "
           "do not have access to it.")
EARLY = "2026-11-23 06:05:00"          # a Monday, hours before any market opens


# --- the summary itself: pure ----------------------------------------------------------

def _source(name, rows=10, errors=0, ran=1, skipped=0):
    return {"source": name, "rows_fetched": rows, "ran": ran, "skipped_ttl": skipped,
            "errors": [f"{name}: boom"] * errors, "notes": []}


def test_a_clean_early_run_is_normal():
    health = run_health.summarise(EARLY, [_source("prices", ran=75)], [], {}, "groq")
    assert health["abnormal"] is False and health["reasons"] == []
    assert health["start_hour_utc"] == 6 and health["in_us_session"] is False
    assert health["line"].startswith("normal: started 06:05 UTC, outside the US session")


@pytest.mark.parametrize("started, inside", [
    ("2026-11-23 17:49:53", True),     # run 143: 12:49 in New York, a Monday
    ("2026-11-23 14:29:59", False),    # a second before the winter open
    ("2026-11-23 14:30:00", True),
    ("2026-11-23 21:00:00", False),    # the winter close
    ("2026-07-20 13:45:00", True),     # summer time: the open is 13:30 UTC
    ("2026-11-21 17:00:00", False),    # a Saturday
])
def test_the_us_session_follows_new_york_not_a_fixed_utc_hour(started, inside):
    assert run_health.in_us_session(run_health.parse_utc(started)) is inside


def test_a_run_that_began_in_the_us_session_is_abnormal():
    health = run_health.summarise("2026-11-23 17:49:53", [], [], {}, "groq")
    assert health["abnormal"] and health["start_hour_utc"] == 17
    assert health["reasons"] == ["started at 17:49 UTC, inside the US session"]


def test_an_unreadable_start_is_not_called_outside_the_session():
    health = run_health.summarise(None, [], [], {}, "groq")
    assert health["in_us_session"] is None and "session not known" in health["line"]


def test_one_company_of_seventy_five_erring_is_listed_and_is_not_abnormal():
    """The press page that refuses one company has made almost every run partial since
    August. A summary that called that abnormal would be the word partial again."""
    health = run_health.summarise(
        EARLY, [_source("press_ir", rows=900, errors=1, ran=75)], [], {}, "groq")
    assert [s["source"] for s in health["sources_erred"]] == ["press_ir"]
    assert health["sources_failed"] == [] and health["abnormal"] is False
    assert "sources erred: press_ir" in health["line"]


def test_a_source_that_fetched_nothing_and_erred_every_time_is_abnormal():
    health = run_health.summarise(
        EARLY, [_source("trials", rows=0, errors=75, ran=75),
                _source("purple_book", rows=0, errors=1)], [], {}, "groq")
    assert health["sources_failed"] == ["trials", "purple_book"]
    assert health["abnormal"]
    assert health["reasons"] == ["2 sources fetched nothing and erred: trials, purple_book"]


def _quiet(name, runs):
    return {"source": name, "last_rows": 412, "last_run": 9,
            "last_seen": "2026-10-20 06:00:00", "quiet_runs": runs}


def test_a_quiet_day_is_listed_once_and_is_not_abnormal():
    """went_quiet writes an error onto the source it reports; one event, one mention.
    And one quiet run is usually a quiet day: 31 of the 33 spells in the committed log
    that ended by themselves lasted one or two runs."""
    health = run_health.summarise(
        EARLY, [_source("pulse", rows=0, errors=1)], [_quiet("pulse", 2)], {}, "groq")
    assert health["sources_quiet"] == [{"source": "pulse", "runs": 2}]
    assert health["sources_erred"] == [] and health["sources_failed"] == []
    assert health["abnormal"] is False and "quiet: pulse (2 runs)" in health["line"]


def test_a_source_quiet_for_three_runs_is_abnormal():
    health = run_health.summarise(
        EARLY, [_source("purple_book", rows=0, errors=1)],
        [_quiet("purple_book", run_health.QUIET_RUNS)], {}, "groq")
    assert health["sources_quiet_long"] == ["purple_book"] and health["abnormal"]
    assert health["reasons"] == [
        "1 source returned nothing for 3 runs or more: purple_book (3 runs)"]


def test_a_reader_whose_every_call_failed_is_abnormal_and_a_partly_failed_one_is_listed():
    readers = {"pdufa": {"calls": 5, "failed": 5, "last_error": RETIRED},
               "guidance": {"calls": 28, "failed": 3, "last_error": "gemini HTTP 503"},
               "deals": {"calls": 0, "failed": 0, "last_error": None}}
    health = run_health.summarise(EARLY, [], [], readers, "groq")
    assert health["readers_failed"] == ["pdufa"]
    assert health["reasons"] == ["every model call failed in: pdufa (5 of 5)"]
    by_name = {r["reader"]: r for r in health["readers"]}
    assert by_name["guidance"] == {"reader": "guidance", "calls": 28, "failed": 3,
                                   "error": "gemini HTTP 503"}
    assert "deals" not in by_name, "a reader that asked nothing has nothing to report"


def test_no_model_at_all_is_abnormal():
    """How the scheduled run spent its first 128 runs: every reader said "no key"."""
    health = run_health.summarise(EARLY, [], [], {}, None)
    assert health["abnormal"] and "no model provider" in health["line"]


def test_the_job_start_is_carried_when_the_schedule_supplies_it():
    health = run_health.summarise(EARLY, [], [], {}, "groq",
                                  job_started_at="2026-11-23 06:00:41")
    assert health["job_started_at"] == "2026-11-23 06:00:41"
    assert "job_started_at" not in run_health.summarise(EARLY, [], [], {}, "groq")


# --- the seam counts what the readers do not report ------------------------------------

@pytest.fixture
def groq_only(monkeypatch):
    for var in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "LLM_PROVIDER", "ER_JOB_STARTED_AT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")


def _retired_model(label, url, headers, body, timeout=None):
    raise RuntimeError(RETIRED)


def test_a_failure_the_reader_swallows_is_still_counted(groq_only, monkeypatch):
    monkeypatch.setattr(llm, "_post", _retired_model)
    with llm.counting() as count:
        for _ in range(3):
            try:
                llm.complete("s", "u")
            except Exception:
                pass                    # what the readout readers do with it
    assert (count.calls, count.failed) == (3, 3)
    assert "is not served to this key" in count.last_error


def test_an_answered_call_is_counted_as_answered(groq_only, monkeypatch):
    monkeypatch.setattr(llm, "_post", lambda *a, **k: {
        "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})
    with llm.counting() as count:
        assert llm.complete("s", "u") == "{}"
    assert count.as_dict() == {"calls": 1, "failed": 0, "last_error": None}
    with llm.counting() as later:
        pass
    assert later.calls == 0, "a count sees only what happens while it is open"


def test_a_retired_groq_model_says_what_to_change_and_keeps_what_groq_said(
        groq_only, monkeypatch):
    monkeypatch.setattr(llm, "_post", _retired_model)
    with pytest.raises(RuntimeError) as caught:
        llm.complete("s", "u")
    message = str(caught.value)
    assert "Set GROQ_MODEL" in message and RETIRED in message
    # And it stops a reader's loop: the next filing would fail the same way.
    assert pdufa.is_fatal(caught.value)
    assert not pdufa.is_fatal(RuntimeError("groq HTTP 404: no such route"))


def test_an_answer_cut_off_before_it_began_is_an_error_not_an_empty_answer():
    """Read on 2026-11-23: a reasoning model given 64 tokens spent 62 reasoning and
    returned "" with finish_reason length. An empty string parses as nothing found."""
    spent = {"choices": [{"message": {"content": "", "reasoning": "thinking it over"},
                          "finish_reason": "length"}]}
    with pytest.raises(ValueError, match="before answering"):
        llm.groq_text(spent)
    empty_by_choice = {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}
    assert llm.groq_text(empty_by_choice) == ""


def test_a_groq_reasoning_model_is_asked_for_a_short_think_and_no_other_model_is(
        groq_only, monkeypatch):
    sent = []

    def answer(label, url, headers, body, timeout=None):
        sent.append(body)
        return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

    monkeypatch.setattr(llm, "_post", answer)
    monkeypatch.setattr(llm, "GROQ_MODEL", "openai/gpt-oss-120b")
    llm.complete("s", "u")
    monkeypatch.setattr(llm, "GROQ_MODEL", "some-other-model")
    llm.complete("s", "u")
    assert sent[0]["model"] == "openai/gpt-oss-120b"
    assert sent[0]["reasoning_effort"] == "low"
    assert "reasoning_effort" not in sent[1], "Groq documents it for two ids only"


# --- through a whole run ---------------------------------------------------------------

def _probe(name, behaviour):
    class Probe(BaseFetcher):
        source = name
        ttl_seconds = 0

        @property
        def entity_key(self):
            return name

        def fetch(self):
            return behaviour()

        def normalise(self, raw):
            return []

        def snapshot(self, rows):
            pass

        def _snapshot_cache(self):
            pass

        def upsert(self, rows):
            return self._result if hasattr(self, "_result") else RefreshResult(name, 0)

    return Probe


def _run(tmp_path, monkeypatch, payer=(), started=EARLY, history=()):
    """A whole universe refresh on an empty book, with no download: the universe and
    company fetchers are off, ``payer`` stands in for the late fetch stage, and the
    start is fixed so the session test does not depend on when the suite runs."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = str(tmp_path / "t.db")
    db.init(path)
    if history:
        conn = db.get_connection(path)
        for detail in history:
            conn.execute("INSERT INTO refresh_runs (started_at, finished_at, status,"
                         " detail) VALUES ('2026-11-22 06:00:00', '2026-11-22 06:30:00',"
                         " 'complete', ?)", (json.dumps(detail),))
        conn.commit()
        conn.close()
    monkeypatch.setattr(refresh, "_universe_fetchers", lambda db_path: [])
    monkeypatch.setattr(refresh, "_payer_fetchers",
                        lambda db_path: [make(db_path) for make in payer])
    monkeypatch.setattr(DealsNewsFetcher, "fetch",
                        lambda self: {"feeds": {}, "companies": [], "errors": []})
    monkeypatch.setattr(refresh, "_started_at", lambda db_path, run_id: started)
    return path, refresh.run_refresh_all(path, force=True)


def test_a_healthy_run_writes_a_normal_health_line(tmp_path, monkeypatch, groq_only):
    monkeypatch.setattr(llm, "_post", _retired_model)      # nothing may reach a model
    path, run = _run(tmp_path, monkeypatch)
    health = run["detail"]["health"]
    assert run["status"] == "complete"
    assert health["abnormal"] is False, health["reasons"]
    assert health["line"] == ("normal: started 06:05 UTC, outside the US session; "
                              "sources erred: none; quiet: none; "
                              "readers failing every call: none")
    # It is in the committed record's shape too: the detail column, as JSON.
    conn = db.get_connection(path)
    try:
        stored = json.loads(conn.execute(
            "SELECT detail FROM refresh_runs WHERE id = ?", (run["id"],)).fetchone()[0])
    finally:
        conn.close()
    assert stored["health"] == health


def test_a_deliberately_broken_reader_makes_the_run_abnormal(
        tmp_path, monkeypatch, groq_only):
    """The reader of 2026-11-09 to 2026-11-23: the model refuses every call, the reader
    carries on past each one and reports that all is well."""
    monkeypatch.setattr(llm, "_post", _retired_model)

    def swallowing_reader(db_path=None):
        for _ in range(4):
            try:
                llm.complete("system", "a filing")
            except Exception:
                continue
        return {"status": "ok", "read": 0, "positive": 0, "negative": 0, "errors": []}

    monkeypatch.setattr(refresh.trial_readouts, "extract", swallowing_reader)
    _, run = _run(tmp_path, monkeypatch)
    health = run["detail"]["health"]
    assert health["abnormal"] is True
    assert health["readers_failed"] == ["trial_readouts"]
    assert health["reasons"] == ["every model call failed in: trial_readouts (4 of 4)"]
    assert "readers failing every call: trial_readouts" in health["line"]
    # The run cannot pass as healthy on its status either, and the reader's own entry
    # no longer says ok.
    assert run["status"] == "partial"
    entry = run["detail"]["trial_readouts"]
    assert entry["status"] == "failed"
    assert entry["model_failed"].startswith("every one of 4 model calls failed: the Groq")


def test_the_real_pdufa_reader_stops_at_the_first_call_to_a_retired_model(
        tmp_path, monkeypatch, groq_only):
    """Thirty-three calls went to the retired model on 2026-11-23. One is enough."""
    monkeypatch.setattr(llm, "_post", _retired_model)
    filings = [{"ticker": "AAA", "accession": f"0000000000-26-00000{i}",
                "url": f"https://example.invalid/{i}", "form_type": "8-K",
                "filed_date": "2026-11-20"} for i in range(5)]
    monkeypatch.setattr(pdufa, "candidates", lambda db_path, today=None: filings)
    monkeypatch.setattr(pdufa, "filing_text",
                        lambda filing: "The FDA accepted the NDA with a PDUFA date.")
    monkeypatch.setattr(pdufa, "_FETCH_PAUSE_S", 0)
    _, run = _run(tmp_path, monkeypatch)
    entry, health = run["detail"]["pdufa"], run["detail"]["health"]
    assert entry["status"] == "api unavailable", "the reader's own word is kept"
    assert (entry["read"], len(entry["errors"])) == (1, 1)
    assert health["readers_failed"] == ["pdufa"] and health["abnormal"]
    assert run["status"] == "partial"


def test_a_deliberately_broken_source_makes_the_run_abnormal(
        tmp_path, monkeypatch, groq_only):
    monkeypatch.setattr(llm, "_post", _retired_model)

    def unreachable():
        raise RuntimeError("data.cms.gov did not answer")

    _, run = _run(tmp_path, monkeypatch, payer=[_probe("partd_formulary", unreachable)])
    health = run["detail"]["health"]
    assert run["status"] == "partial"
    assert health["abnormal"] is True
    assert health["sources_failed"] == ["partd_formulary"]
    assert health["reasons"] == ["1 source fetched nothing and erred: partd_formulary"]
    assert health["line"].startswith("abnormal: started 06:05 UTC")
    assert "sources erred: partd_formulary" in health["line"]


def test_a_source_that_stopped_parsing_is_listed_at_once_and_abnormal_on_the_third_run(
        tmp_path, monkeypatch, groq_only):
    """The Purple Book fault: HTTP 200, nothing parsed, no exception, for weeks."""
    monkeypatch.setattr(llm, "_post", _retired_model)
    worked = {"sources": [{"source": "purple_book", "rows_fetched": 412, "ran": 1,
                           "skipped_ttl": 0}]}
    silent = {"sources": [{"source": "purple_book", "rows_fetched": 0, "ran": 1,
                           "skipped_ttl": 0}]}
    not_asked = {"sources": [{"source": "purple_book", "rows_fetched": 0, "ran": 1,
                              "skipped_ttl": 1}]}
    probe = [_probe("purple_book", lambda: [])]

    _, first = _run(tmp_path / "a", monkeypatch, payer=probe, history=[worked])
    health = first["detail"]["health"]
    assert health["sources_quiet"] == [{"source": "purple_book", "runs": 1}]
    assert health["abnormal"] is False and health["sources_failed"] == []
    assert first["status"] == "partial", "went_quiet still reports it, as before"

    # Two silent runs before this one make three; a run that skipped it does not count.
    _, third = _run(tmp_path / "b", monkeypatch, payer=probe,
                    history=[worked, silent, not_asked, silent])
    health = third["detail"]["health"]
    assert health["sources_quiet"] == [{"source": "purple_book", "runs": 3}]
    assert health["abnormal"] is True
    assert health["reasons"] == [
        "1 source returned nothing for 3 runs or more: purple_book (3 runs)"]


def test_a_release_guard_with_nothing_new_is_not_a_source_gone_quiet(
        tmp_path, monkeypatch, groq_only):
    """The three Medicare and Medicaid sources of 2026-10-30 onwards. Each answered "no
    new release, nothing read", and each was reported as gone quiet on every run, which
    alone would have kept every run partial."""
    monkeypatch.setattr(llm, "_post", _retired_model)
    before = [{"sources": [{"source": "partd_formulary", "rows_fetched": 936}]}]

    def guarded(db_path):
        fetcher = _probe("partd_formulary", lambda: {})(db_path)
        fetcher._result = RefreshResult(
            "partd_formulary", 0, skipped_ttl=True,
            notes=["partd_formulary: the 2026-10-08 release is already read, so nothing "
                   "was fetched"])
        return fetcher

    _, run = _run(tmp_path, monkeypatch, payer=[guarded], history=before)
    source = next(s for s in run["detail"]["sources"] if s["source"] == "partd_formulary")
    assert (source["ran"], source["skipped_ttl"], source["errors"]) == (1, 1, [])
    assert "already read" in source["notes"][0]
    assert run["detail"]["went_quiet"] == []
    assert run["status"] == "complete" and run["detail"]["health"]["abnormal"] is False


def test_a_pmda_release_already_read_is_not_due_and_a_new_one_that_parses_nothing_is(
        tmp_path):
    """The same guard on the Japanese approvals list, which a forced Sunday run reaches:
    reported quiet on each of the four Sundays to 2026-11-22."""
    from fetchers.approvals_pmda import PmdaApprovalsFetcher

    path = str(tmp_path / "jp.db")
    db.init(path)
    fetcher = PmdaApprovalsFetcher(path)
    release = {"url": "https://www.pmda.go.jp/files/000281190.pdf",
               "label": "April 2004 to February 2026"}
    fetcher._release = {**release, "new": False}
    assert fetcher.upsert([]).skipped_ttl is True
    # A release never read before that yields no row is a parser that stopped working,
    # and stays in went_quiet's sight.
    fetcher._release = {**release, "new": True}
    assert fetcher.upsert([]).skipped_ttl is False


def test_a_run_that_began_mid_session_says_so(tmp_path, monkeypatch, groq_only):
    monkeypatch.setattr(llm, "_post", _retired_model)
    monkeypatch.setenv("ER_JOB_STARTED_AT", "2026-11-23 17:31:02")
    _, run = _run(tmp_path, monkeypatch, started="2026-11-23 17:49:53")
    health = run["detail"]["health"]
    assert health["abnormal"] and health["in_us_session"] is True
    assert health["job_started_at"] == "2026-11-23 17:31:02"
    assert run["status"] == "complete", "the hour is the summary's business, not the status"


def test_a_single_company_refresh_carries_the_summary_too(
        tmp_path, monkeypatch, groq_only):
    """The Refresh button's run, with the same broken reader: it is one company's run
    that an analyst is looking at when the readers are down."""
    monkeypatch.setattr(llm, "_post", _retired_model)
    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'ZZZ', 'Zed')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(refresh, "_company_fetchers", lambda company, db_path: [])
    monkeypatch.setattr(refresh, "_started_at", lambda db_path, run_id: EARLY)

    def swallowing_reader(db_path=None):
        try:
            llm.complete("system", "a section")
        except Exception:
            pass
        return {"status": "ok", "read": 1, "found": 0, "errors": []}

    monkeypatch.setattr(refresh.guidance_module, "extract", swallowing_reader)
    run = refresh.run_refresh(path, "ZZZ")
    health = run["detail"]["health"]
    assert health["readers_failed"] == ["guidance"] and health["abnormal"]
    assert run["status"] == "partial" and run["detail"]["guidance"]["status"] == "failed"


def test_a_crashed_run_is_abnormal_in_its_own_record(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    db.init(path)

    def crash(db_path, force, run_id):
        raise RuntimeError("FOREIGN KEY constraint failed")

    monkeypatch.setattr(refresh, "_run_refresh_all", crash)
    with pytest.raises(RuntimeError):
        refresh.run_refresh_all(path)
    conn = db.get_connection(path)
    try:
        row = conn.execute("SELECT status, detail FROM refresh_runs").fetchone()
    finally:
        conn.close()
    health = json.loads(row["detail"])["health"]
    assert row["status"] == "failed" and health["abnormal"] is True
    assert health["line"] == ("abnormal: the run crashed: RuntimeError: FOREIGN KEY "
                              "constraint failed")


def test_the_scheduled_job_logs_the_health_line(tmp_path, monkeypatch):
    import scheduled_refresh as sched

    monkeypatch.setattr(sched, "LOCK_FILE", tmp_path / "l.lock")
    monkeypatch.setattr(sched, "LOG_FILE", tmp_path / "r.log")
    monkeypatch.setattr(sched, "LOG_DIR", tmp_path)
    monkeypatch.setattr(sched, "wait_for_network", lambda *a, **k: True)
    monkeypatch.setattr(sched, "_record_calls", lambda *a, **k: None)
    line = "abnormal: started 17:49 UTC, inside the US session; sources erred: none"
    result = {"id": 144, "status": "partial",
              "detail": {"changes": {}, "health": {"abnormal": True, "line": line}}}
    assert sched.run(refresh_fn=lambda path=None: result) == 0
    assert f"run 144 health {line}" in (tmp_path / "r.log").read_text()
