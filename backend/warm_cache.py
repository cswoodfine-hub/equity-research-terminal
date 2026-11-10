"""Compute the app's slow reads once and save them, for a container that starts cold.

The response cache keeps what it computed on disk (``response_cache.py``), so a restarted
API serves the page at once and recomputes behind it. A Streamlit Cloud container never
has that file: every deploy, reboot and wake starts from nothing, and the first company's
fair value, which values the whole book to read its peers' multiples, took 121 seconds
cold on the 2026-11-09 book on a full machine and several minutes on the free tier.

So the daily refresh runs one warming pass after it publishes the database and saves the
responses beside it as a release asset (``refresh.yml``). The cloud app downloads the file
with the database (``streamlit_cloud_app.py``) and serves from it at once. The file records
the database's hash, the commit and the day it was computed from: where the app's own are
the same, its responses are current, company reads included. Anything else is served as
stale and recomputed, so a file from an older database or older code can only be slow to
correct, never wrong for long.

    ER_TOOL_DB=<database> python backend/warm_cache.py <out.db>
"""

from __future__ import annotations

import datetime as dt
import pathlib
import socket
import sqlite3
import sys
import threading
import time
import urllib.request

import db
import response_cache

STARTUP_TIMEOUT_S = 120


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def warm(out_path) -> dict:
    """Run one warming pass against an API in this process and copy its responses to
    ``out_path``. Returns {"reads", "failed", "responses", "seconds"}."""
    import uvicorn

    import main

    # The middleware starts the endless warming loop on the first request; this pass is
    # run by hand instead, so the loop must not run beside it doing the same work twice.
    response_cache._warm_started.set()
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + STARTUP_TIMEOUT_S
    while True:
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=2):
                break
        except Exception:
            if time.time() > deadline:
                raise RuntimeError(f"the API did not answer within {STARTUP_TIMEOUT_S}s")
            time.sleep(0.5)

    # What the responses are computed from, read before the pass so it describes the
    # database as published, whatever a read might write to it.
    saved_for = (response_cache.book_sha(str(db.DB_PATH)), response_cache.code_commit(),
                 dt.date.today().isoformat())
    started = time.time()
    done = response_cache.warm_once(base)
    response_cache.flush()
    server.should_exit = True

    out = pathlib.Path(out_path)
    out.unlink(missing_ok=True)
    source = sqlite3.connect(str(response_cache._disk_path()))
    try:
        # A copy taken through SQLite, so it is whole even if a write were still landing.
        source.execute("VACUUM INTO ?", (str(out),))
        responses = source.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
    finally:
        source.close()
    copy = sqlite3.connect(str(out))
    try:
        with copy:
            copy.execute(f"DROP TABLE IF EXISTS {response_cache.SAVED_FOR}")
            copy.execute(f"CREATE TABLE {response_cache.SAVED_FOR} (book_sha TEXT,"
                         " code_commit TEXT, day TEXT)")
            copy.execute(f"INSERT INTO {response_cache.SAVED_FOR} VALUES (?, ?, ?)",
                         saved_for)
    finally:
        copy.close()
    return {**done, "responses": responses, "seconds": round(time.time() - started),
            "saved_for": {"commit": saved_for[1], "day": saved_for[2]}}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: warm_cache.py <out.db>")
    if not response_cache.enabled() or not response_cache.disk_enabled():
        sys.exit("the response cache is switched off, so there is nothing to save")
    print(warm(sys.argv[1]), flush=True)
    print(f"database {db.DB_PATH}", flush=True)
