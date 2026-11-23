"""Whether a daily bar is a finished session or one still trading.

Yahoo's daily chart carries a bar for today from the opening bell, and its close is the
last trade. Filed as it stands, that bar puts an intraday price into the stored series
and into the day's snapshot under the name of a close. The schedule was meant to prevent
it by running at 06:00 UTC, before any market the book quotes has opened. It does not:
every refresh in the committed run log from 2026-10-10 to 2026-11-23 began between 10:26
and 18:14 UTC, because a scheduled runner starts when the host has room for it. Measured
on 2026-11-23, 28 days of snapshots from 2026-07-24 to 2026-11-20 carry a mid-session
price as that day's close, 1,232 company-days at a median 1.2% from the settled close.
So the rule lives here, where the hour cannot move it: a bar from a session that has not
closed is held back, whenever the read happens. The next read after the bell brings it,
since every read asks for the whole range.

Pure, and outside ``fetchers/`` so the price fetcher and the benchmark fetcher can share
one rule without importing each other.
"""

from __future__ import annotations

_DAY_S = 86400


def unsettled_from(meta: dict | None, now: float) -> int | None:
    """The epoch from which a daily bar cannot yet be called a close, or None where
    every bar in the payload is one.

    Where the payload states the regular session's hours (``currentTradingPeriod``),
    a bar stamped at or after that session's start is unsettled until its end. Before
    the open there is no such bar, and the start is returned all the same, which holds
    back nothing.

    Where it states none, a bar dated today at the exchange cannot be shown to be
    finished, so the cut is that day's midnight. Not knowing the hours is not leave to
    file the bar: the cost is a close that arrives one read later.
    """
    meta = meta or {}
    period = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    start, end = period.get("start"), period.get("end")
    if start is not None and end is not None:
        return int(start) if now < end else None
    offset = int(meta.get("gmtoffset") or 0)
    return (int(now + offset) // _DAY_S) * _DAY_S - offset


def is_settled(stamp, meta: dict | None, now: float | None) -> bool:
    """True where the daily bar stamped ``stamp`` is a finished session at ``now``.
    ``now`` of None asks no question and settles everything, which is how a saved
    payload is parsed in a test and how an intraday series is read."""
    if now is None:
        return True
    cut = unsettled_from(meta, now)
    return cut is None or stamp < cut
