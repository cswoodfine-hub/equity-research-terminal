"""What the book said a company was worth, kept, and then read against what happened.

Every other claim in this book is tested against something. A debt line reconciles to the
filing or the sum refuses it; a forecast reconciles to the company's own guidance; a
change signal is measured against the forward abnormal return it preceded (``backtest``).
The valuation is the one claim that was never tested, and it could not be: the snapshot
history records the sources a call is built from, never the call, so there was nothing to
read back.

Two halves, and only the first can run today.

``record`` writes one row per company per price date on every refresh. A refusal is
written too, with its reason, because a refusal is a call as much as a number is and a
book that remembered only its answers would flatter itself.

``build`` reads those rows back against the price series, the way ``backtest`` reads a
change: the company's own return over the window less the equal-weight return of the rest
of the universe, so a sector move is not read as the book being right. It groups by the
upside the book published, because the question is not whether the level is accurate (it
is a different model from the market's and will differ) but whether it ranks: did the
names the book called cheap beat the names it called dear.

It will say "not enough history yet" for months, and should. A twelve-month window needs
twelve months. Saying so is the point: the alternative is a number computed on four weeks
that reads like evidence.
"""

from __future__ import annotations

import bisect
import datetime as dt
from collections import defaultdict

import benchmark_series
import db

# Forward windows, in trading days. A valuation is a slower claim than an approval, so
# these run from a month to a year where ``backtest``'s run to a month.
WINDOWS = (
    {"key": "fwd_1m", "label": "1 month", "days": 21},
    {"key": "fwd_3m", "label": "3 months", "days": 63},
    {"key": "fwd_6m", "label": "6 months", "days": 126},
    {"key": "fwd_12m", "label": "12 months", "days": 252},
)

# Below this a window is reported as thin rather than as a result. Twenty names is not a
# p-value either, and the view says so, but under it the mean is one or two companies.
MIN_OBSERVATIONS = 20


def record(db_path=None, run_id: int | None = None, tickers=None) -> dict:
    """Write today's call for every company the book covers. Returns counts.

    Keyed on (company, price date), so a refresh run twice in a day replaces its own row
    rather than writing a second one for the same call.
    """
    import forecast_view

    conn = db.get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT id, ticker FROM companies ORDER BY ticker").fetchall()
        wanted = {t.upper() for t in tickers} if tickers else None
        written = refused = skipped = 0
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        for row in rows:
            if wanted and row["ticker"].upper() not in wanted:
                continue
            try:
                verdict = forecast_view.company_verdict(db_path, row["ticker"])
            except Exception:                                      # noqa: BLE001
                skipped += 1
                continue
            sotp = (verdict or {}).get("sotp") or {}
            close = sotp.get("close")
            if not close:
                skipped += 1
                continue
            equity = sotp.get("equity_per_share")
            # Every reason, where there is no figure, not the first one the list happens
            # to hold: BioMarin is refused because none of what it sells is modelled and
            # also carries no CAPM components, and recording either alone would send a
            # later reader after the wrong thing.
            missing = sotp.get("missing") or []
            why = None if equity is not None else ("; ".join(missing) or "no equity value")
            conn.execute(
                """INSERT INTO valuation_snapshots
                       (company_id, as_of, captured_at, close, equity_per_share, upside,
                        coverage_share, marketed_per_share, pipeline_per_share,
                        future_per_share, refused, refresh_run_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (company_id, as_of) DO UPDATE SET
                       captured_at = excluded.captured_at,
                       close = excluded.close,
                       equity_per_share = excluded.equity_per_share,
                       upside = excluded.upside,
                       coverage_share = excluded.coverage_share,
                       marketed_per_share = excluded.marketed_per_share,
                       pipeline_per_share = excluded.pipeline_per_share,
                       future_per_share = excluded.future_per_share,
                       refused = excluded.refused,
                       refresh_run_id = excluded.refresh_run_id""",
                (row["id"], sotp.get("price_date") or stamp[:10], stamp, close, equity,
                 sotp.get("upside_today"),
                 ((verdict or {}).get("coverage") or {}).get("share"),
                 (sotp.get("marketed") or {}).get("per_share"),
                 (sotp.get("pipeline") or {}).get("per_share"),
                 (sotp.get("future") or {}).get("per_share"),
                 why, run_id))
            written += 1
            refused += 1 if equity is None else 0
        conn.commit()
    finally:
        conn.close()
    return {"written": written, "refused": refused, "skipped": skipped}


def _series(conn) -> dict:
    """Sorted daily closes per company: {company_id: [(date, close), ...]}."""
    series: dict[int, list] = defaultdict(list)
    for row in conn.execute(
        "SELECT company_id, as_of, close FROM prices"
        " WHERE interval = '1d' AND close IS NOT NULL ORDER BY company_id, as_of"):
        series[row["company_id"]].append((row["as_of"], row["close"]))
    return series


def forward_return(series: dict, company_id: int, date: str, days: int):
    """Return from the last bar on or before ``date`` to ``days`` trading bars later."""
    bars = series.get(company_id)
    if not bars:
        return None
    idx = bisect.bisect_right([x[0] for x in bars], date) - 1
    end = idx + days
    if not (0 <= idx < len(bars)) or not (0 <= end < len(bars)):
        return None
    base = bars[idx][1]
    return bars[end][1] / base - 1 if base else None


def universe_forward(series: dict, date: str, days: int, exclude: int | None = None):
    """The equal-weight forward return of the rest of the universe over the same window."""
    rets = [forward_return(series, cid, date, days) for cid in series if cid != exclude]
    rets = [r for r in rets if r is not None]
    return sum(rets) / len(rets) if rets else None


def _bucket(upside: float) -> str:
    """The call, in the words the page uses. Cut on the sign and on a wide margin, not on
    deciles: deciles of forty companies are four companies, and the question the book is
    asking is whether a big upside means something, not whether the ninth decile does."""
    if upside >= 0.30:
        return "cheap by 30% or more"
    if upside > 0.0:
        return "cheap"
    if upside > -0.30:
        return "dear"
    return "dear by 30% or more"


ORDER = ("cheap by 30% or more", "cheap", "dear", "dear by 30% or more")


def build(db_path=None) -> dict:
    """Did the book's upside rank what the price did next? {windows, rows, coverage}."""
    conn = db.get_connection(db_path)
    try:
        series = _series(conn)
        bars = benchmark_series.series(conn, benchmark_series.BENCHMARK)
        calls = [dict(r) for r in conn.execute(
            "SELECT company_id, as_of, upside FROM valuation_snapshots"
            " WHERE upside IS NOT NULL ORDER BY as_of")]
        refusals = conn.execute(
            "SELECT COUNT(*) FROM valuation_snapshots WHERE upside IS NULL").fetchone()[0]
        days = conn.execute(
            "SELECT COUNT(DISTINCT as_of) FROM valuation_snapshots").fetchone()[0]
    finally:
        conn.close()

    by_bucket: dict = defaultdict(lambda: defaultdict(list))
    for call in calls:
        bucket = _bucket(call["upside"])
        for window in WINDOWS:
            own = forward_return(series, call["company_id"], call["as_of"], window["days"])
            # XBI, and the book's own universe only where XBI's series does not reach
            # (benchmark_series says why the universe is a benchmark almost anything beats).
            market = benchmark_series.span(bars, call["as_of"], 0, window["days"])
            if market is None:
                market = universe_forward(series, call["as_of"], window["days"],
                                          call["company_id"])
            if own is None or market is None:
                continue
            by_bucket[bucket][window["key"]].append(own - market)

    rows = []
    for bucket in ORDER:
        windows = {}
        for window in WINDOWS:
            values = by_bucket[bucket].get(window["key"], [])
            if not values:
                continue
            windows[window["key"]] = {
                "n": len(values),
                "mean_abnormal": sum(values) / len(values),
                "hit_rate": sum(1 for v in values if v > 0) / len(values),
                "thin": len(values) < MIN_OBSERVATIONS,
            }
        if windows:
            rows.append({"bucket": bucket, "windows": windows})

    measured = max((w["n"] for r in rows for w in r["windows"].values()), default=0)
    return {
        "benchmark": benchmark_series.BENCHMARK if bars else "universe",
        "windows": [{"key": w["key"], "label": w["label"]} for w in WINDOWS],
        "rows": rows,
        "calls": len(calls),
        "refusals": refusals,
        "days": days,
        "first": calls[0]["as_of"] if calls else None,
        "last": calls[-1]["as_of"] if calls else None,
        # Said plainly, because the honest answer for the first year is that there is
        # not enough history, and a mean over four weeks reads like evidence when it is
        # a coincidence.
        "reason": None if measured >= MIN_OBSERVATIONS else (
            "no calls recorded yet; the book starts keeping them on the next refresh"
            if not calls else
            f"only {measured} call-windows have a forward return on file, under the "
            f"{MIN_OBSERVATIONS} this reports on. A twelve-month window needs twelve "
            f"months of calls, and the first was {calls[0]['as_of']}"),
    }
