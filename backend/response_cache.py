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

The responses are kept on disk as well (``backend/cache/responses-*.db``, one file per
book), so a restarted API serves the page at once rather than recomputing the book for
minutes. A response read back from disk is always served as stale and recomputed: the code
that computed it may have changed since, which no stamp can see. Off with the rest, or alone
with ``ER_TOOL_RESPONSE_CACHE_DISK=0``.

Off when ``ER_TOOL_RESPONSE_CACHE=0``, which the test suite sets, since tests rewrite
modules and databases between calls in ways no stamp can see. Not ``ER_TOOL_CACHE``:
that names the directory the SEC revenue fetcher downloads into.
"""

from __future__ import annotations

import hashlib
import os
import queue
import sqlite3
import threading
import time
import datetime as dt
import urllib.request
import zlib
from collections import OrderedDict

from starlette.responses import Response

import db

DATA_DIR = db.BACKEND_DIR.parent / "data"
BYPASS = "x-cache-bypass"
# A route sets this on a body it knows to be incomplete (built before the reads it embeds
# were warm), so the body is served once and never stored as a hit.
SKIP = "x-cache-skip"
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

# Where the responses are kept between processes. Outside data/, whose newest file is part
# of the stamp, and ignored by git.
DISK_DIR = db.BACKEND_DIR / "cache"

_lock = threading.Lock()
_entries: "OrderedDict[str, dict]" = OrderedDict()
_inflight: set[str] = set()
_data_stamp: list = [0.0, None]
_disk_queue: "queue.Queue" = queue.Queue()
_disk_state = {"loaded": False, "writer": False}


def enabled() -> bool:
    return os.getenv("ER_TOOL_RESPONSE_CACHE", "1") != "0"


def disk_enabled() -> bool:
    return enabled() and os.getenv("ER_TOOL_RESPONSE_CACHE_DISK", "1") != "0"


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
    _disk_send(("clear",))


def _store(key: str, entry: dict) -> None:
    with _lock:
        _entries[key] = entry
        _entries.move_to_end(key)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)
    _disk_send(("put", key, entry["body"], entry["media_type"]))


# --- the copy on disk -----------------------------------------------------------------
def _disk_path():
    tag = hashlib.sha1(str(db.DB_PATH).encode("utf-8")).hexdigest()[:12]
    return DISK_DIR / f"responses-{tag}.db"


def _disk_connect() -> sqlite3.Connection:
    path = _disk_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.execute("CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, body BLOB NOT"
                 " NULL, media_type TEXT, stored REAL NOT NULL)")
    return conn


def load_from_disk() -> None:
    """Once per process, before the first read is served: the responses the last process
    stored, each with no stamp, so it is served at once as stale and recomputed."""
    with _lock:
        if _disk_state["loaded"]:
            return
        _disk_state["loaded"] = True
    if not disk_enabled():
        return
    try:
        conn = _disk_connect()
        try:
            rows = conn.execute("SELECT key, body, media_type FROM responses ORDER BY stored"
                                " DESC LIMIT ?", (MAX_ENTRIES,)).fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return
    with _lock:
        for key, body, media_type in reversed(rows):
            if key in _entries:
                continue
            try:
                raw = zlib.decompress(body)
            except zlib.error:
                continue
            _entries[key] = {"stamp": None, "body": raw, "checked": 0.0,
                             "media_type": media_type or "application/json"}


def _disk_send(op: tuple) -> None:
    """Hand a write to the one writer thread, so a request never waits on the disk."""
    if not disk_enabled():
        return
    with _lock:
        if not _disk_state["writer"]:
            _disk_state["writer"] = True
            threading.Thread(target=_disk_writer, name="response-cache disk",
                             daemon=True).start()
    _disk_queue.put(op)


def _disk_writer() -> None:
    while True:
        batch = [_disk_queue.get()]
        while True:
            try:
                batch.append(_disk_queue.get_nowait())
            except queue.Empty:
                break
        try:
            conn = _disk_connect()
            try:
                with conn:
                    for op in batch:
                        if op[0] == "clear":
                            conn.execute("DELETE FROM responses")
                        else:
                            conn.execute("INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?)",
                                         (op[1], zlib.compress(op[2], 1), op[3], time.time()))
                    conn.execute("DELETE FROM responses WHERE key NOT IN (SELECT key FROM"
                                 " responses ORDER BY stored DESC LIMIT ?)", (MAX_ENTRIES,))
            finally:
                conn.close()
        except Exception:          # a failed write loses only the copy, never a response
            pass
        finally:
            for _ in batch:
                _disk_queue.task_done()


def flush() -> None:
    """Wait until every write handed to the disk has landed (tests, shutdown)."""
    if _disk_state["writer"]:
        _disk_queue.join()


def cached_json(path: str, query: str = ""):
    """The last response stored for a read, parsed, or None. Stale entries count: this is
    for a view that assembles many companies' reads at once (the indication landscape)
    and would otherwise recompute every one of them cold, which is what the page itself
    would be served anyway."""
    import json
    load_from_disk()
    with _lock:
        entry = _entries.get(f"{path}?{query}")
    if entry is None:
        return None
    try:
        return json.loads(entry["body"])
    except (TypeError, ValueError):
        return None


def _serve(entry: dict, state: str) -> Response:
    return Response(content=entry["body"], status_code=200, media_type=entry["media_type"],
                    headers={"x-cache": state})


def _fetch(url: str) -> None:
    """Recompute one read by asking the API for it with the cache bypassed."""
    request = urllib.request.Request(url, headers={BYPASS: "1"})
    with urllib.request.urlopen(request, timeout=600) as resp:
        resp.read()


# Stale reads are recomputed one at a time, oldest request first. A thread each starved the
# API after a restart: one change of company served 56 stale reads, set 56 recomputes
# running at once, and the next stale read, which needs no computing at all, took 34
# seconds to come back (2026-10-07).
_revalidate_queue: "queue.Queue" = queue.Queue()
_revalidator = {"started": False}


def _revalidate(url: str, key: str) -> None:
    with _lock:
        entry = _entries.get(key)
        if key in _inflight or (entry and time.monotonic() - entry["checked"]
                                < REVALIDATE_FLOOR_S):
            return
        _inflight.add(key)
        if entry:
            entry["checked"] = time.monotonic()
        if not _revalidator["started"]:
            _revalidator["started"] = True
            threading.Thread(target=_revalidate_worker, name="response-cache revalidate",
                             daemon=True).start()
    _revalidate_queue.put((url, key))


def _revalidate_worker() -> None:
    while True:
        url, key = _revalidate_queue.get()
        try:
            _fetch(url)
        except Exception:          # a failed recompute leaves the last good response
            pass
        finally:
            with _lock:
                _inflight.discard(key)
            _revalidate_queue.task_done()


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
    load_from_disk()
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
    # Checked before the body is read: an incomplete body is handed on untouched.
    if response.headers.get(SKIP) == "1":
        return response
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
GLOBAL_READS = ("/screen", "/productivity/scorecard", "/pipeline", "/price-grid?days=90",
                "/indications", "/areas")
# The last one embeds the company's verdict through ``cached_json`` (comps_context), so it
# stays last: each company's verdict is warm before its context is built.
COMPANY_READS = ("/companies/{t}/forecast-verdict", "/companies/{t}/fair-value",
                 "/companies/{t}/breakpoints", "/companies/{t}/forecast",
                 # Before the context, which reads the stakes from here rather than
                 # pricing every big pharma gate again.
                 "/companies/{t}/catalysts/stakes",
                 # What a change of company asks for on first paint; each was a fifth of
                 # a second to most of one cold (2026-10-07).
                 "/companies/{t}/catalysts/view", "/companies/{t}/street",
                 "/companies/{t}/prices", "/changes?ticker={t}",
                 # Key insights reads the cost to each next gate; about 2 s cold.
                 "/companies/{t}/development",
                 "/companies/{t}/comps-context")
# Global reads that embed the company reads above through ``cached_json``, so they are
# warmed after every one of them. Warmed first, they would be built from missing entries.
LATE_GLOBAL_READS = ("/comps/valuation",)


# The Universe tab's read, for every company in its cohort. It embeds each company's value
# and the comps valuation through ``cached_json``, so it is warmed after both. The cohort is
# the companies the read itself names, taken from the first company's.
UNIVERSE_READ = "/universe/command?ticker={t}&part=all"


def _universe_reads(base: str, first: str) -> list:
    import json
    request = urllib.request.Request(base + UNIVERSE_READ.format(t=first),
                                     headers={BYPASS: "1"})
    with urllib.request.urlopen(request, timeout=600) as resp:
        cohort = sorted((json.loads(resp.read()).get("companies") or {}).keys())
    return [base + UNIVERSE_READ.format(t=t) for t in cohort if t != first]


def _area_reads() -> list:
    """Every disease area's page, which reads each company's verdict and stakes through
    ``cached_json`` and so is warmed after them, like the late global reads."""
    import disease_areas
    return [f"/areas/{disease_areas.slug(a)}" for a in disease_areas.area_names()]
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
                urls += [base + p for p in LATE_GLOBAL_READS]
                urls += [base + p for p in _area_reads()]
                for url in urls:
                    try:
                        _fetch(url)
                    except Exception:
                        pass
                    time.sleep(0.05)      # let a reader's request in between
                tickers = _tickers()
                try:
                    for url in _universe_reads(base, tickers[0]) if tickers else []:
                        try:
                            _fetch(url)
                        except Exception:
                            pass
                        time.sleep(0.05)
                except Exception:
                    pass
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
