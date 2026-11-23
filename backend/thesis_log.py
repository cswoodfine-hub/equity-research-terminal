"""The thesis log: a read of the book, written down on the day so it can be marked later.

The book scores its own calls. ``call_log`` records what every company was worth and what
every gate's odds were on each day, and marks them against XBI once the horizon has
traded. Those are the model's calls. This is the same discipline for a different kind of
claim: a read somebody made of the book, in words. "Dyne's price pays for a result the
Phase 3 has not given yet, and it gives some of that back before the readout." A person
can make that read, and so can a language model working through the terminal's tools.

A read like that is worth nothing until it is on the record, for the reason
``call_log`` states about its own rows: a claim recalled after the fact carries everything
learnt since. So a thesis is written once and never changed. It has to carry five things
or it is refused:

- which company, and whether it will do better or worse than the benchmark;
- over how many days, so there is a date on which it is marked;
- the claim, in a sentence;
- what in the book it rests on;
- what would show it was wrong, written before the outcome.

The price it starts from is the last close on file that day, taken from the book and not
from the writer, with XBI's beside it. A thesis logged for a company with no price on
file is refused, because it could never be marked. What the book itself said that day,
its fair value and its rating, is kept on the row as context, so a thesis that merely
repeats the model can be told from one that disagrees with it.

It lives in a file, ledger/theses.ndjson, one line a thesis, and not in the database. The
database is rebuilt from sources and from data/history; a thesis has no source to rebuild
from. A file in the repository is diffable, travels with a commit, and appending a line
is the whole of the write path: there is no code here that edits or removes one. A
second thought is a new thesis that names the one it replaces (``supersedes``), and both
stay on the ledger and both are marked.

The file sits beside data/ and not inside it, on purpose. ``response_cache`` stamps every
cached read with the newest modification time under data/, because a curated file there
changes what the book computes. A thesis changes nothing the book computes, and a line
appended under data/ would have every company's valuation recomputed for it.

Marking is ``call_log``'s rule. The stock's return from the starting close to the last
close on or before the due date, less XBI's over the same dates; a thesis is right where
the sign of that excess is the side it took. An open thesis shows its excess so far and
is not counted. A count of theses is not a count of independent bets, and the summary
says how many companies and how many starting days it rests on.

This is a research record. It is not advice and nothing in the terminal acts on it.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import benchmark_series
import call_log
import db

LEDGER = Path(__file__).resolve().parent.parent / "ledger" / "theses.ndjson"
SIDES = ("outperform", "underperform")
MIN_DAYS, MAX_DAYS = 5, 730
# A sentence, not an essay and not a word: short enough to read in a table, long enough
# to be a claim rather than a label.
MIN_TEXT, MAX_TEXT = 20, 1200
# The marking close may sit a few days before the due date (a weekend, a holiday), as in
# call_log. Further back than that the price is stale and the thesis stays unmarked.
END_SLACK_DAYS = call_log.END_SLACK_DAYS


class Refused(ValueError):
    """A thesis that cannot be logged, with the reason in words a writer can act on."""


def ledger_path(path=None) -> Path:
    return Path(path or os.getenv("ER_TOOL_THESES") or LEDGER)


def entries(path=None) -> list:
    """Every thesis on the ledger, oldest first. A line that does not parse is skipped
    rather than raised on: one damaged line must not hide the rest of the record."""
    source = ledger_path(path)
    if not source.exists():
        return []
    out = []
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _text(value, name: str) -> str:
    text = " ".join(str(value or "").split())
    if len(text) < MIN_TEXT:
        raise Refused(f"{name} is too short to be marked against: say it in a sentence "
                      f"of at least {MIN_TEXT} characters")
    if len(text) > MAX_TEXT:
        raise Refused(f"{name} is over {MAX_TEXT} characters: keep it to what will be "
                      "tested")
    return text


def record(db_path=None, *, ticker: str, side: str, horizon_days: int, claim: str,
           rests_on: str, wrong_if: str, asset_id: int | None = None,
           catalyst_id: int | None = None, supersedes: int | None = None,
           author: str | None = None, today: dt.date | None = None, path=None) -> dict:
    """Append one thesis and return the row as written. Raises ``Refused`` with the
    reason where it cannot be marked later."""
    ticker = (ticker or "").strip().upper()
    side = (side or "").strip().lower()
    if side not in SIDES:
        raise Refused(f"side must be one of {', '.join(SIDES)}, measured against "
                      f"{benchmark_series.BENCHMARK}")
    try:
        horizon = int(horizon_days)
    except (TypeError, ValueError):
        raise Refused("horizon_days must be a whole number of days")
    if not MIN_DAYS <= horizon <= MAX_DAYS:
        raise Refused(f"horizon_days must be between {MIN_DAYS} and {MAX_DAYS}")
    claim = _text(claim, "claim")
    rests_on = _text(rests_on, "rests_on")
    wrong_if = _text(wrong_if, "wrong_if")
    today = today or dt.date.today()

    conn = db.get_connection(db_path)
    try:
        if conn.execute("SELECT 1 FROM companies WHERE ticker = ?", (ticker,)).fetchone() is None:
            raise Refused(f"{ticker or 'that ticker'} is not in the universe")
        close = call_log._close_on(conn, ticker, today.isoformat())
        bench = call_log._bench_on(conn, today.isoformat())
        book = conn.execute(
            """SELECT as_of, fair_value, rating, upside_12m FROM model_calls
                WHERE ticker = ? AND as_of <= ? ORDER BY as_of DESC LIMIT 1""",
            (ticker, today.isoformat())).fetchone()
    finally:
        conn.close()
    if close is None or not close[1]:
        raise Refused(f"no closing price on file for {ticker}, so the thesis could never "
                      "be marked")
    if bench is None or not bench[1]:
        raise Refused(f"no {benchmark_series.BENCHMARK} close on file to mark against")
    if (today - dt.date.fromisoformat(close[0])).days > END_SLACK_DAYS:
        raise Refused(f"the last close on file for {ticker} is {close[0]}, too old to "
                      "start a thesis from: refresh prices first")

    held = entries(path)
    if supersedes is not None and not any(e.get("id") == supersedes for e in held):
        raise Refused(f"there is no thesis {supersedes} to supersede")
    row = {
        "id": max([e.get("id") or 0 for e in held] or [0]) + 1,
        "logged_at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "as_of": today.isoformat(),
        "ticker": ticker, "side": side, "horizon_days": horizon,
        "due": (dt.date.fromisoformat(close[0]) + dt.timedelta(days=horizon)).isoformat(),
        "claim": claim, "rests_on": rests_on, "wrong_if": wrong_if,
        "asset_id": asset_id, "catalyst_id": catalyst_id, "supersedes": supersedes,
        "price": close[1], "price_date": close[0],
        "benchmark": benchmark_series.BENCHMARK,
        "benchmark_close": bench[1], "benchmark_date": bench[0],
        "book": ({"as_of": book["as_of"], "fair_value": book["fair_value"],
                  "rating": book["rating"], "upside_12m": book["upside_12m"]}
                 if book else None),
        "author": " ".join(str(author or "").split())[:80] or None,
        "code_version": call_log.code_version(),
    }
    target = ledger_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    return row


def _mark(conn, bars: list, row: dict, today: dt.date) -> dict:
    """The row with its marking: the excess return to the due date where it has passed
    and can be priced, the excess so far where it has not."""
    out = dict(row)
    out.update({"status": "open", "excess": None, "right": None, "marked_on": None})
    try:
        start = dt.date.fromisoformat(row["price_date"])
        due = dt.date.fromisoformat(row["due"])
        base, bench0 = float(row["price"]), float(row["benchmark_close"])
    except (KeyError, TypeError, ValueError):
        out["status"] = "unreadable"
        return out
    passed = due <= today
    end = due if passed else today
    stock = call_log._close_on(conn, row["ticker"], end.isoformat())
    bench1 = benchmark_series.on_or_before(bars, end.isoformat())
    if not (stock and bench1 and base and bench0) or stock[0] <= start.isoformat():
        out["status"] = "unpriced" if passed else "open"
        return out
    if passed and ((end - dt.date.fromisoformat(stock[0])).days > END_SLACK_DAYS
                   or (end - dt.date.fromisoformat(bench1[0])).days > END_SLACK_DAYS):
        out["status"] = "unpriced"
        return out
    excess = (stock[1] / base - 1) - (bench1[1] / bench0 - 1)
    out["excess"] = round(excess, 4)
    out["marked_on"] = stock[0]
    if passed:
        out["status"] = "marked"
        out["right"] = (excess > 0) if row["side"] == "outperform" else (excess < 0)
    return out


def score(db_path=None, today: dt.date | None = None, path=None,
          ticker: str | None = None) -> dict:
    """Every thesis with its marking, newest first, and the record of the marked ones."""
    today = today or dt.date.today()
    wanted = (ticker or "").strip().upper() or None
    held = [e for e in entries(path) if not wanted or e.get("ticker") == wanted]
    conn = db.get_connection(db_path)
    try:
        bars = benchmark_series.series(conn, benchmark_series.BENCHMARK)
        rows = [_mark(conn, bars, e, today) for e in held]
    finally:
        conn.close()
    marked = [r for r in rows if r["status"] == "marked"]
    replaced = {r.get("supersedes") for r in rows if r.get("supersedes") is not None}
    for row in rows:
        row["superseded"] = row.get("id") in replaced

    def signed(r):
        return r["excess"] if r["side"] == "outperform" else -r["excess"]

    summary = {
        "theses": len(rows), "open": sum(1 for r in rows if r["status"] == "open"),
        "marked": len(marked),
        "right": sum(1 for r in marked if r["right"]),
        "hit_rate": (round(sum(1 for r in marked if r["right"]) / len(marked), 3)
                     if marked else None),
        "mean_excess_on_side": (round(sum(signed(r) for r in marked) / len(marked), 4)
                                if marked else None),
        "companies": len({r["ticker"] for r in marked}),
        "starting_days": len({r["as_of"] for r in marked}),
    }
    return {
        "benchmark": benchmark_series.BENCHMARK, "today": today.isoformat(),
        "summary": summary, "theses": sorted(rows, key=lambda r: -(r.get("id") or 0)),
        "note": ("Marked against XBI on the due date and never re-marked. Theses on the "
                 "same company or logged on the same day are not independent, so read "
                 "the hit rate against the number of companies and starting days. A "
                 "research record, not advice."),
    }
