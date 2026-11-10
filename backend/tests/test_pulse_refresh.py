"""The pulse-only pass: exit codes, the shared lock, and the run row it must not open.

The pass exists because the universe refresh cannot move off 06:00 UTC without writing
intraday prices into the snapshot history, while the pulse's value is the European
morning. What is tested here is the wrapper's own behaviour, which is what the second
schedule depends on, plus the one invariant that is easy to break later: a pulse pass
reads a briefing, so it must not leave the terminal claiming the universe was refreshed.
"""

import datetime as dt
import shutil
from pathlib import Path

import db
import pulse_refresh
import seed
from fetchers.news_pulse import PulseNewsFetcher

FIXTURES = Path(__file__).parent / "fixtures" / "pulse"
TODAY = dt.date(2026, 10, 30)


def _redirect(tmp_path, monkeypatch):
    """The wrapper logs and locks through scheduled_refresh, so both are redirected."""
    import scheduled_refresh
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(scheduled_refresh, "LOG_DIR", log_dir)
    monkeypatch.setattr(scheduled_refresh, "LOG_FILE", log_dir / "refresh.log")
    monkeypatch.setattr(scheduled_refresh, "LOCK_FILE", log_dir / "refresh.lock")
    return log_dir


def _book(tmp_path):
    path = tmp_path / "p.db"
    db.init(path)
    seed.load_companies(path)
    folder = tmp_path / "pulse"
    folder.mkdir()
    shutil.copy(FIXTURES / "2026-10-30.json", folder)
    return path, folder


def test_a_pass_that_reads_a_briefing_logs_its_count_and_returns_zero(
        tmp_path, monkeypatch):
    log_dir = _redirect(tmp_path, monkeypatch)
    from fetchers.base import RefreshResult
    fake = lambda path: RefreshResult(source="pulse", rows_fetched=5, errors=[],
                                      skipped_ttl=False, elapsed_ms=4, notes=[])
    assert pulse_refresh.run(fetcher_fn=fake) == 0
    assert "pulse: 5 items read" in (log_dir / "refresh.log").read_text()


def test_an_empty_folder_is_a_quiet_day_and_not_a_failure(tmp_path, monkeypatch):
    log_dir = _redirect(tmp_path, monkeypatch)
    from fetchers.base import RefreshResult
    fake = lambda path: RefreshResult(source="pulse", rows_fetched=0, errors=[],
                                      skipped_ttl=False, elapsed_ms=1, notes=[])
    assert pulse_refresh.run(fetcher_fn=fake) == 0
    assert "pulse: 0 items read" in (log_dir / "refresh.log").read_text()


def test_a_hard_failure_is_reported_and_returns_non_zero(tmp_path, monkeypatch):
    log_dir = _redirect(tmp_path, monkeypatch)

    def boom(path):
        raise RuntimeError("the folder is a file")

    assert pulse_refresh.run(fetcher_fn=boom) == 2
    assert "pulse failed: RuntimeError" in (log_dir / "refresh.log").read_text()


def test_a_refresh_already_running_holds_the_lock_and_the_pass_stands_down(
        tmp_path, monkeypatch):
    """Both write the same database. In CI the workflow's concurrency group keeps them
    apart; on a machine running both from cron this is what does it."""
    log_dir = _redirect(tmp_path, monkeypatch)
    import scheduled_refresh
    monkeypatch.setattr(scheduled_refresh, "_acquire_lock", lambda: False)
    called = []
    assert pulse_refresh.run(fetcher_fn=lambda path: called.append(1)) == 0
    assert not called
    assert "a refresh is already running" in (log_dir / "refresh.log").read_text()


def test_the_pass_reads_the_briefing_without_opening_a_refresh_run(
        tmp_path, monkeypatch):
    """The whole point of the separate pass. /runs/latest is the top bar's "last
    refresh", so a pulse pass that opened a run would date the universe to the morning's
    briefing. The pulse's rows carry a null refresh_run_id instead."""
    _redirect(tmp_path, monkeypatch)
    path, folder = _book(tmp_path)
    fetcher = PulseNewsFetcher(path, folder=folder, today=TODAY)
    assert pulse_refresh.run(fetcher_fn=lambda _: fetcher.run(), db_path=path) == 0

    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM news WHERE source = 'pulse'"
                        ).fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM refresh_runs").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM changes WHERE refresh_run_id IS NOT NULL"
    ).fetchone()[0] == 0
