"""A source that fails should not look like a source that was skipped.

When a fetcher raises, the base class falls back to a continuity snapshot so the change
history has no gap. Every fetcher stamps that snapshot ``fetch_kind: "cache"``, which is
exactly what a TTL skip writes, so the two were indistinguishable and the only record of
the difference was the run's detail JSON. Merck's press page failed that way on four
consecutive nights while the runs that would have reported it were themselves crashing
before they wrote their detail. The readout it was carrying, a Phase 3 meeting both its
endpoints, went unseen for a fortnight.
"""

import json
import socket
import urllib.error

import db
from fetchers import base
from fetchers.base import BaseFetcher, RefreshResult


class _Probe(BaseFetcher):
    """A fetcher that fetches nothing, and can be told to fail."""

    source = "probe"
    ttl_seconds = 3600

    def __init__(self, db_path, explode=False):
        super().__init__(db_path)
        self.explode = explode

    @property
    def entity_key(self) -> str:
        return "LLY"

    def fetch(self):
        if self.explode:
            raise RuntimeError("HTTP Error 403: Forbidden")
        return [{"ok": True}]

    def normalise(self, raw):
        return list(raw)

    def snapshot(self, rows) -> None:
        self._write({"rows": len(rows), "fetch_kind": "live"})

    def _snapshot_cache(self) -> None:
        self._write({"rows": 0, "fetch_kind": "cache"})

    def _write(self, payload) -> None:
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload)"
                " VALUES (?, 'company', ?, ?)",
                (self.source, self.entity_key, json.dumps(payload)))
            conn.commit()
        finally:
            conn.close()

    def upsert(self, rows) -> RefreshResult:
        return RefreshResult(self.source, len(rows))


def _snapshots(path):
    conn = db.get_connection(path)
    try:
        return [json.loads(r["payload"]) for r in conn.execute(
            "SELECT payload FROM snapshots WHERE source = 'probe' ORDER BY id")]
    finally:
        conn.close()


def test_a_fetch_that_raises_is_marked_an_error_not_a_cache_hit(tmp_path):
    path = str(tmp_path / "p.db")
    db.init(path)
    result = _Probe(path, explode=True).run()

    assert result.errors and "403" in result.errors[0]
    assert not result.skipped_ttl          # it was not skipped, it failed
    payload = _snapshots(path)[-1]
    assert payload["fetch_kind"] == "error"
    assert "403" in payload["error"]


def test_a_skipped_fetch_still_says_cache(tmp_path):
    path = str(tmp_path / "p.db")
    db.init(path)
    _Probe(path).run()                     # a live fetch, so the TTL has something to
    second = _Probe(path).run()            # measure against
    assert second.skipped_ttl
    kinds = [p["fetch_kind"] for p in _snapshots(path)]
    assert kinds == ["live", "cache"]
    assert "error" not in _snapshots(path)[-1]


def test_a_failed_fetch_does_not_satisfy_the_ttl(tmp_path):
    # An error snapshot must not stand in for a live one, or a source that is down
    # would be skipped for the length of its TTL on top of being down.
    path = str(tmp_path / "p.db")
    db.init(path)
    _Probe(path, explode=True).run()
    assert _Probe(path)._within_ttl() is False


def test_the_continuity_snapshot_is_still_written(tmp_path):
    # The change history must not gap just because a source was unreachable.
    path = str(tmp_path / "p.db")
    db.init(path)
    _Probe(path, explode=True).run()
    assert len(_snapshots(path)) == 1


# --- the resolver, not the source ------------------------------------------
# The 2026-08-21 runs recorded 439 DNS failures against 408 successful fetches, spread
# evenly across every source, about forty each. With every provider failing equally the
# common factor is this machine's resolver under the load of seventy companies, not any
# of them, and a second attempt a moment later succeeds.

class _Flaky(_Probe):
    """Fails the first ``fails`` attempts with a resolver error, then answers."""

    def __init__(self, db_path, fails, error=None):
        super().__init__(db_path)
        self.fails = fails
        self.attempts = 0
        self.error = error or socket.gaierror(
            socket.EAI_NONAME, "nodename nor servname provided, or not known")

    def fetch(self):
        self.attempts += 1
        if self.attempts <= self.fails:
            raise self.error
        return [{"ok": True}]


def test_a_resolver_failure_is_tried_again(tmp_path, monkeypatch):
    monkeypatch.setattr(base.time, "sleep", lambda _s: None)
    path = str(tmp_path / "p.db")
    db.init(path)
    fetcher = _Flaky(path, fails=1)
    result = fetcher.run()

    assert fetcher.attempts == 2
    assert result.errors == []
    assert _snapshots(path)[-1]["fetch_kind"] == "live"


def test_it_gives_up_after_the_third_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(base.time, "sleep", lambda _s: None)
    path = str(tmp_path / "p.db")
    db.init(path)
    fetcher = _Flaky(path, fails=99)
    result = fetcher.run()

    assert fetcher.attempts == base.FETCH_ATTEMPTS
    assert result.errors and "nodename" in result.errors[0]
    assert _snapshots(path)[-1]["fetch_kind"] == "error"


def test_a_resolver_error_wrapped_in_a_urlerror_counts(tmp_path, monkeypatch):
    # urllib raises URLError(gaierror(...)), which is the shape the run actually saw.
    monkeypatch.setattr(base.time, "sleep", lambda _s: None)
    path = str(tmp_path / "p.db")
    db.init(path)
    fetcher = _Flaky(path, fails=1, error=urllib.error.URLError(
        socket.gaierror(socket.EAI_NONAME, "nodename nor servname provided")))
    fetcher.run()
    assert fetcher.attempts == 2


def test_a_source_that_answered_no_is_not_asked_again(tmp_path, monkeypatch):
    """A 403 means the same thing on the second attempt as on the first, and retrying
    it would triple the load on a source that already answered clearly."""
    monkeypatch.setattr(base.time, "sleep", lambda _s: None)
    path = str(tmp_path / "p.db")
    db.init(path)
    fetcher = _Flaky(path, fails=99, error=urllib.error.HTTPError(
        "https://example.com", 403, "Forbidden", {}, None))
    result = fetcher.run()

    assert fetcher.attempts == 1
    assert result.errors and "403" in result.errors[0]


def test_a_malformed_payload_is_not_a_network_problem(tmp_path, monkeypatch):
    monkeypatch.setattr(base.time, "sleep", lambda _s: None)
    path = str(tmp_path / "p.db")
    db.init(path)
    fetcher = _Flaky(path, fails=99, error=ValueError("bad json"))
    fetcher.run()
    assert fetcher.attempts == 1


def test_a_fetch_that_works_first_time_is_asked_once(tmp_path):
    path = str(tmp_path / "p.db")
    db.init(path)
    fetcher = _Flaky(path, fails=0)
    fetcher.run()
    assert fetcher.attempts == 1
