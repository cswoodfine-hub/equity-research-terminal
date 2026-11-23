"""An input meant to have been known beforehand is read as of the day (dated_inputs.py)."""

import inspect

import pytest

import dated_inputs as D
import db
import signal_test


@pytest.fixture
def book(tmp_path):
    path = str(tmp_path / "inputs.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AAA', 'Aaa Bio')")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (10, 1, 'examplumab', 1)")
    conn.commit()
    yield conn
    conn.close()


def test_no_input_reads_a_column_that_carries_no_date():
    for name, (fn, dated_by) in D.INPUTS.items():
        text = inspect.getsource(fn)
        assert dated_by.split(".")[1] in text, f"{name} does not read {dated_by}"
        for column in signal_test.UNDATED_COLUMNS:
            assert column not in text, f"{name} reads {column}, which carries no date"
        assert "day" in inspect.signature(fn).parameters, f"{name} takes no day"


def test_an_approval_after_the_day_is_not_seen(book):
    """The drug is marketed today. On the day of its readout it was not approved."""
    book.execute("INSERT INTO approvals (asset_id, application_number, approval_date)"
                 " VALUES (10, 'BLA1', '2025-06-30')")
    book.commit()
    assert D.approved_before(book, 10, "2025-01-15") is False      # before the approval
    assert D.approved_before(book, 10, "2025-06-30") is False      # the day itself
    assert D.approved_before(book, 10, "2025-07-01") is True
    assert D.approved_before(book, None, "2025-07-01") is None
    assert D.approved_before(book, 10, "not a day") is None


def test_a_later_positive_phase_3_is_not_an_earlier_one(book):
    def readout(accession, day, outcome="positive", phase=3):
        book.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase,"
                     " outcome, event_date) VALUES (?, 1, 'Examplumab', ?, ?, ?)",
                     (accession, phase, outcome, day))
    readout("a", "2025-03-01")
    readout("b", "2025-09-01")                       # the readout being asked about
    readout("c", "2026-02-01")                       # a later one
    readout("d", "2024-01-01", outcome="negative")   # an earlier failure is not a success
    readout("e", "2024-06-01", phase=2)              # nor is a Phase 2
    book.commit()
    assert D.earlier_positive_phase3(book, 1, "examplumab", "2025-09-01") is True
    assert D.earlier_positive_phase3(book, 1, "examplumab", "2025-03-01") is False
    # A second announcement a fortnight on is the same result, not an earlier one.
    assert D.earlier_positive_phase3(book, 1, "examplumab", "2025-03-15") is False
    assert D.earlier_positive_phase3(book, 1, "", "2025-09-01") is None


def test_results_posted_after_the_day_are_not_seen(book):
    book.execute("INSERT INTO trial_result_fetches (nct_id, has_results, results_date)"
                 " VALUES ('NCT1', 1, '2025-05-10')")
    book.execute("INSERT INTO trial_result_fetches (nct_id, has_results, results_date)"
                 " VALUES ('NCT2', 0, NULL)")
    book.commit()
    assert D.results_posted_before(book, "NCT1", "2025-05-01") is False
    assert D.results_posted_before(book, "NCT1", "2025-06-01") is True
    assert D.results_posted_before(book, "NCT2", "2025-06-01") is False
    assert D.results_posted_before(book, "NCT9", "2025-06-01") is None   # never asked
