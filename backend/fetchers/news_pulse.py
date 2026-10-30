"""The daily biopharma pulse, read from its files into news and the change feed.

The pulse's scheduled run commits ``data/pulse/YYYY-MM-DD.json`` to the
``claude/pulse-feed`` branch, and the daily refresh checks the folder out into
``ER_PULSE_DIR`` (``.github/workflows/refresh.yml``). Run anywhere else, the folder in
the repository is read. No network: the files are the source. See ``pulse.py``.

Every item is kept, whichever company it names, so private rounds and biotechs outside
the universe stay in the sector feed. An item naming universe companies also reaches
each one's news and What Changed, labelled as the pulse. A file already read is read
again only when it changes.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib

import db
import pulse
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "pulse"
ENTITY_KEY = "daily_pulse"
TTL_SECONDS = 0                      # local files: reading them costs nothing
DEFAULT_DIR = pathlib.Path(__file__).resolve().parents[2] / "data" / "pulse"
# How old an item may be and still enter the change feed. The first read takes every
# briefing on the branch, and a month of them arriving as today's changes would be noise;
# older items still reach news and the sector feed.
CHANGE_WINDOW_DAYS = 7


def pulse_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("ER_PULSE_DIR") or DEFAULT_DIR)


class PulseNewsFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, db_path=None, folder=None, today=None):
        super().__init__(db_path)
        self.folder = pathlib.Path(folder) if folder else None
        self.today = today
        self.problems: list[str] = []

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def fetch(self) -> list[dict]:
        folder = self.folder or pulse_dir()
        if not folder.is_dir():
            return []
        conn = db.get_connection(self.db_path)
        try:
            read = {r["pulse_date"]: r["file_sha"]
                    for r in conn.execute("SELECT pulse_date, file_sha FROM pulse_reads")}
        finally:
            conn.close()
        out = []
        for path in sorted(folder.glob("*.json")):
            day = pulse.date_of(path.name)
            if not day:
                continue
            body = path.read_bytes()
            sha = hashlib.sha256(body).hexdigest()
            if read.get(day) == sha:
                continue
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                self.problems.append(f"{path.name}: not JSON ({exc})")
                continue
            out.append({"file": path.name, "sha": sha, "payload": payload})
        return out

    def normalise(self, raw) -> list[dict]:
        rows = []
        for entry in raw:
            parsed, problems = pulse.parse(entry["payload"], entry["file"])
            self.problems.extend(problems)
            if parsed:
                rows.append({**parsed, "sha": entry["sha"]})
        return rows

    def snapshot(self, rows: list[dict]) -> None:
        self._write_snapshot({"briefings": [r["pulse_date"] for r in rows],
                              "items": sum(len(r["items"]) for r in rows),
                              "problems": self.problems[:20], "fetch_kind": "live"})

    def _snapshot_cache(self) -> None:
        self._write_snapshot({"fetch_kind": "cache"})

    def _write_snapshot(self, payload: dict) -> None:
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'feed', ?, ?, ?)",
                (self.source, ENTITY_KEY, json.dumps(payload), self.refresh_run_id))
            conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        today = self.today or dt.date.today()
        cutoff = (today - dt.timedelta(days=CHANGE_WINDOW_DAYS)).isoformat()
        conn = db.get_connection(self.db_path)
        written = 0
        try:
            index = pulse.universe_index(conn)
            tickers = {r["id"]: r["ticker"] for r in conn.execute(
                "SELECT id, ticker FROM companies")}
            for briefing in rows:
                day = briefing["pulse_date"]
                for item in briefing["items"]:
                    companies = pulse.match(item, index)
                    held = conn.execute(
                        "SELECT id FROM pulse_items WHERE pulse_date = ? AND url = ?",
                        (day, item["url"])).fetchone()
                    values = (item["tier"], item["kind"], item["headline"], item["detail"],
                              item["published"], json.dumps(item["companies"]),
                              ",".join(tickers[c] for c in companies) or None)
                    if held:
                        item_id = held["id"]
                        conn.execute(
                            "UPDATE pulse_items SET tier = ?, kind = ?, headline = ?,"
                            " detail = ?, published_at = ?, companies = ?, tickers = ?,"
                            " fetched_at = datetime('now') WHERE id = ?",
                            (*values, item_id))
                        conn.execute("DELETE FROM pulse_item_companies WHERE item_id = ?",
                                     (item_id,))
                    else:
                        item_id = conn.execute(
                            "INSERT INTO pulse_items (pulse_date, tier, kind, headline,"
                            " detail, published_at, companies, tickers, url)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (day, *values, item["url"])).lastrowid
                        written += 1
                    conn.executemany(
                        "INSERT OR IGNORE INTO pulse_item_companies (item_id, company_id)"
                        " VALUES (?, ?)", [(item_id, c) for c in companies])
                    # News is keyed on the link, so an article a company's own feed or
                    # the FDA's already carries is not stored twice.
                    dated = item["published"] or day
                    conn.execute(
                        "INSERT INTO news (company_id, source, title, url, published_at)"
                        " VALUES (?, ?, ?, ?, ?) ON CONFLICT(url) DO NOTHING",
                        (companies[0] if companies else None, SOURCE, item["headline"],
                         item["url"], dated))
                    if held or dated < cutoff:
                        continue
                    for company_id in companies:
                        conn.execute(
                            "INSERT INTO changes (entity_type, entity_key, field,"
                            "  old_value, new_value, change_type, significance,"
                            "  refresh_run_id)"
                            " VALUES ('company', ?, 'daily pulse', NULL, ?, ?, ?, ?)",
                            (f"{tickers[company_id]}|{item['url']}", item["headline"],
                             f"pulse_{item['kind']}",
                             pulse.SIGNIFICANCE.get(item["tier"], "low"),
                             self.refresh_run_id))
                conn.execute(
                    "INSERT INTO pulse_reads (pulse_date, read, items, file_sha)"
                    " VALUES (?, ?, ?, ?) ON CONFLICT(pulse_date) DO UPDATE SET"
                    " read = excluded.read, items = excluded.items,"
                    " file_sha = excluded.file_sha, fetched_at = datetime('now')",
                    (day, briefing["read"], len(briefing["items"]), briefing["sha"]))
            conn.commit()
        finally:
            conn.close()
        # A dropped item is reported, not failed on: the briefing still reached the inbox,
        # and a run marked partial every time it skips a link teaches nothing.
        return RefreshResult(self.source, written, notes=list(self.problems))
