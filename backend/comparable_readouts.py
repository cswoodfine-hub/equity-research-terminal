"""Past readouts, one row each, with what the share price did around them.

``backtest`` answers the question in aggregate: across every signed Phase 3 on file, how
far did the stock run before the result and how far did it move after. That is the right
figure for "does the market front-run readouts" and the wrong one for a readout that is
due next month, because the answer depends on whose readout it is. A positive Phase 3 at
a company with forty products moves it a point; the same result at a company with one
asset is the company.

So this lists the readouts themselves. Each is a result the book read out of a filing, a
press release or the registry (``trial_readouts``), dated to the day the market saw it,
with the result sentence kept verbatim and its source beside it. Around that day it
measures the same windows ``backtest`` uses, against the same benchmark, and nothing is
averaged until the caller has seen the rows.

"Comparable" is two things and only two, because they are what the book can state without
guessing. The phase, since a Phase 2 and a Phase 3 are different events. And the engine
the company sits on (``engines``), which stands in for how much of the company one asset
is: big pharma, biotech, cell and gene. Therapeutic area is not a filter, because a
readout row carries a drug name and not an indication, and matching one to the other is
the judgement ``catalyst_outcomes`` already makes with more evidence than is to hand here.

What this cannot say is stated in the payload. The sample is the readouts the book has
read, which is tens of rows, and it leans positive: a company announces a success the day
it has one and lets a failure surface in a quarterly filing or the registry. The summary
is a median and a count, never a probability.
"""

from __future__ import annotations

import statistics

import backtest
import benchmark_series
import db
import engines
import market_session

# The windows a reader of a single readout wants: was it anticipated, and how did it land.
# The offsets are backtest's own, so a row here and a mean there are the same measurement.
WINDOWS = (
    {"key": "runup_3m", "label": "three months before", "kind": "runup", "days": 63},
    {"key": "runup_1m", "label": "one month before", "kind": "runup", "days": 21},
    {"key": "after_1d", "label": "the reaction", "kind": "reaction", "days": 0},
    {"key": "after_1w", "label": "the week after it", "kind": "after", "days": 5},
    {"key": "after_1m", "label": "the month after it", "kind": "after", "days": 21},
)
OUTCOMES = ("positive", "negative")
DEFAULT_LIMIT = 25
MAX_LIMIT = 100

CAVEATS = (
    "The sample is the readouts this book has read out of filings, press releases and the "
    "registry, not every readout in the sector.",
    "It leans positive: a success is announced the day it happens, a failure often "
    "surfaces later and less plainly.",
    "A window is the stock's return less XBI's over the same trading days. A window that "
    "runs off either price series is left empty, not estimated.",
    "The windows before end at the last close before the result. The reaction runs from "
    "that close for one session where the filing was accepted before the New York close, "
    "and two where it was accepted after it or only a date is on file. The windows after "
    "are counted from the end of the reaction.",
)


def _abnormal(series: dict, bars: list, company_id: int, day: str,
              accepted_at: str | None = None) -> dict:
    """{window key: abnormal return or None} for one event, placed among the closes by
    ``market_session.news_window`` as ``backtest`` places it."""
    news = market_session.news_window(day, accepted_at)
    out = {}
    for window in WINDOWS:
        if news is None:
            out[window["key"]] = None
            continue
        a, b = backtest.offsets(window, news["sessions"])
        own = backtest.span_return(series, company_id, news["anchor"], a, b)
        market = benchmark_series.span(bars, news["anchor"], a, b)
        out[window["key"]] = (None if own is None or market is None
                              else round(own - market, 4))
    return out


def _summary(rows: list) -> list:
    """One line per outcome: how many readouts, and the median of each window with the
    number of rows it is the median of. A median, because one collapse to nil would set
    a mean on its own in a sample this small."""
    out = []
    for outcome in OUTCOMES:
        mine = [r for r in rows if r["outcome"] == outcome]
        if not mine:
            continue
        windows = {}
        for window in WINDOWS:
            values = [r["abnormal"][window["key"]] for r in mine
                      if r["abnormal"][window["key"]] is not None]
            windows[window["key"]] = {
                "n": len(values),
                "median": round(statistics.median(values), 4) if values else None,
                "worst": round(min(values), 4) if values else None,
                "best": round(max(values), 4) if values else None,
            }
        out.append({"outcome": outcome, "readouts": len(mine),
                    "companies": len({r["ticker"] for r in mine}), "windows": windows})
    return out


def build(db_path=None, *, ticker: str | None = None, phase: int | None = None,
          outcome: str | None = None, engine: str | None = None,
          limit: int = DEFAULT_LIMIT) -> dict:
    """The signed readouts on file that match, newest first, each with its windows.

    ``ticker`` narrows to one company's own record. ``engine`` narrows to companies on
    one engine, and where a ticker is given with no engine, the comparison set is the
    ticker's own engine, which is returned beside its own rows rather than mixed in.
    """
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    conn = db.get_connection(db_path)
    try:
        home = engines.home(db_path)
        series = backtest._series(conn)
        bars = benchmark_series.series(conn, benchmark_series.BENCHMARK)
        clauses, params = ["r.outcome IN ('positive', 'negative')"], []
        if phase in (2, 3):
            clauses.append("r.phase = ?")
            params.append(phase)
        if outcome in OUTCOMES:
            clauses.append("r.outcome = ?")
            params.append(outcome)
        found = conn.execute(
            f"""SELECT r.company_id, c.ticker, c.name, r.drug, r.phase, r.outcome,
                       r.event_date, r.quote, r.source_url, r.nct_id, r.source,
                       f.accepted_at
                  FROM trial_readouts r JOIN companies c ON c.id = r.company_id
                  LEFT JOIN filings f ON f.accession = r.accession
                 WHERE {' AND '.join(clauses)}
                 ORDER BY r.event_date DESC, r.id DESC""", params).fetchall()
    finally:
        conn.close()

    wanted = (ticker or "").strip().upper() or None
    peer_engine = engine if engine in engines.ENGINES else (home.get(wanted) if wanted else None)
    rows = []
    for r in found:
        row = {
            "ticker": r["ticker"], "company": r["name"], "engine": home.get(r["ticker"]),
            "drug": r["drug"], "phase": r["phase"], "outcome": r["outcome"],
            "event_date": r["event_date"], "quote": r["quote"],
            "source_url": r["source_url"], "nct_id": r["nct_id"],
            "read_from": r["source"] or "filing",
            "abnormal": _abnormal(series, bars, r["company_id"], r["event_date"] or "",
                                  r["accepted_at"]),
        }
        rows.append(row)

    own = [r for r in rows if wanted and r["ticker"] == wanted]
    peers = [r for r in rows
             if (not wanted or r["ticker"] != wanted)
             and (peer_engine is None or r["engine"] == peer_engine)]
    return {
        "benchmark": benchmark_series.BENCHMARK if bars else None,
        "windows": [{"key": w["key"], "label": w["label"]} for w in WINDOWS],
        "filters": {"ticker": wanted, "phase": phase if phase in (2, 3) else None,
                    "outcome": outcome if outcome in OUTCOMES else None,
                    "engine": peer_engine},
        "own": own[:limit],
        "comparables": peers[:limit],
        "comparables_on_file": len(peers),
        "summary": _summary(peers),
        "caveats": list(CAVEATS),
    }
