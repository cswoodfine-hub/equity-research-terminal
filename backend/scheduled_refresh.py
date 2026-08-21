"""Standalone daily refresh, for cron or launchd.

Runs the whole-universe refresh directly through ``refresh`` rather than over HTTP,
so it needs no server up. Appends a one-line summary to ``logs/refresh.log`` and
holds a lock file for the duration, so a slow run cannot be double-fired by an
overlapping schedule. Exit code is 0 on complete or partial (a partial run still
advanced the snapshot history), non-zero only on a hard failure to run at all.

This is what turns slippage from a thin series into the proprietary one it is meant
to be: every daily run that catches a registry completion date moving writes a
change the diff engine can never backfill.

Cron (2am daily):
    0 2 * * * cd /path/to/repo && backend/.venv/bin/python backend/scheduled_refresh.py

launchd: see docs; StartCalendarInterval with the same command.
"""

from __future__ import annotations

import datetime as dt
import json
import traceback
import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import env  # noqa: F401,E402  load .env before any module reads a key

import refresh  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent
LOG_DIR = _REPO / "logs"
LOG_FILE = LOG_DIR / "refresh.log"
LOCK_FILE = LOG_DIR / "refresh.lock"

# The machine this runs on is a laptop that wakes for the job, and its
# network associates after the process starts. EDGAR is the probe because it
# is the source the run cannot do without. Twenty minutes, which is longer
# than any wake has taken and far short of the next scheduled run.
NETWORK_PROBE = "data.sec.gov"
NETWORK_ATTEMPTS = 40
NETWORK_PAUSE_S = 30


def _log(message: str) -> None:
    """Append to the log file and say the same thing on stdout.

    The file is for a cron job on a machine someone can log into. A CI runner has no
    such machine: its log file is thrown away with the container, so a failure written
    only there leaves the step reporting an exit code and nothing else, which is how
    two runs failed with no visible reason.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp} UTC  {message}"
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(line, flush=True)


def _acquire_lock() -> bool:
    """Atomic lock. Returns False when another run holds it and is still alive; a
    stale lock (dead pid) is reclaimed."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            pid = int(LOCK_FILE.read_text().strip() or "0")
            os.kill(pid, 0)          # raises if the pid is gone
            return False             # a live run holds the lock
        except (ValueError, ProcessLookupError, PermissionError):
            LOCK_FILE.unlink(missing_ok=True)
            return _acquire_lock()   # stale lock reclaimed


def wait_for_network(probe=None, attempts: int = NETWORK_ATTEMPTS,
                     pause_s: float = NETWORK_PAUSE_S, sleep=time.sleep) -> bool:
    """Wait until a name resolves, or give up. True when the network answered.

    A refresh that starts before the machine has a network does not fail, which is the
    problem. It fetches seventy companies over a dozen sources and every one of them
    raises a DNS error, so the run finishes 'partial' having written almost nothing: on
    2026-08-21 the 06:00 job recorded 688 failed fetches against 179 live ones and
    detected zero changes, and a reader would have had to open the run detail to find
    out that the morning's data never arrived.

    A laptop that wakes for a scheduled job is the ordinary case here, and its Wi-Fi
    associates seconds to minutes after the process starts. So waiting is not a
    workaround, it is the job's first step.
    """
    probe = probe or NETWORK_PROBE
    for attempt in range(attempts):
        try:
            socket.getaddrinfo(probe, 443)
            if attempt:
                _log(f"network up after {attempt * pause_s:.0f}s")
            return True
        except OSError:
            if attempt + 1 < attempts:
                sleep(pause_s)
    return False


def run(refresh_fn=None, db_path=None) -> int:
    """Run one scheduled refresh. ``refresh_fn`` is injectable for tests."""
    # A scheduled run fetches. Left to the TTLs it would skip everything a rebuilt
    # database claims to have already, which is how a runner published a database with
    # prices and nothing else.
    # The path is optional here: this is called with no arguments when the database is
    # the default one, which is every scheduled run.
    refresh_fn = refresh_fn or (
        lambda path=None: refresh.run_refresh_all(path, force=True))
    if not _acquire_lock():
        _log("skipped: another refresh is already running")
        return 0
    try:
        # Before the lock is spent on a run that cannot fetch. A refresh with no network
        # is not a refresh; better to say so and let the next scheduled run have it than
        # to write an hour of failed fetches and call the result partial.
        if not wait_for_network():
            _log(f"skipped: no network after "
                 f"{NETWORK_ATTEMPTS * NETWORK_PAUSE_S / 60:.0f} minutes waiting for "
                 f"{NETWORK_PROBE}")
            return 3
        result = refresh_fn(db_path) if db_path is not None else refresh_fn()
        status = result.get("status", "unknown")
        detail = result.get("detail", {}) if isinstance(result, dict) else {}
        changes = detail.get("changes") if isinstance(detail, dict) else None
        _log(f"run {result.get('id')} {status}; changes={json.dumps(changes)}")
        return 0 if status in ("complete", "partial") else 1
    except Exception as exc:                       # a hard failure to run at all
        _log(f"failed: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 2
    finally:
        LOCK_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(run())
