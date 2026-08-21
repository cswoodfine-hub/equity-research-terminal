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


# --- a run that starts before the machine has a network --------------------
# On 2026-08-21 the 06:00 job recorded 688 failed fetches against 179 live ones and
# detected zero changes. Every failure was a DNS error: the laptop had woken for the
# job and its network had not associated yet. The run reported partial, which is what
# a run reports when a few sources are down, so the morning looked quiet rather than
# missing.

def test_the_run_waits_for_the_network_before_fetching(tmp_path, monkeypatch):
    import scheduled_refresh as sched

    monkeypatch.setattr(sched, "LOCK_FILE", tmp_path / "l.lock")
    monkeypatch.setattr(sched, "LOG_FILE", tmp_path / "r.log")
    monkeypatch.setattr(sched, "LOG_DIR", tmp_path)

    tries, slept = [], []
    def resolving_on_the_third_go(host, port):
        tries.append(host)
        if len(tries) < 3:
            raise OSError(8, "nodename nor servname provided, or not known")
        return [(2, 1, 6, "", ("1.2.3.4", 443))]

    monkeypatch.setattr(sched.socket, "getaddrinfo", resolving_on_the_third_go)
    assert sched.wait_for_network(pause_s=0, sleep=slept.append) is True
    assert len(tries) == 3


def test_a_refresh_is_not_started_without_one(tmp_path, monkeypatch):
    import scheduled_refresh as sched

    monkeypatch.setattr(sched, "LOCK_FILE", tmp_path / "l.lock")
    monkeypatch.setattr(sched, "LOG_FILE", tmp_path / "r.log")
    monkeypatch.setattr(sched, "LOG_DIR", tmp_path)
    monkeypatch.setattr(sched, "wait_for_network", lambda *a, **k: False)

    ran = []
    code = sched.run(refresh_fn=lambda path=None: ran.append(path) or {"status": "x"})
    # Nothing fetched, a distinct exit code, and the lock handed back for the next run.
    assert ran == []
    assert code == 3
    assert not (tmp_path / "l.lock").exists()
    assert "no network" in (tmp_path / "r.log").read_text()


def test_it_gives_up_rather_than_waiting_forever(tmp_path, monkeypatch):
    import scheduled_refresh as sched

    monkeypatch.setattr(sched, "LOG_FILE", tmp_path / "r.log")
    monkeypatch.setattr(sched, "LOG_DIR", tmp_path)
    monkeypatch.setattr(sched.socket, "getaddrinfo",
                        lambda *a: (_ for _ in ()).throw(OSError(8, "no dns")))
    slept = []
    assert sched.wait_for_network(attempts=4, pause_s=0, sleep=slept.append) is False
    # Waits between attempts but not after the last one.
    assert len(slept) == 3


def test_a_network_that_is_up_costs_no_wait(tmp_path, monkeypatch):
    import scheduled_refresh as sched

    monkeypatch.setattr(sched, "LOG_FILE", tmp_path / "r.log")
    monkeypatch.setattr(sched, "LOG_DIR", tmp_path)
    monkeypatch.setattr(sched.socket, "getaddrinfo",
                        lambda *a: [(2, 1, 6, "", ("1.2.3.4", 443))])
    slept = []
    assert sched.wait_for_network(sleep=slept.append) is True
    assert slept == []
