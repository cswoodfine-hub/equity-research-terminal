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
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import env  # noqa: F401,E402  load .env before any module reads a key

import refresh  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent
LOG_DIR = _REPO / "logs"
LOG_FILE = LOG_DIR / "refresh.log"
LOCK_FILE = LOG_DIR / "refresh.lock"


def _log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} UTC  {message}\n")


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
        result = refresh_fn(db_path) if db_path is not None else refresh_fn()
        status = result.get("status", "unknown")
        detail = result.get("detail", {}) if isinstance(result, dict) else {}
        changes = detail.get("changes") if isinstance(detail, dict) else None
        _log(f"run {result.get('id')} {status}; changes={json.dumps(changes)}")
        return 0 if status in ("complete", "partial") else 1
    except Exception as exc:                       # a hard failure to run at all
        _log(f"failed: {type(exc).__name__}: {exc}")
        return 2
    finally:
        LOCK_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(run())
