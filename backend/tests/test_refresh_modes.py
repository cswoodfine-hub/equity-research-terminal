"""The daily run on a restored database: which sources fetch, which skip, and when the
restored file is trusted. No network."""

import datetime as dt
import json
import sqlite3

import pytest

import history
import scheduled_refresh
from fetchers import base


class _Fetcher(base.BaseFetcher):
    """A fetcher whose last live fetch is set by the test, in hours ago."""

    def __init__(self, ttl_hours, last_hours_ago, force):
        super().__init__(None)
        self.ttl_seconds = int(ttl_hours * 3600)
        self.force = force
        self._ago = last_hours_ago

    entity_key = "t"

    def _last_live_fetch_at(self):
        if self._ago is None:
            return None
        when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=self._ago)
        return when.strftime("%Y-%m-%d %H:%M:%S")

    def fetch(self):
        return []

    def normalise(self, raw):
        return raw

    def snapshot(self, rows):
        pass

    def _snapshot_cache(self):
        pass

    def upsert(self, rows):
        return base.RefreshResult("t", 0)


@pytest.mark.parametrize("ttl,ago,force,skips", [
    # Forced: nothing skips, as every scheduled run did before.
    (24 * 7, 1, True, False),
    # Daily mode: a daily source fetches even 20 hours after the last run, the case a
    # job that started earlier than yesterday's would otherwise have skipped.
    (24, 20, base.DAILY, False),
    (12, 1, base.DAILY, False),
    # Daily mode: a weekly source skips inside its TTL, and comes due six hours early.
    (24 * 7, 24 * 3, base.DAILY, True),
    (24 * 7, 24 * 7 - 5, base.DAILY, False),
    # Never fetched: fetches.
    (24 * 7, None, base.DAILY, False),
    # An analyst's refresh: every TTL holds, with no slack.
    (24, 20, False, True),
    (24 * 7, 24 * 7 - 5, False, True),
])
def test_which_sources_skip(ttl, ago, force, skips):
    assert _Fetcher(ttl, ago, force)._within_ttl() is skips


def test_force_mode_needs_the_restore_and_backs_itself_up_on_sunday():
    monday, sunday = dt.date(2026, 10, 26), dt.date(2026, 11, 1)
    assert scheduled_refresh.force_mode({}, monday) is True                  # rebuilt
    assert scheduled_refresh.force_mode({"ER_REFRESH_FORCE": "daily"}, monday) == "daily"
    assert scheduled_refresh.force_mode({"ER_REFRESH_FORCE": "daily"}, sunday) is True
    assert scheduled_refresh.force_mode({"ER_REFRESH_FORCE": "all"}, monday) is True


def _history(tmp_path, last_run):
    folder = tmp_path / "history"
    folder.mkdir()
    (folder / "refresh_runs.ndjson").write_text(
        "\n".join(json.dumps({"id": i}) for i in range(1, last_run + 1)) + "\n")
    return folder


def _database(tmp_path, last_run):
    path = tmp_path / "er_tool.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE refresh_runs (id INTEGER PRIMARY KEY)")
    conn.executemany("INSERT INTO refresh_runs (id) VALUES (?)",
                     [(i,) for i in range(1, last_run + 1)])
    conn.commit()
    conn.close()
    return path


def test_a_restore_at_or_past_the_history_stands(tmp_path):
    folder = _history(tmp_path, 115)
    assert history.restore_check(_database(tmp_path, 115), folder)["restored"] is True
    # A release that went out when the history push failed is newer, and still good.
    (tmp_path / "later").mkdir()
    assert history.restore_check(_database(tmp_path / "later", 116),
                                 folder)["restored"] is True


def test_a_stale_or_broken_restore_is_removed(tmp_path):
    folder = _history(tmp_path, 115)
    stale = _database(tmp_path, 114)
    got = history.restore_check(stale, folder)
    assert got["restored"] is False and "before the committed" in got["why"]
    assert not stale.exists()                          # the rebuild starts clean
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not a database at all")
    assert history.restore_check(broken, folder)["restored"] is False
    assert not broken.exists()
    assert history.restore_check(tmp_path / "missing.db", folder)["restored"] is False
