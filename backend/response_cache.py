"""Serve a read from the last time it was computed, until what it was computed from changes.

The app's heaviest reads recompute the whole book. ``/companies/{t}/fair-value`` values
every modelled company to read its peers' multiples and took 47 seconds cold on the
2026-09-25 book; ``/productivity/scorecard``, ``/breakpoints``, ``/screen`` and the verdict
take two to five more. The Streamlit page renders every tab on every rerun and holds a
response for thirty seconds, so any click after half a minute paid all of it again.

A read here depends on three things only: the database, the curated files under ``data/``
and the date. So a response is kept against a stamp of exactly those, and served again for
as long as the stamp is unchanged, which makes a hit exact rather than merely recent. The
stamp is the database file and its write-ahead log's modification times, the newest
modification time under ``data/``, and today's date.

When the stamp moves because something outside the API wrote (the daily refresh runs as its
own process), the last response is served at once and recomputed in the background, so a
click never waits on a cold book. A write through the API clears everything instead: an
analyst who saves an assumption reads the new forecast on the very next call, never the
one from before the edit. A read that writes (a note generated on request) is never
cached, and nor are the health and freshness checks, which exist to be live.

Off when ``ER_TOOL_CACHE=0``, which the test suite sets, since tests rewrite modules and
databases between calls in ways no stamp can see.
"""

from __future__ import annotations

import os
import threading
import time
import datetime as dt
import urllib.request
from collections import OrderedDict

from starlette.responses import Response

import db

DATA_DIR = db.BACKEND_DIR.parent / "data"
BYPASS = "x-cache-bypass"
# Reads that must be live, or that write. Matched as prefixes or substrings of the path.
NEVER_PATHS = ("/health", "/runs/latest", "/as-of")
NEVER_SUFFIXES = ("/note", "/intraday", "/tearsheet")
MAX_ENTRIES = 3000
# A stale entry is recomputed at most this often, so a writer that commits every few
# seconds cannot keep the book recomputing in a loop.
REVALIDATE_FLOOR_S = 60.0
# The data directory holds several hundred files; its newest mtime is re-read at most this
# often rather than on every request.
DATA_STAMP_TTL_S = 2.0

_lock = threading.Lock()
_entries: "OrderedDict[str, dict]" = OrderedDict()
_inflight: set[str] = set()
_data_stamp: list = [0.0, None]


def enabled() -> bool:
    return os.getenv("ER_TOOL_CACHE", "1") != "0"


def cacheable(path: str, query: str) -> bool:
    if any(path.startswith(p) for p in NEVER_PATHS):
        return False
    if any(path.endswith(s) for s in NEVER_SUFFIXES):
        return False
    return "refresh=" not in query


def _mtime(path) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return 0


def _newest_data_file() -> int:
    now = time.monotonic()
    if _data_stamp[1] is not None and now - _data_stamp[0] < DATA_STAMP_TTL_S:
        return _data_stamp[1]
    newest = 0
    for root, _dirs, files in os.walk(DATA_DIR):
        for name in files:
            newest = max(newest, _mtime(os.path.join(root, name)))
    _data_stamp[0], _data_stamp[1] = now, newest
    return newest


def stamp() -> tuple:
    """What every cached read was computed from, as cheaply comparable values."""
    database = str(db.DB_PATH)
    return (database, _mtime(database), _mtime(database + "-wal"), _newest_data_file(),
            dt.date.today().isoformat())


def clear() -> None:
    with _lock:
        _entries.clear()


def _store(key: str, entry: dict) -> None:
    with _lock:
        _entries[key] = entry
        _entries.move_to_end(key)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)


def _serve(entry: dict, state: str) -> Response:
    return Response(content=entry["body"], status_code=200, media_type=entry["media_type"],
                    headers={"x-cache": state})


def _fetch(url: str) -> None:
    """Recompute one read by asking the API for it with the cache bypassed."""
    request = urllib.request.Request(url, headers={BYPASS: "1"})
    with urllib.request.urlopen(request, timeout=600) as resp:
        resp.read()


def _revalidate(url: str, key: str) -> None:
    with _lock:
        entry = _entries.get(key)
        if key in _inflight or (entry and time.monotonic() - entry["checked"]
                                < REVALIDATE_FLOOR_S):
            return
        _inflight.add(key)
        if entry:
            entry["checked"] = time.monotonic()

    def run():
        try:
            _fetch(url)
        except Exception:          # a failed recompute leaves the last good response
            pass
        finally:
            with _lock:
                _inflight.discard(key)

    threading.Thread(target=run, name=f"revalidate {key}", daemon=True).start()


async def handle(request, call_next):
    """The middleware body: serve, store, or clear, then hand on."""
    if not enabled():
        return await call_next(request)
    if request.method != "GET":
        response = await call_next(request)
        clear()
        return response
    path, query = request.url.path, request.url.query
    if not cacheable(path, query):
        return await call_next(request)
    key = f"{path}?{query}"
    current = stamp()
    bypass = request.headers.get(BYPASS) == "1"
    if not bypass:
        with _lock:
            entry = _entries.get(key)
        if entry is not None:
            if entry["stamp"] == current:
                return _serve(entry, "hit")
            _revalidate(str(request.url), key)
            return _serve(entry, "stale")
    response = await call_next(request)
    if response.status_code != 200 or not (response.media_type or response.headers.get(
            "content-type", "")).startswith("application/json"):
        return response
    body = b"".join([chunk async for chunk in response.body_iterator])
    # The stamp read before computing, so a write that lands mid-computation leaves this
    # entry stale rather than passing it off as current.
    _store(key, {"stamp": current, "body": body, "checked": time.monotonic(),
                 "media_type": response.headers.get("content-type", "application/json")})
    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
    headers["x-cache"] = "miss"
    return Response(content=body, status_code=200, headers=headers)


# --- warming ------------------------------------------------------------------------
# The reads a company page makes that cost more than a moment, in the form the page asks
# for them, so a warmed entry is the one the page hits.
GLOBAL_READS = ("/screen", "/productivity/scorecard", "/pipeline", "/price-grid?days=90")
COMPANY_READS = ("/companies/{t}/forecast-verdict", "/companies/{t}/fair-value",
                 "/companies/{t}/breakpoints", "/companies/{t}/forecast")
WARM_EVERY_S = 30.0
_warm_started = threading.Event()


def _tickers() -> list[str]:
    conn = db.get_connection()
    try:
        # Modelled companies first: they are the ones whose reads are slow.
        return [r[0] for r in conn.execute(
            """SELECT c.ticker FROM companies c
                ORDER BY NOT EXISTS (SELECT 1 FROM assets a JOIN assumptions s
                                       ON s.asset_id = a.id
                                      WHERE a.owner_company_id = c.id), c.ticker""")]
    finally:
        conn.close()


def warm_forever(base: str) -> None:
    """Compute the slow reads ahead of the page, and again whenever the stamp moves."""
    warmed = None
    while True:
        current = stamp()
        if current != warmed:
            try:
                urls = [base + p for p in GLOBAL_READS]
                for ticker in _tickers():
                    urls += [base + p.format(t=ticker) for p in COMPANY_READS]
                for url in urls:
                    try:
                        _fetch(url)
                    except Exception:
                        pass
                    time.sleep(0.05)      # let a reader's request in between
                warmed = current
            except Exception:
                pass
        time.sleep(WARM_EVERY_S)


def start_warming(base: str) -> None:
    """Once per process, from the first request, which is the first moment the API knows
    its own address."""
    if not enabled() or _warm_started.is_set():
        return
    _warm_started.set()
    threading.Thread(target=warm_forever, args=(base.rstrip("/"),),
                     name="response-cache warm", daemon=True).start()
