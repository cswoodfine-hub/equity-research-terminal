"""Fetcher contract shared by every data source.

Each source implements fetch/normalise/snapshot/upsert (see CLAUDE.md). BaseFetcher
adds a template run() that times the work, honours the per-source TTL, writes a
continuity snapshot when a fetch is skipped or fails, and turns source errors into a
reported RefreshResult rather than a crash.
"""

from __future__ import annotations

import datetime as dt
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import db

_SQLITE_TS = "%Y-%m-%d %H:%M:%S"  # shape of datetime('now'), always UTC


@dataclass
class RefreshResult:
    source: str
    rows_fetched: int = 0
    errors: list[str] = field(default_factory=list)
    skipped_ttl: bool = False
    elapsed_ms: int = 0
    # Things worth reporting that are not failures: a quarter the SEC has not published
    # yet, a figure declined because it did not reconcile. Kept out of ``errors`` because
    # a run is marked partial by errors alone, and a run that says partial every time
    # teaches the analyst to ignore the word.
    notes: list[str] = field(default_factory=list)


@runtime_checkable
class Fetcher(Protocol):
    source: str
    ttl_seconds: int

    def fetch(self) -> list[dict]: ...
    def normalise(self, raw) -> list[dict]: ...
    def snapshot(self, rows: list[dict]) -> None: ...
    def upsert(self, rows: list[dict]) -> RefreshResult: ...


class BaseFetcher(ABC):
    """Concrete fetchers subclass this and implement the four contract methods
    plus ``entity_key`` and ``_snapshot_cache``."""

    source: str = ""
    ttl_seconds: int = 0

    force = False          # set by a run that must fetch whatever the TTL says

    def __init__(self, db_path=None):
        self.db_path = db_path
        self.refresh_run_id: int | None = None

    # --- contract methods (implemented by subclasses) ---------------------
    @property
    @abstractmethod
    def entity_key(self) -> str:
        """Natural key for snapshots and TTL, e.g. the ticker."""

    @abstractmethod
    def fetch(self) -> list[dict]: ...

    @abstractmethod
    def normalise(self, raw) -> list[dict]: ...

    @abstractmethod
    def snapshot(self, rows: list[dict]) -> None:
        """Write a live snapshot of the tracked current-state fields."""

    @abstractmethod
    def _snapshot_cache(self) -> None:
        """Write a continuity snapshot from current DB state (no fresh fetch)."""

    @abstractmethod
    def upsert(self, rows: list[dict]) -> RefreshResult: ...

    # --- shared machinery -------------------------------------------------
    def _last_live_fetch_at(self) -> str | None:
        conn = db.get_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT MAX(captured_at) FROM snapshots
                 WHERE source = ? AND entity_key = ?
                   AND json_extract(payload, '$.fetch_kind') = 'live'
                """,
                (self.source, self.entity_key),
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row and row[0] else None

    def _last_snapshot_id(self) -> int:
        conn = db.get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT MAX(id) FROM snapshots WHERE source = ? AND entity_key = ?",
                (self.source, self.entity_key)).fetchone()
        finally:
            conn.close()
        return (row[0] or 0) if row else 0

    def _mark_snapshot_failed(self, before_id: int, exc: BaseException) -> None:
        """Say that the fetch failed, on the snapshot the failure just wrote.

        A source that raises falls back to ``_snapshot_cache``, which every fetcher
        stamps ``fetch_kind: "cache"``, exactly what a TTL skip writes. So a source that
        was down and a source that was deliberately not fetched left the same mark, and
        the only record of the difference was the run's detail JSON. Merck's press page
        failed that way on four consecutive nights while the runs that would have
        reported it were themselves crashing before they wrote their detail, and the
        readout it was carrying went unseen for a fortnight.

        The continuity snapshot still goes in, because the change history must not gap.
        It just no longer claims the fetch was skipped.
        """
        conn = db.get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT MAX(id) FROM snapshots WHERE source = ? AND entity_key = ?",
                (self.source, self.entity_key)).fetchone()
            new_id = (row[0] or 0) if row else 0
            if new_id <= before_id:
                return                  # the fallback wrote nothing to correct
            conn.execute(
                "UPDATE snapshots SET payload = json_set(payload,"
                " '$.fetch_kind', 'error', '$.error', ?) WHERE id = ?",
                (f"{type(exc).__name__}: {exc}"[:500], new_id))
            conn.commit()
        finally:
            conn.close()

    def _within_ttl(self) -> bool:
        # A run told to fetch, fetches. The TTL exists so an analyst clicking refresh
        # twice does not re-download the Orange Book; it is not a reason for the daily
        # job to skip a source, and on a rebuilt database it is actively wrong: the
        # snapshots restored from history say a fetch happened that this machine never
        # made, and the data that fetch produced is not in the export.
        if getattr(self, "force", False):
            return False
        if self.ttl_seconds <= 0:
            return False
        last = self._last_live_fetch_at()
        if not last:
            return False
        last_dt = dt.datetime.strptime(last, _SQLITE_TS).replace(tzinfo=dt.timezone.utc)
        age_s = (dt.datetime.now(dt.timezone.utc) - last_dt).total_seconds()
        return age_s < self.ttl_seconds

    def run(self) -> RefreshResult:
        start = time.perf_counter()
        errors: list[str] = []
        notes: list[str] = []
        rows_fetched = 0
        skipped = False
        try:
            if self._within_ttl():
                skipped = True
                self._snapshot_cache()  # keep the change history gap-free
            else:
                rows = self.normalise(self.fetch())
                self.snapshot(rows)
                result = self.upsert(rows)
                rows_fetched = result.rows_fetched
                errors.extend(result.errors)
                # A fetcher's notes were being dropped here, so the one place designed
                # to report what a run declined or could not find said nothing.
                notes.extend(result.notes)
        except Exception as exc:  # a source outage is reported, not fatal
            errors.append(f"{self.source}: {exc}")
            try:
                before = self._last_snapshot_id()
                self._snapshot_cache()
                self._mark_snapshot_failed(before, exc)
            except Exception:
                pass
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return RefreshResult(self.source, rows_fetched, errors, skipped, elapsed_ms,
                             notes=notes)
