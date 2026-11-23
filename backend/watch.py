"""The watch: what was announced since the last look, read between refreshes.

The refresh runs once a day, before any market opens, because of what it does to prices
(``pulse_refresh`` says why that hour cannot move). A result is announced when the
company chooses, which is usually seven in the morning in New York, an hour after the
refresh has finished. So a readout the whole calendar was waiting on sat unread for
most of a day, and the terminal's gate stayed open through the session that priced it.

This is the look in between. It asks two things and only two: each company's press feed,
and each SEC filer's filing list. Those are where a result, an acceptance or an approval
is said first, each is one request a company, and neither touches a price. A run during
a session is safe for the reason the live price read is: nothing here goes near the
price history.

**Nothing new, nothing written.** Each answer is compared with what the book holds, by
the release's address and the filing's accession, and only a company with something new
is written to. A quiet hour, which is most of them, leaves the database file untouched.
That is the difference between this and running the fetchers on a short timer: a
fetcher's ``run`` writes a snapshot whether or not anything changed, and
``response_cache`` stamps every valuation with the database's modification time, so an
hourly snapshot would have every company revalued every hour to learn that nothing had
happened.

**Then the reading, and only then.** Where something new arrived the readers the refresh
already has are run over it, in the refresh's order: the filings and release bodies are
read for a result (``trial_readouts``, ``press_readouts``), a result tied to its study
is recorded (``landed_readouts``), the calendar is resolved (``catalyst_outcomes``), a
filing is read for a decision date (``pdufa``) and joined to its asset
(``applications``), and a submission is filed from its release (``submissions``). The
resolver runs a second time after the decision dates are read, because an acceptance
closes a filing gate and is only on file once ``pdufa`` has read it. Each reader keeps
its own ledger of what it has read, so the model is asked about the new documents and
no others.

What it leaves to the refresh: the registry, which moves by the day; the change feed's
row for a new filing, which the refresh's diff files; and everything about prices,
trials, labels and estimates. No ``refresh_runs`` row is opened, for the reason the
pulse pass gives: the top bar reads that table for "last refresh" and this is not one.

Every step is soft. A feed that does not answer costs that company this hour, a reader
that fails costs its own step, and the pass reports what it could not do.

Run by the API on a timer while it is up (``start``), and by hand:

    backend/.venv/bin/python backend/watch.py
"""

from __future__ import annotations

import datetime as dt
import os
import threading
import time

import db

DEFAULT_MINUTES = 60
# The first look comes this long after the API starts, not at once: in development the
# API restarts on every saved file, and a pass on each start would be a pass a minute.
FIRST_AFTER_S = 300
# Between companies. EDGAR asks for fewer than ten requests a second; this is five, and
# a company's own feed is asked once.
PAUSE_S = 0.2

_state = {"last": None, "running": False, "thread": None}
_lock = threading.Lock()


def minutes() -> int:
    """How often the API looks, from ``ER_TOOL_WATCH_MINUTES``. Zero is off."""
    try:
        return max(0, int(os.getenv("ER_TOOL_WATCH_MINUTES", str(DEFAULT_MINUTES))))
    except ValueError:
        return DEFAULT_MINUTES


def sources(conn) -> list:
    """(ticker, kind, fetcher factory) for every feed and filing list worth asking."""
    from fetchers.filings_edgar import FilingsEdgarFetcher
    from fetchers.press_ir import PressIrFetcher
    out = []
    for c in conn.execute(
            "SELECT ticker, cik, is_sec_filer, ir_rss_url FROM companies ORDER BY ticker"):
        if (c["ir_rss_url"] or "").strip():
            out.append((c["ticker"], "press", PressIrFetcher))
        if c["is_sec_filer"] and c["cik"]:
            out.append((c["ticker"], "filings", FilingsEdgarFetcher))
    return out


def _unseen(conn, kind: str, rows: list) -> list:
    """The rows the book does not hold yet: a filing by its accession, a release by its
    address or, failing that, by its headline.

    The headline matters because a feed lists some releases at two addresses.
    AstraZeneca's carries a release and its social card as separate items, and
    ``press_releases.record`` keeps the first and refuses the second as the same release
    under another url. Asked by address alone, the second looked new on every pass, and
    a pass that thinks it found something writes a snapshot and runs every reader. So a
    release is put to the same test the write path will put it to.
    """
    column, table, key = (("url", "news", "url") if kind == "press"
                          else ("accession", "filings", "accession"))
    keys = [r.get(key) for r in rows if r.get(key)]
    if not keys:
        return []
    held = set()
    for start in range(0, len(keys), 400):
        chunk = keys[start:start + 400]
        held.update(r[0] for r in conn.execute(
            f"SELECT {column} FROM {table} WHERE {column} IN ({','.join('?' * len(chunk))})",
            chunk))
    fresh = [r for r in rows if r.get(key) and r[key] not in held]
    if kind == "press" and fresh:
        import press_releases
        fresh = [r for r in fresh if not press_releases._held_under_another_url(conn, r)]
    return fresh


def look(db_path=None, make=None, pause: float = PAUSE_S) -> dict:
    """Ask every source and write what is new. {"asked", "new", "by_company", "errors"}.

    ``make`` builds a fetcher from (factory, ticker, db_path), so a test can hand in
    fetchers that answer from a fixture.
    """
    make = make or (lambda factory, ticker, path: factory(ticker, path))
    conn = db.get_connection(db_path)
    try:
        wanted = sources(conn)
    finally:
        conn.close()
    out = {"asked": 0, "new": {"press": 0, "filings": 0}, "by_company": {}, "errors": []}
    for ticker, kind, factory in wanted:
        fetcher = make(factory, ticker, db_path)
        try:
            rows = fetcher.normalise(fetcher.fetch())
            out["asked"] += 1
            conn = db.get_connection(db_path)
            try:
                fresh = _unseen(conn, kind, rows)
            finally:
                conn.close()
            if fresh:
                # The whole answer goes to the fetcher's own write path, which snapshots
                # and upserts as a refresh would and decides for itself what is a new
                # row: only the decision to write at all is made here.
                fetcher.snapshot(rows)
                fetcher.upsert(rows)
                out["new"][kind] += len(fresh)
                out["by_company"].setdefault(ticker, {})[kind] = len(fresh)
        except Exception as exc:                                # noqa: BLE001
            out["errors"].append(f"{ticker} {kind}: {type(exc).__name__}: {exc}"[:200])
        if pause:
            time.sleep(pause)
    return out


def read(db_path=None, today: dt.date | None = None) -> dict:
    """Run the readers and the resolver over what is on file, in the refresh's order.
    Each step is reported, and one that fails costs only itself."""
    import applications
    import catalyst_outcomes
    import landed_readouts
    import pdufa
    import press_readouts
    import submissions
    import trial_readouts

    def resolved():
        got = catalyst_outcomes.resolve(db_path, today=today)
        return {k: v for k, v in got.items() if isinstance(v, int)}

    def joined():
        conn = db.get_connection(db_path)
        try:
            got = applications.resolve(conn)
            conn.commit()
            return got
        finally:
            conn.close()

    steps = (
        ("trial_readouts", lambda: trial_readouts.extract(db_path)),
        ("press_readouts", lambda: press_readouts.extract(db_path)),
        ("landed_readouts", lambda: {k: v for k, v in landed_readouts.run(
            db_path, today=today).items() if isinstance(v, int)}),
        ("catalyst_outcomes", resolved),
        ("pdufa", lambda: pdufa.extract(db_path)),
        ("applications", joined),
        # Again, now the decision dates are read: an acceptance closes a filing gate.
        ("catalyst_outcomes_after_pdufa", resolved),
        ("submissions", lambda: submissions.derive(db_path)),
    )
    out, errors = {}, []
    for name, step in steps:
        try:
            out[name] = step()
        except Exception as exc:                                # noqa: BLE001
            errors.append(f"{name}: {type(exc).__name__}: {exc}"[:200])
    out["errors"] = errors
    return out


def _closed(db_path) -> dict:
    """Every catalyst closed met or missed, by (catalyst, outcome). Taken before the
    reading and after it, the difference is what this pass closed. The day a resolution
    was written cannot say that: it is a date, and the morning's refresh shares it."""
    conn = db.get_connection(db_path)
    try:
        return {(r["id"], r["outcome"]): dict(r) for r in conn.execute(
            """SELECT c.ticker, cat.id, cat.catalyst_type AS kind, cat.title, res.outcome,
                      res.event_date, res.source
                 FROM catalyst_resolutions res
                 JOIN catalysts cat ON cat.id = res.catalyst_id
                 JOIN companies c ON c.id = cat.company_id
                WHERE res.outcome IN ('met', 'missed')
                ORDER BY res.id""")}
    finally:
        conn.close()


def run(db_path=None, today: dt.date | None = None, make=None, pause: float = PAUSE_S,
        refresh_in_flight=None) -> dict:
    """One pass: look, and read if the look found anything.

    Stands aside while a refresh is running. The refresh asks the same sources and runs
    the same readers, and two of them over one book is the same work twice on the same
    rows.
    """
    started = dt.datetime.utcnow().replace(microsecond=0)
    out = {"started_at": started.isoformat() + "Z", "skipped": None}
    if refresh_in_flight is None:
        import refresh

        def refresh_in_flight():
            conn = db.get_connection(db_path)
            try:
                return refresh._in_flight(conn) is not None
            finally:
                conn.close()
    try:
        busy = refresh_in_flight()
    except Exception:                                           # noqa: BLE001
        busy = False
    if busy:
        out["skipped"] = "a refresh is running, and it reads these sources itself"
        return out
    out["look"] = look(db_path, make=make, pause=pause)
    found = sum(out["look"]["new"].values())
    if found:
        before = _closed(db_path)
        out["read"] = read(db_path, today=today)
        out["closed"] = [row for key, row in _closed(db_path).items() if key not in before]
    out["seconds"] = round((dt.datetime.utcnow() - started).total_seconds(), 1)
    return out


def sentence(result: dict) -> str:
    """The pass in a line, for the API's log and the status route."""
    if result.get("skipped"):
        return f"watch stood aside: {result['skipped']}"
    look_ = result.get("look") or {}
    new = look_.get("new") or {}
    found = sum(new.values())
    line = (f"watch asked {look_.get('asked', 0)} sources in {result.get('seconds')}s: "
            + (f"{new.get('press', 0)} new releases and {new.get('filings', 0)} new filings"
               if found else "nothing new"))
    closed = result.get("closed") or []
    if closed:
        line += "; closed " + ", ".join(
            f"{c['ticker']} {c['kind']} {c['outcome']}" for c in closed[:6])
    problems = len(look_.get("errors") or []) + len((result.get("read") or {}).get("errors") or [])
    return line + (f"; {problems} steps did not answer" if problems else "")


def status() -> dict:
    """What the timer is set to and what its last pass found."""
    with _lock:
        last, running = _state["last"], _state["running"]
    return {"every_minutes": minutes(), "on": minutes() > 0, "running": running,
            "last": last, "last_sentence": sentence(last) if last else None}


def run_once(db_path=None) -> dict:
    """One pass under the lock, kept as the last result. A pass already running is not
    joined by a second."""
    with _lock:
        if _state["running"]:
            return {"skipped": "a watch pass is already running"}
        _state["running"] = True
    try:
        result = run(db_path)
    except Exception as exc:                                    # noqa: BLE001
        result = {"started_at": dt.datetime.utcnow().isoformat() + "Z", "skipped": None,
                  "look": {"asked": 0, "new": {}, "errors": [f"{type(exc).__name__}: {exc}"]},
                  "seconds": 0}
    finally:
        with _lock:
            _state["running"] = False
    with _lock:
        _state["last"] = result
    return result


def start(db_path=None, first_after: float = FIRST_AFTER_S) -> bool:
    """Start the timer thread, once a process. False where the watch is off."""
    every = minutes()
    if every <= 0:
        return False
    with _lock:
        if _state["thread"] is not None and _state["thread"].is_alive():
            return True

        def loop():
            time.sleep(first_after)
            while True:
                print(sentence(run_once(db_path)), flush=True)
                time.sleep(every * 60)
        thread = threading.Thread(target=loop, name="watch", daemon=True)
        _state["thread"] = thread
        thread.start()
    return True


if __name__ == "__main__":
    import env  # noqa: F401  the SEC User-Agent and the model key, from .env
    print(sentence(run_once()))
