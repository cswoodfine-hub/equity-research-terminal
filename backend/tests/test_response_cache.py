"""A read served from its last computation until the book it was computed from changes."""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import db
import response_cache as RC


@pytest.fixture
def client(tmp_path, monkeypatch):
    database = tmp_path / "book.db"
    database.write_bytes(b"")
    data = tmp_path / "data"
    data.mkdir()
    (data / "seed.csv").write_text("a,b\n")
    monkeypatch.setenv("ER_TOOL_RESPONSE_CACHE", "1")
    monkeypatch.setenv("ER_TOOL_RESPONSE_CACHE_DISK", "1")
    monkeypatch.setattr(db, "DB_PATH", database)
    monkeypatch.setattr(RC, "DATA_DIR", data)
    monkeypatch.setattr(RC, "DATA_STAMP_TTL_S", 0.0)
    monkeypatch.setattr(RC, "DISK_DIR", tmp_path / "cache")
    monkeypatch.setitem(RC._disk_state, "loaded", True)
    revalidated = []
    monkeypatch.setattr(RC, "_revalidate", lambda url, key: revalidated.append(key))
    RC.clear()

    calls = {"n": 0}
    app = FastAPI()

    @app.middleware("http")
    async def cache(request, call_next):
        return await RC.handle(request, call_next)

    @app.get("/value")
    def value():
        calls["n"] += 1
        return {"n": calls["n"]}

    @app.get("/companies/LLY/note")
    def note():
        calls["n"] += 1
        return {"n": calls["n"]}

    @app.post("/edit")
    def edit():
        return {"ok": True}

    yield TestClient(app), calls, revalidated, database, data
    RC.clear()
    RC.flush()


def _bump(path):
    stat = os.stat(path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


def test_a_read_is_computed_once_while_the_book_is_unchanged(client):
    c, calls, _revalidated, _db, _data = client
    first, second = c.get("/value"), c.get("/value")
    assert first.json() == second.json() == {"n": 1}
    assert calls["n"] == 1
    assert (first.headers["x-cache"], second.headers["x-cache"]) == ("miss", "hit")


def test_a_write_to_the_database_serves_the_last_answer_and_recomputes_it(client):
    """The daily refresh writes from its own process. The page must not wait on it."""
    c, calls, revalidated, database, _data = client
    c.get("/value")
    _bump(database)
    stale = c.get("/value")
    assert stale.json() == {"n": 1} and stale.headers["x-cache"] == "stale"
    assert revalidated == ["/value?"]


def test_a_changed_curated_file_counts_as_a_change_too(client):
    c, _calls, revalidated, _db, data = client
    c.get("/value")
    _bump(data / "seed.csv")
    assert c.get("/value").headers["x-cache"] == "stale"
    assert revalidated == ["/value?"]


def test_a_write_through_the_api_clears_everything(client):
    """An analyst who saves an assumption reads the new forecast on the next call, never
    the one from before the edit."""
    c, calls, _revalidated, _db, _data = client
    c.get("/value")
    c.post("/edit")
    after = c.get("/value")
    assert after.json() == {"n": 2} and after.headers["x-cache"] == "miss"


def test_the_bypass_header_recomputes_and_stores(client):
    c, calls, _revalidated, _db, _data = client
    c.get("/value")
    fresh = c.get("/value", headers={RC.BYPASS: "1"})
    assert fresh.json() == {"n": 2}
    assert c.get("/value").json() == {"n": 2}


def test_a_read_that_writes_or_regenerates_is_never_cached(client):
    c, calls, _revalidated, _db, _data = client
    c.get("/companies/LLY/note")
    c.get("/companies/LLY/note")
    c.get("/value?refresh=true")
    c.get("/value?refresh=true")
    assert calls["n"] == 4


def test_the_query_is_part_of_the_key(client):
    c, calls, _revalidated, _db, _data = client
    c.get("/value?days=30")
    c.get("/value?days=90")
    assert calls["n"] == 2


def test_off_when_the_environment_says_so(client, monkeypatch):
    c, calls, _revalidated, _db, _data = client
    monkeypatch.setenv("ER_TOOL_RESPONSE_CACHE", "0")
    c.get("/value")
    c.get("/value")
    assert calls["n"] == 2


def _restart():
    """What a new API process sees: nothing in memory, the copy on disk not yet read."""
    RC.flush()
    with RC._lock:
        RC._entries.clear()
        RC._disk_state["loaded"] = False


def test_a_restarted_process_serves_the_last_answer_and_recomputes_it(client):
    test, calls, revalidated, _database, _data = client
    assert test.get("/value").json() == {"n": 1}
    _restart()
    first = test.get("/value")
    # Served from disk at once, but as stale: the code may have changed since it was stored.
    assert first.json() == {"n": 1} and first.headers["x-cache"] == "stale"
    assert calls["n"] == 1 and revalidated == ["/value?"]


def test_a_write_through_the_api_clears_the_copy_on_disk_too(client):
    test, calls, _revalidated, _database, _data = client
    test.get("/value")
    test.post("/edit")
    _restart()
    assert test.get("/value").headers["x-cache"] == "miss" and calls["n"] == 2


def test_the_copy_on_disk_is_off_when_the_environment_says_so(client, monkeypatch):
    test, calls, _revalidated, _database, _data = client
    monkeypatch.setenv("ER_TOOL_RESPONSE_CACHE_DISK", "0")
    test.get("/value")
    _restart()
    assert test.get("/value").headers["x-cache"] == "miss" and calls["n"] == 2



def test_stale_reads_are_recomputed_one_at_a_time(monkeypatch):
    import threading
    import time as _time
    running, peak, done = [0], [0], []
    gate = threading.Lock()

    def fetch(url):
        with gate:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        _time.sleep(0.02)
        with gate:
            running[0] -= 1
        done.append(url)

    monkeypatch.setattr(RC, "_fetch", fetch)
    for i in range(5):
        RC._revalidate(f"http://api/r{i}", f"/r{i}?")
    RC._revalidate_queue.join()
    assert sorted(done) == [f"http://api/r{i}" for i in range(5)] and peak[0] == 1
