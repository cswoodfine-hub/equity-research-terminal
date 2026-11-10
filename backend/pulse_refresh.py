"""The daily pulse on its own, without touching a price.

The universe refresh and the pulse want times that cannot be reconciled. Prices have to
be read before any market opens: ``fetchers/prices.py`` takes Yahoo's daily chart as it
stands, and from the opening bell that chart carries a bar for today whose close is the
last trade rather than the close, so a refresh run after 08:00 UTC would write an
intraday price into the snapshot history and no later run could tell it was wrong. That
is why the refresh is at 06:00 UTC and stays there.

The pulse wants the opposite. Its value is the European morning: the briefing read on
2026-10-30 carried Sanofi's and Regeneron's results published that same morning, which a
run before 06:00 could not have seen. So the pulse is read by this pass instead, hours
after the refresh, and the two never move each other.

Nothing here fetches over the network. The pulse's own scheduled run has already pushed
the day's file to ``claude/pulse-feed``; the workflow checks that folder out into
``ER_PULSE_DIR`` and this reads it (``fetchers/news_pulse.py``).

No ``refresh_runs`` row is opened on purpose. ``/runs/latest`` is what the top bar reads
for "last refresh", and a pulse pass that opened a run would have the terminal claim the
universe was refreshed when only the briefing was read. ``refresh_run_id`` is a nullable
provenance column that nothing queries, so the pulse's rows carry none.

    backend/.venv/bin/python backend/pulse_refresh.py
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import env  # noqa: F401,E402  load .env before any module reads a key

import scheduled_refresh  # noqa: E402
from fetchers.news_pulse import PulseNewsFetcher  # noqa: E402


def run(fetcher_fn=None, db_path=None) -> int:
    """Read the pulse folder into the book. ``fetcher_fn`` is injectable for tests.

    Exit code 0 when the pass ran, whether or not it found anything: an empty folder is
    a quiet day, not a failure. Non-zero only on a hard failure to run at all.
    """
    fetcher_fn = fetcher_fn or (lambda path: PulseNewsFetcher(path).run())
    # The same lock the refresh holds. The two write the same database, and in CI the
    # workflow's concurrency group keeps them apart; on a machine running both from cron
    # this is what does it.
    if not scheduled_refresh._acquire_lock():
        scheduled_refresh._log("pulse skipped: a refresh is already running")
        return 0
    try:
        result = fetcher_fn(db_path)
        rows = getattr(result, "rows_fetched", 0)
        errors = list(getattr(result, "errors", None) or [])
        scheduled_refresh._log(
            f"pulse: {rows} items read"
            + (f"; {len(errors)} errors: {errors[0]}" if errors else ""))
        return 0
    except Exception as exc:                       # a hard failure to run at all
        scheduled_refresh._log(f"pulse failed: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 2
    finally:
        scheduled_refresh.LOCK_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(run())
