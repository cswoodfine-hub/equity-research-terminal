"""The scheduled refresh entrypoint: logging, exit codes, and the overlap lock.

The real refresh hits the network, so a stub stands in for it; what is tested here
is the wrapper's own behaviour, which is what cron depends on.
"""

import os

import scheduled_refresh


def _redirect(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(scheduled_refresh, "LOG_DIR", log_dir)
    monkeypatch.setattr(scheduled_refresh, "LOG_FILE", log_dir / "refresh.log")
    monkeypatch.setattr(scheduled_refresh, "LOCK_FILE", log_dir / "refresh.lock")
    return log_dir


def test_a_complete_run_logs_and_returns_zero(tmp_path, monkeypatch):
    log_dir = _redirect(tmp_path, monkeypatch)
    fake = lambda: {"id": 7, "status": "complete",
                    "detail": {"changes": {"trial_changes": 3}}}
    assert scheduled_refresh.run(refresh_fn=fake) == 0
    log = (log_dir / "refresh.log").read_text()
    assert "run 7 complete" in log and "trial_changes" in log
    assert not (log_dir / "refresh.lock").exists()   # lock released


def test_a_partial_run_still_returns_zero(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    fake = lambda: {"id": 8, "status": "partial", "detail": {"changes": {}}}
    assert scheduled_refresh.run(refresh_fn=fake) == 0


def test_a_hard_failure_returns_nonzero_and_logs(tmp_path, monkeypatch):
    log_dir = _redirect(tmp_path, monkeypatch)

    def boom():
        raise RuntimeError("db locked")

    assert scheduled_refresh.run(refresh_fn=boom) == 2
    assert "failed: RuntimeError: db locked" in (log_dir / "refresh.log").read_text()
    assert not (log_dir / "refresh.lock").exists()   # released even on failure


def test_an_existing_live_lock_skips_the_run(tmp_path, monkeypatch):
    log_dir = _redirect(tmp_path, monkeypatch)
    log_dir.mkdir(parents=True)
    (log_dir / "refresh.lock").write_text(str(os.getpid()))  # our own live pid
    ran = {"called": False}

    def fake():
        ran["called"] = True
        return {"id": 9, "status": "complete", "detail": {}}

    assert scheduled_refresh.run(refresh_fn=fake) == 0
    assert ran["called"] is False                    # the live lock blocked it
    assert "skipped" in (log_dir / "refresh.log").read_text()


def test_a_stale_lock_is_reclaimed(tmp_path, monkeypatch):
    log_dir = _redirect(tmp_path, monkeypatch)
    log_dir.mkdir(parents=True)
    (log_dir / "refresh.lock").write_text("999999")  # a pid that is not running
    assert scheduled_refresh.run(
        refresh_fn=lambda: {"id": 10, "status": "complete", "detail": {}}) == 0
