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
    monkeypatch.setenv("ER_TOOL_CACHE", "1")
    monkeypatch.setattr(db, "DB_PATH", database)
    monkeypatch.setattr(RC, "DATA_DIR", data)
    monkeypatch.setattr(RC, "DATA_STAMP_TTL_S", 0.0)
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
    monkeypatch.setenv("ER_TOOL_CACHE", "0")
    c.get("/value")
    c.get("/value")
    assert calls["n"] == 2
