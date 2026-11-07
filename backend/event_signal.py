"""Which of the things the book notices precede a move, measured against a benchmark
that cannot flatter them.

``backtest`` asks what happens after an event and the answer, measured, is nothing: a
positive Phase 3 readout is preceded by +19.4% of abnormal return over three months and
followed by +0.4% on the day. The move is in the price before the data is public, so the
readout is not the trade. It also says, correctly, that a trial status or date change
carries no event date of its own and so cannot be measured that way.

This is the other half. A detection time is not an event date, but it is the honest
timestamp for a signal: it is the day this book could first have acted. The feed's own
stamps stand up to that: across the filings it records, a change is detected a mean of
1.37 days after the filing date and never more than eight.

**The benchmark is the whole measurement, and the obvious one is wrong.** Measured
against the equal-weight return of the rest of this book's own universe, every one of
fifteen change types showed positive abnormal returns and the busiest showed +3.1% a
month at a 64% hit rate. None of it was real. A book of biotech is dragged by whatever
is collapsing inside it, so its own equal-weight mean is a benchmark almost anything
beats: a random company-day beats it 45% of the time on the mean and loses on the
median. Against XBI, the equal-weight biotech ETF this repository already stores back to
2016, the same three types read -0.1%, -0.7% and -1.9%, and their hit rates fall from
+19, +17 and +26 points to +3, +7 and +9. The effect was the benchmark.

So the benchmark here is XBI, which is sector-matched, equal-weight like the signal, and
tradeable, which the book's own universe is not. ``universe`` stays available for
comparison, and a view that quotes one should say which.

Two further things are handled rather than hoped past.

**The placebo has to be drawn on the same days.** Events are not spread evenly through
time and a quarter when the sector rallied makes every event look clever. The placebo
samples the event days themselves, at the frequency they occur, so the regime is held
still. Drawn across the whole price history instead it reads -0.21% where the
date-matched one reads +0.77%, and that difference is regime rather than signal.

**Overlapping windows are not independent observations.** Three hundred and seventy
status changes across fifty-two companies in one quarter is not three hundred and
seventy samples: two events on one company a week apart share almost all of their
forward window. So the count that governs whether anything is reported is distinct
company-months, and the view says both.

What it will say for a while is that there is not enough history. The change feed starts
2026-07-18, which is one quarter. That is the honest answer and it is the same one
``valuation_history`` gives: the instrument is the point, and it accrues.
"""

from __future__ import annotations

import random
import statistics
from collections import Counter, defaultdict

import backtest
import benchmark_series as _bench
import db

# The benchmark a signal has to beat. XBI is the equal-weight biotech ETF, so it matches
# the kind of name this book holds and is something a reader could actually short
# against a long. "universe" is the equal-weight mean of the book's own companies, kept
# for comparison and not as the default: it is dragged by its own casualties and almost
# anything beats it (the module docstring measures by how much).
BENCHMARKS = ("XBI", "IBB", "XLV", "^GSPC")
DEFAULT_BENCHMARK = _bench.BENCHMARK

# Forward windows, in trading days from the day the book recorded the change.
WINDOWS = ({"key": "fwd_1m", "label": "1 month", "days": 21},
           {"key": "fwd_3m", "label": "3 months", "days": 63})

# Below these a change type is reported as thin rather than as a result. The months and
# the company-months are the ones that bind: events are cheap and independence is not.
MIN_EVENTS = 20
MIN_COMPANY_MONTHS = 40
MIN_MONTHS = 12

# Draws behind the date-matched placebo. Large enough that its own standard error is
# small beside the effects being measured, and it costs nothing to compute.
PLACEBO_DRAWS = 6000
PLACEBO_SEED = 11


def events(conn) -> list[dict]:
    """Every recorded change joined to the company it belongs to, with its detection day.

    Three entity kinds carry a company differently: a change on an asset joins through
    the asset's owner, one on a trial through the trial's sponsor, and a company change
    writes the ticker into the front of its own key. A change this cannot place is left
    out rather than attributed to a guess.
    """
    return [dict(r) for r in conn.execute(
        """SELECT c.change_type, substr(c.detected_at, 1, 10) AS day, a.owner_company_id AS cid
             FROM changes c JOIN assets a
               ON CAST(a.id AS TEXT) = CAST(c.entity_key AS TEXT)
            WHERE c.entity_type = 'asset' AND a.owner_company_id IS NOT NULL
           UNION ALL
           SELECT c.change_type, substr(c.detected_at, 1, 10), t.sponsor_company_id
             FROM changes c JOIN trials t ON t.nct_id = c.entity_key
            WHERE c.entity_type = 'trial' AND t.sponsor_company_id IS NOT NULL
           UNION ALL
           SELECT c.change_type, substr(c.detected_at, 1, 10), co.id
             FROM changes c JOIN companies co
               ON co.ticker = substr(c.entity_key, 1, instr(c.entity_key, '|') - 1)
            WHERE c.entity_type = 'company' AND instr(c.entity_key, '|') > 0""")]


def benchmark_series(conn, symbol: str = DEFAULT_BENCHMARK) -> list:
    """[(day, close)] for one benchmark; [] for "universe", which has no series."""
    return [] if symbol == "universe" else _bench.series(conn, symbol)


def benchmark_return(bars: list, day: str, days: int):
    """The benchmark's forward return over ``days`` bars, or None off the series."""
    return _bench.span(bars, day, 0, days)


def abnormal(series: dict, company_id: int, day: str, days: int, bars: list = None):
    """The company's forward return less the benchmark's, or None.

    ``bars`` is a benchmark series; with none, the comparison falls back to the book's
    own equal-weight universe, which the docstring explains is the weaker choice.
    """
    own = backtest.span_return(series, company_id, day, 0, days)
    if own is None:
        return None
    rest = (benchmark_return(bars, day, days) if bars
            else backtest.universe_span(series, day, 0, days, exclude=company_id))
    return None if rest is None else own - rest


def placebo(series: dict, days: int, days_pool: list, bars: list = None,
            draws: int = PLACEBO_DRAWS) -> dict:
    """What a random company-day earns on the same days the events fall on.

    ``days_pool`` carries each event day once per event, so a day with forty changes is
    forty times as likely to be drawn. That holds the regime still: the question is
    whether the event beat its own week, not whether its quarter beat the decade.
    """
    rng = random.Random(PLACEBO_SEED)
    ids = [cid for cid, bars in series.items() if len(bars) > 200]
    if not ids or not days_pool:
        return {"n": 0, "mean": None, "hit": None}
    got = []
    for _ in range(draws):
        value = abnormal(series, rng.choice(ids), rng.choice(days_pool), days, bars)
        if value is not None:
            got.append(value)
    if not got:
        return {"n": 0, "mean": None, "hit": None}
    return {"n": len(got), "mean": statistics.mean(got),
            "hit": sum(1 for v in got if v > 0) / len(got)}


def build(db_path=None, benchmark: str = DEFAULT_BENCHMARK) -> dict:
    """{benchmark, windows, rows, placebo, reason}. Reads; never writes."""
    conn = db.get_connection(db_path)
    try:
        series = backtest._series(conn)
        found = events(conn)
        bars = benchmark_series(conn, benchmark)
    finally:
        conn.close()
    if benchmark != "universe" and not bars:
        benchmark = "universe"          # said in the result rather than silently

    days_pool = [e["day"] for e in found]
    months = {e["day"][:7] for e in found}
    placebos = {w["key"]: placebo(series, w["days"], days_pool, bars) for w in WINDOWS}

    rows = []
    for change_type in sorted({e["change_type"] for e in found}):
        mine = [e for e in found if e["change_type"] == change_type]
        cells = {(e["cid"], e["day"][:7]) for e in mine}
        windows = {}
        for window in WINDOWS:
            got = [v for v in (abnormal(series, e["cid"], e["day"], window["days"], bars)
                               for e in mine) if v is not None]
            if not got:
                continue
            base = placebos[window["key"]]
            mean = statistics.mean(got)
            hit = sum(1 for v in got if v > 0) / len(got)
            windows[window["key"]] = {
                "n": len(got), "mean_abnormal": mean, "hit_rate": hit,
                "excess_mean": None if base["mean"] is None else mean - base["mean"],
                "excess_hit": None if base["hit"] is None else hit - base["hit"],
                # Thin on the count that governs: two events on one company a week
                # apart share almost all of their forward window.
                "thin": len(got) < MIN_EVENTS or len(cells) < MIN_COMPANY_MONTHS,
            }
        if windows:
            rows.append({"change_type": change_type, "events": len(mine),
                         "company_months": len(cells),
                         "companies": len({e["cid"] for e in mine}), "windows": windows})

    rows.sort(key=lambda r: -(r["windows"].get("fwd_1m", {}).get("excess_hit") or -9))
    enough = (len(months) >= MIN_MONTHS
              and max((r["company_months"] for r in rows), default=0) >= MIN_COMPANY_MONTHS)
    return {
        "benchmark": benchmark,
        "windows": [{"key": w["key"], "label": w["label"]} for w in WINDOWS],
        "rows": rows, "placebo": placebos,
        "events": len(found), "companies": len({e["cid"] for e in found}),
        "months": len(months),
        "first": min(days_pool) if days_pool else None,
        "last": max(days_pool) if days_pool else None,
        "reason": None if enough else (
            "no changes recorded yet" if not found else
            f"the change feed starts {min(days_pool)} and covers {len(months)} months "
            f"across {len({e['cid'] for e in found})} companies. A forward window needs "
            f"months that have closed and events that do not share one, and the count "
            f"that governs is company-months rather than events: the largest type has "
            f"{max(r['company_months'] for r in rows) if rows else 0} against the "
            f"{MIN_COMPANY_MONTHS} this reports on. Read the rows as a direction to "
            f"watch, not as a result"),
    }
